<script>
	// StackedViewer.svelte
	import { onMount } from "svelte";
	import debounce from "lodash.debounce";
	import LineChart from "$components/StackedAreaChart.svelte";
	import YearBrush from "$components/YearBrush.svelte";
	import Switch from "$components/ui/Switch.svelte";
	import { getMonths, searchAuthors, getAuthor } from "$components/db.js";

	// Colors for title lines.
	const TITLE_COLORS = [
		"#e3120b", "#1f7a4d", "#e58a00", "#6a4c93",
		"#0b7285", "#c2255c", "#5c940d", "#7048e8"
	];
	const INK = "var(--color-fg)";

	let authors = $state([]); // the search index
	let months = $state([]); // the shared month axis (from meta.json)
	let query = $state("");
	let results = $state([]);
	let current = $state(null); // loaded author object

	let groups = $state([]); // selection groups: { id, name, idxs: [] }
	let activeGroupId = $state(null); // which group the title checkboxes edit right now null means "single selection" mode
	let groupIdCounter = 0; // increasing id source for groups
	let singleIdxs = $state([]); // titles ticked while no group was active
	let titleFilter = $state(""); // text filter for the title list
	let chartMode = $state("line"); // 'line' = author's total as one line (default); 'area' = stacked by title
	let titleSort = $state("work"); // 'work' = editions grouped by work; 'borrowed' = most checkouts; 'alpha' = A–Z
	let workOrder = $state("checkouts"); // in 'work' mode, order the works by 'checkouts' (total, default) or 'name' (A–Z)
	let isolatedKeys = $state([]); // when non-empty, the chart shows ONLY these series (keys 'g<id>' | 's<idx>'); multiple = compare
	let showAuthorTotal = $state(true); // show the author's aggregate total line in the line view
	let dragIdx = $state(null); // title index currently being dragged onto a group pill
	let dragGroupId = $state(null); // group pill currently being dragged (to merge into another)
	let dragOverId = $state(null); // group pill currently under the dragged title/pill
	// Manual overrides to the auto work-clustering: edition idx -> the work key it
	// should belong to (a merge target, or its own `excl-<idx>` key when pulled out
	// of a cluster). Empty = pure auto-clustering.
	let workAssign = $state({});
	let dragWorkKey = $state(null); // work row being dragged in the table (to merge into another)
	let dragOverWorkKey = $state(null); // work row currently under the dragged work
	let autoGroupNote = $state(""); // feedback after "Group editions into works"
	let loadError = $state(""); // message when an author fails to load
	let loading = $state(false); // true while an author's data is being fetched
	let hoverTip = $state(null); // { text, x, y } instant tooltip for full edition titles
	let workColW = $state(150); // resizable width (px) of the title-table Work column
	let editionColW = $state(240); // min width (px) of the Edition column (drag to see full titles)
	let yearLo = $state(0); // first month index shown (set by the YearBrush)
	let yearHi = $state(0); // last month index shown (inclusive)

	// Drag a column divider in the title table to widen a column.
	function startColResize(event, which) {
		event.preventDefault();
		const startX = event.clientX;
		const startW = which === "work" ? workColW : editionColW;
		const onMove = (e) => {
			const w = Math.max(60, startW + (e.clientX - startX));
			if (which === "work") workColW = w;
			else editionColW = w;
		};
		const onUp = () => {
			window.removeEventListener("pointermove", onMove);
			window.removeEventListener("pointerup", onUp);
		};
		window.addEventListener("pointermove", onMove);
		window.addEventListener("pointerup", onUp);
	}

	onMount(async () => {
		// The site queries a single SQLite database (static/data/library.sqlite3)
		// directly over HTTP range requests via sql.js-httpvfs -- see db.js.
		// months is the shared x-axis; the top authors seed the "Most borrowed"
		// chips (and an empty search returns the top authors by total).
		months = await getMonths();
		yearHi = Math.max(months.length - 1, 0);
		authors = await searchAuthors("", 25);
		// Open on Kevin Kwan by default (a nice multi-edition example); fall back
		// to the most-borrowed author if he isn't in the index.
		const defaultAuthor =
				authors.find((a) => a.slug === "kevin-kwan") ||
				(await searchAuthors("kevin kwan", 5)).find((a) => a.slug === "kevin-kwan") ||
				authors[0];
		if (defaultAuthor) await selectAuthor(defaultAuthor);
	});

	// Expand a sparse series ([[monthIndex, count], ...]) into a full array of
	// length months.length, filling the gaps with 0.
	function densify(sparse) {
		const arr = new Array(months.length).fill(0);
		for (const [i, v] of sparse) arr[i] = v;
		return arr;
	}

	// The first letter of each word typed so far, e.g. "octavia b" -> ["O", "B"].
	// build_data.py buckets each author's file under authors/<INITIALS>/ where
	// intitals is the first letter of their first name + first letter of their
	// last name (e.g. "OB" for Octavia Butler), so these are the letters we use
	// to figure out which "folders" a given search could live in.
	function typedLetters(q) {
		return q
				.trim()
				.split(/\s+/)
				.filter(Boolean)
				.map((w) => w[0].toUpperCase());
	}

	// Filter the author list as the user types -- a full-text (or LIKE) query
	// against the authors table in the SQLite database.
	const runSearch = debounce(async (q) => {
		const needle = q.trim();
		if (needle.length < 2) {
			results = [];
			return;
		}
		results = await searchAuthors(needle, 25);
	}, 120);
	$effect(() => runSearch(query));

	async function selectAuthor(a) {
		// One author's drilldown (their series + every qualifying title) comes
		// from their static JSON file (see db.js).
		loadError = "";
		loading = true;
		const data = await getAuthor(a.slug).catch(() => null);
		if (!data) {
			loading = false;
			loadError = `Couldn't load "${displayName(a.name)}". (In local preview only the sample authors are available; on the live site every author loads.)`;
			return;
		}
		// expand the sparse series the ETL produced into full arrays
		data.months = months;
		data.series = densify(data.series);
		data.titles.forEach((t) => {
			t.series = densify(t.series);
			t.format = t.fmt; // the ETL stores the short field name "fmt"
		});
		current = data;
		// reset the controls for the new author
		groups = [];
		activeGroupId = null;
		singleIdxs = [];
		titleFilter = "";
		chartMode = "line";
		isolatedKeys = [];
		showAuthorTotal = true;
		autoGroupNote = "";
		titleSort = "work";
		workOrder = "checkouts";
		expandedWorks = [];
		workAssign = {};
		yearLo = 0;
		yearHi = Math.max(months.length - 1, 0);
		query = "";
		results = [];
		loading = false;
	}

	// Short label shown in a title's format badge.
	function formatLabel(f) {
		return {ebook: "ebook", audiobook: "audio", print: "print", other: "other"}[f] || f;
	}

	// The catalog stores author names inconsistently -- often all-lowercase
	// ("mo willems") or "Lastname, First" ("Davis, Jim"). Tidy them for display:
	// flip the comma form and Title-Case the words, while leaving already
	// mixed-case names (McDonald, DeLillo) alone.
	function titleCaseWord(w) {
		if (w === w.toLowerCase() || w === w.toUpperCase()) {
			return w.charAt(0).toUpperCase() + w.slice(1).toLowerCase();
		}
		return w;
	}
	function displayName(name) {
		if (!name) return name;
		let n = name.trim();
		const comma = n.match(/^([^,]+),\s*(.+)$/);
		if (comma) n = `${comma[2].trim()} ${comma[1].trim()}`;
		return n.replace(/\S+/g, titleCaseWord);
	}

	// Make a new group. If titles are currently single-selected, seed the group
	// with them (so "select a few, then hit New group" bundles them in one go)
	// and clear the single selection.
	function addGroup() {
		const g = {id: ++groupIdCounter, name: "", idxs: [...singleIdxs]};
		singleIdxs = [];
		groups = [...groups, g];
		activeGroupId = g.id;
		return g;
	}

	function removeGroup(id) {
		groups = groups.filter((g) => g.id !== id);
		if (activeGroupId === id) {
			activeGroupId = groups.length ? groups[groups.length - 1].id : null;
		}
		isolatedKeys = isolatedKeys.filter((k) => k !== `g${id}`);
	}

	// Finish editing the active group (clearer "I'm done adding titles" action).
	function finishGroup() {
		activeGroupId = null;
	}

	// "Only" is a toggle you can apply to more than one line at once: the chart
	// shows just the isolated set, so ticking two titles' "Only" compares them
	// head to head. Clicking an already-isolated line drops it back out.
	function toggleIsolate(key) {
		isolatedKeys = isolatedKeys.includes(key)
				? isolatedKeys.filter((k) => k !== key)
				: [...isolatedKeys, key];
	}
	const isIsolated = (key) => isolatedKeys.includes(key);
	function clearIsolate() {
		isolatedKeys = [];
	}

	// Human label for a series key (used for the chart title while isolating).
	function keyLabel(key) {
		if (!current) return "";
		if (key.startsWith("g")) {
			const g = groups.find((g) => g.id === Number(key.slice(1)));
			return g ? groupLabel(g) : "";
		}
		if (key.startsWith("s")) return current.titles[Number(key.slice(1))]?.title ?? "";
		return "";
	}

	// Sum a set of title indices into one densified series (for a group's line).
	function sumSeries(idxs) {
		const out = new Array(months.length).fill(0);
		for (const idx of idxs) {
			const s = current.titles[idx].series;
			for (let i = 0; i < out.length; i++) out[i] += s[i];
		}
		return out;
	}

	const groupColor = (gi) => TITLE_COLORS[gi % TITLE_COLORS.length];
	const singleColor = (i) => TITLE_COLORS[i % TITLE_COLORS.length];
	// A group's color is fixed to its position in `groups` (the chart uses the
	// same), so the pills can be displayed in any order without colors shuffling.
	const groupColorFor = (g) => groupColor(groups.findIndex((x) => x.id === g.id));
	// Non-empty groups, displayed alphabetically by name.
	const sortedGroups = $derived(
			[...groups]
					.filter((g) => g.idxs.length)
					.sort((a, b) => groupLabel(a).localeCompare(groupLabel(b), undefined, { sensitivity: "base", numeric: true }))
	);

	// --- Auto-cluster titles into "works" ----------------------------------
	// The same book shows up many times (print / audio / ebook / illustrated /
	// unabridged), differing only in cataloging boilerplate. Strip that boilerplate
	// to a "work key" so all the editions of one work collapse to the same string.
	// e.g. every "Harry Potter and the Sorcerer's Stone ..." variant ->
	//      "harry potter and the sorcerers stone".
	function normalizeWorkKey(title) {
		let t = (title || "").toLowerCase();
		// Fold accents to plain ASCII so "Galápagos" and "Galapagos" match
		// (otherwise "á" gets stripped to a space and the keys diverge).
		t = t.normalize("NFD").replace(/[̀-ͯ]/g, "");
		t = t.split(" / ")[0]; // drop "/ by Author ; illustrations by ..."
		t = t.replace(/&/g, " and "); // "beasts & where" -> "beasts and where"
		t = t.replace(/\([^)]*\)/g, " "); // drop "(unabridged)" etc.
		// Repeatedly strip a trailing ":"/";" segment when it's edition/format noise
		// (series/book/volume, "the original screenplay", "read by <narrator>",
		// illustrated/anniversary editions, "a novel", etc.) OR an "or, ..."
		// alternative title (e.g. "Slaughterhouse-Five: or, The Children's Crusade"
		// is the same book). Stop at the first segment that's a real distinct
		// subtitle (e.g. "The Crimes of Grindelwald"), so those stay separate.
		const NOISE = /(book|bk|series|volume|vol|part|edition|unabridged|abridged|screenplay|read by|narrated|illustrated|deluxe|anniversary|collector|special|movie|film|adapted|reissue|boxe?d? ?set|complete|novel|novella|memoir|thriller|mystery|story|stories|tale|tales|romance|biography|autobiography|poems|essays)/i;
		let prev;
		do {
			prev = t;
			t = t.replace(/[:;]\s*[^:;]*$/, (seg) => (NOISE.test(seg) || /[:;]\s*or[\s,]/i.test(seg) ? " " : seg));
		} while (t !== prev);
		t = t.replace(/\b(unabridged|abridged|audiobook|e-?book|large print|compact disc|sound recording)\b/g, " ");
		t = t.replace(/\b(the|a|an)\b/g, " "); // drop articles so "Look at the birdie" == "Look at Birdie"
		t = t.replace(/['’]/g, ""); // sorcerer's -> sorcerers
		// Remove ALL non-alphanumerics INCLUDING spaces/hyphens, so word-boundary
		// differences don't matter ("Slaughter-House Five" == "Slaughterhouse-Five").
		t = t.replace(/[^a-z0-9]+/g, "");
		return t;
	}

	// A readable name for a work, taken from its best-known edition's title.
	function cleanTitleForDisplay(title) {
		let t = (title || "").split(" / ")[0];
		t = t.replace(/\s*:\s*.*$/, ""); // drop subtitle after the first colon
		t = t.replace(/\([^)]*\)/g, "").replace(/\s+/g, " ").trim();
		return t;
	}

	// Cluster the current author's titles into works and seed the groups. Only
	// works with 2+ editions are grouped (that's where the dedup value is); the
	// top ones by total are kept so the line chart stays readable. This REPLACES
	// any existing groups -- it's a "do it for me" starting point the user revises.
	const MAX_AUTO_GROUPS = 5;
	function autoGroupByWork(opts = {}) {
		if (!current) return;
		const buckets = new Map();
		current.titles.forEach((t, idx) => {
			const key = effectiveKey(idx, t.title);
			if (!key) return;
			if (!buckets.has(key)) buckets.set(key, []);
			buckets.get(key).push(idx);
		});
		// Top works by total checkouts -- include single-edition works too, so the
		// 5 most-borrowed works always show even if some aren't multi-edition.
		const works = [...buckets.values()]
				.map((idxs) => ({ idxs, total: idxs.reduce((s, i) => s + current.titles[i].total, 0) }))
				.sort((a, b) => b.total - a.total)
				.slice(0, MAX_AUTO_GROUPS);

		groups = works.map((w) => {
			const topIdx = w.idxs.reduce((best, i) => (current.titles[i].total > current.titles[best].total ? i : best), w.idxs[0]);
			return { id: ++groupIdCounter, name: cleanTitleForDisplay(current.titles[topIdx].title), idxs: [...w.idxs] };
		});
		singleIdxs = [];
		activeGroupId = null;
		isolatedKeys = [];
		// The ✨ button jumps to the line view to show one line per work; when
		// the stacked view triggers this automatically, stay put.
		if (!opts.keepChartMode) chartMode = "line";
		const merged = works.reduce((s, w) => s + w.idxs.length, 0);
		autoGroupNote = works.length
				? `Showing the top ${works.length} works (${merged} editions). Tick more works in the table, drag titles between groups, or delete a group to adjust.`
				: "No works to show for this author.";
	}

	// The work key an edition actually belongs to: its manual override if any
	// (a merge target, or an `excl-<idx>` singleton when excluded), else the
	// auto-computed key. Everything work-related routes through this.
	function effectiveKey(idx, title) {
		return workAssign[idx] ?? normalizeWorkKey(title);
	}

	// Pull one edition out of its work cluster into its own singleton work.
	function excludeEdition(idx) {
		workAssign = { ...workAssign, [idx]: `excl-${idx}` };
	}

	// Merge one work into another: reassign every edition currently in srcKey to
	// destKey (used when a work row is dragged onto another in the table).
	function mergeWorks(srcKey, destKey) {
		if (!current || srcKey === destKey) return;
		const updates = {};
		current.titles.forEach((t, idx) => {
			if (effectiveKey(idx, t.title) === srcKey) updates[idx] = destKey;
		});
		workAssign = { ...workAssign, ...updates };
	}

	// Map of workKey -> { idxs (all editions of the work), name }. Powers the
	// per-work "Plot" tick and the collapsible work rows in the title table.
	const workGroups = $derived.by(() => {
		const m = new Map();
		if (!current) return m;
		current.titles.forEach((t, idx) => {
			const key = effectiveKey(idx, t.title);
			if (!key) return;
			if (!m.has(key)) m.set(key, { idxs: [], name: cleanTitleForDisplay(t.title) || t.title, topTotal: -1, total: 0 });
			const w = m.get(key);
			w.idxs.push(idx);
			w.total += t.total;
			if (t.total > w.topTotal) {
				w.topTotal = t.total;
				w.name = cleanTitleForDisplay(t.title) || t.title;
			}
		});
		return m;
	});

	// Is every edition of this work currently on the chart (as a group, or in the
	// group being edited)?
	function isWorkPlotted(key) {
		const w = workGroups.get(key);
		if (!w || !w.idxs.length) return false;
		if (activeGroupId) {
			const g = groups.find((g) => g.id === activeGroupId);
			return !!g && w.idxs.every((i) => g.idxs.includes(i));
		}
		return groups.some((g) => w.idxs.every((i) => g.idxs.includes(i)));
	}

	// Add (or remove) a whole work -- all its editions as one aggregated line.
	// If a group is being edited, the editions go into that group; otherwise the
	// work becomes its own group (named after the work).
	function toggleWork(key) {
		const w = workGroups.get(key);
		if (!w || !w.idxs.length) return;
		if (activeGroupId) {
			const g = groups.find((g) => g.id === activeGroupId);
			if (!g) return;
			if (w.idxs.every((i) => g.idxs.includes(i))) {
				g.idxs = g.idxs.filter((i) => !w.idxs.includes(i));
			} else {
				w.idxs.forEach((i) => releaseTitle(i));
				g.idxs = [...new Set([...g.idxs, ...w.idxs])];
			}
			return;
		}
		const existing = groups.find(
				(g) => g.idxs.length === w.idxs.length && w.idxs.every((i) => g.idxs.includes(i))
		);
		if (existing) {
			removeGroup(existing.id);
		} else {
			w.idxs.forEach((i) => releaseTitle(i));
			// Name the group with the work's (short) title.
			groups = [...groups, { id: ++groupIdCounter, name: w.name, idxs: [...w.idxs] }];
		}
	}

	// Drag-and-drop onto a group pill: either a title (add it) or another group
	// pill (merge the two groups into one).
	function dropOnGroup(id) {
		if (dragGroupId !== null && dragGroupId !== id) {
			mergeGroups(dragGroupId, id);
		} else if (dragIdx !== null) {
			const g = groups.find((g) => g.id === id);
			if (g && !g.idxs.includes(dragIdx)) {
				releaseTitle(dragIdx);
				g.idxs = [...g.idxs, dragIdx];
			}
		}
		dragIdx = null;
		dragGroupId = null;
	}

	// Merge the dragged group's titles into the target group, then drop the
	// now-empty source group. Keeps the target's name.
	function mergeGroups(srcId, destId) {
		const src = groups.find((g) => g.id === srcId);
		const dest = groups.find((g) => g.id === destId);
		if (!src || !dest) return;
		const merged = [...dest.idxs];
		for (const i of src.idxs) if (!merged.includes(i)) merged.push(i);
		dest.idxs = merged;
		groups = groups.filter((g) => g.id !== srcId);
		if (activeGroupId === srcId) activeGroupId = destId;
		isolatedKeys = isolatedKeys.filter((k) => k !== `g${srcId}`);
	}

	// strip a title out of every group and out of the single-selection list, so it can be picked up by whichever owner is claiming it next.
	function releaseTitle(idx) {
		groups.forEach((g) => {
			if (g.idxs.includes(idx)) g.idxs = g.idxs.filter((i) => i !== idx);
		});
		if (singleIdxs.includes(idx)) singleIdxs = singleIdxs.filter((i) => i !== idx);
	}

	function toggleTitle(idx) {
		if (activeGroupId) {
			const g = groups.find((g) => g.id === activeGroupId);
			if (!g) return;
			if (g.idxs.includes(idx)) {
				g.idxs = g.idxs.filter((i) => i !== idx);
			} else {
				releaseTitle(idx);
				g.idxs = [...g.idxs, idx];
			}
		} else {
			// single-selection mode: no group is active
			if (singleIdxs.includes(idx)) {
				singleIdxs = singleIdxs.filter((i) => i !== idx);
			} else {
				releaseTitle(idx);
				singleIdxs = [...singleIdxs, idx];
			}
		}
	}

	// which group a title currently belongs to
	function groupForTitle(idx) {
		return groups.find((g) => g.idxs.includes(idx)) ?? null;
	}

	// is this title one of single selections
	function isSingleSelected(idx) {
		return singleIdxs.includes(idx);
	}

	// The 15 most-borrowed authors overall (authors.json is sorted by total),
	// shown as quick-pick buttons under the search box.
	const topAuthors = $derived(authors.slice(0, 15));

	// The title table, filtered by the little search box. Each row is annotated
	// with its normalized "work" (so editions of the same book share a work name
	// and key) and can be sorted three ways: by work (editions of a book grouped
	// together -- the clustering view), most borrowed, or A–Z.
	const filteredTitles = $derived.by(() => {
		if (!current) return [];
		let rows = current.titles.map((t, idx) => ({
			...t,
			idx,
			workKey: effectiveKey(idx, t.title),
			workName: cleanTitleForDisplay(t.title) || t.title
		}));

		const f = titleFilter.trim().toLowerCase();
		if (f) rows = rows.filter((r) => r.title.toLowerCase().includes(f) || r.workName.toLowerCase().includes(f));

		if (titleSort === "alpha") {
			rows.sort((a, b) => a.title.localeCompare(b.title, undefined, { sensitivity: "base", numeric: true }));
		} else if (titleSort === "work") {
			// Group editions of a work together, ordered A–Z by the work's name or
			// by its combined checkouts. CRITICAL: sort on a *per-work* value (from
			// workGroups), not the per-edition workName -- editions of one work have
			// different display names, so sorting by those would scatter them and
			// break the "consecutive editions" grouping the table relies on.
			// Editions within a work lead with the best-known (most-borrowed).
			const wName = (key) => workGroups.get(key)?.name ?? key;
			const wTotal = (key) => workGroups.get(key)?.total ?? 0;
			rows.sort((a, b) => {
				const cmp =
						workOrder === "checkouts"
								? wTotal(b.workKey) - wTotal(a.workKey)
								: wName(a.workKey).localeCompare(wName(b.workKey), undefined, { sensitivity: "base", numeric: true });
				if (cmp) return cmp;
				if (a.workKey !== b.workKey) return a.workKey < b.workKey ? -1 : 1;
				return b.total - a.total;
			});
		} else {
			rows.sort((a, b) => b.total - a.total);
		}
		return rows;
	});

	// Prolific authors have hundreds-to-thousands of titles (J.K. Rowling ~190,
	// James Patterson ~1500). Rendering a DOM row for every one janks or hangs
	// the tab, so only render the first slice and let the filter box find the
	// rest. Selected titles are always shown so a selection never "disappears".
	// Also flag the first row of each work so the table can show the work name
	// once and draw a divider between works (only meaningful in "by work" sort).
	const TITLE_RENDER_CAP = 120;
	const visibleTitles = $derived.by(() => {
		let rows;
		if (filteredTitles.length <= TITLE_RENDER_CAP) {
			rows = filteredTitles;
		} else {
			const head = filteredTitles.slice(0, TITLE_RENDER_CAP);
			const seen = new Set(head.map((t) => t.idx));
			const selectedTail = filteredTitles
					.slice(TITLE_RENDER_CAP)
					.filter((t) => !seen.has(t.idx) && (isSingleSelected(t.idx) || groupForTitle(t.idx)));
			rows = [...head, ...selectedTail];
		}
		let prevWork = null;
		return rows.map((r) => {
			const firstOfWork = titleSort === "work" ? r.workKey !== prevWork : true;
			prevWork = r.workKey;
			return { ...r, firstOfWork };
		});
	});
	const hiddenTitleCount = $derived(filteredTitles.length - visibleTitles.length);

	// In "by work" sort, roll the (already work-sorted) editions up into one
	// collapsible block per work: a single header row you can expand to see and
	// edit the individual editions underneath.
	const WORK_BLOCK_CAP = 150;
	const workBlocks = $derived.by(() => {
		if (titleSort !== "work") return [];
		// Group by work key into a Map first (guarantees exactly one block per key,
		// regardless of row order), then sort the blocks. Grouping by consecutive
		// rows was fragile -- editions of one work could be sorted apart and produce
		// two blocks with the same key (a duplicate keyed-each key).
		const byKey = new Map();
		for (const t of filteredTitles) {
			if (!byKey.has(t.workKey)) {
				byKey.set(t.workKey, { key: t.workKey, name: workGroups.get(t.workKey)?.name ?? t.workName, editions: [], total: 0 });
			}
			const blk = byKey.get(t.workKey);
			blk.editions.push(t);
			blk.total += t.total;
		}
		const blocks = [...byKey.values()];
		for (const b of blocks) b.editions.sort((x, y) => y.total - x.total);
		blocks.sort((a, b) =>
				workOrder === "checkouts"
						? b.total - a.total
						: a.name.localeCompare(b.name, undefined, { sensitivity: "base", numeric: true }) || (a.key < b.key ? -1 : 1)
		);
		return blocks;
	});
	const visibleWorkBlocks = $derived(workBlocks.slice(0, WORK_BLOCK_CAP));
	const hiddenWorkCount = $derived(Math.max(0, workBlocks.length - visibleWorkBlocks.length));

	let expandedWorks = $state([]); // work keys currently expanded in the table
	const isExpanded = (key) => expandedWorks.includes(key);
	function toggleExpand(key) {
		expandedWorks = isExpanded(key) ? expandedWorks.filter((k) => k !== key) : [...expandedWorks, key];
	}

	// Currently-active group object (or null if none selected/created yet).
	const activeGroup = $derived(groups.find((g) => g.id === activeGroupId) ?? null);

	// Name a group is whatever the user typed, otherwise auto-name it after its
	// most-borrowed member (lowest original index = most checkouts), plus a
	// count of the rest.
	function groupLabel(g) {
		if (g.name.trim()) return g.name.trim();
		if (!current || !g.idxs.length) return "New group";
		const firstIdx = Math.min(...g.idxs);
		const firstTitle = current.titles[firstIdx].title;
		const extra = g.idxs.length - 1;
		return extra > 0 ? `${firstTitle}  +${extra} more` : firstTitle;
	}

	// Chart title. When a series is isolated ("Only"), name it. Otherwise, in the
	// stacked-area view, show the group name(s).
	// Only title the chart when exactly one line/work is on screen -- naming it.
	// When several are shown (a comparison), the legend does the labeling and a
	// long concatenated title just clutters, so leave it blank.
	const plotTitle = $derived.by(() => {
		if (!current) return "";
		if (isolatedKeys.length === 1) return keyLabel(isolatedKeys[0]);
		return "";
	});

	// StackedViewer.svelte
	const chartSeries = $derived.by(() => {
		if (!current) return [];

		const groupIndexOf = new Map();
		groups.forEach((g, gi) => {
			g.idxs.forEach((idx) => groupIndexOf.set(idx, gi));
		});

		const singleColorOf = new Map();
		singleIdxs.forEach((idx, i) => {
			singleColorOf.set(idx, TITLE_COLORS[i % TITLE_COLORS.length]);
		});

		let mapped = current.titles.map((t, idx) => {
			const gi = groupIndexOf.has(idx) ? groupIndexOf.get(idx) : -1;
			const isGrouped = gi !== -1;
			const isSingle = singleColorOf.has(idx);
			let color = "var(--color-gray-200)";
			if (isGrouped) color = TITLE_COLORS[gi % TITLE_COLORS.length];
			else if (isSingle) color = singleColorOf.get(idx);
			return {
				label: t.title,
				color,
				values: t.series,
				isSelected: isGrouped || isSingle, // Expose this flag for sorting and tooltip logic
				groupIndex: gi, // which group this book belongs to (-1 if none/single)
				titleIdx: idx // original title index, for isolate filtering
			};
		});

		// Grouped/single-selected books sink to the bottom of the stack grouped ones cluster by group
		mapped.sort((a, b) => {
			if (a.isSelected !== b.isSelected) return a.isSelected ? -1 : 1;
			if (a.isSelected && a.groupIndex !== b.groupIndex) return a.groupIndex - b.groupIndex;
			return 0;
		});

		return mapped;
	});

	// The author's own total checkouts as one bold line -- the default view.
	const authorLine = $derived(
			current
					? {key: "author", label: current.name, color: INK, values: current.series, groupIndex: -2, isAggregate: true}
					: null
	);

	// Line-mode series (before isolation): the author's total, plus ONE
	// aggregated line per group (summed over its titles) and one line per
	// individually-ticked title.
	const lineParts = $derived.by(() => {
		if (!current) return [];
		const parts = showAuthorTotal ? [authorLine] : [];
		groups.forEach((g, gi) => {
			if (g.idxs.length) {
				parts.push({
					key: `g${g.id}`,
					label: groupLabel(g),
					color: groupColor(gi),
					values: sumSeries(g.idxs),
					groupIndex: gi,
					isGroup: true
				});
			}
		});
		singleIdxs.forEach((idx, i) => {
			parts.push({
				key: `s${idx}`,
				label: current.titles[idx].title,
				color: singleColor(i),
				values: current.titles[idx].series,
				isSingle: true
			});
		});
		return parts;
	});

	// The union of title indices the isolated keys refer to (null = show all).
	function isolatedIdxSet() {
		if (!isolatedKeys.length) return null;
		const set = new Set();
		for (const key of isolatedKeys) {
			if (key.startsWith("g")) {
				const g = groups.find((g) => g.id === Number(key.slice(1)));
				if (g) g.idxs.forEach((i) => set.add(i));
			} else if (key.startsWith("s")) {
				set.add(Number(key.slice(1)));
			}
		}
		return set;
	}

	// A prolific author can have 1000+ qualifying titles; drawing a stacked-area
	// layer for each one janks/hangs the tab. Keep the biggest AREA_LAYER_CAP
	// layers (plus anything the user selected) and roll the rest into one "Other
	// titles" band, so the stack total is preserved but stays fast to render.
	const AREA_LAYER_CAP = 30;
	function capAreaLayers(all) {
		if (all.length <= AREA_LAYER_CAP) return all;
		const kept = [];
		const rest = [];
		for (const s of all) {
			if (s.isSelected || kept.length < AREA_LAYER_CAP) kept.push(s);
			else rest.push(s);
		}
		if (!rest.length) return kept;
		const monthCount = months.length;
		const otherValues = new Array(monthCount).fill(0);
		for (const s of rest) for (let i = 0; i < monthCount; i++) otherValues[i] += s.values[i];
		kept.push({
			label: `Other titles (${rest.length})`,
			color: "var(--color-gray-200)",
			values: otherValues,
			isSelected: false,
			groupIndex: -1,
			titleIdx: -1
		});
		return kept;
	}

	// What the chart actually draws. "line": author total + per-group and
	// per-title lines. "area": the stacked-by-title chart (capped). Either way,
	// when a series is isolated we show only it.
	const displaySeries = $derived.by(() => {
		if (!current) return [];
		if (chartMode === "line") {
			if (isolatedKeys.length) return lineParts.filter((s) => isolatedKeys.includes(s.key));
			return lineParts;
		}
		// area mode
		const only = isolatedIdxSet();
		const areaAll = only ? chartSeries.filter((s) => only.has(s.titleIdx)) : chartSeries;
		return capAreaLayers(areaAll);
	});

	// ---- Year window (the YearBrush under the chart) -----------------------
	// When the brush is narrowed, slice the month axis and every series to the
	// window so the chart re-scales to just those years.
	const isYearFiltered = $derived(months.length > 0 && (yearLo > 0 || yearHi < months.length - 1));
	const viewMonths = $derived(isYearFiltered ? months.slice(yearLo, yearHi + 1) : months);
	const viewSeries = $derived(
		isYearFiltered
			? displaySeries.map((s) => ({ ...s, values: s.values.slice(yearLo, yearHi + 1) }))
			: displaySeries
	);
