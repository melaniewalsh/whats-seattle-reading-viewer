<script>
	// StackedViewer.svelte
	import { onMount, tick } from "svelte";
	import debounce from "lodash.debounce";
	import LineChart from "$components/StackedAreaChart.svelte";
	import YearBrush from "$components/YearBrush.svelte";
	import Switch from "$components/ui/Switch.svelte";
	import { getMonths, searchAuthors, searchTitles, titleIndexMin, getAuthor, getAllCheckouts, randomAuthor, randomTitle } from "$components/db.js";

	// "author" (default): search authors. "title": reverse lookup — search a title,
	// resolve to its author, open the author's drilldown with that work highlighted.
	// landing: "overview" (the "All" tab -> library-wide total trend) or "search"
	// (the "By author" tab -> open straight to the search box).
	let { searchMode = "author", landing = "overview" } = $props();

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
	let hlWorkKey = $state(null); // work key highlighted by hovering its pill or its table row (they're linked)
	let autoGroupNote = $state(""); // feedback after "Group editions into works"
	let loadError = $state(""); // message when an author fails to load
	let loading = $state(false); // true while an author's data is being fetched
	let hoverTip = $state(null); // { text, x, y } instant tooltip for full edition titles
	let workColW = $state(150); // resizable width (px) of the title-table Work column
	let editionColW = $state(240); // min width (px) of the Edition column (drag to see full titles)
	let yearLo = $state(0); // first month index shown (set by the YearBrush)
	let yearHi = $state(0); // last month index shown (inclusive)
	let currentSlug = $state(null); // slug of the selected author (for shareable URLs)
	let isOverview = $state(false); // true when showing the library-wide "all checkouts" landing view (no per-title data)
	let mobileTableOpen = $state(false); // on narrow screens the title table opens as a drawer
	let tableCollapsed = $state(false); // on desktop the title table can be collapsed to just its header
	let autoHidAuthorTotal = $state(false); // whether we've auto-hidden the author-total line for this author yet
	let shareMsg = $state(""); // transient toast after copying a share link
	let shareOpen = $state(false); // whether the share-platform popover is open
	let chartWrap = $state(null); // ref to the chart container, for the PNG export
	let sideEl = $state(null); // ref to the titles panel, for keeping it still when ticking

	// Ticking a work grows the "on the chart" panel above the (stacked) table,
	// which would shove the table -- and the row under the cursor -- downward.
	// Run the change, then nudge the window scroll by however much the table
	// moved so it stays put. (On mobile the table is a fixed drawer, so its top
	// doesn't move and this is a no-op.)
	async function keepTableStill(fn) {
		const y0 = sideEl ? sideEl.getBoundingClientRect().top : 0;
		fn();
		await tick();
		const dy = (sideEl ? sideEl.getBoundingClientRect().top : 0) - y0;
		if (dy) window.scrollBy(0, dy);
	}

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
		// A shared link (?author=slug) opens that author; otherwise the default
		// landing view is the library-wide "all checkouts" line, from which the
		// user searches for a specific author.
		let wantSlug = null;
		try { wantSlug = new URLSearchParams(window.location.search).get("author"); } catch {}
		if (wantSlug) {
			const a = authors.find((x) => x.slug === wantSlug)
					|| (await searchAuthors(wantSlug.replace(/-/g, " "), 8)).find((x) => x.slug === wantSlug);
			if (a) { await selectAuthor(a); return; }
		}
		// "By author" (landing="search") opens straight to the search box (current
		// stays null -> the search-first empty state renders). "All" and the
		// By-title tab still load the overview / default title.
		if (searchMode === "author" && landing === "search") {
			loading = false;
			return;
		}
		await loadOverview();
	});

	// Load the default "all Seattle checkouts" view (a single total line).
	async function loadOverview() {
		loadError = "";
		loading = true;
		const data = await getAllCheckouts().catch(() => null);
		if (!data) {
			loading = false;
			loadError = "Couldn't load the Seattle-wide totals right now. Search for an author to explore the data.";
			return;
		}
		current = {
			name: "All Seattle Public Library checkouts",
			total: data.total.reduce((s, v) => s + v, 0),
			series: data.total,
			formats: { print: data.print, ebook: data.ebook, audiobook: data.audiobook },
			titles: []
		};
		currentSlug = null;
		isOverview = true;
		// reset the controls
		groups = []; singleIdxs = []; activeGroupId = null; titleFilter = "";
		chartMode = "line"; isolatedKeys = []; showAuthorTotal = true;
		autoHidAuthorTotal = false; autoGroupNote = ""; workAssign = {};
		expandedWorks = []; workOrder = "checkouts"; titleSort = "work";
		yearLo = 0; yearHi = Math.max(months.length - 1, 0);
		mobileTableOpen = false; tableCollapsed = false; query = ""; results = [];
		try {
			const url = new URL(window.location.href);
			url.searchParams.delete("author");
			window.history.replaceState({}, "", url);
		} catch {}
		loading = false;
	}

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
		results = searchMode === "title"
			? await searchTitles(needle, 75)
			: await searchAuthors(needle, 75);
	}, 120);
	$effect(() => runSearch(query));

	// A few top titles to seed the "By title" quick-picks (like the author chips).
	let topTitles = $state([]);
	let titleMin = $state(0); // min all-time checkouts a title needs to be searchable
	// Load-once flag (plain, non-reactive): if we keyed off topTitles.length and the
	// index is empty (e.g. not yet on R2), setting topTitles = [] would re-trigger the
	// effect forever. Fetch exactly once when the title tab is first opened.
	let titlePicksLoaded = false;
	$effect(() => {
		if (searchMode === "title" && !titlePicksLoaded) {
			titlePicksLoaded = true;
			searchTitles("", 8).then((t) => (topTitles = t));
			titleIndexMin().then((m) => (titleMin = m));
		}
	});
	// Round down to a clean figure so the note never overstates the threshold.
	const titleMinLabel = $derived(titleMin ? (Math.floor(titleMin / 500) * 500).toLocaleString() : "");

	// When the "By title" tab is first opened, seed it with a well-known title
	// (Baldwin's The Fire Next Time) instead of the Seattle-wide overview, so the
	// tab lands on a concrete example rather than a blank prompt. Load-once flag.
	let titleDefaultLoaded = false;
	$effect(() => {
		if (searchMode === "title" && months.length && !titleDefaultLoaded) {
			titleDefaultLoaded = true;
			loadDefaultTitle();
		}
	});
	async function loadDefaultTitle() {
		// ?title=<work> (e.g. from a Top-works link) opens that title; otherwise
		// seed the tab with a well-known example.
		let want = null;
		try { want = new URLSearchParams(window.location.search).get("title"); } catch {}
		try {
			const r = (await searchTitles(want || "the fire next time", 5))[0];
			if (r) await selectTitle(r, { scroll: false });
		} catch {}
	}

	// "Surprise me": jump to a random author (or title in title mode).
	async function surpriseMe() {
		query = "";
		const pick = searchMode === "title" ? await randomTitle() : await randomAuthor();
		if (!pick) return;
		if (searchMode === "title") await selectTitle(pick);
		else await selectAuthor(pick);
	}

	// Switching "By title" -> "By author" should drop the single-book focus and
	// show the WHOLE author's checkouts (their total line), not the one title you
	// happened to be looking at. (The author stays loaded; we just clear the plot.)
	let prevSearchMode = searchMode;
	$effect(() => {
		const mode = searchMode;
		if (mode !== prevSearchMode) {
			if (prevSearchMode === "title" && mode === "author" && current && !isOverview) {
				groups = [];
				singleIdxs = [];
				activeGroupId = null;
				isolatedKeys = [];
				showAuthorTotal = true;
				autoHidAuthorTotal = false;
				chartMode = "line";
			}
			prevSearchMode = mode;
		}
	});

	// Reverse lookup: open a title's author, then plot the searched BOOK as one
	// line — gathering every edition of it. We use the SAME work-clustering as the
	// title table (normalizeWorkKey) so a title search pulls together exactly the
	// editions shown as one work there — including alt-title forms the plain
	// matcher missed (e.g. "Slaughterhouse-five, or, The children's crusade").
	async function selectTitle(r, { scroll = true } = {}) {
		await selectAuthor({ slug: r.slug, name: r.author });
		await tick();
		if (!current) return;
		const want = normalizeWorkKey(r.title);
		// Seed from the searched title's own edition(s)...
		let seed = [];
		current.titles.forEach((t, idx) => { if (normalizeWorkKey(t.title) === want) seed.push(idx); });
		if (!seed.length) { // loose fallback: substring match on the normalized work key
			current.titles.forEach((t, idx) => {
				const wk = normalizeWorkKey(t.title);
				if (!seed.length && want && wk && (wk.includes(want) || want.includes(wk))) seed = [idx];
			});
		}
		if (!seed.length) return;
		// ...then gather the WHOLE work the seed belongs to via effectiveKey, which
		// respects any saved/restored custom grouping (a translation you dragged in,
		// an edition you split out) rather than re-clustering purely by title key.
		const workKey = effectiveKey(seed[0], current.titles[seed[0]].title);
		let idxs = [];
		current.titles.forEach((t, idx) => { if (effectiveKey(idx, t.title) === workKey) idxs.push(idx); });
		if (!idxs.length) idxs = seed;
		idxs.forEach((i) => releaseTitle(i));
		const name = cleanTitleForDisplay(current.titles[idxs[0]].title) || r.title;
		groups = [...groups, { id: ++groupIdCounter, name, idxs }];
		hlWorkKey = `g${groupIdCounter}`;
		await tick();
		if (scroll) chartWrap?.scrollIntoView?.({ block: "start", behavior: "smooth" });
	}

	// When the first work is plotted on a line chart, auto-hide the busy
	// author-total line so the added trend line stands out. Only fires once per
	// author (tracked by autoHidAuthorTotal), so the Hide/Show toggle still wins
	// after that.
	$effect(() => {
		if (chartMode === "line" && groups.length + singleIdxs.length > 0 && !autoHidAuthorTotal) {
			showAuthorTotal = false;
			autoHidAuthorTotal = true;
		}
	});

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
		currentSlug = a.slug;
		isOverview = false;
		mobileTableOpen = false;
		// reflect the author in the URL so the page is shareable / reloadable
		try {
			const url = new URL(window.location.href);
			url.searchParams.set("author", a.slug);
			window.history.replaceState({}, "", url);
		} catch {}
		// reset the controls for the new author
		groups = [];
		activeGroupId = null;
		singleIdxs = [];
		titleFilter = "";
		chartMode = "line";
		isolatedKeys = [];
		showAuthorTotal = true;
		autoHidAuthorTotal = false;
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
		// Re-apply any grouping the user saved for this author (localStorage).
		restoreGroupings(a.slug);
	}

	// A shareable link (reopens the current author) plus a caption.
	function shareTarget() {
		let link = window.location.href;
		try {
			const url = new URL(window.location.href);
			if (currentSlug) url.searchParams.set("author", currentSlug);
			link = url.toString();
		} catch {}
		const text = `What Is Seattle Reading? — ${current ? displayName(current.name) : ""}`;
		return { link, text };
	}

	// Open a platform's composer, having copied the chart image to the clipboard
	// so it can be pasted in (share URLs can't attach an image directly). The
	// promise-valued ClipboardItem keeps the write inside the click gesture, and
	// window.open runs in the same tick so the popup isn't blocked.
	function shareTo(platform) {
		const { link, text } = shareTarget();
		let copied = false;
		try {
			if (navigator.clipboard && window.ClipboardItem) {
				navigator.clipboard.write([new ClipboardItem({ "image/png": renderChartBlob() })]).catch(() => {});
				copied = true;
			}
		} catch {}
		const u = encodeURIComponent(link);
		const t = encodeURIComponent(text);
		const urls = {
			facebook: `https://www.facebook.com/sharer/sharer.php?u=${u}`,
			twitter: `https://twitter.com/intent/tweet?url=${u}&text=${t}`,
			bluesky: `https://bsky.app/intent/compose?text=${encodeURIComponent(text + " " + link)}`,
			linkedin: `https://www.linkedin.com/sharing/share-offsite/?url=${u}`,
		};
		if (urls[platform]) window.open(urls[platform], "_blank", "noopener,noreferrer,width=600,height=540");
		shareOpen = false;
		if (copied) {
			shareMsg = "Chart image copied — paste it (⌘/Ctrl+V) into your post";
			setTimeout(() => (shareMsg = ""), 4500);
		}
	}

	async function copyShareLink() {
		const { link } = shareTarget();
		try { await navigator.clipboard.writeText(link); } catch {}
		shareMsg = "Link copied!";
		setTimeout(() => (shareMsg = ""), 2000);
		shareOpen = false;
	}

	// Copy the chart image itself to the clipboard (paste it straight into any
	// post/doc). Falls back to downloading if the browser can't copy images.
	async function copyImage() {
		shareOpen = false;
		try {
			if (!(navigator.clipboard && window.ClipboardItem)) throw new Error("no clipboard");
			await navigator.clipboard.write([new ClipboardItem({ "image/png": renderChartBlob() })]);
			shareMsg = "Chart image copied to clipboard";
		} catch {
			const blob = await renderChartBlob();
			if (blob) saveBlob(blob, `seattle-reading-${currentSlug || "chart"}.png`);
			shareMsg = "Image saved (clipboard unavailable)";
		}
		setTimeout(() => (shareMsg = ""), 2600);
	}

	// Rasterize the chart SVG to a titled PNG (Blob), reused by download + share.
	async function renderChartBlob() {
		const src = chartWrap?.querySelector("svg");
		if (!src) return null;
		// Inline computed styles onto a clone: the SVG is painted by scoped
		// component CSS that would be lost once it's serialized on its own.
		const clone = src.cloneNode(true);
		const from = src.querySelectorAll("*");
		const to = clone.querySelectorAll("*");
		const PROPS = ["fill", "stroke", "stroke-width", "stroke-dasharray", "stroke-linecap", "stroke-linejoin", "opacity", "font-family", "font-size", "font-weight", "text-anchor", "color"];
		to.forEach((node, i) => {
			const cs = getComputedStyle(from[i]);
			node.setAttribute("style", PROPS.map((p) => `${p}:${cs.getPropertyValue(p)}`).join(";"));
		});
		const w = Math.round(src.clientWidth || src.viewBox.baseVal.width || 800);
		const h = Math.round(src.clientHeight || src.viewBox.baseVal.height || 400);
		clone.setAttribute("width", w);
		clone.setAttribute("height", h);
		clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
		const svgUrl = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(new XMLSerializer().serializeToString(clone));
		const img = new Image();
		await new Promise((res, rej) => { img.onload = res; img.onerror = rej; img.src = svgUrl; });
		const scale = 2, padX = 28, titleH = 68, footH = 40;
		const canvas = document.createElement("canvas");
		const ctx = canvas.getContext("2d");
		// Lay out the legend (wrapped) first so we know how tall to make the canvas.
		const LEG_FONT = '600 13px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
		// When lines are isolated, the exported chart draws only those — so the
		// legend should list only those too (not every plotted title).
		const legItems = isolatedKeys.length ? legendItems.filter((it) => it.key != null && isolatedKeys.includes(it.key)) : legendItems;
		const showLegend = legItems.length >= 1;
		const legLH = 22, legSw = 12, legGapSw = 6, legGapItem = 20;
		const legLines = [];
		if (showLegend) {
			ctx.font = LEG_FONT;
			let line = [], lineW = 0;
			for (const it of legItems) {
				const iw = legSw + legGapSw + ctx.measureText(it.label).width;
				if (lineW + iw > w && line.length) { legLines.push(line); line = []; lineW = 0; }
				line.push(it); lineW += iw + legGapItem;
			}
			if (line.length) legLines.push(line);
		}
		const legendH = showLegend ? legLines.length * legLH + 12 : 0;

		canvas.width = (w + padX * 2) * scale;
		canvas.height = (h + titleH + legendH + footH) * scale;
		ctx.scale(scale, scale);
		ctx.fillStyle = "#ffffff";
		ctx.fillRect(0, 0, canvas.width, canvas.height);
		ctx.textBaseline = "alphabetic";
		ctx.fillStyle = "#1a1a1a";
		ctx.font = '600 22px Georgia, "Times New Roman", serif';
		ctx.fillText(current ? (isOverview ? current.name : displayName(current.name)) : "", padX, 34);
		ctx.fillStyle = "#666666";
		ctx.font = '13px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
		ctx.fillText(plotTitle || (current ? `${abbrevCount(current.total)} checkouts` : ""), padX, 54);
		ctx.drawImage(img, padX, titleH, w, h);
		if (showLegend) {
			ctx.font = LEG_FONT;
			ctx.textBaseline = "middle";
			let ly = titleH + h + 18;
			for (const line of legLines) {
				let lx = padX;
				for (const it of line) {
					ctx.fillStyle = it.color;
					ctx.fillRect(lx, ly - legSw / 2, legSw, legSw);
					ctx.fillStyle = "#333333";
					ctx.fillText(it.label, lx + legSw + legGapSw, ly + 0.5);
					lx += legSw + legGapSw + ctx.measureText(it.label).width + legGapItem;
				}
				ly += legLH;
			}
			ctx.textBaseline = "alphabetic";
		}
		ctx.fillStyle = "#999999";
		ctx.font = '11px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
		ctx.fillText("What Is Seattle Reading?  \u00b7  Seattle Public Library checkouts", padX, titleH + h + legendH + 24);
		return await new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
	}

	function saveBlob(blob, name) {
		const a = document.createElement("a");
		a.href = URL.createObjectURL(blob);
		a.download = name;
		a.click();
		setTimeout(() => URL.revokeObjectURL(a.href), 1000);
	}

	async function downloadChart() {
		const blob = await renderChartBlob();
		if (blob) saveBlob(blob, `seattle-reading-${currentSlug || "chart"}.png`);
	}

	// Share the current view AS AN IMAGE via the native share sheet (mobile and
	// some desktop browsers). The platform-link buttons can't attach a picture --
	// they only show the page's preview image -- so this is the way to actually
	// post the chart itself. Falls back to saving the PNG to attach by hand.
	async function shareImage() {
		shareOpen = false;
		const blob = await renderChartBlob();
		if (!blob) return;
		const name = `seattle-reading-${currentSlug || "chart"}.png`;
		const file = new File([blob], name, { type: "image/png" });
		const { link, text } = shareTarget();
		if (navigator.canShare && navigator.canShare({ files: [file] })) {
			try { await navigator.share({ files: [file], title: text, text: `${text}\n${link}` }); } catch {}
			return;
		}
		saveBlob(blob, name);
		shareMsg = "Image saved — attach it to your post";
		setTimeout(() => (shareMsg = ""), 3200);
	}

	// Abbreviate a big checkout count: 28,244,964 -> "28.2M". Smaller totals
	// (authors) stay exact.
	function abbrevCount(n) {
		return n >= 1e6 ? (n / 1e6).toFixed(1).replace(/\.0$/, "") + "M" : n.toLocaleString();
	}

	// Short label shown in a title's format badge.
	function formatLabel(f) {
		return {ebook: "ebook", audiobook: "audio", print: "print", largeprint: "large print", other: "other"}[f] || f;
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
		// Drop a trailing life-dates clause the catalog appends ("Baldwin, James,
		// 1924-1987" or "james baldwin, 1924-1987") so it isn't flipped to the front.
		n = n.replace(/,\s*\d{4}(?:\s*-\s*\d{0,4})?\.?\s*$/, "");
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
		// Bilingual catalog records use "Original Title = English parallel title"
		// (e.g. "Harī Pottā ... = Harry Potter and the half-blood prince"). Keep the
		// English parallel title so foreign editions cluster with the English work.
		if (/\s=\s/.test(t)) t = t.split(/\s=\s/).pop();
		// Classic alternate-title form "Main Title, or, The Alternate Title"
		// (Slaughterhouse-Five, or, The Children's Crusade; Moby-Dick, or, The
		// Whale) -- drop everything from ", or, " on so an edition catalogued with
		// the alt-title clusters with plain "Slaughterhouse-Five". The SECOND comma
		// is the tell: alt-titles write ", or, X" while lists write ", or X"
		// ("Beg, Borrow, or Steal"), so requiring it avoids over-matching.
		t = t.replace(/,\s+or,\s+.*$/i, "");
		t = t.replace(/&/g, " and "); // "beasts & where" -> "beasts and where"
		t = t.replace(/\([^)]*\)/g, " "); // drop "(unabridged)" etc.
		// Some catalog titles have an UNCLOSED paren, e.g. "The Inn at Rose Harbor
		// (with bonus short story: Rose Harbor Series, Book 1" -- the balanced rule
		// above misses it, so also strip a dangling "(" clause to end of string.
		t = t.replace(/\s*\([^)]*$/, " ");
		t = t.replace(/\[[^\]]*\]/g, " "); // drop cataloging brackets: "[text ]", "[sound recording]", etc.
		// Repeatedly strip a trailing ":"/";" segment when it's edition/format noise
		// (series/book/volume, "the original screenplay", "read by <narrator>",
		// illustrated/anniversary editions, "a novel", etc.) OR an "or, ..."
		// alternative title (e.g. "Slaughterhouse-Five: or, The Children's Crusade"
		// is the same book). Stop at the first segment that's a real distinct
		// subtitle (e.g. "The Crimes of Grindelwald"), so those stay separate.
		const NOISE = /(book|bk|series|volume|vol|part|edition|unabridged|abridged|screenplay|read by|narrated|illustrated|deluxe|anniversary|collector|special|movie|film|adapted|reissue|boxe?d? ?set|complete|novel|novella|memoir|thriller|mystery|story|stories|tale|tales|romance|biography|autobiography|poems|essays|playscript|litrpg|gamelit|\bscript\b|\bproduction|\bserie|\blivre|\btome|\blibro|\btomo|\bedicion)/i;
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
				? `Showing the top ${works.length} works (${merged} editions). Tick more works in the table, drag titles between works, or remove a work to adjust.`
				: "No works to show for this author.";
	}

	// Whether anything is currently plotted on top of the author-total line.
	const hasPlotted = $derived(groups.some((g) => g.idxs.length) || singleIdxs.length > 0);

	// The "Show top works" button doubles as a toggle: once works are plotted it
	// clears them and returns to the author-only view.
	function toggleTopWorks() {
		if (hasPlotted) {
			// Clear the chart back to just the author's total line. KEEP the user's
			// work grouping (workAssign) -- that lives in the table, not the chart,
			// so clearing the graph shouldn't discard it.
			groups = [];
			singleIdxs = [];
			activeGroupId = null;
			isolatedKeys = [];
			autoGroupNote = "";
			showAuthorTotal = true;
			autoHidAuthorTotal = false;
			chartMode = "line";
		} else {
			autoGroupByWork({ keepChartMode: true });
			chartMode = "area"; // show the works stacked as an area chart
		}
	}

	// The work key an edition actually belongs to. Precedence:
	//   1. If it's in a selection group, that GROUP is its work -- so editing a
	//      group's membership (add/remove a title) moves it in the table too, and
	//      the pills and the table's work clusters stay in sync.
	//   2. Else a manual table override (drag-merge target, or `excl-<idx>` when
	//      excluded).
	//   3. Else the auto-computed key.
	function effectiveKey(idx, title) {
		for (const g of groups) if (g.idxs.includes(idx)) return `g${g.id}`;
		return workAssign[idx] ?? normalizeWorkKey(title);
	}

	// Pull one edition out of its work cluster into its own singleton work. Also
	// take it out of any group first, so the exclusion actually sticks.
	function excludeEdition(idx) {
		releaseTitle(idx);
		workAssign = { ...workAssign, [idx]: `excl-${idx}` };
	}

	// Merge one work into another: reassign every edition currently in srcKey to
	// destKey (used when a work row is dragged onto another in the table).
	function mergeWorks(srcKey, destKey) {
		if (!current || srcKey === destKey) return;
		const srcIdxs = [];
		current.titles.forEach((t, idx) => {
			if (effectiveKey(idx, t.title) === srcKey) srcIdxs.push(idx);
		});
		if (!srcIdxs.length) return;
		// If the destination work is PLOTTED (a group), fold the source editions
		// into that group so its LINE updates -- not just the table clustering.
		// (workAssign alone re-clusters the table but leaves the group's series,
		// and therefore its plotted line, unchanged.)
		if (/^g\d+$/.test(destKey)) {
			const g = groups.find((gr) => `g${gr.id}` === destKey);
			if (g) {
				srcIdxs.forEach((i) => releaseTitle(i));
				g.idxs = [...new Set([...g.idxs, ...srcIdxs])];
				groups = groups.filter((gr) => gr.idxs.length || gr.id === activeGroupId);
			}
			return;
		}
		const updates = {};
		srcIdxs.forEach((idx) => (updates[idx] = destKey));
		workAssign = { ...workAssign, ...updates };
	}

	// --- Persist manual work groupings (localStorage, per author) -------------
	// GROUPING only (not which lines are plotted). Saved as clusters of TITLE
	// STRINGS -- not edition indices -- so the choices survive a data rebuild that
	// reorders titles. Per-browser; a title renamed in a future rebuild is quietly
	// dropped rather than misapplied.
	let savedGrouping = $state(false); // this author has a saved custom grouping
	const worksLSKey = (slug) => `spl:works:${slug}`;

	// Snapshot the current grouping as clusters of title strings.
	function currentClusters() {
		const byKey = new Map();
		current.titles.forEach((t, idx) => {
			const k = effectiveKey(idx, t.title);
			if (!byKey.has(k)) byKey.set(k, []);
			byKey.get(k).push(t.title);
		});
		return [...byKey.values()];
	}

	function saveGroupings() {
		if (!current || !currentSlug) return;
		try {
			localStorage.setItem(worksLSKey(currentSlug), JSON.stringify(currentClusters()));
			savedGrouping = true;
			autoGroupNote = "Groupings saved — they'll be restored next time you open this author (in this browser).";
		} catch {}
	}

	// Revert to automatic clustering and forget the saved grouping for this author.
	function clearGroupings() {
		if (currentSlug) { try { localStorage.removeItem(worksLSKey(currentSlug)); } catch {} }
		workAssign = {};
		groups = [];
		singleIdxs = [];
		activeGroupId = null;
		isolatedKeys = [];
		expandedWorks = [];
		chartMode = "line";
		showAuthorTotal = true;
		autoHidAuthorTotal = false;
		savedGrouping = false;
		autoGroupNote = "Reset to automatic grouping.";
	}

	// On opening an author, re-apply their saved grouping by forcing each saved
	// cluster's editions to share a work key (matched by title string).
	function restoreGroupings(slug) {
		let clusters = null;
		try {
			const raw = localStorage.getItem(worksLSKey(slug));
			if (raw) clusters = JSON.parse(raw);
		} catch {}
		if (!current || !Array.isArray(clusters) || !clusters.length) { savedGrouping = false; return; }
		const idxByTitle = new Map();
		current.titles.forEach((t, idx) => { if (!idxByTitle.has(t.title)) idxByTitle.set(t.title, idx); });
		const assign = {};
		clusters.forEach((titles, c) => {
			for (const title of titles) {
				const idx = idxByTitle.get(title);
				if (idx != null) assign[idx] = `sv${c}`;
			}
		});
		workAssign = assign;
		savedGrouping = true;
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
		// A group-defined work takes its name from the group label (which the user
		// may have renamed), so the table row matches the pill.
		for (const g of groups) {
			const w = m.get(`g${g.id}`);
			if (w) w.name = groupLabel(g);
		}
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

	// Drop an edition (dragged from the table) onto a work row: fold it into that
	// work. If the work is a plotted group, join the group; otherwise reassign the
	// edition's work key (pulling it out of any group first so it sticks).
	function addEditionToWork(idx, workKey) {
		if (idx == null || !workKey) return;
		if (/^g\d+$/.test(workKey)) {  // a plotted group key "g<id>" (not a work key like "greatgatsby")
			const g = groups.find((gr) => `g${gr.id}` === workKey);
			if (g && !g.idxs.includes(idx)) {
				releaseTitle(idx);
				g.idxs = [...g.idxs, idx];
			}
		} else {
			releaseTitle(idx);
			workAssign = { ...workAssign, [idx]: workKey };
		}
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
	const TITLE_RENDER_CAP = 400;
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
	const WORK_BLOCK_CAP = 400;
	const workBlocks = $derived.by(() => {
		if (titleSort !== "work" || !current) return [];
		// Build blocks straight from workGroups (the WHOLE author's works) rather
		// than from the filtered rows, so each work's edition count and total stay
		// STATIC regardless of the filter. The filter only decides which works show
		// and flags which editions match (highlighted) -- searching within a work
		// must never make it look like the cluster has fewer editions/checkouts.
		const f = titleFilter.trim().toLowerCase();
		const blocks = [];
		for (const [key, w] of workGroups) {
			const nameMatch = f ? w.name.toLowerCase().includes(f) : false;
			const editions = w.idxs.map((idx) => {
				const t = current.titles[idx];
				return {
					...t,
					idx,
					workKey: key,
					workName: cleanTitleForDisplay(t.title) || t.title,
					match: f ? (nameMatch || t.title.toLowerCase().includes(f)) : false
				};
			});
			const matchCount = f ? editions.filter((e) => e.match).length : 0;
			// While filtering, show a work only if it (or an edition) matches -- but
			// still show ALL of its editions and its full count/total.
			if (f && !nameMatch && matchCount === 0) continue;
			editions.sort((x, y) => y.total - x.total);
			blocks.push({ key, name: w.name, editions, total: w.total, matchCount });
		}
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
	// While a filter is active, auto-expand any work with a matching edition so the
	// highlighted rows are visible without a manual click.
	const filtering = $derived(!!titleFilter.trim());
	const workOpen = (w) => isExpanded(w.key) || (filtering && w.matchCount > 0);
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
		if (!current || !g.idxs.length) return "New work";
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

	// In "By title" mode the chart is about a specific book, so the heading names
	// the TITLE (not its author) when exactly one work is plotted; with several
	// works plotted it's a comparison, so the legend labels them and the heading
	// stays blank. Author mode and the overview keep their own headings.
	const headingText = $derived.by(() => {
		if (!current) return "";
		if (isOverview) return current.name;
		if (searchMode === "title") {
			const gs = groups.filter((g) => g.idxs.length);
			const n = gs.length + singleIdxs.length;
			if (n !== 1) return ""; // 0 or 2+ works -> no title heading
			return gs.length
				? groupLabel(gs[0])
				: cleanTitleForDisplay(current.titles[singleIdxs[0]].title);
		}
		return displayName(current.name);
	});

	// In "By title" mode, the total checkouts of the single plotted title (summed
	// over its editions). null when zero or several titles are shown -- then the
	// title heading is blank anyway, so there's no single count to report.
	const titleCheckouts = $derived.by(() => {
		if (!current || isOverview || searchMode !== "title") return null;
		const gs = groups.filter((g) => g.idxs.length);
		let idxs = null;
		if (gs.length === 1 && !singleIdxs.length) idxs = gs[0].idxs;
		else if (!gs.length && singleIdxs.length === 1) idxs = singleIdxs;
		if (!idxs) return null;
		return idxs.reduce((s, i) => s + (current.titles[i]?.total || 0), 0);
	});

	// Top subject-heading terms to show under the Download/Share buttons: the
	// author's terms in author mode, or (in "By title" mode) the plotted work's
	// terms when exactly one work is shown. Baked into the author file by the
	// build (annotate_subjects); data built before that just renders nothing.
	// Stored subjects are [[term, weight], ...] (older data may be a plain [term,...]).
	// Pool a term list into a running term->weight Map so we can combine a work's
	// editions (a book's ebook record is often sparse/generic while its print
	// record carries the specific headings) and re-rank the union.
	function poolSubjects(map, list) {
		for (const it of list ?? []) {
			const term = Array.isArray(it) ? it[0] : it;
			const w = Array.isArray(it) ? (it[1] || 0) : 0;
			if (term) map.set(term, (map.get(term) || 0) + w);
		}
	}
	const top5Terms = (map) => [...map.entries()].sort((a, b) => b[1] - a[1]).slice(0, 5).map((e) => e[0]);

	const subjectTerms = $derived.by(() => {
		if (!current || isOverview) return [];
		if (searchMode === "title") {
			const gs = groups.filter((g) => g.idxs.length);
			let idxs = null;
			if (gs.length === 1 && !singleIdxs.length) idxs = gs[0].idxs;
			else if (!gs.length && singleIdxs.length === 1) idxs = singleIdxs;
			if (!idxs) return [];
			const m = new Map();
			for (const i of idxs) poolSubjects(m, current.titles[i]?.subjects);
			return top5Terms(m);
		}
		// author mode: already pooled across everything in the build
		const m = new Map();
		poolSubjects(m, current.subjects);
		return top5Terms(m);
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

		// Each group's all-time total (summed over its editions), for the tooltip's
		// "X% of the author's checkouts" line.
		const groupTotals = new Map();
		groups.forEach((g, gi) => groupTotals.set(gi, g.idxs.reduce((s, idx) => s + current.titles[idx].total, 0)));

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
				format: t.format, // ebook / audiobook / print -- shown as edition pills in the area tooltip
				groupName: isGrouped ? groupLabel(groups[gi]) : (isSingle ? cleanTitleForDisplay(t.title) : null), // work title for the tooltip
				workTotal: isGrouped ? groupTotals.get(gi) : (isSingle ? t.total : null), // work's all-time total, for the "% of author" line
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
	// Label uses the tidied display name (the tooltip shows this), not the raw
	// catalog form like "emily st john mandel, 1979".
	const authorLine = $derived(
			current
					? {key: "author", label: isOverview ? current.name : displayName(current.name), color: INK, values: current.series, groupIndex: -2, isAggregate: true}
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

	// The default overview's stacked-by-format area series (print / ebook /
	// audiobook), built from the per-format monthly totals fetched from the API.
	const OVERVIEW_FORMATS = [
		{ key: "print", label: "Print", format: "print", color: "#6a4c93" },
		{ key: "ebook", label: "Ebook", format: "ebook", color: "#e58a00" },
		{ key: "audiobook", label: "Audiobook", format: "audiobook", color: "#1f7a4d" }
	];
	const overviewAreaSeries = $derived.by(() => {
		if (!current || !current.formats) return [];
		return OVERVIEW_FORMATS.map((f, i) => ({
			key: f.key,
			label: f.label,
			color: f.color,
			values: current.formats[f.key] ?? [],
			format: f.format,
			groupName: f.label,
			workTotal: (current.formats[f.key] ?? []).reduce((s, v) => s + v, 0),
			isSelected: true,
			groupIndex: i,
			titleIdx: -(100 + i)
		}));
	});

	// What the chart actually draws. "line": author total + per-group and
	// per-title lines. "area": the stacked-by-title chart (capped). Either way,
	// when a series is isolated we show only it.
	const displaySeries = $derived.by(() => {
		if (!current) return [];
		if (isOverview) {
			return chartMode === "area" ? overviewAreaSeries : [authorLine].filter(Boolean);
		}
		if (chartMode === "line") {
			if (isolatedKeys.length) return lineParts.filter((s) => isolatedKeys.includes(s.key));
			return lineParts;
		}
		// area mode
		const only = isolatedIdxSet();
		const areaAll = only ? chartSeries.filter((s) => only.has(s.titleIdx)) : chartSeries;
		return capAreaLayers(areaAll);
	});

	// Legend for what's on the chart -- one swatch + label per line (line mode),
	// per plotted work (area mode), or per format (overview). Shown on the page
	// and drawn into the downloaded/shared image so the colors are labeled there
	// too. (A single series needs no legend.)
	const legendItems = $derived.by(() => {
		if (!current) return [];
		if (isOverview) {
			return chartMode === "area" ? [...OVERVIEW_FORMATS].reverse().map((f) => ({ label: f.label, color: f.color, key: null })) : [];
		}
		// Build from the full PLOTTED set (not the isolation-filtered displaySeries)
		// so the legend stays put while isolating -- the isolated entry just lights
		// up and the rest dim, and you can click again to bring them back.
		if (chartMode === "line") {
			return lineParts.map((s) => ({ label: s.label, color: s.color, key: s.key }));
		}
		const out = [];
		groups.forEach((g, gi) => { if (g.idxs.length) out.push({ label: groupLabel(g), color: groupColor(gi), key: `g${g.id}` }); });
		singleIdxs.forEach((idx, i) => out.push({ label: cleanTitleForDisplay(current.titles[idx].title), color: singleColor(i), key: `s${idx}` }));
		return out;
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
	{#snippet authorPicker()}
		<div class="search">
			<label class="sr-only" for="author-search">{searchMode === "title" ? "Search for a title" : "Search for an author"}</label>
			<input
					id="author-search"
					type="search"
					placeholder={searchMode === "title" ? "Search a title — try Braiding Sweetgrass, or Educated" : "Search an author — try Octavia Butler, or Mo Willems"}
					bind:value={query}
					autocomplete="off"
			/>
			{#if results.length}
				<ul class="results">
					{#each results as a}
						<li>
							{#if searchMode === "title"}
								<button onclick={() => selectTitle(a)}>
									<span class="res-title">{a.title}</span>
									<span class="count res-author">{displayName(a.author)}</span>
								</button>
							{:else}
								<button onclick={() => selectAuthor(a)}>
									<span>{displayName(a.name)}</span>
									<span class="count">{a.total.toLocaleString()}</span>
								</button>
							{/if}
						</li>
					{/each}
				</ul>
			{:else if query.trim().length >= 2}
				<p class="no-results">No {searchMode === "title" ? "titles" : "authors"} found for “{query.trim()}”.</p>
			{/if}
		</div>

		{#if searchMode === "title"}
			<p class="title-note"><span class="tn-ic" aria-hidden="true">ℹ</span><span><strong>Only the most-borrowed titles are searchable here</strong>{#if titleMinLabel} — those with at least ~{titleMinLabel} all-time checkouts{/if}. To find any title, search <strong>By&nbsp;author</strong> instead.</span></p>
		{/if}

		<!-- quick-pick: most-borrowed authors, or most-borrowed titles in title mode -->
		{#if searchMode === "title" && topTitles.length}
			<div class="top-authors">
				<span class="quick-label">Most borrowed:</span>
				{#each topTitles as t}
					<button class="chip" onclick={() => selectTitle(t)}>{t.title}</button>
				{/each}
				<button class="chip surprise-chip" onclick={surpriseMe}><span aria-hidden="true">🎲</span> Surprise me</button>
			</div>
		{:else if searchMode !== "title" && topAuthors.length}
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
				<button class="chip surprise-chip" onclick={surpriseMe}><span aria-hidden="true">🎲</span> Surprise me</button>
			</div>
		{/if}
	{/snippet}

	{#if loadError}
		<p class="load-error">{loadError}</p>
	{/if}

	{#if loading}
		<p class="loading" role="status" aria-live="polite"><span class="spinner" aria-hidden="true"></span>Loading…</p>
	{/if}

	<!-- ===== Selected author ===== -->
	{#if current}
		<div class="author">
			<div class="split" class:collapsed={tableCollapsed}>
			<div class="split-main">
			{#if headingText}
				<h2>{headingText}</h2>
			{/if}
			<p class="meta">
				{#if isOverview}
					{abbrevCount(current.total)} checkouts · books, ebooks &amp; audiobooks · {months[0]?.slice(0, 4)}–{months[months.length - 1]?.slice(0, 4)}
				{:else if searchMode === "title"}
					by {displayName(current.name)}{#if titleCheckouts != null}{" · "}{abbrevCount(titleCheckouts)} checkouts{/if}
				{:else}
					{abbrevCount(current.total)} checkouts · {workGroups.size.toLocaleString()} works
				{/if}
			</p>

			{#if !isOverview && current.variants?.length}
				<details class="name-variants">
					<summary>{current.variants.length} catalog name variants merged into this author</summary>
					<ul>
						{#each current.variants as v}
							<li>{v}</li>
						{/each}
					</ul>
					<p class="nv-note">These are the raw <code>Creator</code> spellings the library catalog used. They were automatically clustered into one author — if any look like a different person, the clustering may have over-merged.</p>
				</details>
			{/if}

						<div class="plot-toolbar">
					<div class="mode-toggle" role="group" aria-label="Chart type">
				<button
						type="button"
						class:active={chartMode === "line"}
						onclick={() => (chartMode = "line")}
				>
					<svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true"><polyline points="2,18 8,11 13,15 22,4" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>
					{isOverview ? "Total" : "Line"}
				</button>
				<button
						type="button"
						class:active={chartMode === "area"}
						onclick={() => {
							// First visit to the stacked view with nothing selected yet:
							// cluster editions into works automatically so the stack is
							// colored by work instead of an all-gray pile of editions.
							if (!isOverview && chartMode !== "area" && !groups.length && !singleIdxs.length) {
								autoGroupByWork({ keepChartMode: true });
							}
							chartMode = "area";
						}}
				>
					<svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true"><path d="M2 19 L8 11 L13 15 L22 5 L22 20 L2 20 Z" fill="currentColor" opacity="0.85"/></svg>
					{isOverview ? "By format" : "Area"}
				</button>
			</div>

						{#if !isOverview}
						<button class="top-works-btn" onclick={toggleTopWorks} title={hasPlotted ? "Clear the chart back to just the author's total line (keeps your work grouping)" : "Plot the 5 most-borrowed works (their editions grouped into one line each)"}>
							{hasPlotted ? "✕ Clear chart" : "Show top works"}
						</button>
						{/if}
					</div>
					<div class="chart-wrap" bind:this={chartWrap}>
				{#if plotTitle}
					<p class="plot-title">{plotTitle}</p>
				{/if}
				<LineChart months={viewMonths} series={viewSeries} mode={chartMode} grandTotal={current.total} shareOf={isOverview ? "all Seattle checkouts" : `${displayName(current.name)}'s checkouts`}/>
			</div>

			{#if legendItems.length >= 2}
				<div class="format-legend">
					{#each legendItems as it}
						{#if it.key}
							<button
									class="fmt-leg leg-btn"
									class:on={isIsolated(it.key)}
									class:dim={isolatedKeys.length && !isIsolated(it.key)}
									title="Show only this — click again to bring the others back"
									onclick={() => toggleIsolate(it.key)}
							><span class="fmt-sw" style="background:{it.color}"></span>{it.label}</button>
						{:else}
							<span class="fmt-leg"><span class="fmt-sw" style="background:{it.color}"></span>{it.label}</span>
						{/if}
					{/each}
					{#if isolatedKeys.length}
						<button class="leg-showall" onclick={clearIsolate}>Show all</button>
					{/if}
				</div>
			{/if}

			{#if months.length > 1}
				<YearBrush {months} values={current.series} bind:lo={yearLo} bind:hi={yearHi} />
			{/if}

			<div class="chart-actions">
				<button class="chart-action" onclick={downloadChart} title="Download the chart as a PNG image">
					<span aria-hidden="true">⤓</span> Download image
				</button>
				<div class="share-wrap">
					<button class="chart-action" onclick={() => (shareOpen = !shareOpen)} title="Share this chart" aria-haspopup="true" aria-expanded={shareOpen}>
						<span aria-hidden="true">↗</span> Share
					</button>
					{#if shareOpen}
						<button class="share-backdrop" aria-label="Close share menu" onclick={() => (shareOpen = false)}></button>
						<div class="share-menu" role="menu">
							<button role="menuitem" class="share-item fb" onclick={() => shareTo("facebook")}><span class="share-ic" aria-hidden="true">f</span> Facebook</button>
							<button role="menuitem" class="share-item tw" onclick={() => shareTo("twitter")}><span class="share-ic" aria-hidden="true">𝕏</span> Twitter</button>
							<button role="menuitem" class="share-item bs" onclick={() => shareTo("bluesky")}><span class="share-ic" aria-hidden="true">🦋</span> Bluesky</button>
							<button role="menuitem" class="share-item li" onclick={() => shareTo("linkedin")}><span class="share-ic" aria-hidden="true">in</span> LinkedIn</button>
							<div class="share-sep"></div>
							<button role="menuitem" class="share-item img" onclick={shareImage}><span class="share-ic" aria-hidden="true">▦</span> Share image</button>
							<button role="menuitem" class="share-item copyimg" onclick={copyImage}><span class="share-ic" aria-hidden="true">⧉</span> Copy image</button>
							<button role="menuitem" class="share-item copy" onclick={copyShareLink}><span class="share-ic" aria-hidden="true">🔗</span> Copy link</button>
						</div>
					{/if}
				</div>
				{#if !isOverview}
				<button class="chart-action edit-titles-btn" onclick={() => (mobileTableOpen = true)}>
					<span aria-hidden="true">✎</span> Add/edit titles
				</button>
				{/if}
				{#if shareMsg}<span class="share-msg" role="status">{shareMsg}</span>{/if}
			</div>

			{#if subjectTerms.length}
				<div class="subject-terms">
					<span class="st-label">{searchMode === "title" ? "Top subjects for this title" : "Top subjects for this author"}</span>
					<ul class="st-chips">
						{#each subjectTerms as term}
							<li><code class="st-chip">{term}</code></li>
						{/each}
					</ul>
				</div>
			{/if}

			<div class="picker-below">
				{@render authorPicker()}
			</div>

			{#if !isOverview}
			<div class="groups-panel">
				<div class="groups-header">
					<span class="groups-label">On the chart</span>
					<div class="groups-actions">
						<button class="new-group" onclick={addGroup}>Make a custom work</button>
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
							<li
									class="group-chip-row"
									class:dim={isolatedKeys.length && !isIsolated(`g${g.id}`)}
									class:hl={hlWorkKey === `g${g.id}`}
									onmouseenter={() => (hlWorkKey = `g${g.id}`)}
									onmouseleave={() => (hlWorkKey === `g${g.id}` && (hlWorkKey = null))}
							>
								<span
										class="group-chip"
										class:active={g.id === activeGroupId}
										class:drag-over={dragOverId === g.id}
										style="--chip-color: {groupColorFor(g)}"
										title="Drag onto another work to merge them"
										draggable="true"
										ondragstart={(e) => { dragGroupId = g.id; try { e.dataTransfer.setData("text/plain", String(g.id)); e.dataTransfer.effectAllowed = "move"; } catch {} }}
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
										title="Edit which editions are in this work"
										onclick={() => (activeGroupId = activeGroupId === g.id ? null : g.id)}
								>{g.id === activeGroupId ? "Done" : "Edit"}</button>
								<button
										class="chip-only"
										class:on={isIsolated(`g${g.id}`)}
										title="Show only this (click more than one to compare)"
										onclick={() => toggleIsolate(`g${g.id}`)}
								>Only</button>
								<button class="chip-remove" title="Remove from the chart" onclick={() => removeGroup(g.id)}>×</button>
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
							or drag them onto the work.
						</span>
						<button class="done-btn" onclick={finishGroup}>Done</button>
					</div>
					<div class="bundle-name">
						<label for="group-name-input">Name this work</label>
						<input
								id="group-name-input"
								type="text"
								bind:value={activeGroup.name}
								placeholder={groupLabel(activeGroup)}
						/>
					</div>
				{:else if groups.length}
					<p class="editing-hint">Click a work to edit it, or drag a title onto a work to add it.</p>
				{/if}
			</div>
			{/if}
			</div><!-- /.split-main -->

			{#if !isOverview}
			<div class="split-side" class:open={mobileTableOpen} class:collapsed={tableCollapsed} bind:this={sideEl}>
				<div class="side-mobile-head">
					<span>Add / remove works</span>
					<button class="side-close" onclick={() => (mobileTableOpen = false)}>Done</button>
				</div>
				<button class="side-desktop-head" onclick={() => (tableCollapsed = !tableCollapsed)} aria-expanded={!tableCollapsed}>
					<span>Add/remove works by this author</span>
					<span class="side-chevron" aria-hidden="true">{tableCollapsed ? "▸" : "▾"}</span>
				</button>
				<div class="titles">
				<p class="works-min-note">Only titles borrowed at least <strong>25 times</strong> all-time are listed here — smaller ones still count toward the author's total.</p>
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
					<div class="works-actions">
						<button type="button" class="wa-btn" onclick={saveGroupings} title="Remember this author's grouping in your browser, so your fixes are here next time">💾 Save my groupings</button>
						<button type="button" class="wa-btn wa-reset" onclick={clearGroupings} title="Discard custom grouping and go back to automatic clustering">↺ Reset to automatic</button>
						{#if savedGrouping}<span class="wa-saved" role="status">✓ custom grouping saved</span>{/if}
					</div>
				{/if}
				<div class="title-table" role="table" aria-label="Titles, grouped by work" style="--work-w:{workColW}px; --edition-w:{editionColW}px">
					<div class="tt-head" role="row">
						<span class="tt-cell tt-plot" role="columnheader" class:editing={activeGroup} title={activeGroup ? `Tick to add editions to “${groupLabel(activeGroup)}”` : "Tick to plot a title on the chart"}>{activeGroup ? "Add to work" : ""}</span>
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
								draggable={groups.length > 0 || titleSort === "work"}
								ondragstart={(e) => { dragIdx = t.idx; try { e.dataTransfer.setData("text/plain", String(t.idx)); e.dataTransfer.effectAllowed = "move"; } catch {} }}
								ondragend={() => { dragIdx = null; dragOverId = null; }}
						>
							<label
									class="tt-row"
									role="presentation"
									class:selected={owner !== null || single}
									class:filter-match={t.match}
									style={ownerColor ? `--chip-color:${ownerColor}` : ""}
							>
								<span class="tt-cell tt-plot" role="cell">
									<input
											type="checkbox"
											aria-label="Plot “{t.title}” on the chart"
											checked={isCurrentOwner}
											onchange={() => keepTableStill(() => toggleTitle(t.idx))}
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
										class:expanded={workOpen(w)}
										class:work-drop={dragOverWorkKey === w.key}
										class:hl={hlWorkKey === w.key}
										draggable="true"
										onmouseenter={() => (hlWorkKey = w.key)}
										onmouseleave={() => (hlWorkKey === w.key && (hlWorkKey = null))}
										ondragstart={(e) => { dragWorkKey = w.key; try { e.dataTransfer.setData("text/plain", w.key); e.dataTransfer.effectAllowed = "move"; } catch {} }}
										ondragend={() => { dragWorkKey = null; dragOverWorkKey = null; }}
										ondragover={(e) => { if ((dragWorkKey && dragWorkKey !== w.key) || dragIdx !== null) { e.preventDefault(); dragOverWorkKey = w.key; } }}
										ondragleave={() => (dragOverWorkKey === w.key && (dragOverWorkKey = null))}
										ondrop={(e) => { e.preventDefault(); if (dragWorkKey && dragWorkKey !== w.key) mergeWorks(dragWorkKey, w.key); else if (dragIdx !== null) addEditionToWork(dragIdx, w.key); dragWorkKey = null; dragOverWorkKey = null; dragIdx = null; }}
								>
									<span class="tt-cell tt-plot" role="cell">
										<input
												type="checkbox"
												class="plot-check"
												aria-label={multi ? `Plot the work “${w.name}” (${w.editions.length} editions) on the chart` : `Plot “${w.name}” on the chart`}
												title={multi ? `Plot “${w.name}” — all ${w.editions.length} editions as one line` : `Plot “${w.name}”`}
												checked={isWorkPlotted(w.key)}
												indeterminate={!isWorkPlotted(w.key) && w.editions.some((e) => groupForTitle(e.idx) || isSingleSelected(e.idx))}
												onchange={() => keepTableStill(() => toggleWork(w.key))}
										/>
									</span>
									<span class="tt-cell tt-work" role="cell" title={w.name}>
										<button
												class="disclosure"
												aria-expanded={workOpen(w)}
												aria-label="{workOpen(w) ? 'Collapse' : 'Expand'} {w.name}"
												onclick={() => toggleExpand(w.key)}
										>{workOpen(w) ? "▾" : "▸"}</button>
										<span class="tt-work-name">{w.name}</span>
									</span>
									<button class="tt-cell tt-edition ed-summary" onclick={() => toggleExpand(w.key)}>
											{#if multi}
												<span class="cluster-badge" class:has-match={w.matchCount > 0}>{w.editions.length} editions</span>{#if w.matchCount > 0}<span class="match-note"> · {w.matchCount} match{w.matchCount === 1 ? "" : "es"}</span>{/if}{workOpen(w) ? "" : " — click to edit"}
											{:else}
												<span class="ed-single">1 edition</span>{workOpen(w) ? "" : " — click for full title"}
											{/if}
										</button>
									<span class="tt-cell tt-format" role="cell">
										{#each fmts as f}<span class="badge badge-{f}">{formatLabel(f)}</span>{/each}
									</span>
									<span class="tt-cell tt-count" role="cell">{w.total.toLocaleString()}</span>
								</li>
								{#if workOpen(w)}
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
			</div><!-- /.split-side -->
			{/if}
			</div><!-- /.split -->
		</div>
	{:else}
		{@render authorPicker()}
		<p class="hint">Search for an author to begin.</p>
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
		margin-top: 52px;
	}

	.back-to-all {
		display: inline-block;
		margin-bottom: 8px;
		padding: 0;
		background: none;
		border: none;
		font-family: var(--font-sans);
		font-size: 0.82rem;
		font-weight: 600;
		color: var(--color-fg-light);
		cursor: pointer;
	}
	.back-to-all:hover {
		color: var(--color-fg);
	}

	/* On desktop the titles/search table sits stacked BELOW the plot. On narrow
	   screens the table instead opens as a bottom drawer from the top-right
	   "Add/edit titles" button (see the mobile media query). */
	.split {
		display: block;
		position: relative;
	}
	.split-main {
		min-width: 0;
	}
	.split-side {
		min-width: 0;
		margin-top: 22px;
	}

	.chart-actions {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: flex-end; /* download / share sit at the right, OWID-style */
		gap: 8px;
		margin: 10px 0 4px;
	}

	/* top subject-heading terms for the current author / title, just under the
	   download + share row */
	.subject-terms {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: 6px 8px;
		margin: 2px 0 6px;
		font-family: var(--font-sans);
	}
	.st-label {
		font-size: 0.78rem;
		font-weight: 600;
		color: var(--color-fg-light);
		letter-spacing: 0.01em;
	}
	.st-chips {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.st-chip {
		/* inline-code look (matches the genre tab's <code> terms) rather than a
		   rounded pill, so it doesn't read as a clickable button */
		padding: 1px 6px;
		border-radius: 4px;
		background: #efe9f5;
		color: #6a4c93;
		font-family: var(--font-sans);
		font-size: 0.82rem;
		line-height: 1.5;
		white-space: nowrap;
	}

	/* the author search + "most borrowed" chips, relocated below the chart --
	   in the same gray panel styling as the "on the chart" section below it */
	.picker-below {
		margin: 8px 0 14px;
		padding: 14px 16px;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-gray-100);
	}
	/* format legend for the overview "by format" area chart */
	.format-legend {
		display: flex;
		justify-content: center;
		flex-wrap: wrap;
		gap: 18px;
		margin: 10px 0 2px;
		font-family: var(--font-sans);
		font-size: 0.82rem;
		font-weight: 600;
		color: var(--color-fg);
	}
	.fmt-leg {
		display: inline-flex;
		align-items: center;
		gap: 6px;
	}
	/* clickable legend entry: click to isolate that series (like the pill's "Only") */
	.leg-btn {
		border: none;
		background: none;
		padding: 2px 4px;
		border-radius: 6px;
		font: inherit;
		color: inherit;
		cursor: pointer;
		transition: opacity 0.12s, background 0.12s;
	}
	.leg-btn:hover {
		background: var(--color-gray-100);
	}
	.leg-btn.dim {
		opacity: 0.38;
	}
	.leg-btn.on {
		background: var(--color-gray-100);
		box-shadow: inset 0 0 0 1.5px var(--color-border);
	}
	.fmt-sw {
		width: 12px;
		height: 12px;
		border-radius: 3px;
		flex: none;
	}
	/* "Show all" appears in the legend while a series is isolated */
	.leg-showall {
		border: 1px solid var(--color-border);
		background: var(--color-white);
		padding: 3px 12px;
		border-radius: 999px;
		font-family: var(--font-sans);
		font-size: 0.78rem;
		font-weight: 600;
		color: var(--color-fg);
		cursor: pointer;
	}
	.leg-showall:hover {
		border-color: var(--color-fg-light);
		background: var(--color-gray-100);
	}

	.chart-action {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		font-family: var(--font-sans);
		font-size: 0.8rem;
		font-weight: 600;
		padding: 6px 12px;
		border: 1.5px solid var(--color-border);
		border-radius: 999px;
		background: var(--color-white);
		color: var(--color-fg);
		cursor: pointer;
		transition: background 0.12s, border-color 0.12s;
	}
	.chart-action:hover {
		border-color: var(--color-fg-light);
		background: #f7f7f7;
	}
	.chart-action span {
		opacity: 0.7;
		font-size: 0.95em;
	}
	/* square icon-only buttons (download / share) */
	.chart-action.square {
		width: 34px;
		height: 34px;
		padding: 0;
		justify-content: center;
		border-radius: 8px;
		font-size: 1.05rem;
	}
	.chart-action.square span {
		opacity: 0.85;
		font-size: 1em;
	}
	.edit-titles-btn {
		display: none; /* mobile only -- positioned top-right in the mobile media query */
	}
	.share-msg {
		font-family: var(--font-sans);
		font-size: 0.8rem;
		font-weight: 600;
		color: #2e7d32;
	}

	.share-wrap {
		position: relative;
		display: inline-flex;
	}
	.share-backdrop {
		position: fixed;
		inset: 0;
		z-index: 40;
		background: none;
		border: none;
		cursor: default;
	}
	.share-menu {
		position: absolute;
		top: calc(100% + 6px);
		right: 0; /* anchored to the right, since the button now sits on the right */
		z-index: 41;
		display: flex;
		flex-direction: column;
		min-width: 168px;
		padding: 5px;
		background: var(--color-white);
		border: 1px solid var(--color-border);
		border-radius: 10px;
		box-shadow: 0 8px 24px rgba(0, 0, 0, 0.16);
	}
	.share-item {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 8px 10px;
		border: none;
		border-radius: 7px;
		background: none;
		font-family: var(--font-sans);
		font-size: 0.85rem;
		font-weight: 600;
		color: var(--color-fg);
		cursor: pointer;
		text-align: left;
	}
	.share-item:hover {
		background: #f2f2f2;
	}
	.share-ic {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 22px;
		height: 22px;
		flex: none;
		border-radius: 5px;
		font-size: 0.75rem;
		font-weight: 700;
		color: #fff;
		font-style: normal;
	}
	.share-item.fb .share-ic { background: #1877f2; }
	.share-item.tw .share-ic { background: #000; }
	.share-item.bs .share-ic { background: #0a7aff; }
	.share-item.li .share-ic { background: #0a66c2; }
	.share-item.img .share-ic { background: #2e7d32; }
	.share-item.copyimg .share-ic { background: #444; }
	.share-item.copy .share-ic { background: #666; }
	.share-sep {
		height: 1px;
		margin: 4px 6px;
		background: var(--color-border);
	}

	.side-mobile-head {
		display: none; /* only shown as the drawer header on mobile */
	}
	.side-desktop-head {
		display: none; /* only shown as the collapsible header on desktop */
	}

	/* On desktop the "Add/remove works by this author" line is a subtitle heading
	   above the below-the-plot table, and clicking it collapses the table. */
	@media (min-width: 861px) {
		.side-desktop-head {
			display: flex;
			align-items: baseline;
			gap: 8px;
			width: 100%;
			padding: 0 2px 8px;
			margin: 2px 0 12px;
			border: none;
			border-bottom: 1.5px solid var(--color-border);
			border-radius: 0;
			background: none;
			font-family: var(--font-serif);
			font-weight: 600;
			font-size: 1.2rem;
			line-height: 1.15;
			color: var(--color-fg);
			cursor: pointer;
			text-align: left;
		}
		.side-desktop-head:hover {
			border-color: var(--color-fg-light);
		}
		.side-desktop-head:hover .side-chevron {
			opacity: 0.9;
		}
		.side-chevron {
			margin-left: auto;
			opacity: 0.5;
			font-size: 0.7rem;
			align-self: center;
		}
		.split-side.collapsed .titles {
			display: none;
		}
	}

	@media (max-width: 860px) {
		.split {
			display: block;
		}
		.split-side {
			position: fixed;
			inset: 0;
			z-index: 60;
			height: 100dvh;
			max-width: none;
			max-height: none;
			border-radius: 0;
			background: var(--color-white);
			padding: 10px 14px 48px;
			overflow: auto;
			transform: translateY(100%);
			visibility: hidden;
			transition: transform 0.25s ease, visibility 0.25s ease;
			box-shadow: 0 -6px 28px rgba(0, 0, 0, 0.22);
		}
		.split-side.open {
			transform: translateY(0);
			visibility: visible;
		}
		.side-mobile-head {
			display: flex;
			align-items: center;
			justify-content: space-between;
			position: sticky;
			top: 0;
			background: var(--color-white);
			padding: 6px 0 10px;
			margin-bottom: 8px;
			border-bottom: 1px solid var(--color-border);
			font-family: var(--font-sans);
			font-weight: 700;
			font-size: 0.95rem;
		}
		.side-close {
			font-family: var(--font-sans);
			font-weight: 700;
			font-size: 0.85rem;
			padding: 6px 18px;
			border: none;
			border-radius: 999px;
			background: var(--color-fg);
			color: var(--color-white);
			cursor: pointer;
		}
		/* the "Add/edit titles" button floats in the top-right corner on mobile */
		.edit-titles-btn {
			display: inline-flex;
			position: absolute;
			top: 0;
			right: 0;
			z-index: 3;
		}
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

	.name-variants {
		font-family: var(--font-sans);
		margin: -12px 0 20px;
		font-size: 0.85rem;
	}
	.name-variants summary {
		cursor: pointer;
		color: var(--color-fg-light);
		list-style-position: inside;
		width: fit-content;
	}
	.name-variants summary:hover {
		color: var(--color-fg);
	}
	.name-variants ul {
		margin: 8px 0 0;
		padding: 8px 0 8px 18px;
		max-height: 220px;
		overflow-y: auto;
		border-left: 2px solid var(--color-border);
	}
	.name-variants li {
		font-family: var(--font-mono, monospace);
		font-size: 0.8rem;
		line-height: 1.5;
		color: var(--color-fg);
		list-style: none;
	}
	.name-variants .nv-note {
		margin: 6px 0 0;
		font-size: 0.78rem;
		line-height: 1.45;
		color: var(--color-fg-light);
	}
	.name-variants .nv-note code {
		font-family: var(--font-mono, monospace);
		font-size: 0.72rem;
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

	/* linked highlight (see .work-header.hl): ring the whole pill when its work
	   row is hovered, and vice versa */
	.group-chip-row.hl {
		border-radius: 999px;
		box-shadow: 0 0 0 2px #e58a00;
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

	.title-note {
		display: flex;
		align-items: flex-start;
		gap: 9px;
		font-family: var(--font-sans);
		font-size: 0.88rem;
		line-height: 1.45;
		color: var(--color-fg);
		background: #eef4fb;
		border: 1px solid #cfe0f3;
		border-radius: 10px;
		padding: 10px 14px;
		margin: 12px 0 0;
	}
	.title-note strong { font-weight: 700; }
	.tn-ic {
		flex: none;
		width: 20px;
		height: 20px;
		border-radius: 50%;
		background: #3f88cc;
		color: #fff;
		font-size: 0.8rem;
		font-weight: 700;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		font-style: italic;
		font-family: Georgia, serif;
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

	.surprise-chip {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		font-weight: 600;
		border-color: #6a4c93;
		color: #6a4c93;
	}
	.surprise-chip:hover {
		background: #6a4c93;
		border-color: #6a4c93;
		color: var(--color-white);
	}

	/* chart type toggle (line vs stacked area) + title sort toggle share a look */
	/* Row above the plot: Line/Area toggle on the left, "Show top works" on the
	   right so it's prominent instead of buried in the panel below. */
	.plot-toolbar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		flex-wrap: wrap;
		margin: 0 0 14px;
	}
	.plot-toolbar .mode-toggle {
		margin: 0;
	}
	.top-works-btn {
		font-family: var(--font-sans);
		font-size: 0.85rem;
		font-weight: 600;
		padding: 6px 14px;
		border-radius: 999px;
		border: 1.5px solid #6a4c93;
		background: #6a4c93;
		color: var(--color-white);
		cursor: pointer;
		white-space: nowrap;
	}
	.top-works-btn:hover {
		background: #593f7d;
		border-color: #593f7d;
	}

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
		display: inline-flex;
		align-items: center;
		gap: 6px;
		padding: 6px 15px;
		font-size: 0.85rem;
		background: var(--color-white);
		border: none;
		color: var(--color-fg-light);
		cursor: pointer;
	}
	.mode-toggle button svg {
		flex: none;
		width: 14px;
		height: 14px;
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
	.works-min-note {
		font-family: var(--font-sans);
		font-size: 0.78rem;
		line-height: 1.4;
		color: var(--color-fg-light);
		margin: 0 0 10px;
	}

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

	/* In the OWID-style side panel the table is narrow, so use a compact
	   fit-to-width grid (Edition shrinks) instead of the wide resizable columns
	   -- otherwise Format and Checkouts get pushed off the right and clipped. */
	.split-side .tt-head,
	.split-side .tt-row,
	.split-side .work-header {
		/* narrow Work column, wide Edition column so expanded edition titles
		   show as much of their (long) titles as possible; the last column is
		   wide enough for the "Checkouts" header + comma'd values so nothing
		   spills off the right edge. */
		/* Checkouts gets a min-width so the value isn't crunched against Format
		   (each row is its own grid, so an `auto` last column shrinks to just the
		   number). A fixed min also keeps the width stable when editions expand. */
		grid-template-columns: 26px minmax(50px, 0.7fr) minmax(0, 1.7fr) auto minmax(62px, auto);
		gap: 9px;
		padding: 7px 9px;
		font-size: 0.8rem;
	}
	/* keep the Checkouts header/value on one line, right-aligned, and a touch
	   smaller so its (auto-sized) column doesn't get too wide */
	.split-side .tt-count {
		text-align: right;
		white-space: nowrap;
	}
	.split-side .tt-head .tt-count {
		font-size: 0.64rem;
		letter-spacing: 0.02em;
	}
	.split-side .title-table {
		max-height: 460px;
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

	/* linked highlight: hovering a work row or its "on the chart" pill lights up
	   the other, so it's clear a pill and a work row are the same thing */
	.work-header.hl {
		background: #fff8e6;
		box-shadow: inset 0 0 0 2px #e58a00;
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
	/* format column can show several badges for a multi-format work -- stacked
	   vertically so the column stays narrow */
	.work-header .tt-format {
		display: flex;
		flex-direction: column;
		gap: 3px;
		align-items: flex-end;
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

	/* Editions matching the table filter are highlighted in place -- the work
	   still shows ALL its editions, these are just the ones you searched for. */
	.tt-row.filter-match {
		background: #fff3bf;
		box-shadow: inset 3px 0 0 0 #f0b429;
	}
	.tt-row.filter-match:hover {
		background: #ffec99;
	}
	.match-note {
		color: #a37500;
		font-weight: 600;
	}
	.cluster-badge.has-match {
		background: #fff3bf;
		color: #8a6100;
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

	.badge-largeprint {
		background: #e6f4f1;
		color: #0b7285;
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
	.works-actions {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 8px;
		margin: 0 2px 10px;
	}
	.wa-btn {
		font-family: var(--font-sans);
		font-size: 0.8rem;
		font-weight: 600;
		padding: 5px 12px;
		border: 1px solid var(--color-border);
		border-radius: 999px;
		background: var(--color-white);
		color: var(--color-fg);
		cursor: pointer;
	}
	.wa-btn:hover { background: var(--color-gray-100); }
	.wa-reset { color: var(--color-fg-light); }
	.wa-saved {
		font-family: var(--font-sans);
		font-size: 0.78rem;
		font-weight: 600;
		color: #1f7a4d;
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