</script>

<div class="viewer">
	<div class="search">
		<label class="sr-only" for="author-search">Search for an author</label>
		<input
				id="author-search"
				type="search"
				placeholder="Search an author — try Octavia Butler, or Mo Willems"
				bind:value={query}
				autocomplete="off"
		/>
		{#if results.length}
			<ul class="results">
				{#each results as a}
					<li>
						<button onclick={() => selectAuthor(a)}>
							<span>{displayName(a.name)}</span>
							<span class="count">{a.total.toLocaleString()}</span>
						</button>
					</li>
				{/each}
			</ul>
		{:else if query.trim().length >= 2}
			<p class="no-results">No authors found for “{query.trim()}”.</p>
		{/if}
	</div>

	<!-- quick-pick: the 10 most-borrowed authors -->
	{#if topAuthors.length}
		<div class="top-authors">
			<span class="quick-label">Most borrowed:</span>
			{#each topAuthors as a}
				<button
						class="chip"
						class:current={current && current.name === a.name}
						onclick={() => selectAuthor(a)}
				>
					{displayName(a.name)}
				</button>
			{/each}
		</div>
	{/if}

	{#if loadError}
		<p class="load-error">{loadError}</p>
	{/if}

	{#if loading}
		<p class="loading" role="status" aria-live="polite"><span class="spinner" aria-hidden="true"></span>Loading…</p>
	{/if}

	<!-- ===== Selected author ===== -->
	{#if current}
		<div class="author">
			<h2>{displayName(current.name)}</h2>
			<p class="meta">
				{current.total.toLocaleString()} checkouts · {current.titles.length} titles
			</p>

			<div class="mode-toggle" role="group" aria-label="Chart type">
				<button
						type="button"
						class:active={chartMode === "line"}
						onclick={() => (chartMode = "line")}
				>Total (line)</button>
				<button
						type="button"
						class:active={chartMode === "area"}
						onclick={() => {
							// First visit to the stacked view with nothing selected yet:
							// cluster editions into works automatically so the stack is
							// colored by work instead of an all-gray pile of editions.
							if (chartMode !== "area" && !groups.length && !singleIdxs.length) {
								autoGroupByWork({ keepChartMode: true });
							}
							chartMode = "area";
						}}
				>By title (stacked)</button>
			</div>

			{#if plotTitle}
				<p class="plot-title">{plotTitle}</p>
			{/if}
			<LineChart months={viewMonths} series={viewSeries} mode={chartMode}/>

			{#if months.length > 1}
				<YearBrush {months} values={current.series} bind:lo={yearLo} bind:hi={yearHi} />
			{/if}

			<div class="groups-panel">
				<div class="groups-header">
					<span class="groups-label">Selection groups</span>
					<div class="groups-actions">
						<button class="auto-group" onclick={autoGroupByWork} title="Plot the 5 most-borrowed works (their editions grouped into one line each)">
							Show top works
						</button>
						<button class="new-group" onclick={addGroup}>Make a new group</button>
					</div>
				</div>
				{#if autoGroupNote}
					<p class="auto-group-note">{autoGroupNote}</p>
				{/if}

				{#if (groups.some((g) => g.idxs.length) || singleIdxs.length)}
					<!-- This doubles as the chart legend: every line on the chart is a row
					     here, with its color, an "Only" toggle to isolate it, and controls. -->
					<ul class="group-chips">
						{#if chartMode === "line"}
							<li class="group-chip-row" class:dim={!showAuthorTotal || isolatedKeys.length}>
								<span class="group-chip static-chip" style="--chip-color: {INK}">
									<span class="chip-sw"></span>
									<span class="chip-name">Author total</span>
								</span>
								<button
										class="chip-only end"
										title={showAuthorTotal ? "Hide the author's total line" : "Show the author's total line"}
										onclick={() => (showAuthorTotal = !showAuthorTotal)}
								>{showAuthorTotal ? "Hide" : "Show"}</button>
							</li>
						{/if}
						{#each sortedGroups as g (g.id)}
							<li class="group-chip-row" class:dim={isolatedKeys.length && !isIsolated(`g${g.id}`)}>
								<span
										class="group-chip"
										class:active={g.id === activeGroupId}
										class:drag-over={dragOverId === g.id}
										style="--chip-color: {groupColorFor(g)}"
										title="Drag onto another group to merge them"
										draggable="true"
										ondragstart={() => (dragGroupId = g.id)}
										ondragend={() => { dragGroupId = null; dragOverId = null; }}
										ondragover={(e) => { e.preventDefault(); if (dragGroupId !== g.id) dragOverId = g.id; }}
										ondragleave={() => (dragOverId === g.id && (dragOverId = null))}
										ondrop={(e) => { e.preventDefault(); dropOnGroup(g.id); dragOverId = null; }}
								>
									<span class="chip-sw"></span>
									<span
											class="chip-name"
											onmousemove={(e) => (hoverTip = { text: groupLabel(g), x: e.clientX, y: e.clientY })}
											onmouseleave={() => (hoverTip = null)}
									>{groupLabel(g)}</span>
								</span>
								<button
										class="chip-edit"
										class:on={g.id === activeGroupId}
										title="Edit which titles are in this group"
										onclick={() => (activeGroupId = activeGroupId === g.id ? null : g.id)}
								>{g.id === activeGroupId ? "Done" : "Edit"}</button>
								<button
										class="chip-only"
										class:on={isIsolated(`g${g.id}`)}
										title="Show only this (click more than one to compare)"
										onclick={() => toggleIsolate(`g${g.id}`)}
								>Only</button>
								<button class="chip-remove" title="Delete group" onclick={() => removeGroup(g.id)}>×</button>
							</li>
						{/each}
						{#each singleIdxs as idx, i (idx)}
							<li class="group-chip-row" class:dim={isolatedKeys.length && !isIsolated(`s${idx}`)}>
								<span class="group-chip static-chip" style="--chip-color: {singleColor(i)}">
									<span class="chip-sw"></span>
									<span
											class="chip-name"
											onmousemove={(e) => (hoverTip = { text: current.titles[idx].title, x: e.clientX, y: e.clientY })}
											onmouseleave={() => (hoverTip = null)}
									>{current.titles[idx].title}</span>
								</span>
								<button
										class="chip-only"
										class:on={isIsolated(`s${idx}`)}
										title="Show only this (click more than one to compare)"
										onclick={() => toggleIsolate(`s${idx}`)}
								>Only</button>
								<button class="chip-remove" title="Remove this title" onclick={() => toggleTitle(idx)}>×</button>
							</li>
						{/each}
						{#if isolatedKeys.length}
							<li class="group-chip-row">
								<button class="show-all-btn" onclick={clearIsolate}>Show all</button>
							</li>
						{/if}
					</ul>
					{#if isolatedKeys.length === 1}
						<p class="compare-hint">Click “Only” on another line to compare them side by side.</p>
					{/if}
				{/if}

				{#if activeGroup}
					<div class="editing-banner">
						<span class="editing-text">
							Adding titles to <strong>{groupLabel(activeGroup)}</strong> — tick titles below,
							or drag them onto the group.
						</span>
						<button class="done-btn" onclick={finishGroup}>Done</button>
					</div>
					<div class="bundle-name">
						<label for="group-name-input">Name this group</label>
						<input
								id="group-name-input"
								type="text"
								bind:value={activeGroup.name}
								placeholder={groupLabel(activeGroup)}
						/>
					</div>
				{:else if groups.length}
					<p class="editing-hint">Click a group to edit it, or drag a title onto a group to add it.</p>
				{/if}
			</div>

			<div class="titles">
				<div class="titles-header">
					<input
							class="title-filter"
							type="search"
							placeholder="Filter titles…"
							bind:value={titleFilter}
							autocomplete="off"
					/>
					<div class="sort-toggle" role="group" aria-label="Sort titles">
						<span class="sort-label">Sort:</span>
						<button
								type="button"
								class:active={titleSort === "work"}
								onclick={() => (titleSort = "work")}
						>By work</button>
						<button
								type="button"
								class:active={titleSort === "borrowed"}
								onclick={() => (titleSort = "borrowed")}
						>Most borrowed</button>
						<button
								type="button"
								class:active={titleSort === "alpha"}
								onclick={() => (titleSort = "alpha")}
						>A–Z</button>
					</div>
				</div>
				{#if titleSort === "work"}
					<p class="table-hint">Highlighted rows are works with multiple editions. Drag one work onto another to merge them; expand a work and hit <em>exclude</em> to split an edition off.</p>
				{/if}
				<div class="title-table" role="table" aria-label="Titles, grouped by work" style="--work-w:{workColW}px; --edition-w:{editionColW}px">
					<div class="tt-head" role="row">
						<span class="tt-cell tt-plot" role="columnheader" title="Tick to plot a title on the chart">Add to plot</span>
						<span
								class="tt-cell tt-work"
								role="columnheader"
								aria-sort={titleSort === "work" && workOrder === "name" ? "ascending" : "none"}
						>
							<button
									class="col-sort"
									class:active={titleSort === "work" && workOrder === "name"}
									title="Group by work, ordered A–Z"
									onclick={() => { titleSort = "work"; workOrder = "name"; }}
							>Work{#if titleSort === "work" && workOrder === "name"}&nbsp;↓{/if}</button>
							<span class="col-resize" title="Drag to resize" onpointerdown={(e) => startColResize(e, "work")}></span>
						</span>
						<span class="tt-cell tt-edition" role="columnheader">
							Edition
							<span class="col-resize" title="Drag to widen and see full titles" onpointerdown={(e) => startColResize(e, "edition")}></span>
						</span>
						<span class="tt-cell tt-format" role="columnheader">Format</span>
						<span
								class="tt-cell tt-count"
								role="columnheader"
								aria-sort={titleSort === "work" && workOrder === "checkouts" ? "descending" : "none"}
						>
							<button
									class="col-sort"
									class:active={titleSort === "work" && workOrder === "checkouts"}
									title="Group by work, ordered by total checkouts"
									onclick={() => { titleSort = "work"; workOrder = "checkouts"; }}
							>{#if titleSort === "work" && workOrder === "checkouts"}↓&nbsp;{/if}Checkouts</button>
						</span>
					</div>
					{#snippet editionRow(t, showWork, indent)}
						{@const owner = groupForTitle(t.idx)}
						{@const ownerIdx = owner ? groups.indexOf(owner) : -1}
						{@const single = isSingleSelected(t.idx)}
						{@const singleIdx = single ? singleIdxs.indexOf(t.idx) : -1}
						{@const ownerColor = owner
								? TITLE_COLORS[ownerIdx % TITLE_COLORS.length]
								: single
										? TITLE_COLORS[singleIdx % TITLE_COLORS.length]
										: ""}
						{@const isCurrentOwner = activeGroupId ? owner?.id === activeGroupId : single}
						<li
								class="title-row"
								role="row"
								class:dragging={dragIdx === t.idx}
								draggable={groups.length > 0}
								ondragstart={() => (dragIdx = t.idx)}
								ondragend={() => { dragIdx = null; dragOverId = null; }}
						>
							<label
									class="tt-row"
									role="presentation"
									class:selected={owner !== null || single}
									style={ownerColor ? `--chip-color:${ownerColor}` : ""}
							>
								<span class="tt-cell tt-plot" role="cell">
									<input
											type="checkbox"
											aria-label="Plot “{t.title}” on the chart"
											checked={isCurrentOwner}
											onchange={() => toggleTitle(t.idx)}
									/>
								</span>
								<span class="tt-cell tt-work" role="cell" title={showWork ? t.workName : ""}>
									{#if showWork}
										<span class="tt-work-name">{t.workName}</span>
									{:else if indent}
										<button
												class="exclude-btn"
												title="Pull this edition out of the work — make it its own work"
												onclick={() => excludeEdition(t.idx)}
										>exclude</button>
									{/if}
								</span>
								<span
										class="tt-cell tt-edition"
										class:indent
										role="cell"
										onmousemove={(e) => (hoverTip = { text: t.title, x: e.clientX, y: e.clientY })}
										onmouseleave={() => (hoverTip = null)}
								>
									{#if (owner || single) && !isCurrentOwner}
										<span class="other-group-dot"
											  title="In “{owner ? groupLabel(owner) : t.title}”"></span>
									{/if}
									<span class="t-name">{t.title}</span>
								</span>
								<span class="tt-cell tt-format" role="cell">
									<span class="badge badge-{t.format}">{formatLabel(t.format)}</span>
								</span>
								<span class="tt-cell tt-count" role="cell">{t.total.toLocaleString()}</span>
							</label>
						</li>
					{/snippet}

					<ul class="title-list" role="rowgroup">
						{#if titleSort === "work"}
							{#each visibleWorkBlocks as w (w.key)}
								{@const multi = w.editions.length > 1}
								{@const fmts = [...new Set(w.editions.map((e) => e.format))]}
								<li
										class="work-header"
										role="row"
										class:cluster={multi}
										class:expanded={multi && isExpanded(w.key)}
										class:work-drop={dragOverWorkKey === w.key}
										draggable="true"
										ondragstart={() => (dragWorkKey = w.key)}
										ondragend={() => { dragWorkKey = null; dragOverWorkKey = null; }}
										ondragover={(e) => { if (dragWorkKey && dragWorkKey !== w.key) { e.preventDefault(); dragOverWorkKey = w.key; } }}
										ondragleave={() => (dragOverWorkKey === w.key && (dragOverWorkKey = null))}
										ondrop={(e) => { e.preventDefault(); if (dragWorkKey && dragWorkKey !== w.key) mergeWorks(dragWorkKey, w.key); dragWorkKey = null; dragOverWorkKey = null; }}
								>
									<span class="tt-cell tt-plot" role="cell">
										<input
												type="checkbox"
												class="plot-check"
												aria-label={multi ? `Plot the work “${w.name}” (${w.editions.length} editions) on the chart` : `Plot “${w.name}” on the chart`}
												title={multi ? `Plot “${w.name}” — all ${w.editions.length} editions as one line` : `Plot “${w.name}”`}
												checked={isWorkPlotted(w.key)}
												onchange={() => toggleWork(w.key)}
										/>
									</span>
									<span class="tt-cell tt-work" role="cell" title={w.name}>
										{#if multi}
											<button
													class="disclosure"
													aria-expanded={isExpanded(w.key)}
													aria-label="{isExpanded(w.key) ? 'Collapse' : 'Expand'} the {w.editions.length} editions of {w.name}"
													onclick={() => toggleExpand(w.key)}
											>{isExpanded(w.key) ? "▾" : "▸"}</button>
										{:else}
											<span class="disclosure-spacer" aria-hidden="true"></span>
										{/if}
										<span class="tt-work-name">{w.name}</span>
									</span>
									{#if multi}
										<button class="tt-cell tt-edition ed-summary" onclick={() => toggleExpand(w.key)}>
											<span class="cluster-badge">{w.editions.length} editions</span>{isExpanded(w.key) ? "" : " — click to edit"}
										</button>
									{:else}
										<span class="tt-cell tt-edition ed-single" role="cell">single edition</span>
									{/if}
									<span class="tt-cell tt-format" role="cell">
										{#each fmts as f}<span class="badge badge-{f}">{formatLabel(f)}</span>{/each}
									</span>
									<span class="tt-cell tt-count" role="cell">{w.total.toLocaleString()}</span>
								</li>
								{#if multi && isExpanded(w.key)}
									{#each w.editions as t (t.idx)}
										{@render editionRow(t, false, true)}
									{/each}
								{/if}
							{/each}
						{:else}
							{#each visibleTitles as t (t.idx)}
								{@render editionRow(t, t.firstOfWork, false)}
							{/each}
						{/if}
					</ul>
				</div>
				{#if titleSort === "work" && hiddenWorkCount > 0}
					<p class="titles-more">
						Showing the top {visibleWorkBlocks.length} works. {hiddenWorkCount.toLocaleString()} more —
						type in the filter above to find a specific one.
					</p>
				{:else if titleSort !== "work" && hiddenTitleCount > 0}
					<p class="titles-more">
						Showing the top {visibleTitles.length} titles. {hiddenTitleCount.toLocaleString()} more —
						type in the filter above to find a specific one.
					</p>
				{/if}
			</div>
		</div>
	{:else}
		<p class="hint">Start typing an author's name above.</p>
	{/if}

	{#if hoverTip}
		<div class="title-tip" style="left:{hoverTip.x + 14}px; top:{hoverTip.y + 16}px">{hoverTip.text}</div>
	{/if}
</div>


<style>
	.viewer {
		max-width: 720px;
		margin: 0 auto;
	}

	/* The starter's reset hides native checkboxes this turns them
	   back on so the ticked/unticked state is visible. */
	.viewer input[type="checkbox"] {
		appearance: auto;
		-webkit-appearance: auto;
		width: 17px;
		height: 17px;
		accent-color: var(--color-fg);
		background: none;
		flex: none;
		cursor: pointer;
	}

	.search {
		position: relative;
	}

	.search input {
		width: 100%;
		padding: 14px 16px;
		font-family: var(--font-sans);
		font-size: 1.05rem;
		background: var(--color-input-bg);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
	}

	.search input:focus {
		outline: 2px solid var(--color-focus);
		outline-offset: 1px;
	}

	.results {
		list-style: none;
		margin: 6px 0 0;
		padding: 6px;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-white);
		max-height: 340px;
		overflow-y: auto;
		position: absolute;
		width: 100%;
		z-index: var(--z-top);
		box-shadow: 0 6px 20px rgba(0, 0, 0, 0.08);
	}

	.results button {
		width: 100%;
		display: flex;
		justify-content: space-between;
		gap: 12px;
		padding: 9px 12px;
		background: none;
		border: none;
		border-radius: var(--radius-sm);
		font-family: var(--font-sans);
		font-size: 0.95rem;
		text-align: left;
		cursor: pointer;
		color: var(--color-fg);
	}

	.results button:hover {
		background: var(--color-gray-100);
	}

	.results .count {
		color: var(--color-fg-light);
		font-variant-numeric: tabular-nums;
	}

	.author {
		margin-top: 36px;
	}

	.author h2 {
		font-family: var(--font-serif);
		font-size: 2rem;
		line-height: 1.1;
		margin: 0;
	}

	.author .meta {
		font-family: var(--font-sans);
		color: var(--color-fg-light);
		margin: 4px 0 20px;
	}

	.plot-title {
		font-family: var(--font-serif);
		font-size: 1.3rem;
		line-height: 1.2;
		text-align: center;
		margin: 0 0 8px;
	}

	.legend {
		list-style: none;
		display: flex;
		flex-wrap: wrap;
		gap: 6px 18px;
		margin: 12px 0 0;
		padding: 0;
		font-family: var(--font-sans);
		font-size: 0.82rem;
	}

	.legend li {
		display: flex;
		align-items: center;
		gap: 6px;
		max-width: 320px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.legend .sw {
		width: 12px;
		height: 12px;
		border-radius: 2px;
		flex: none;
	}

	.legend-item {
		max-width: none;
	}

	.legend-item.dim {
		opacity: 0.4;
	}

	.legend-item .lg-name {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		max-width: 240px;
	}

	.only-btn {
		flex: none;
		font-family: var(--font-sans);
		font-size: 0.7rem;
		font-weight: 600;
		padding: 2px 8px;
		border-radius: 999px;
		border: 1px solid var(--color-border);
		background: var(--color-white);
		color: var(--color-fg-light);
		cursor: pointer;
	}

	.only-btn:hover {
		border-color: var(--color-fg-light);
		color: var(--color-fg);
	}

	.only-btn.on {
		background: var(--color-fg);
		border-color: var(--color-fg);
		color: var(--color-white);
	}

	.show-all-btn {
		font-family: var(--font-sans);
		font-size: 0.72rem;
		font-weight: 600;
		padding: 3px 12px;
		border-radius: 999px;
		border: 1px solid var(--color-fg);
		background: var(--color-fg);
		color: var(--color-white);
		cursor: pointer;
	}

	.show-all-btn:hover {
		opacity: 0.85;
	}

	.compare-hint {
		font-family: var(--font-sans);
		font-size: 0.78rem;
		color: var(--color-fg-light);
		margin: 6px 2px 0;
	}

	.editing-banner {
		display: flex;
		align-items: center;
		gap: 12px;
		margin: 12px 0 0;
		padding: 10px 12px;
		border-radius: var(--radius-sm);
		background: var(--color-white);
		border: 1.5px solid var(--color-fg);
	}

	.editing-text {
		flex: 1;
		font-family: var(--font-sans);
		font-size: 0.82rem;
		color: var(--color-fg);
	}

	.done-btn {
		flex: none;
		font-family: var(--font-sans);
		font-size: 0.85rem;
		font-weight: 600;
		padding: 6px 18px;
		border-radius: 999px;
		border: none;
		background: var(--color-fg);
		color: var(--color-white);
		cursor: pointer;
	}

	.done-btn:hover {
		opacity: 0.85;
	}

	.group-chip.drag-over {
		border-color: var(--chip-color, var(--color-fg));
		background: var(--chip-color, var(--color-fg));
		color: var(--color-white);
		box-shadow: 0 0 0 3px rgba(0, 0, 0, 0.08);
	}

	.title-row[draggable="true"] {
		cursor: grab;
	}

	.title-row.dragging {
		opacity: 0.5;
	}

	/* options row */
	.options {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 10px;
		margin: 18px 0 14px;
		font-family: var(--font-sans);
		font-size: 0.9rem;
	}

	.bundle-name {
		display: flex;
		align-items: center;
		gap: 10px;
		margin: 12px 0 0;
		font-family: var(--font-sans);
		font-size: 0.85rem;
	}

	.bundle-name label {
		font-weight: 600;
		white-space: nowrap;
	}

	.bundle-name input {
		flex: 1;
		min-width: 0;
		padding: 8px 12px;
		font-family: var(--font-sans);
		font-size: 0.9rem;
		background: var(--color-input-bg);
		border: 1.5px solid var(--color-border);
		border-radius: var(--radius-sm);
	}

	.bundle-name input:focus {
		outline: none;
		border-color: #e3120b;
	}

	.groups-panel {
		margin: 4px 0 18px;
		padding: 14px 16px;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-gray-100);
	}

	.groups-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 10px;
	}

	.groups-label {
		font-family: var(--font-sans);
		font-size: 0.78rem;
		font-weight: 700;
		color: var(--color-fg-light);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.groups-actions {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
	}

	.new-group {
		font-family: var(--font-sans);
		font-size: 0.85rem;
		font-weight: 600;
		padding: 6px 14px;
		border-radius: 999px;
		border: 1.5px solid var(--color-fg);
		background: var(--color-fg);
		color: var(--color-white);
		cursor: pointer;
	}

	.new-group:hover {
		opacity: 0.85;
	}

	.auto-group {
		font-family: var(--font-sans);
		font-size: 0.85rem;
		font-weight: 600;
		padding: 6px 14px;
		border-radius: 999px;
		border: 1.5px solid #6a4c93;
		background: #6a4c93;
		color: var(--color-white);
		cursor: pointer;
	}

	.auto-group:hover {
		opacity: 0.85;
	}

	.auto-group-note {
		font-family: var(--font-sans);
		font-size: 0.8rem;
		color: var(--color-fg-light);
		margin: 10px 0 0;
	}

	.group-chips {
		list-style: none;
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		margin: 12px 0 0;
		padding: 0;
	}

	.group-chip-row {
		display: flex;
		align-items: stretch;
	}

	.group-chip {
		display: flex;
		align-items: center;
		gap: 7px;
		font-family: var(--font-sans);
		font-size: 0.85rem;
		padding: 6px 10px 6px 8px;
		border-radius: 999px 0 0 999px;
		border: 1.5px solid var(--color-border);
		border-right: none;
		background: var(--color-white);
		color: var(--color-fg);
		cursor: pointer;
		max-width: 420px;
		transition: background 0.12s, border-color 0.12s, color 0.12s;
	}

	.group-chip:hover {
		border-color: var(--chip-color, var(--color-fg-light));
	}

	.group-chip.active {
		border-color: var(--chip-color);
		background: var(--chip-color);
		color: var(--color-white);
	}

	.group-chip.active .chip-sw {
		background: var(--color-white);
	}

	/* the "Single selection" chip stands alone (no remove button beside it)
	   and has no group color of its own, so it gets its own shape + active
	   treatment */
	.group-chip.single-chip {
		border-radius: 999px;
		border-right: 1.5px solid var(--color-border);
		border-style: dashed;
		padding: 6px 14px;
	}

	.group-chip.single-chip:hover {
		border-color: var(--color-fg-light);
	}

	.group-chip.single-chip.active {
		background: var(--color-fg);
		border-color: var(--color-fg);
		border-style: solid;
		color: var(--color-white);
	}

	.chip-sw {
		width: 9px;
		height: 9px;
		border-radius: 2px;
		flex: none;
		background: var(--chip-color);
	}

	.chip-name {
		/* show the full title -- wrap instead of truncating */
		white-space: normal;
		overflow-wrap: anywhere;
		word-break: break-word;
	}

	.chip-count {
		flex: none;
		opacity: 0.75;
		font-variant-numeric: tabular-nums;
	}

	.chip-remove {
		font-family: var(--font-sans);
		font-size: 0.95rem;
		line-height: 1;
		padding: 0 10px;
		border: 1.5px solid var(--color-border);
		border-radius: 0 999px 999px 0;
		background: var(--color-white);
		color: var(--color-fg-light);
		cursor: pointer;
	}

	.chip-remove:hover {
		color: #e3120b;
		border-color: #e3120b;
	}

	/* row dims when another line is isolated / the author total is hidden */
	.group-chip-row.dim {
		opacity: 0.4;
	}

	/* non-interactive pill (author-total + single-title legend rows) */
	.static-chip {
		cursor: default;
	}

	.static-chip:hover {
		border-color: var(--color-border);
	}

	/* the "Only" isolate toggle, between the pill and the × */
	.chip-only {
		display: flex;
		align-items: center;
		font-family: var(--font-sans);
		font-size: 0.72rem;
		font-weight: 600;
		padding: 0 10px;
		border: 1.5px solid var(--color-border);
		border-right: none;
		background: var(--color-white);
		color: var(--color-fg-light);
		cursor: pointer;
	}

	.chip-only:hover {
		color: var(--color-fg);
	}

	.chip-only.on {
		background: var(--color-fg);
		border-color: var(--color-fg);
		color: var(--color-white);
	}

	/* when the button is the last thing in the row (author total's Hide/Show) */
	.chip-only.end {
		border-right: 1.5px solid var(--color-border);
		border-radius: 0 999px 999px 0;
	}

	/* the "Edit" segment in a group pill (sits between the name and "Only") */
	.chip-edit {
		display: flex;
		align-items: center;
		font-family: var(--font-sans);
		font-size: 0.72rem;
		font-weight: 600;
		padding: 0 10px;
		border: 1.5px solid var(--color-border);
		border-right: none;
		background: var(--color-white);
		color: var(--color-fg-light);
		cursor: pointer;
	}
	.chip-edit:hover {
		color: var(--color-fg);
	}
	.chip-edit.on {
		background: var(--color-fg);
		border-color: var(--color-fg);
		color: var(--color-white);
	}

	.editing-hint {
		font-family: var(--font-sans);
		font-size: 0.82rem;
		color: var(--color-fg-light);
		margin: 12px 0 0;
	}

	.editing-hint strong {
		color: var(--color-fg);
	}

	.other-group-dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		flex: none;
		background: var(--chip-color, var(--color-fg-light));
	}

	/* top-author quick-pick chips (under the search box) */
	.top-authors {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 8px;
		margin: 14px 0 4px;
		font-family: var(--font-sans);
	}

	.quick-label {
		font-size: 0.82rem;
		font-weight: 600;
		color: var(--color-fg-light);
	}

	.chip {
		font-family: var(--font-sans);
		font-size: 0.82rem;
		padding: 4px 12px;
		border-radius: 999px;
		border: 1px solid var(--color-border);
		background: var(--color-white);
		color: var(--color-fg);
		cursor: pointer;
	}

	.chip:hover {
		background: var(--color-gray-100);
		border-color: var(--color-fg-light);
	}

	.chip.current {
		background: var(--color-fg);
		border-color: var(--color-fg);
		color: var(--color-white);
	}

	/* chart type toggle (line vs stacked area) + title sort toggle share a look */
	.mode-toggle {
		display: inline-flex;
		gap: 0;
		margin: 0 0 14px;
		border: 1px solid var(--color-border);
		border-radius: 999px;
		overflow: hidden;
		font-family: var(--font-sans);
	}

	.mode-toggle button {
		padding: 6px 16px;
		font-size: 0.85rem;
		background: var(--color-white);
		border: none;
		color: var(--color-fg-light);
		cursor: pointer;
	}

	.mode-toggle button + button {
		border-left: 1px solid var(--color-border);
	}

	.mode-toggle button.active {
		background: var(--color-fg);
		color: var(--color-white);
		font-weight: 600;
	}

	/* title list */
	.titles-header {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 10px;
		margin-bottom: 8px;
	}

	.title-filter {
		flex: 1;
		min-width: 180px;
		padding: 9px 12px;
		font-family: var(--font-sans);
		font-size: 0.9rem;
		background: var(--color-input-bg);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
	}

	.sort-toggle {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		font-family: var(--font-sans);
		font-size: 0.8rem;
	}

	.sort-label {
		color: var(--color-fg-light);
	}

	.sort-toggle button {
		padding: 5px 10px;
		font-size: 0.8rem;
		background: var(--color-white);
		border: 1px solid var(--color-border);
		border-radius: 999px;
		color: var(--color-fg-light);
		cursor: pointer;
	}

	.sort-toggle button.active {
		background: var(--color-fg);
		border-color: var(--color-fg);
		color: var(--color-white);
		font-weight: 600;
	}

	/* Title table: Work | Edition | Format | Checkouts (with a leading checkbox).
	   The header and every row share one grid template so columns line up. */
	.title-table {
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		max-height: 360px;
		overflow: auto; /* one scroll box: vertical for rows, horizontal for wide columns */
	}

	.tt-head,
	.tt-row,
	.work-header {
		display: grid;
		/* Work + Edition widths are user-resizable via the header drag handles.
		   Edition grows to fill, but never shrinks below --edition-w -- drag it
		   wider than the table and the whole table scrolls horizontally. */
		grid-template-columns: 62px var(--work-w, 150px) minmax(var(--edition-w, 240px), 1fr) auto 84px;
		align-items: center;
		gap: 10px;
		padding: 8px 12px;
	}

	/* one row per work; click to expand its editions */
	.work-header {
		font-family: var(--font-sans);
		font-size: 0.9rem;
		font-weight: 500;
		cursor: pointer;
		border-top: 1px solid var(--color-gray-100);
	}
	.title-list > li:first-child.work-header {
		border-top: none;
	}
	.work-header:hover {
		background: var(--color-gray-100);
	}

	/* a real work cluster (2+ editions) -- highlight it with an accent bar + tint
	   so it stands apart from single-edition rows */
	.work-header.cluster {
		background: #f7f3fb;
		box-shadow: inset 3px 0 0 0 #6a4c93;
		border-top-color: #e6dcf1;
	}
	.work-header.cluster:hover {
		background: #f1eaf8;
	}

	.work-header[draggable="true"] {
		cursor: grab;
	}

	/* a work row being hovered as a merge target while another work is dragged */
	.work-header.work-drop {
		background: #efe7f7;
		box-shadow: inset 0 0 0 2px #6a4c93;
	}

	.exclude-btn {
		font-family: var(--font-sans);
		font-size: 0.72rem;
		padding: 2px 9px;
		border-radius: 999px;
		border: 1px solid var(--color-border);
		background: var(--color-white);
		color: var(--color-fg-light);
		cursor: pointer;
	}
	.exclude-btn:hover {
		border-color: #c2255c;
		color: #c2255c;
	}

	.disclosure {
		background: none;
		border: none;
		cursor: pointer;
		font-size: 1.05rem;
		line-height: 1;
		color: #6a4c93;
		padding: 0 6px 0 0;
		flex: none;
	}
	.disclosure:hover {
		color: #4e3670;
	}
	.disclosure-spacer {
		width: 22px;
		flex: none;
	}
	.ed-summary {
		min-width: 0;
		text-align: left;
		background: none;
		border: none;
		cursor: pointer;
		font-family: var(--font-sans);
		font-size: 0.82rem;
		color: var(--color-fg-light);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.cluster-badge {
		display: inline-block;
		background: #efe7f7;
		color: #6a4c93;
		font-weight: 600;
		font-size: 0.72rem;
		padding: 1px 8px;
		border-radius: 999px;
	}
	.ed-single {
		color: var(--color-gray-400, #b0b0b0);
		font-size: 0.8rem;
		font-style: italic;
	}
	/* format column can show several badges for a multi-format work */
	.work-header .tt-format {
		display: flex;
		gap: 4px;
		flex-wrap: wrap;
		justify-content: flex-end;
	}
	/* indent the edition title when it's shown nested under an expanded work */
	.tt-edition.indent {
		padding-left: 20px;
	}

	.tt-head {
		position: sticky;
		top: 0;
		z-index: 1;
		font-family: var(--font-sans);
		font-size: 0.7rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--color-fg-light);
		background: var(--color-gray-100);
		border-bottom: 1px solid var(--color-border);
	}

	/* clickable header labels that set the "by work" ordering */
	.col-sort {
		font: inherit;
		text-transform: inherit;
		letter-spacing: inherit;
		color: inherit;
		background: none;
		border: none;
		padding: 0;
		cursor: pointer;
		white-space: nowrap;
	}

	.col-sort:hover {
		color: var(--color-fg);
	}

	.col-sort.active {
		color: var(--color-fg);
	}

	.tt-count .col-sort {
		width: 100%;
		text-align: right;
	}

	/* the draggable divider on the right edge of a resizable header cell */
	.tt-work,
	.tt-edition {
		position: relative;
	}

	.col-resize {
		position: absolute;
		top: 0;
		right: -5px;
		width: 10px;
		height: 100%;
		cursor: col-resize;
		z-index: 2;
	}

	.col-resize::after {
		content: "";
		position: absolute;
		top: 3px;
		bottom: 3px;
		left: 4px;
		width: 2px;
		background: var(--color-border);
		border-radius: 1px;
	}

	.col-resize:hover::after {
		background: var(--color-fg-light);
	}

	.title-list {
		list-style: none;
		margin: 0;
		padding: 0;
	}

	.title-list li + li .tt-row {
		border-top: 1px solid var(--color-gray-100);
	}

	/* a heavier divider where a new work begins (only in "by work" sort) */
	.title-list li.work-start + li.work-start,
	.title-list li.work-start {
		border-top: 1px solid var(--color-border);
	}
	.title-list li.work-start:first-child {
		border-top: none;
	}

	.tt-row {
		cursor: pointer;
		font-family: var(--font-sans);
		font-size: 0.9rem;
	}

	.tt-row:hover {
		background: var(--color-gray-100);
	}

	.tt-row.selected {
		background: var(--color-gray-100);
		font-weight: 600;
		box-shadow: inset 3px 0 0 0 var(--chip-color, var(--color-fg));
	}

	.tt-work {
		font-weight: 600;
		color: var(--color-fg);
		min-width: 0;
		display: flex;
		flex-direction: row;
		align-items: center;
		gap: 4px;
	}

	.tt-work-name {
		overflow: hidden;
		text-overflow: ellipsis;
		max-width: 100%;
	}

	/* the "+ whole work" option under a work's name -- adds all its editions as
	   one aggregated line (a button, not a second checkbox) */
	.plot-all {
		font-family: var(--font-sans);
		font-size: 0.68rem;
		font-weight: 600;
		padding: 1px 7px;
		border-radius: 999px;
		border: 1px solid var(--color-border);
		background: var(--color-white);
		color: #6a4c93;
		cursor: pointer;
		white-space: nowrap;
	}

	.plot-all:hover {
		border-color: #6a4c93;
	}

	.plot-all.on {
		background: #6a4c93;
		border-color: #6a4c93;
		color: var(--color-white);
	}

	.tt-edition {
		display: flex;
		align-items: center;
		gap: 8px;
		min-width: 0;
		color: var(--color-fg-light);
	}

	.tt-edition .t-name {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.tt-check {
		display: flex;
		align-items: center;
	}

	.tt-plot {
		display: flex;
		align-items: center;
		justify-content: center;
	}

	/* let the "Add to plot" header wrap to two lines, centered */
	.tt-head .tt-plot {
		white-space: normal;
		text-align: center;
		line-height: 1.15;
	}

	/* the work-level "plot the whole work" tick -- a distinct color from the
	   per-edition checkbox so it reads as a different, work-level action */
	.viewer .plot-check {
		accent-color: #6a4c93;
		width: 18px;
		height: 18px;
	}

	.tt-count {
		text-align: right;
		color: var(--color-fg-light);
		font-variant-numeric: tabular-nums;
	}

	.badge {
		flex: none;
		font-size: 0.66rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		padding: 2px 8px;
		border-radius: 999px;
		white-space: nowrap;
	}

	.badge-ebook {
		background: #e7f0ff;
		color: #1c4ed8;
	}

	.badge-audiobook {
		background: #f3eafe;
		color: #7048e8;
	}

	.badge-print {
		background: #eaf6ee;
		color: #1f7a4d;
	}

	.badge-other {
		background: var(--color-gray-100);
		color: var(--color-fg-light);
	}

	.titles-more {
		font-family: var(--font-sans);
		font-size: 0.8rem;
		color: var(--color-fg-light);
		margin: 8px 2px 0;
	}

	.table-hint {
		font-family: var(--font-sans);
		font-size: 0.8rem;
		color: var(--color-fg-light);
		margin: 0 2px 8px;
	}
	.table-hint em {
		font-style: normal;
		font-weight: 600;
		color: #c2255c;
	}

	.hint {
		font-family: var(--font-sans);
		color: var(--color-fg-light);
		text-align: center;
		margin-top: 28px;
	}

	/* instant, cursor-following tooltip showing a title's full text */
	.title-tip {
		position: fixed;
		z-index: 100;
		max-width: 360px;
		padding: 7px 10px;
		background: var(--color-fg);
		color: var(--color-white);
		font-family: var(--font-sans);
		font-size: 0.82rem;
		line-height: 1.35;
		border-radius: 6px;
		box-shadow: 0 6px 18px rgba(0, 0, 0, 0.18);
		pointer-events: none;
		word-break: break-word;
	}

	.load-error {
		font-family: var(--font-sans);
		font-size: 0.9rem;
		color: #b00020;
		background: #fdecef;
		border: 1px solid #f5c2cb;
		border-radius: var(--radius-sm);
		padding: 10px 12px;
		margin: 16px 0 0;
	}

	/* visually hidden but available to screen readers (form labels, etc.) */
	.sr-only {
		position: absolute;
		width: 1px;
		height: 1px;
		padding: 0;
		margin: -1px;
		overflow: hidden;
		clip: rect(0 0 0 0);
		white-space: nowrap;
		border: 0;
	}

	.no-results {
		font-family: var(--font-sans);
		font-size: 0.9rem;
		color: var(--color-fg-light);
		margin: 8px 4px 0;
	}

	.loading {
		display: flex;
		align-items: center;
		gap: 10px;
		font-family: var(--font-sans);
		color: var(--color-fg-light);
		margin: 24px 0;
	}

	.spinner {
		width: 18px;
		height: 18px;
		border: 2.5px solid var(--color-gray-200, #e0e0e0);
		border-top-color: var(--color-fg);
		border-radius: 50%;
		animation: spin 0.7s linear infinite;
	}

	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.spinner {
			animation-duration: 2.5s;
		}
	}

	/* phones: tighten things up (the title table keeps its own horizontal
	   scroll, so nothing pushes the page wider than the screen) */
	@media (max-width: 600px) {
		.author {
			margin-top: 28px;
		}

		.author h2 {
			font-size: 1.6rem;
		}

		.groups-panel {
			padding: 12px;
		}

		.group-chip {
			max-width: 160px;
		}

		.chip-name {
			max-width: 120px;
		}

		.title-table {
			max-height: 300px;
		}
	}
</style>
