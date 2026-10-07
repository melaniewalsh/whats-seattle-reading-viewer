<script>
	// StackedViewer.svelte
	import { onMount, tick, untrack } from "svelte";
	import { MediaQuery } from "svelte/reactivity";
	import { searchTitle as coreTitle } from "$utils/cleanTitle.js";
	import ImageIcon from "@lucide/svelte/icons/image";
	import LinkIcon from "@lucide/svelte/icons/link";
	import ShareIcon from "@lucide/svelte/icons/share-2";
	import DownloadIcon from "@lucide/svelte/icons/download";
	import ExternalLinkIcon from "@lucide/svelte/icons/external-link";
	import ChevronDownIcon from "@lucide/svelte/icons/chevron-down";
	import TableIcon from "@lucide/svelte/icons/table";
	import ArrowUpRightIcon from "@lucide/svelte/icons/arrow-up-right";
	import GlobeIcon from "@lucide/svelte/icons/globe";
	import PlusIcon from "@lucide/svelte/icons/plus";
	import ChartAreaIcon from "@lucide/svelte/icons/chart-area";
	import ChartLineIcon from "@lucide/svelte/icons/chart-line";
	import BookCopyIcon from "@lucide/svelte/icons/book-copy";
	import SlidersIcon from "@lucide/svelte/icons/sliders-horizontal";
	import ShoppingBagIcon from "@lucide/svelte/icons/shopping-bag";
	import { base } from "$app/paths";
	import { drawChartLogo, chartLogoWidth } from "$utils/chartLogo.js";
	import workOverrides from "$data/work-overrides.json";
	import { displayName } from "$utils/displayName.js";
	import { titleCase } from "$utils/titleCase.js";
	import { normalizeWorkKey, cleanTitleForDisplay, bareTitleAliases } from "$utils/workTitle.js";
	import { lookupUrls } from "$utils/lookup.js";
	import { coverUrl } from "$utils/covers.js";
	import { compactNumber } from "$utils/format.js";
	import { HIDDEN_GENRES } from "$utils/rankGenres.js";
	import debounce from "lodash.debounce";
	import LineChart from "$components/StackedAreaChart.svelte";
	import DataInfo from "$components/DataInfo.svelte";
	import { EVENT_ANNOTATIONS } from "$data/eventAnnotations.js";
	import YearBrush from "$components/YearBrush.svelte";
	import WikiCard from "$components/WikiCard.svelte";
	import { wikiSummary, wikiWork } from "$utils/wiki.js";
	import Switch from "$components/ui/Switch.svelte";
	import { getMonths, searchAuthors, searchTitles, searchAll, titleIndexMin, getAuthor, getAllCheckouts, randomAuthor, randomTitle, getTopAuthors, getTopWorks, getCoauthors, getGenreTerms } from "$components/db.js";

	// "author" (default): search authors. "title": reverse lookup — search a title,
	// resolve to its author, open the author's drilldown with that work highlighted.
	// landing: "overview" (the "All" tab -> library-wide total trend) or "search"
	// (the "By author" tab -> open straight to the search box).
	let { searchMode = "author", landing = "overview", setSearchKind = () => {}, openGenre = () => {}, openAuthor = () => {}, openTitle = () => {}, onCompare = null, onLoaded = null, onCompareIds = null } = $props();
	// Phones: the year slider and the Download/Share row run the full width
	// (the plot itself is narrower, beside the line names).
	const phone = new MediaQuery("max-width: 600px");

	// Colors for title lines.
	// Palette for the stacked "All titles" bands. Leads with the site blue so the
	// biggest work matches the "Total" area, then alternates high-contrast hues so
	// adjacent bands stay distinguishable for color-blind viewers (orange sits
	// between blue and purple — blue↔purple is the pair red-green color-blindness
	// most confuses).
	const TITLE_COLORS = [
		"#3f88cc", // site blue — the dominant band
		"#e58a00", // orange
		"#6a4c93", // purple (site accent)
		"#1f7a4d", // green
		"#c2255c", // magenta
		"#0b7285", // teal
		"#b0813b", // warm tan
		"#5f6b7a"  // slate
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
	let workOrderFlip = $state(false); // reversed: fewest checkouts first / Z–A
	// The table's column headers: a new column sorts its natural way (most
	// checkouts first, A–Z); the same column again reverses it.
	function sortBooks(by) {
		if (workOrder === by) workOrderFlip = !workOrderFlip;
		else { workOrder = by; workOrderFlip = false; }
	}
	let isolatedKeys = $state([]); // when non-empty, the chart shows ONLY these series (keys 'g<id>' | 's<idx>'); multiple = compare
	let hiddenKeys = $state([]); // keys the user has clicked to hide/ignore from the stacked "All titles" chart
	let showAuthorTotal = $state(true); // show the author's aggregate total line in the line view
	let smoothOn = $state(true);
	let plotInset = $state(0); // the chart's right margin, to line the footer up with the plot's edge // draw 3-month averages (raw months as faint bars behind the total)
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
	let legendHoverKey = $state(null); // legend entry being hovered -> lights up its band on the chart
	let autoGroupNote = $state(""); // feedback after "Group editions into works"
	let searchedWork = $state(null); // { name, idxs } of the work searched in title mode, so "Total" can snap back to it
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
	let tableCollapsed = $state(false); // the books table is open by default; its header still collapses it
	let customizeOpen = $state(false); // phones: the "Customize" panel (3-month average, Compare)
	let editMode = $state(false); // "Edit groupings": reveals drag handles, exclude, save/reset/custom work
	let booksShowAll = $state(false); // view mode lists the top BOOKS_PREVIEW books until "Show all"
	const BOOKS_PREVIEW = 8;
	let autoHidAuthorTotal = $state(false); // whether we've auto-hidden the author-total line for this author yet
	let shareMsg = $state(""); // transient toast after copying a share link
	let shareOpen = $state(false); // whether the share-platform popover is open
	let downloadOpen = $state(false); // whether the Download (data / image) popover is open
	let lookupOpen = $state(false); // whether the "Look up" (Wikipedia/etc.) popover is open

	// Wikipedia preview card on the heading (author or work). Desktop opens on hover
	// with an intent delay; touch devices open on tap.
	let wikiHover = $state(false);
	let wikiTouch = $state(false);
	let wikiTimer;
	function wikiEnter() {
		if (wikiTouch) return;
		clearTimeout(wikiTimer);
		wikiTimer = setTimeout(() => (wikiHover = true), 300);
	}
	function wikiLeave() {
		if (wikiTouch) return;
		clearTimeout(wikiTimer);
		wikiHover = false;
	}
	function wikiActivate() {
		if (wikiTouch) wikiHover = !wikiHover;
	}
	let chartWrap = $state(null); // ref to the chart container, for the PNG export
	let titleEl = $state(null); // ref to the plot heading, so a search scrolls to the title
	let workCover = $state(null); // book-cover thumbnail for the heading in work-search mode
	let showCover = $derived(!isOverview && searchMode === "title" && !!workCover);
	let topWorksData = $state(null); // genre-ranked top works (for the "#N in Genre" badges)
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
		try {
			wikiTouch = window.matchMedia("(hover: none)").matches;
		} catch {}
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
		// In title mode, a ?title (which may sit alongside its ?author) must win —
		// otherwise we'd open the author and never seed the searched work. Let the
		// title effect (loadDefaultTitle) handle it instead of selecting the author.
		if (wantSlug && searchMode !== "title") {
			const a = authors.find((x) => x.slug === wantSlug)
					|| (await searchAuthors(wantSlug.replace(/-/g, " "), 8)).find((x) => x.slug === wantSlug);
			// Arrived with an explicit ?author (a click from Most Borrowed, or a
			// shared link): scroll the plot's title into view so the user lands on it.
			if (a) { await selectAuthor(a, { scroll: false }); return; }
		}
		// Search with nothing picked yet starts blank: the page's search field gets
		// the cursor (Index.svelte), with the "Try" links under it.
		if (landing === "search") {
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
		mobileTableOpen = false; tableCollapsed = false; editMode = false; booksShowAll = false; query = ""; results = [];
		wikiHover = false;
		try {
			const url = new URL(window.location.href);
			url.searchParams.delete("author");
			window.history.replaceState({}, "", url);
		} catch {}
		loading = false;
	}

	// Default start of the year window for a freshly loaded series: the January
	// of the first year with any checkouts, so an author whose first book came
	// out in 2017 opens on 2017-present instead of a decade of flat zero. The
	// YearBrush still shows the whole history, so the user can drag back.
	function firstActiveMonth(values) {
		const i = (values || []).findIndex((v) => v > 0);
		if (i <= 0) return 0;
		const yr = months[i]?.slice(0, 4);
		const jan = months.findIndex((m) => m.slice(0, 4) === yr);
		return Math.max(0, jan);
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
		// One box searches BOTH authors and works; each result carries a `kind` so
		// the click routes to the right view (no Author/Title toggle).
		results = await searchAll(needle, 60);
	}, 120);
	$effect(() => runSearch(query));

	// Quick-pick chips: a curated MIX rather than just the overall top — a few
	// recent favorites plus picks from classic literature, romance and nonfiction —
	// so the suggestions feel varied. Built from the genre ranking data.
	let mixAuthors = $state([]);
	let mixTitles = $state([]);
	let mixLoaded = false;
	// The "Try" links: two authors and two books, alternating.
	const tryPicks = $derived.by(() => {
		const out = [];
		for (let k = 0; k < 2; k++) {
			const a = mixAuthors[k], t = mixTitles[k];
			if (a) out.push({ kind: "author", slug: a.slug, label: displayName(a.name) });
			if (t) out.push({ kind: "title", slug: t.slug, title: t.title, label: cleanTitleForDisplay(t.title) });
		}
		// One comparison among them, to show you can put several on one chart.
		if (onCompareIds && out.length >= 2) {
			out.splice(2, 0, { kind: "compare", label: "Wuthering Heights vs. Pride and Prejudice",
				ids: ["w~emily-bronte-1818~Wuthering Heights", "w~jane-austen-1775~Pride and Prejudice"] });
		}
		return out;
	});
	function buildMix(data, mode) {
		if (!data || !data.data) return [];
		const recentYear = data.years?.length ? String(data.years[data.years.length - 1]) : "all";
		// [genre, year, howMany] — recent first, then classics / romance / nonfiction.
		const plan = [
			["All genres", recentYear, 3],
			["Literary & Classic Fiction", "all", 3],
			["Romance", "all", 2],
			["Memoir & Biography", "all", 2],
			["All genres", "all", 3],
		];
		const seen = new Set();
		const out = [];
		for (const [g, y, n] of plan) {
			const rows = data.data[g]?.[y] || [];
			let added = 0;
			for (const r of rows) {
				if (added >= n) break;
				const item = mode === "title" ? { title: r[0], author: r[1], slug: r[2] } : { slug: r[0], name: r[1] };
				const k = item.slug || item.name || item.title;
				if (k && !seen.has(k)) { seen.add(k); out.push(item); added++; }
			}
		}
		for (let i = out.length - 1; i > 0; i--) {
			const j = Math.floor(Math.random() * (i + 1));
			[out[i], out[j]] = [out[j], out[i]];
		}
		return out.slice(0, 12);
	}
	$effect(() => {
		if (landing === "search" && !mixLoaded) {
			mixLoaded = true;
			getTopAuthors().then((d) => (mixAuthors = buildMix(d, "author"))).catch(() => {});
			getTopWorks().then((d) => (mixTitles = buildMix(d, "title"))).catch(() => {});
		}
	});

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
	const titleMinLabel = $derived(titleMin ? (Math.max(Math.floor(titleMin / 100) * 100, 100)).toLocaleString() : "");

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
		// A ?title=<work> link (e.g. from Top works) loads that title; otherwise the
		// tab lands on a well-known default, The Fire Next Time.
		let want = null, wantAuthor = null;
		try {
			const sp = new URLSearchParams(window.location.search);
			want = sp.get("title");
			wantAuthor = sp.get("author");
		} catch {}
		// No ?title: start blank, like the author search (see onMount).
		if (!want) return;
		try {
			// A link that names the author (a book name in the Books table, a
			// ranking) goes straight to that author's own titles: the search index
			// below only holds books with 500+ checkouts, so smaller ones would
			// never be found there.
			if (want && wantAuthor) {
				await selectTitle({ slug: wantAuthor, title: want, author: "" }, { scroll: false });
				if (searchedWork) return;
			}
			const q = want || "The Fire Next Time";
			const hits = await searchTitles(q, 50);
			// searchTitles is a substring match over a popularity-sorted index, so
			// the FIRST hit for "Whistler" is Grisham's "The Whistler", not
			// Patchett's "Whistler". Prefer, in order: an exact title by the linked
			// author, any title by that author, an exact title, then the top hit.
			// Compare core titles (subtitle after ":" stripped), so "Whistler" is an
			// exact match for "Whistler : a novel" but not "The Whistler: A Novel".
			const norm = (t) => coreTitle(t || "").toLowerCase();
			const ql = norm(q);
			const exact = (h) => norm(h.title) === ql;
			const r = (wantAuthor && hits.find((h) => h.slug === wantAuthor && exact(h)))
				|| (wantAuthor && hits.find((h) => h.slug === wantAuthor))
				|| hits.find(exact)
				|| hits[0];
			// Scroll to the plot title only when a specific ?title was requested (a
			// click from Most Borrowed / shared link), not for the blank-tab default.
			if (r) await selectTitle(r, { scroll: false });
		} catch {}
	}

	// "Surprise me": jump to a random author (or title in title mode).
	// Every author the catalog credits on this book, from the "/ ..." credit
	// line of its records ("Freakonomics ... / Steven D. Levitt and Stephen J.
	// Dubner."): the library files each record under its FIRST author, so a
	// co-author would otherwise go unnamed. Only multi-author credit lines that
	// include this page's author count; "; translated by ..." and the like are
	// dropped. Empty when there's just the one author.
	const bookAuthors = $derived.by(() => {
		if (searchMode !== "title" || !searchedWork || !current) return [];
		const surname = displayName(current.name).split(/\s+/).pop()?.toLowerCase() || "";
		const tally = new Map();
		for (const i of searchedWork.idxs) {
			const t = current.titles[i]?.title || "";
			const k = t.indexOf(" / ");
			if (k < 0) continue;
			const line = t.slice(k + 3).split(/\s*;\s*/)[0].replace(/^(written |story )?by\s+/i, "").replace(/[.\s]+$/, "").trim();
			if (/illustrat|translat|edited|editor|introduc|foreword|with /i.test(line)) continue;
			const names = line.split(/\s*,\s*(?:and\s+|&\s+)?|\s+and\s+|\s+&\s+/).map((n) => n.trim()).filter(Boolean);
			if (names.length < 2 || names.length > 4) continue;
			if (!names.every((n) => /^[A-Z][\p{L}.'’-]*(\s+[A-Z][\p{L}.'’-]*){1,3}$/u.test(n))) continue;
			if (!names.some((n) => n.toLowerCase().includes(surname))) continue;
			const key = names.join("|");
			tally.set(key, (tally.get(key) || 0) + 1);
		}
		const best = [...tally.entries()].sort((a, b) => b[1] - a[1])[0];
		return best ? best[0].split("|") : [];
	});

	// On an author's page: books they're credited on that the library files
	// under someone else (Dubner on Levitt's Freakonomics).
	let alsoCredited = $state([]);
	$effect(() => {
		const slug = currentSlug;
		const authorPage = searchMode !== "title" && !isOverview;
		alsoCredited = [];
		if (!slug || !authorPage) return;
		let alive = true;
		getCoauthors().then((d) => { if (alive) alsoCredited = d?.[slug] || []; });
		return () => { alive = false; };
	});

	// Co-authors who have their own page on the site (Stephen J. Dubner does)
	// get a link to it: name -> slug, looked up in the author index.
	let coAuthorSlugs = $state({});
	$effect(() => {
		const names = bookAuthors;
		const own = current ? displayName(current.name).split(/\s+/).pop().toLowerCase() : "";
		const key = (n) => (n || "").toLowerCase().replace(/[^a-z ]/g, "").replace(/\s+/g, " ").trim();
		let alive = true;
		coAuthorSlugs = {};
		for (const n of names) {
			if (n.toLowerCase().includes(own)) continue;
			searchAuthors(n, 5).then((rows) => {
				const hit = rows.find((r) => key(displayName(r.name)) === key(n));
				if (alive && hit) coAuthorSlugs = { ...coAuthorSlugs, [n]: hit.slug };
			}).catch(() => {});
		}
		return () => { alive = false; };
	});

	// Tell the page what's on the chart, so its search field can show it
	// ("Sally Rooney") and a comma can add more.
	$effect(() => {
		if (!onLoaded || !current || isOverview || !currentSlug) return;
		if (searchMode === "title") {
			if (!searchedWork) return;
			let t = null;
			try { t = new URLSearchParams(window.location.search).get("title"); } catch {}
			onLoaded({ id: `w~${currentSlug}~${t || searchedWork.name}`, label: headingText || searchedWork.name });
		} else {
			onLoaded({ id: `a~${currentSlug}`, label: displayName(current.name) });
		}
	});

	// "+ Compare": hand this author (or, on a book page, this book) to the
	// compare view, as the first line.
	function startCompare() {
		if (!currentSlug) return;
		let title = null;
		if (searchMode === "title") {
			try { title = new URLSearchParams(window.location.search).get("title"); } catch {}
			title = title || searchedWork?.name || null;
		}
		onCompare?.(title ? `w~${currentSlug}~${title}` : `a~${currentSlug}`);
	}

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
		await selectAuthor({ slug: r.slug, name: r.author }, { scroll: false });
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
		searchedWork = { name, idxs: [...idxs] };
		// Open on the years this work has actually circulated (it may be much
		// newer than the author's other books).
		{
			const sum = new Array(months.length).fill(0);
			for (const i of idxs) current.titles[i].series.forEach((v, k) => { sum[k] += v; });
			yearLo = firstActiveMonth(sum);
			yearHi = Math.max(months.length - 1, 0);
		}
		// Reflect the opened title in the URL so it updates as you pick new works
		// (selectAuthor, called above, cleared the previous ?title).
		try {
			const url = new URL(window.location.href);
			url.searchParams.set("title", r.title);
			window.history.replaceState({}, "", url);
		} catch {}
		await tick();
		if (scroll) (titleEl || chartWrap)?.scrollIntoView?.({ block: "start", behavior: "smooth" });
	}

	// Unified-search click: a result is either an author or a work. Route through the
	// parent's openTitle/openAuthor, which set ?title/?author BEFORE the search view
	// remounts — so the fresh instance loads exactly this pick. (Loading on THIS
	// instance instead raced the remount's default-title loader, which sometimes
	// won and flashed "The Fire Next Time".)
	function pickResult(res) {
		query = "";
		results = [];
		if (res.kind === "work") openTitle(res.title, res.slug);
		else openAuthor(res.slug);
	}

	// When you overlay an individual edition on the "Total" line chart, auto-hide the
	// busy author-total area so the added trend line stands out. Only fires for
	// overlaid editions (singles) — NOT for broadened works, which in "Total" mode
	// are summed into the total rather than drawn as their own lines, so hiding the
	// total there would just leave the chart empty while graying the pill. Fires once
	// per author (tracked by autoHidAuthorTotal), so the Hide/Show toggle wins after.
	$effect(() => {
		if (chartMode === "line" && singleIdxs.length > 0 && !autoHidAuthorTotal) {
			showAuthorTotal = false;
			autoHidAuthorTotal = true;
		}
	});

	async function selectAuthor(a, { scroll = true } = {}) {
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
		// reflect the author in the URL so the page is shareable / reloadable.
		// Clear any stale ?title from a previous work drilldown; selectTitle re-adds
		// it right after when we're actually opening a specific title.
		try {
			const url = new URL(window.location.href);
			url.searchParams.set("author", a.slug);
			url.searchParams.delete("title");
			window.history.replaceState({}, "", url);
		} catch {}
		// reset the controls for the new author
		groups = [];
		activeGroupId = null;
		singleIdxs = [];
		titleFilter = "";
		chartMode = "line";
		isolatedKeys = [];
		hiddenKeys = [];
		showAuthorTotal = true;
		autoHidAuthorTotal = false;
		autoGroupNote = "";
		titleSort = "work";
		workOrder = "checkouts";
		expandedWorks = [];
		workAssign = {};
		yearLo = firstActiveMonth(data.series);
		yearHi = Math.max(months.length - 1, 0);
		query = "";
		results = [];
		loading = false;
		// Re-apply any grouping the user saved for this author (localStorage).
		restoreGroupings(a.slug);
		// Bring the plot's title to the top of the viewport after a search.
		if (scroll) {
			await tick();
			titleEl?.scrollIntoView?.({ block: "start", behavior: "smooth" });
		}
	}

	// A shareable link (reopens the current author) plus a caption.
	function shareTarget() {
		let link = window.location.href;
		try {
			const url = new URL(window.location.href);
			if (currentSlug) url.searchParams.set("author", currentSlug);
			link = url.toString();
		} catch {}
		const text = `What’s Seattle Reading? — ${current ? displayName(current.name) : ""}`;
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
		// No "display" here on purpose: the event labels drawn only for images
		// (.ev-export, hidden on screen) must show up in the export.
		const PROPS = ["fill", "stroke", "stroke-width", "stroke-dasharray", "stroke-linecap", "stroke-linejoin", "opacity", "font-family", "font-size", "font-weight", "text-anchor", "color", "paint-order", "fill-opacity", "stroke-opacity"];
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
		const scale = 2, padX = 28, footH = 40;
		const canvas = document.createElement("canvas");
		const ctx = canvas.getContext("2d");
		// The logo sits top-right, beside the title, when there's room; on a
		// narrow (phone) chart it gets its own row above the title instead.
		// The page's own heading: the book on a book page, else the author.
		const imgTitle = current ? (isOverview ? current.name : headingText || displayName(current.name)) : "";
		ctx.font = '600 22px Georgia, "Times New Roman", serif';
		const logoRow = ctx.measureText(imgTitle).width + 16 > w - chartLogoWidth(ctx) ? 30 : 0;
		const titleH = 68 + logoRow;
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
		ctx.fillText(imgTitle, padX, 34 + logoRow);
		ctx.fillStyle = "#666666";
		ctx.font = '13px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
		const byline = searchMode === "title" && current && !isOverview
			? `by ${(bookAuthors.length ? bookAuthors : [displayName(current.name)]).join(", ")}${titleCheckouts != null ? ` · ${abbrevCount(titleCheckouts)} checkouts` : ""}`
			: current ? `${abbrevCount(current.total)} checkouts` : "";
		ctx.fillText(plotTitle || byline, padX, 54 + logoRow);
		await drawChartLogo(ctx, logoRow ? padX + chartLogoWidth(ctx) : padX + w, logoRow ? 18 : 26);
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
		ctx.fillText("What’s Seattle Reading?  \u00b7  Seattle Public Library checkouts", padX, titleH + h + legendH + 24);
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

	// Download the current author's (or title's) checkout data as a tidy CSV: one
	// row per (title, month) with a nonzero count, plus the work-cluster column so
	// merged editions are traceable. Everything is already loaded client-side.
	function downloadData() {
		if (!current || isOverview || !months.length || !current.titles?.length) return;
		const author = displayName(current.name);
		const wg = workGroups;
		const rows = [["author", "work", "title", "format", "date", "checkouts"]];
		current.titles.forEach((t, idx) => {
			const work = wg.get(workIdentityKey(idx, t.title))?.name || cleanTitleForDisplay(t.title) || t.title;
			const series = t.series || [];
			for (let i = 0; i < months.length; i++) {
				const v = series[i] || 0;
				if (!v) continue;
				// Append a dummy day so "2023-05" becomes a full "2023-05-01" date that
				// spreadsheets and pandas parse as a date out of the box.
				rows.push([author, titleCase(work), t.title, formatLabel(t.format), `${months[i]}-01`, v]);
			}
		});
		const cell = (v) => {
			const s = String(v ?? "");
			return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
		};
		const csv = rows.map((r) => r.map(cell).join(",")).join("\r\n");
		const stub =
			(headingText || author || "spl-checkouts").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") ||
			"spl-checkouts";
		const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" });
		const url = URL.createObjectURL(blob);
		const a = document.createElement("a");
		a.href = url;
		a.download = `${stub}-spl-checkouts.csv`;
		document.body.appendChild(a);
		a.click();
		a.remove();
		URL.revokeObjectURL(url);
	}

	// Make a new group. If titles are currently single-selected, seed the group
	// with them (so "select a few, then hit New group" bundles them in one go)
	// and clear the single selection.
	// "New book" in the books table: an empty book you fill with "Move to…".
	// It's a work key in workAssign (like any other book), not a chart group.
	let customBooks = $state([]); // [{ key, name }]
	let customBookCounter = 0;
	function newBook() {
		const key = `custom-${++customBookCounter}`;
		customBooks = [{ key, name: "New book" }, ...customBooks];
		editMode = true;
	}
	function renameBook(key, name) {
		customBooks = customBooks.map((b) => (b.key === key ? { ...b, name: name.trim() || "New book" } : b));
	}
	function dropEmptyBook(key) {
		customBooks = customBooks.filter((b) => b.key !== key);
	}
	const isCustomBook = (key) => customBooks.some((b) => b.key === key);
	const emptyCustomBooks = $derived(customBooks.filter((b) => !workGroups.has(b.key)));

	function addGroup() {
		const g = {id: ++groupIdCounter, name: "", idxs: [...singleIdxs]};
		singleIdxs = [];
		groups = [...groups, g];
		activeGroupId = g.id;
		// Open the works table so there's somewhere to add editions to the new work.
		tableCollapsed = false;
		mobileTableOpen = true;
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
	// Clicking a line's name (legend or line end): one of several picked out ->
	// show only it; the only one showing -> bring everything back; grayed out ->
	// add it. (Taking a picked line OFF on click read as "it jumped to the other
	// book".)
	function toggleIsolate(key) {
		if (!isolatedKeys.includes(key)) isolatedKeys = [...isolatedKeys, key];
		else isolatedKeys = isolatedKeys.length === 1 ? [] : [key];
	}
	const isIsolated = (key) => isolatedKeys.includes(key);
	function clearIsolate() {
		isolatedKeys = [];
	}

	// One book picked out on an author's page: its title, for a link to the
	// book's own page (where the chart, and its image, are just that book).
	const soloBook = $derived(
		searchMode === "author" && !isOverview && currentSlug && isolatedKeys.length === 1 && /^[gs]/.test(isolatedKeys[0])
			? keyLabel(isolatedKeys[0]) || null
			: null
	);

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
	// Index 0 (site blue) is reserved for the primary aggregate — the author/work
	// total, or the first plotted work band. Individually-clicked editions start
	// AFTER the plotted groups so a clicked edition never wears the same blue as
	// the work band it was pulled out of; it gets its own distinct hue.
	const plottedGroupCount = $derived(groups.filter((g) => g.idxs.length).length);
	const singleColor = (i) => TITLE_COLORS[(Math.max(plottedGroupCount, 1) + i) % TITLE_COLORS.length];
	// The colour a work's band wears on the chart (the group its editions live in),
	// so the table row can show the same swatch. "" when the work isn't plotted.
	function workPlotColor(w) {
		for (let gi = 0; gi < groups.length; gi++) {
			if (groups[gi].idxs.length && w.editions.some((e) => groups[gi].idxs.includes(e.idx))) return groupColor(gi);
		}
		return "";
	}
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
	// (normalizeWorkKey, in $utils/workTitle.js, collapses a book's editions to one key.)
	// A bare title joins its one subtitled version ("Freakonomics" ->
	// "Freakonomics: A Rogue Economist ..."); see bareTitleAliases.
	const titleAliases = $derived(current?.titles ? bareTitleAliases(current.titles.map((t) => t.title)) : new Map());
	function workKeyOf(title) {
		const k = normalizeWorkKey(title);
		return titleAliases.get(k) ?? k;
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

	// A "solo" single is a plotted edition that is NOT already inside a plotted
	// group. Clicking an edition whose work is on the chart (e.g. a work search)
	// keeps it in its work and floats it in the table — but it must not spawn a
	// phantom single line/legend chip, so chart + legend use this filtered list.
	const soloSingleIdxs = $derived(singleIdxs.filter((idx) => !groups.some((g) => g.idxs.includes(idx))));

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
	// Curated groupings shipped in src/data/work-overrides.json ("slug": [[title,…],…]).
	// Maps each listed title -> a stable cluster key, applied as the baseline below a
	// visitor's own drag/drop edits and above the automatic normalizeWorkKey.
	const overrideKeyByTitle = $derived.by(() => {
		const clusters = currentSlug ? workOverrides[currentSlug] : null;
		if (!Array.isArray(clusters)) return null;
		const m = new Map();
		clusters.forEach((titles, i) => (titles || []).forEach((t) => m.set(t, `ovr-${i}`)));
		return m.size ? m : null;
	});
	function effectiveKey(idx, title) {
		for (const g of groups) if (g.idxs.includes(idx)) return `g${g.id}`;
		return workAssign[idx] ?? overrideKeyByTitle?.get(title) ?? workKeyOf(title);
	}
	// A title's WORK identity, independent of what's plotted on the chart. The table
	// clusters by this so plotting/selecting an edition (which moves it in/out of a
	// chart group) never reshuffles the table — the edition stays under its work.
	function workIdentityKey(idx, title) {
		return workAssign[idx] ?? overrideKeyByTitle?.get(title) ?? workKeyOf(title);
	}

	// Pull one edition out of its work cluster into its own singleton work. Also
	// take it out of any group first, so the exclusion actually sticks.
	function excludeEdition(idx) {
		const undo = groupingSnapshot();
		releaseTitle(idx);
		workAssign = { ...workAssign, [idx]: `excl-${idx}` };
		if (!expandedWorks.includes(`excl-${idx}`)) expandedWorks = [...expandedWorks, `excl-${idx}`];
		showMoved(idx, `Split the ${formatLabel(current.titles[idx].format)} edition out into its own book`, undo);
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
	let savedFlash = $state(false); // transient "✓ saved" confirmation (fades on its own)
	let savedFlashTimer;
	function flashSaved() {
		savedFlash = true;
		clearTimeout(savedFlashTimer);
		savedFlashTimer = setTimeout(() => (savedFlash = false), 4000);
	}
	// Curator mode: a hidden "Export groupings" button for the maintainer only.
	// Enable by visiting the site once with ?curate=1 (remembered per browser).
	let curator = $state(false);
	let exportNote = $state("");
	onMount(() => {
		try {
			const p = new URLSearchParams(window.location.search);
			if (p.get("curate") === "1") localStorage.setItem("spl:curate", "1");
			curator = localStorage.getItem("spl:curate") === "1";
		} catch {}
	});
	// Copy this author's groupings as a `"slug": [[...]]` entry ready to paste into
	// data-prep/work_overrides.json (which the build applies over the auto-clustering).
	function exportGroupings() {
		if (!current || !currentSlug) return;
		const entry = `${JSON.stringify(currentSlug)}: ${JSON.stringify(currentClusters())}`;
		try {
			navigator.clipboard.writeText(entry);
			exportNote = "Copied — paste into src/data/work-overrides.json (inside the { }).";
		} catch {
			exportNote = entry;
		}
		setTimeout(() => (exportNote = ""), 6000);
	}
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
			flashSaved();
			autoGroupNote = "Groupings saved — they'll be restored next time you open this author (in this browser).";
		} catch {}
	}

	// Revert to automatic clustering and forget the saved grouping for this author.
	function clearGroupings() {
		if (currentSlug) { try { localStorage.removeItem(worksLSKey(currentSlug)); } catch {} }
		workAssign = {};
		customBooks = [];
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
		flashSaved(); // brief reminder that this author's saved grouping is applied
	}

	// Map of workKey -> { idxs (all editions of the work), name }. Powers the
	// per-work "Plot" tick and the collapsible work rows in the title table.
	const workGroups = $derived.by(() => {
		const m = new Map();
		if (!current) return m;
		current.titles.forEach((t, idx) => {
			const key = workIdentityKey(idx, t.title);
			if (!key) return;
			if (!m.has(key)) m.set(key, { idxs: [], name: cleanTitleForDisplay(t.title) || t.title, topTotal: -1, total: 0, nativeTop: -1, nativeName: null });
			const w = m.get(key);
			w.idxs.push(idx);
			w.total += t.total;
			const label = cleanTitleForDisplay(t.title) || t.title;
			if (t.total > w.topTotal) {
				w.topTotal = t.total;
				w.name = label;
			}
			// An edition the user MOVED in doesn't rename the book it joined (moving
			// the Normal People ebook into Intermezzo mustn't relabel Intermezzo).
			const natural = overrideKeyByTitle?.get(t.title) ?? workKeyOf(t.title);
			const movedIn = workAssign[idx] != null && workAssign[idx] !== natural;
			if (!movedIn && t.total > w.nativeTop) {
				w.nativeTop = t.total;
				w.nativeName = label;
			}
		});
		for (const w of m.values()) if (w.nativeName) w.name = w.nativeName;
		// A group-defined work takes its name from the group label (which the user
		// may have renamed), so the table row matches the pill.
		for (const g of groups) {
			const w = m.get(`g${g.id}`);
			if (w) w.name = groupLabel(g);
		}
		for (const b of customBooks) {
			const w = m.get(b.key);
			if (w) w.name = b.name;
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
			// Flip to the stacked "All titles" view so the newly-plotted work is
			// actually visible — in "Total" (line) mode only the aggregate + clicked
			// editions are drawn, so a ticked work would otherwise be invisible.
			// (Mirrors toggleTitle's flip for individual editions.)
			if (chartMode !== "area") chartMode = "area";
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
			// single-selection mode: no group is active. Plot this edition as its own
			// line. releaseTitle pulls it out of the work's plotted AGGREGATE (so its
			// checkouts aren't double-counted) — but the TABLE clusters by work
			// identity, so the edition still shows under its work, just floated + lit up.
			if (singleIdxs.includes(idx)) {
				// Untick: remove the standalone edition and, if it's an edition of a
				// plotted work, fold it back into that work's group so the work total
				// stays whole (rather than leaving the edition orphaned).
				singleIdxs = singleIdxs.filter((i) => i !== idx);
				if (searchMode === "title" && searchedWork?.idxs.includes(idx)) {
					const g = groups.find((gr) => gr.idxs.some((i) => searchedWork.idxs.includes(i)));
					if (g) g.idxs = [...g.idxs, idx];
				}
			} else {
				// Pull it out of the work's aggregate so it shows as its own band (no
				// double-count); the table still clusters it under its work (identity).
				releaseTitle(idx);
				singleIdxs = [...singleIdxs, idx];
				// Flip to the stacked "All titles" view so the edition is visible there.
				if (chartMode !== "area") chartMode = "area";
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
			workKey: workIdentityKey(idx, t.title),
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
			// While filtering, a work is "filtered out" unless it (or an edition)
			// matches. We DON'T drop it from the list -- it stays rendered but hidden
			// via CSS (.work-header.filtered-hidden). That way starting a drag can
			// reveal every work as a drop target by just un-hiding them, WITHOUT
			// inserting DOM nodes mid-drag (node insertion moves the dragged row and
			// cancels the native drag). The badge/total keep the work's FULL numbers.
			const filteredOut = !!f && !nameMatch && matchCount === 0;
			// A plotted individual edition floats to the top of its work, so the one
			// you're looking at is visually prioritized; otherwise by checkouts.
			editions.sort((x, y) => {
				const xp = singleIdxs.includes(x.idx) ? 1 : 0;
				const yp = singleIdxs.includes(y.idx) ? 1 : 0;
				return yp - xp || y.total - x.total;
			});
			// "Primary" format = the format of the work's most-borrowed edition, used
			// when sorting the table by format.
			blocks.push({ key, name: w.name, editions, total: w.total, matchCount, primaryFormat: editions[0]?.format || "other", filteredOut });
		}
		const FMT_ORDER = { print: 0, largeprint: 1, ebook: 2, audiobook: 3, other: 4 };
		// While editing groupings, books hold the places they had when editing
		// began, so moving an edition doesn't reshuffle the list; a book that
		// only now exists (an edition split out) sits just below where its
		// editions came from.
		const rank = editRank && ((w) => editRank.b.get(w.key) ?? Math.min(...w.editions.map((e) => editRank.e.get(e.idx) ?? 1e9)) + 0.5);
		blocks.sort((a, b) => {
			// While filtering, matches sort first (and so stay within the display cap);
			// filtered-out works trail behind, hidden until a drag reveals them below
			// the matches. No effect when not filtering (filteredOut is false for all).
			if (a.filteredOut !== b.filteredOut) return a.filteredOut ? 1 : -1;
			if (rank) return rank(a) - rank(b) || b.total - a.total;
			if (workOrder === "format") {
				return (FMT_ORDER[a.primaryFormat] ?? 9) - (FMT_ORDER[b.primaryFormat] ?? 9) || b.total - a.total;
			}
			const order = workOrder === "checkouts"
					? b.total - a.total
					: a.name.localeCompare(b.name, undefined, { sensitivity: "base", numeric: true }) || (a.key < b.key ? -1 : 1);
			return workOrderFlip ? -order : order;
		});
		return blocks;
	});
	// The book order frozen while editing groupings (see workBlocks): each
	// book's place, and each edition's book's place, when editing began (or the
	// sort / filter last changed).
	let editRank = $state(null);
	$effect(() => {
		const on = editMode;
		workOrder; workOrderFlip; titleFilter; currentSlug;
		untrack(() => (editRank = null));
		if (!on) return;
		tick().then(() => untrack(() => {
			const b = new Map(), e = new Map();
			workBlocks.forEach((w, i) => { b.set(w.key, i); w.editions.forEach((ed) => e.set(ed.idx, i)); });
			editRank = { b, e };
		}));
	});
	// "Move to…" targets in edit mode: every book (by its table key), plus any
	// new, still-empty book made with "New book".
	const moveTargets = $derived.by(() => {
		// "(N editions)" helps tell apart near-duplicate books, e.g. the big
		// "Nicholas Nickleby" cluster vs a stray one-edition "Life and Adventures of…".
		const eds = (n) => `${n} edition${n === 1 ? "" : "s"}`;
		const out = workBlocks.map((w) => ({ key: w.key, name: `${w.name} (${eds(w.editions.length)})` }));
		for (const b of emptyCustomBooks) out.unshift({ key: b.key, name: `${b.name} (new, empty)` });
		return out;
	});
	// Move one edition into another book. If that book is plotted, the edition
	// joins its line too.
	function moveEdition(idx, key) {
		if (!key) return;
		const target = workBlocks.find((w) => w.key === key);
		const g = target ? groups.find((gr) => gr.idxs.length && target.editions.some((e) => gr.idxs.includes(e.idx))) : null;
		const undo = groupingSnapshot();
		addEditionToWork(idx, key);
		if (g && !g.idxs.includes(idx)) g.idxs = [...g.idxs, idx];
		if (!expandedWorks.includes(key)) expandedWorks = [...expandedWorks, key];
		const name = moveTargets.find((m) => m.key === key)?.name?.replace(/\s*\((?:\d+ editions?|new, empty)\)$/, "") || target?.name || "another book";
		showMoved(idx, `Moved the ${formatLabel(current.titles[idx].format)} edition to ${name}`, undo);
	}

	// Feedback for a move or split: the edition flashes in its new place (scrolled
	// into view), and a short note at the bottom says what happened, with Undo.
	let movedIdx = $state(null);
	let moveNote = $state(null); // { text, undo }
	let moveTimers = [];
	function groupingSnapshot() {
		return {
			workAssign: { ...workAssign },
			groups: groups.map((g) => ({ ...g, idxs: [...g.idxs] })),
			singleIdxs: [...singleIdxs],
			expandedWorks: [...expandedWorks],
		};
	}
	function showMoved(idx, text, snap) {
		moveTimers.forEach(clearTimeout);
		movedIdx = idx;
		moveNote = { text, undo: snap };
		tick().then(() => document.querySelector(`[data-ed="${idx}"]`)?.scrollIntoView({ block: "nearest", behavior: "smooth" }));
		moveTimers = [setTimeout(() => (movedIdx = null), 1800), setTimeout(() => (moveNote = null), 8000)];
	}
	function undoMove() {
		const snap = moveNote?.undo;
		if (!snap) return;
		workAssign = snap.workAssign;
		groups = snap.groups;
		singleIdxs = snap.singleIdxs;
		expandedWorks = snap.expandedWorks;
		moveTimers.forEach(clearTimeout);
		moveNote = null;
		movedIdx = null;
	}
	// Table totals at one precision: "14.0k" beside "13.1k", not "14k".
	function tableNumber(n) {
		if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
		if (n >= 1e5) return `${Math.round(n / 1e3)}k`;
		if (n >= 1e3) return `${(n / 1e3).toFixed(1)}k`;
		return n.toLocaleString();
	}
	const booksYears = $derived.by(() => {
		if (!months.length || !current) return "";
		const lo = isYearFiltered ? yearLo : Math.max(0, current.series.findIndex((v) => v > 0));
		const hi = isYearFiltered ? yearHi : months.length - 1;
		const a1 = months[lo]?.slice(0, 4), b1 = months[hi]?.slice(0, 4);
		return a1 === b1 ? a1 : `${a1}\u2013${b1}`;
	});

	// View mode shows the top few books; editing, filtering or "Show all" lists them all.
	const booksCapped = $derived(!editMode && !titleFilter.trim() && !booksShowAll);
	const visibleWorkBlocks = $derived(workBlocks.slice(0, booksCapped ? BOOKS_PREVIEW : WORK_BLOCK_CAP));
	// Tiny trend line for a book's row: its checkouts over the visible window.
	function sparkPath(idxs, w = 78, h = 18) {
		if (!current || !idxs?.length) return "";
		const s = sumSeries(idxs);
		const lo = isYearFiltered ? yearLo : Math.max(0, current.series.findIndex((v) => v > 0));
		const hi = isYearFiltered ? yearHi : s.length - 1;
		const seg = s.slice(lo, hi + 1);
		if (seg.length < 2) return "";
		const avg = seg.map((_, i) => { let t = 0, n = 0; for (let k = i - 1; k <= i + 1; k++) if (k >= 0 && k < seg.length) { t += seg[k]; n++; } return t / n; });
		// One scale for every row, so a 30-checkout book draws a flat line next
		// to a 22k one instead of spikes just as tall.
		const mx = Math.max(1, sparkMax);
		return avg.map((v, i) => `${i ? "L" : "M"}${(1 + (i * (w - 2)) / (avg.length - 1)).toFixed(1)},${(h - 1 - (v / mx) * (h - 3)).toFixed(1)}`).join("");
	}
	// The tallest 3-month average among the books, over the years in view.
	const sparkMax = $derived.by(() => {
		if (!current) return 1;
		const lo = isYearFiltered ? yearLo : Math.max(0, current.series.findIndex((v) => v > 0));
		const hi = isYearFiltered ? yearHi : months.length - 1;
		let mx = 1;
		for (const w of workBlocks) {
			const s = sumSeries(w.editions.map((e) => e.idx));
			for (let i = lo; i <= hi; i++) {
				let t = 0, n = 0;
				for (let k = i - 1; k <= i + 1; k++) if (k >= lo && k <= hi) { t += s[k] || 0; n++; }
				if (n && t / n > mx) mx = t / n;
			}
		}
		return mx;
	});
	const hiddenWorkCount = $derived(Math.max(0, workBlocks.length - visibleWorkBlocks.length));

	let expandedWorks = $state([]); // work keys currently expanded in the table
	const isExpanded = (key) => expandedWorks.includes(key);
	// While a filter is active, auto-expand any work with a matching edition so the
	// highlighted rows are visible without a manual click.
	const filtering = $derived(!!titleFilter.trim());
	// A drag (a title or a whole work) is in progress -> reveal the filtered-out
	// works so any of them can be a drop target.
	const dragActive = $derived(dragIdx !== null || dragWorkKey !== null);
	const workOpen = (w) => isExpanded(w.key) || (filtering && w.matchCount > 0);
	function toggleExpand(key) {
		expandedWorks = isExpanded(key) ? expandedWorks.filter((k) => k !== key) : [...expandedWorks, key];
	}
	// "Edit groupings" opens every book so all the editions are in view to move;
	// "Done editing" puts back whatever was open before.
	let expandedBeforeEdit = null;
	let wasEditing = false;
	$effect(() => {
		const editing = editMode;
		if (editing === wasEditing) return;
		wasEditing = editing;
		if (editing) {
			expandedBeforeEdit = untrack(() => expandedWorks);
			expandedWorks = untrack(() => workBlocks.map((w) => w.key));
		} else if (expandedBeforeEdit) {
			expandedWorks = expandedBeforeEdit;
			expandedBeforeEdit = null;
		}
	});

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
		// "Total" (line mode) is the author's overall trend, so a lingering
		// isolated-title caption doesn't belong — only caption the stacked view.
		if (chartMode === "line") return "";
		if (isolatedKeys.length === 1 && isOverview) return keyLabel(isolatedKeys[0]);
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
			// Show the FULL edition title ONLY when a single clicked edition is the sole
			// thing on the chart (nothing else plotted). If a work band or other titles
			// are also shown, the bare edition title would misrepresent the chart, so we
			// keep the work/author name instead.
			if (gs.length === 0 && soloSingleIdxs.length === 1) return titleCase(current.titles[soloSingleIdxs[0]].title);
			// Focused on a single work (the searched work) -> its title stays the
			// heading even when you click individual editions to overlay them.
			if (gs.length === 1) return groupLabel(gs[0]);
			if (isolatedKeys.length === 1) return keyLabel(isolatedKeys[0]);
			const n = gs.length + singleIdxs.length;
			// 2+ works plotted ("All titles" broadened to the author's top works) ->
			// name the author, so the heading isn't blank. Exactly one work -> its title.
			if (n !== 1) return n > 1 ? displayName(current.name) : "";
			return titleCase(current.titles[singleIdxs[0]].title);
		}
		return displayName(current.name);
	});

	// Catalog / WorldCat / Bookshop searches: the book with its author on a book
	// page, the author's name on an author page.
	const borrowLinks = $derived(lookupUrls(searchMode === "title" && current ? `${headingText} ${displayName(current.name)}` : headingText || ""));
	const lookupLinks = $derived.by(() => {
		if (!current || isOverview) return null;
		const q = headingText;
		if (!q) return null;
		return lookupUrls(q);
	});

	// In work-search mode, fetch a book cover for the single plotted work and show
	// it next to the title heading (Open Library, cached — same source as the
	// Most Borrowed thumbnails). Null while loading, missing, or in author mode.
	$effect(() => {
		const title = headingText;
		const author = current ? displayName(current.name) : "";
		// Only when exactly one work is on the plot (so the heading IS a book title).
		// When "All titles" broadened the chart the heading is the AUTHOR name — no
		// cover then, and never in author-search mode.
		const singleWork = groups.filter((g) => g.idxs.length).length + singleIdxs.length === 1;
		if (searchMode !== "title" || !singleWork || !title) { workCover = null; return; }
		let cancelled = false;
		workCover = null;
		coverUrl(title, author).then((u) => { if (!cancelled) workCover = u; });
		return () => { cancelled = true; };
	});

	// Load the genre-ranked top-works once, to badge a searched work with its
	// all-time rank in each genre ("#1 in Romance").
	$effect(() => {
		if (searchMode === "title" && !topWorksData) {
			getTopWorks().then((d) => (topWorksData = d)).catch(() => {});
		}
	});

	// The genres where the current work sits in the all-time top 20, best rank first.
	const GENRE_RANK_MAX = 20;
	const genreRanks = $derived.by(() => {
		if (searchMode !== "title" || !topWorksData || !headingText || !current) return [];
		const wantTitle = normalizeWorkKey(headingText);
		if (!wantTitle) return [];
		const wantAuthor = displayName(current.name).toLowerCase();
		const out = [];
		for (const genre of topWorksData.genres) {
			if (genre === "All genres" || HIDDEN_GENRES.has(genre)) continue;
			const list = topWorksData.data[genre]?.["all"];
			if (!list) continue;
			const n = Math.min(list.length, GENRE_RANK_MAX);
			for (let i = 0; i < n; i++) {
				const row = list[i];
				if (normalizeWorkKey(row[0]) === wantTitle && displayName(row[1]).toLowerCase() === wantAuthor) {
					out.push({ genre, rank: i + 1 });
					break;
				}
			}
		}
		out.sort((a, b) => a.rank - b.rank);
		return out;
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
	// A book's own subject headings (from its editions), for its details row.
	function bookSubjects(w) {
		const m = new Map();
		for (const e of w.editions) poolSubjects(m, current.titles[e.idx]?.subjects);
		const out = [], seen = new Set();
		for (const [raw] of [...m.entries()].sort((a, b) => b[1] - a[1])) {
			const c = cleanSubject(raw);
			if (!c || c.length > 28 || seen.has(c.toLowerCase())) continue;
			seen.add(c.toLowerCase()); out.push(c);
			if (out.length >= 3) break;
		}
		return out;
	}
	const top5Terms = (map) => [...map.entries()].sort((a, b) => b[1] - a[1]).slice(0, 5).map((e) => e[0]);

	// Subject headings for the page header, tidied for reading. SPL's data strips
	// LC punctuation ("Dublin Ireland Fiction", "Man woman relationships Fiction"),
	// mixes in format words ("Large type books", "Novels") and near-duplicates
	// ("Horror" / "Horror fiction"). Clean that up and keep the top five.
	const SUBJ_DROP = /^(fiction|nonfiction|non-fiction|literature|novels?|large type books|large print books|audiobooks?|downloadable audio books|electronic books|juvenile fiction|juvenile literature|general|adult|stories)$/i;
	const PLACES = new Set(["Ireland", "England", "Scotland", "Wales", "France", "Italy", "Spain", "Germany", "Japan", "China", "India", "Mexico", "Canada", "Australia", "Russia", "Nigeria", "Israel", "Egypt", "Greece", "Korea", "Washington", "Calif", "California", "Texas", "Florida", "Alaska", "Oregon", "Mass", "Massachusetts", "Ill", "Illinois", "N.Y", "N Y", "Ohio", "Mich", "Minn", "Ga", "La", "Va", "Pa"]);
	// US state abbreviations as LC writes them ("Jackson Miss" -> "Jackson (Miss.)").
	const STATE_ABBR = new Set(["Ala", "Ariz", "Ark", "Calif", "Colo", "Conn", "Del", "Fla", "Ga", "Ill", "Ind", "Kan", "Ky", "La", "Md", "Mass", "Mich", "Minn", "Miss", "Mo", "Mont", "Neb", "Nev", "Okla", "Or", "Ore", "Pa", "Tenn", "Tex", "Va", "Vt", "Wash", "Wis", "Wyo"]);
	function cleanSubject(raw) {
		let t = String(raw || "").replace(/\s+/g, " ").trim();
		if (!t || SUBJ_DROP.test(t)) return null;
		// "X Fiction" (capital F, LC form subdivision) -> "X"; keep genre phrases
		// like "Psychological fiction" or "Science fiction".
		// A one-word genre adjective keeps its noun: "Historical Fiction" ->
		// "Historical fiction", not "Historical".
		t = /^\S+ Fiction$/.test(t) ? t.replace(/ Fiction$/, " fiction") : t.replace(/ Fiction$/, "");
		t = t.replace(/^Man woman\b/, "Man-woman").replace(/^Parent child\b/, "Parent-child");
		const words = t.split(" ");
		const lastW = words[words.length - 1];
		if (words.length >= 2 && (PLACES.has(lastW) || STATE_ABBR.has(lastW))) t = `${words.slice(0, -1).join(" ")} (${lastW}${STATE_ABBR.has(lastW) && !lastW.endsWith(".") ? "." : ""})`;
		if (!t || SUBJ_DROP.test(t)) return null;
		return t.charAt(0).toUpperCase() + t.slice(1);
	}

	// Split display text into segments, marking the run(s) that match the current
	// table filter, so only the matched word is highlighted (not the whole row).
	function markMatch(text) {
		const f = titleFilter.trim();
		if (!f) return [{ t: text, hit: false }];
		const lo = text.toLowerCase(), flo = f.toLowerCase();
		const parts = [];
		let i = 0;
		for (;;) {
			const idx = lo.indexOf(flo, i);
			if (idx === -1) { parts.push({ t: text.slice(i), hit: false }); break; }
			if (idx > i) parts.push({ t: text.slice(i, idx), hit: false });
			parts.push({ t: text.slice(idx, idx + f.length), hit: true });
			i = idx + f.length;
		}
		return parts;
	}

	// Up to three short, cleaned, de-duplicated subjects for the header line.
	const subjectLine = $derived.by(() => {
		if (!current || isOverview) return [];
		const m = new Map();
		if (searchMode === "title") {
			const gs = groups.filter((g) => g.idxs.length);
			const idxs = gs.length === 1 && !singleIdxs.length ? gs[0].idxs : !gs.length && singleIdxs.length === 1 ? singleIdxs : null;
			if (!idxs) return [];
			for (const i of idxs) poolSubjects(m, current.titles[i]?.subjects);
		} else {
			poolSubjects(m, current.subjects);
		}
		const out = [];
		const seen = new Set();
		for (const [raw] of [...m.entries()].sort((a, b) => b[1] - a[1])) {
			const c = cleanSubject(raw);
			// Long compound LC headings ("Odysseus King of Ithaca Mythological
			// character Poetry") read as noise in a header; keep short ones.
			if (!c || c.length > 28) continue;
			const key = c.toLowerCase().replace(/ fiction$/, "");
			if (seen.has(key)) continue;
			seen.add(key);
			out.push(c);
			if (out.length >= 3) break;
		}
		return out;
	});
	// A subject tag's genre, so the tag can open that genre's Most Borrowed list
	// (where the genre's tags and counts are explained). The most specific
	// matching term wins ("Science fiction" -> Science Fiction, not Science &
	// Nature); "=term" matches the whole tag only. Catch-all buckets that have
	// no Most Borrowed list are skipped.
	let genreTerms = $state({});
	onMount(() => { getGenreTerms().then((m) => (genreTerms = m || {})); });
	const NO_LIST = new Set(["Fiction", "Nonfiction", "Art", "Illustrated Works", "Informational Works", "Instructional & Educational Works", "Readers Publications"]);
	function genreFor(tag) {
		const t = (tag || "").toLowerCase();
		let best = null, bestLen = 0;
		for (const [g, terms] of Object.entries(genreTerms)) {
			if (NO_LIST.has(g) || HIDDEN_GENRES.has(g)) continue;
			for (const term of terms || []) {
				const w = term.toLowerCase();
				const hit = w.startsWith("=") ? t === w.slice(1) : t.includes(w);
				if (hit && w.length > bestLen) { best = g; bestLen = w.length; }
			}
		}
		return best;
	}

	// SPL catalog subject search for a header subject.
	const splSubjectUrl = (t) => `https://seattle.bibliocommons.com/v2/search?query=${encodeURIComponent(t.replace(/[()]/g, ""))}&searchType=subject`;

	// Wikipedia's one-line description under the heading: "Irish author (born
	// 1991)" for an author, "2018 novel by Sally Rooney" for a book. Only shown
	// when it plausibly describes a writer or a book (a same-named place or
	// musician is skipped).
	const DESC_OK = /(author|writer|novelist|poet|journalist|illustrator|cartoonist|historian|playwright|screenwriter|essayist|biographer|memoirist|scholar|critic|editor|professor|philosopher|scientist|activist|politician|president|first lady|comedian|chef|economist|psychologist|novel|book|memoir|collection|series|poem|play|essay|story|graphic)/i;
	const DESC_PERSON = /(author|writer|novelist|poet|journalist|illustrator|cartoonist|historian|playwright|screenwriter|essayist|biographer|memoirist|scholar|critic|editor|professor|philosopher|scientist|activist|politician|comedian|chef|economist|psychologist|actor|actress|musician|singer|artist|lawyer|physician|theologian|priest|monk|teacher|educator|entrepreneur|television|personality|founder|leader|general|president|emperor|king|queen|saint|(born|died|\d{4}[–-]\d{4}))/i;
	const DESC_WORK = /\b(novels?|novellas?|books?|memoirs?|collection|series|poems?|poetry|play|essays?|story|stories|graphic|comics?|manga|autobiography|biography|nonfiction|non-fiction|cookbook|anthology|epic|treatise|saga|trilogy)\b/i;
	let headDesc = $state("");
	let headPhoto = $state(null); // the author's Wikipedia portrait, beside the name
	$effect(() => {
		const isTitle = searchMode === "title";
		const nm = current && !isOverview ? (isTitle ? headingText : displayName(current.name)) : "";
		const au = current ? displayName(current.name) : "";
		headDesc = "";
		headPhoto = null;
		if (!nm) return;
		let alive = true;
		(isTitle ? wikiWork(nm, au) : wikiSummary(nm))
			.then((s) => {
				if (!alive) return;
				const d = (s?.description || "").trim();
				// On an author page, skip a description of a book: an author without
				// their own article redirects to their novel ("2026 debut novel by …").
				const ok = d && DESC_OK.test(d) && (isTitle || (DESC_PERSON.test(d) && !/\bby\b/i.test(d)))
					// On a book page, only a description of a book ("1818 novel by
					// Mary Shelley"), never of a topic around it ("Debate over the
					// identity of an author", "2025 film").
					&& (!isTitle || (DESC_WORK.test(d) && !/\b(debate|controversy|question|theory|film|adaptation|character|franchise)\b/i.test(d)));
				let t = ok ? d.charAt(0).toUpperCase() + d.slice(1) : "";
				// "2025 novel by Virginia Evans": the byline right below already names
				// the author, so keep just "2025 novel".
				if (isTitle) t = t.replace(/\s+by\s+[^,;()]+$/i, "");
				headDesc = t;
				// Same check for the photo, so a novel's cover (or a namesake) never
				// stands in for the author.
				if (!isTitle && ok) headPhoto = s?.thumbnail || null;
			})
			.catch(() => {});
		return () => { alive = false; };
	});


	// StackedViewer.svelte
	const chartSeries = $derived.by(() => {
		if (!current) return [];

		const groupIndexOf = new Map();
		groups.forEach((g, gi) => {
			g.idxs.forEach((idx) => groupIndexOf.set(idx, gi));
		});

		const singleColorOf = new Map();
		soloSingleIdxs.forEach((idx, i) => {
			singleColorOf.set(idx, singleColor(i));
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
				titleIdx: idx, // original title index, for isolate filtering
				// Which legend entry this layer belongs to, so hovering a legend item can
				// light up its band(s) on the chart. Unselected titles map to "other".
				legendKey: isGrouped ? `g${groups[gi].id}` : (isSingle ? `s${idx}` : "other")
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
					? {key: "author", label: isOverview ? current.name : displayName(current.name), color: "#3f88cc", values: current.series, groupIndex: -2, isAggregate: true}
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
		// Use ALL clicked editions here (even ones inside a plotted work): line mode
		// overlays them on the total, so there's no stacking / double-count.
		singleIdxs.forEach((idx, i) => {
			parts.push({
				key: `s${idx}`,
				label: `${cleanTitleForDisplay(current.titles[idx].title) || current.titles[idx].title} (${formatLabel(current.titles[idx].format)})`,
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

	// Clicking a legend entry hides that band from the stacked "All titles" chart.
	const isHidden = (key) => hiddenKeys.includes(key);
	function toggleHidden(key) {
		hiddenKeys = hiddenKeys.includes(key)
				? hiddenKeys.filter((k) => k !== key)
				: [...hiddenKeys, key];
	}
	function clearHidden() { hiddenKeys = []; }
	// The title indices the hidden keys refer to (null = hide nothing).
	function hiddenIdxSet() {
		if (!hiddenKeys.length) return null;
		const set = new Set();
		for (const key of hiddenKeys) {
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
			titleIdx: -1,
			legendKey: "other",
			// The titles rolled into this band, biggest first, so the tooltip can
			// name what's inside "Other".
			otherTitles: rest
				.slice()
				.sort((a, b) => b.values.reduce((s, v) => s + v, 0) - a.values.reduce((s, v) => s + v, 0))
				.map((s) => cleanTitleForDisplay(s.label))
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

	// In "Total" (line) mode the base area IS the author/work total. It's only truly
	// hidden when the user hid it AND there are overlaid edition lines to look at
	// instead — hiding it with nothing else would leave an empty chart, so we keep
	// it. The "Author total" pill's grayed state follows this (not raw showAuthorTotal)
	// so the pill never says "hidden" while the total is on screen.
	const authorTotalShown = $derived(showAuthorTotal || singleIdxs.length === 0);

	// In a title search, the "Total" line's base is the SEARCHED WORK's own total
	// (the blue "The Odyssey" band), not the author aggregate — so it's always the
	// focus of the view and is never decluttered away. Only the author aggregate
	// (author mode, or a broadened multi-work view) gets the hide/declutter behavior.
	const lineBaseIsWork = $derived(
		searchMode === "title" && !isOverview && groups.filter((g) => g.idxs.length).length === 1
	);

	// What the chart actually draws. "line": author total + per-group and
	// per-title lines. "area": the stacked-by-title chart (capped). Either way,
	// when a series is isolated we show only it.
	const displaySeries = $derived.by(() => {
		if (!current) return [];
		if (isOverview) {
			if (chartMode !== "area") return [authorLine].filter(Boolean);
			// "By format": click a format (legend or line label) to show it alone.
			const only = overviewAreaSeries.filter((s) => isolatedKeys.includes(s.key));
			return only.length ? only : overviewAreaSeries;
		}
		if (chartMode === "line") {
			// "Total" = a filled total area, plus any editions you clicked (overlaid
			// as their own lines — no stacking, so no double-count). In work-search
			// mode the base is the WORK's total (its plotted group), not the author's.
			const singles = lineParts.filter((s) => s.isSingle);
			let base = authorLine;
			if (lineBaseIsWork) {
				const gs = groups.filter((g) => g.idxs.length);
				// The searched work's FULL total — all its editions, including any you
				// clicked out to overlay — so "Total" always shows the whole work, with
				// the clicked edition drawn on top for comparison.
				const workIdxs = [...gs[0].idxs, ...singleIdxs.filter((i) => searchedWork?.idxs.includes(i))];
				base = { key: "worktotal", label: groupLabel(gs[0]), color: "#3f88cc", values: sumSeries(workIdxs), isAggregate: true };
			}
			// The work total is always shown (it's the point of a title search); only the
			// author aggregate can be hidden once an edition line is overlaid.
			const showBase = lineBaseIsWork || authorTotalShown;
			return [showBase ? base : null, ...singles].filter(Boolean);
		}
		// "By book" (the non-overview 'area' state): one line per plotted work,
		// plus any individually plotted editions — compared from a common zero
		// baseline instead of stacked, so each book's own trend reads directly.
		if (!isOverview) {
			const parts = [];
			groups.forEach((g, gi) => {
				if (g.idxs.length) parts.push({ key: `g${g.id}`, legendKey: `g${g.id}`, label: groupLabel(g), color: groupColor(gi), values: sumSeries(g.idxs), groupIndex: gi, isGroup: true });
			});
			soloSingleIdxs.forEach((idx, i) => {
				parts.push({ key: `s${idx}`, legendKey: `s${idx}`, label: `${cleanTitleForDisplay(current.titles[idx].title) || current.titles[idx].title} (${formatLabel(current.titles[idx].format)})`, color: singleColor(i), values: current.titles[idx].series, isSingle: true });
			});
			let shown = isolatedKeys.length ? parts.filter((p) => isolatedKeys.includes(p.key)) : parts;
			shown = shown.filter((p) => !hiddenKeys.includes(p.key));
			return shown.length ? shown : [authorLine].filter(Boolean);
		}
		// area mode (overview "By format")
		const only = isolatedIdxSet();
		const hidden = hiddenIdxSet();
		let areaAll = only ? chartSeries.filter((s) => only.has(s.titleIdx)) : chartSeries;
		if (hidden) areaAll = areaAll.filter((s) => !hidden.has(s.titleIdx));
		// "Other" is the rolled-up band of unselected titles — hide it by dropping
		// everything that isn't an individually-labeled work.
		if (hiddenKeys.includes("other")) areaAll = areaAll.filter((s) => s.isSelected);
		return capAreaLayers(areaAll);
	});

	// Legend for what's on the chart -- one swatch + label per line (line mode),
	// per plotted work (area mode), or per format (overview). Shown on the page
	// and drawn into the downloaded/shared image so the colors are labeled there
	// too. (A single series needs no legend.)
	const legendItems = $derived.by(() => {
		if (!current) return [];
		if (isOverview) {
			return chartMode === "area" ? [...OVERVIEW_FORMATS].reverse().map((f) => ({ label: f.label, color: f.color, key: f.key })) : [];
		}
		// Build from the full PLOTTED set (not the isolation-filtered displaySeries)
		// so the legend stays put while isolating -- the isolated entry just lights
		// up and the rest dim, and you can click again to bring them back.
		if (chartMode === "line") {
			// Label any editions overlaid on the total (the total area needs none).
			return singleIdxs.map((idx, i) => ({ label: titleCase(current.titles[idx].title), color: singleColor(i), key: `s${idx}` }));
		}
		const out = [];
		groups.forEach((g, gi) => { if (g.idxs.length) out.push({ label: groupLabel(g), color: groupColor(gi), key: `g${g.id}` }); });
		// Full edition title (not the cleaned work name): if you plotted one specific
		// edition, the legend should name exactly which one.
		soloSingleIdxs.forEach((idx, i) => out.push({ label: titleCase(current.titles[idx].title), color: singleColor(i), key: `s${idx}` }));
		// Everything not individually labeled is drawn in one gray band — label it
		// "Other" so the color is accounted for in the legend (and the shared image).
		// Based on chartSeries (not displaySeries) so the entry stays put — and
		// clickable to un-hide — even after "Other" is hidden. key "other" makes it
		// a toggle like the rest.
		if (isOverview && out.length && chartSeries.some((s) => !s.isSelected)) {
			out.push({ label: "Other", color: "oklch(92.2% 0 0)", key: "other" });
		}
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

	// The year slider's context, over every month: the author's whole record on
	// an author page (not just the lines currently shown, so isolating one book
	// doesn't shrink it), or the plotted book on a book page. It starts at the
	// January the first checkout happened (no empty 2006-on stretch for a 2021
	// book), and is hidden when there are under two years to zoom.
	const brushValues = $derived.by(() => {
		if (searchMode !== "title" && current?.series) return current.series;
		const out = new Array(months.length).fill(0);
		for (const s of displaySeries) s.values.forEach((v, i) => { out[i] += v || 0; });
		return out;
	});
	const brushStart = $derived(Math.min(firstActiveMonth(brushValues), yearLo));

	// Book markers on an author's "Total" chart: the month each of their top
	// three books was FIRST CHECKED OUT at SPL (not its publication or arrival
	// date — the data can't tell us those). Skipped for books already circulating
	// when the data begins, and for the author's very first book, whose marker
	// would just sit at the left edge.
	const MONTH_FULL = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
	const bookMarkers = $derived.by(() => {
		if (!current || isOverview || searchMode === "title" || chartMode !== "line" || !months.length) return [];
		const firstActive = current.series.findIndex((v) => v > 0);
		return [...workGroups.values()]
			.sort((a, b) => b.total - a.total)
			.slice(0, 3)
			// Only label books big enough to matter on the chart (>= 10% of the
			// author's checkouts), not a small anthology that happens to be new.
			.filter((w) => w.total >= current.total * 0.1)
			.map((w) => ({ w, f: sumSeries(w.idxs).findIndex((v) => v > 0) }))
			// Skip the first three years of data: older books' catalog records
			// trickle in then, so a "first checkout" there isn't a real debut.
			.filter((o) => o.f >= 36 && o.f > firstActive + 6)
			.map((o) => {
				const m = months[o.f];
				return { month: m, label: o.w.name, sub: `first checked out ${MONTH_FULL[Number(m.slice(5, 7)) - 1]} ${m.slice(0, 4)}` };
			});
	});

	// Every chart is drawn as lines now. The overview's "By format" used to be a
	// stacked area, but only its bottom band (print) could be read accurately:
	// ebook and audiobook rode on print's swings. One line per format from zero.
	const chartLineMode = "line";

	// On the Total chart, label the peak month (the chart has no latest-month
	// label, which read like the book's size: "1 in July").
	const peakMarker = $derived.by(() => {
		if (chartMode !== "line") return null;
		const agg = viewSeries.find((s) => s.isAggregate);
		const v = agg?.values;
		if (!v || v.length < 6) return null;
		let k = 0;
		for (let i = 1; i < v.length; i++) if (v[i] > v[k]) k = i;
		if (!(v[k] > 0)) return null;
		const m = viewMonths[k];
		return { month: m, kind: "peak", label: `Peak: ${v[k].toLocaleString()} checkouts`, sub: `${MONTH_FULL[Number(m.slice(5, 7)) - 1]} ${m.slice(0, 4)}` };
	});
</script>

<div class="viewer">
	{#snippet authorPicker()}
		<!-- Under the page's search field: a few starting points, half authors and
		     half books, from a varied mix (recent, classic, romance, nonfiction). -->
		{#if tryPicks.length}
			<p class="try-row">
				<span class="try-lead">Try</span>
				{#each tryPicks as p, k}{#if k}<span class="try-sep try-extra" aria-hidden="true">·</span>{/if}<button class="try-link" class:try-extra={k > 0} class:is-title={p.kind === "title"} onclick={() => (p.kind === "compare" ? onCompareIds(p.ids) : p.kind === "title" ? openTitle(p.title, p.slug) : openAuthor(p.slug))}>{p.label}</button>{/each}
				<span class="try-sep" aria-hidden="true">·</span>
				<button class="try-link try-surprise" onclick={surpriseMe}>Surprise me</button>
			</p>
		{/if}
	{/snippet}

	{#if landing === "search"}
		<div class="picker-block">{@render authorPicker()}</div>
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
			<div class="split" class:collapsed={tableCollapsed}>
			<div class="split-main" bind:this={titleEl}>
			<!-- Phones: everything past Total / By book lives under "Customize",
			     above the name. -->
			{#if !isOverview}
				<div class="customize-row on-phone">
					<button type="button" class="customize-btn" class:on={customizeOpen} aria-expanded={customizeOpen} onclick={() => (customizeOpen = !customizeOpen)}><SlidersIcon size={16} strokeWidth={2} aria-hidden="true" /> Customize</button>
				</div>
				{#if customizeOpen}
					<div class="customize-panel on-phone">
						{#if chartLineMode === "line"}
							<label class="smooth-toggle"><input type="checkbox" bind:checked={smoothOn} /> 3-month average</label>
						{/if}
						{#if onCompare && currentSlug}
							<button type="button" class="compare-btn" onclick={startCompare}><PlusIcon size={15} strokeWidth={2.2} aria-hidden="true" /> Compare with another author or book</button>
						{/if}
					</div>
				{/if}
			{/if}
			<div class="hd-top">
			<!-- A book's cover sits beside its title and byline; subjects run full
			     width underneath. Authors get no photo here (the hover card has it). -->
			<div class="hd-main" class:has-cover={showCover}>
			{#if showCover}
				<img class="hd-cover" src={workCover} alt="" loading="lazy" onerror={() => (workCover = null)} />
			{/if}
			<div class="hd-text">
			{#if headingText}
				{#if isOverview}
					<h2>{headingText}</h2>
				{:else}
					<div class="hd-name"><div class="h2-wrap" role="presentation" onmouseenter={wikiEnter} onmouseleave={wikiLeave}>
						<h2 class="h2-hoverable" onclick={wikiActivate}>{headingText}</h2>
						{#if wikiHover}
							<span class="wiki-pop">
								<WikiCard
										query={headingText}
										kind={searchMode === "title" ? "work" : "author"}
										author={searchMode === "title" ? displayName(current.name) : ""}
										links={lookupLinks || {}}
										quiet
								/>
							</span>
						{/if}
					</div>{#if searchMode !== "title" && current.variants?.length}<span class="name-info" tabindex="0" aria-label="{current.variants.length} name variants — hover for details"><span class="ni-icon" aria-hidden="true">i</span><span class="name-info-pop" role="tooltip"><span class="ni-head">{current.variants.length} name variants</span><ul>{#each current.variants as v}<li>{v}</li>{/each}</ul><span class="ni-note">Raw catalog spellings clustered into one author.</span></span></span>{/if}</div>
					{#if wikiTouch && wikiHover}
						<button class="wiki-backdrop" aria-label="Close" onclick={() => (wikiHover = false)}></button>
					{/if}
				{/if}
			{/if}
			{#if headDesc}<p class="hd-desc">{headDesc}</p>{/if}
			<div class="hdr-line">
				<span class="meta">
					{#if isOverview}
						{compactNumber(current.total)} checkouts · books, ebooks &amp; audiobooks · {months[0]?.slice(0, 4)}–{months[months.length - 1]?.slice(0, 4)}
					{:else if searchMode === "title"}
						by {#if bookAuthors.length}{#each bookAuthors as name, k}{#if k}{k === bookAuthors.length - 1 ? (bookAuthors.length > 2 ? ", and " : " and ") : ", "}{/if}{#if name.toLowerCase().includes(displayName(current.name).split(/\s+/).pop().toLowerCase())}<button type="button" class="author-link" onclick={() => currentSlug && openAuthor(currentSlug)} title="See this author's borrowing trends">{name}</button>{:else if coAuthorSlugs[name]}<button type="button" class="author-link" onclick={() => openAuthor(coAuthorSlugs[name])} title="See this author's borrowing trends">{name}</button>{:else}{name}{/if}{/each}{:else}<button type="button" class="author-link" onclick={() => currentSlug && openAuthor(currentSlug)} title="See this author's borrowing trends">{displayName(current.name)}</button>{/if}{#if titleCheckouts != null}{" · "}{compactNumber(titleCheckouts)} total checkouts{/if}{#if genreRanks.length}<span class="off-phone">{" · "}<button type="button" class="author-link" onclick={() => openGenre(genreRanks[0].genre)} title="See the most-borrowed {genreRanks[0].genre} books">#{genreRanks[0].rank} in {genreRanks[0].genre}</button></span>{/if}
					{:else}
						{compactNumber(current.total)} total checkouts<span class="off-phone">{" · "}{workGroups.size.toLocaleString()} {workGroups.size === 1 ? "work" : "works"}</span>
					{/if}
				</span>
			</div>
			</div><!-- /.hd-text -->
			{#if subjectLine.length}
				<p class="hd-subjects">{#each subjectLine as term, k}{#if k}<span class="hd-sep" aria-hidden="true">{" · "}</span>{/if}{#if genreFor(term)}<button type="button" class="subj-genre" onclick={() => openGenre(genreFor(term))} title="The most-borrowed {genreFor(term)} books">{term}</button>{:else}<a href={splSubjectUrl(term)} target="_blank" rel="noopener noreferrer" title="Find books on “{term}” at the Seattle Public Library">{term}</a>{/if}{/each}</p>
			{/if}
			</div>
			{#if lookupLinks}
			<div class="hdr-actions">
					<!-- Borrow at SPL goes straight to the catalog; everything else
					     (other places to borrow or buy, and reading about it) is under More. -->
					<a class="hd-link" href={borrowLinks.spl} target="_blank" rel="noopener noreferrer" title="Search the Seattle Public Library catalog"><img class="hl-logo" src="{base}/spl-logo.png" alt="" width="18" height="18" /> <span class="hl-text">Borrow at SPL</span> <ArrowUpRightIcon size={13} strokeWidth={2} aria-hidden="true" /></a>
					<span class="lookup-wrap">
						<button class="hd-link" onclick={() => (lookupOpen = !lookupOpen)} aria-haspopup="true" aria-expanded={lookupOpen} title="Other places to borrow, buy or read about it"><span class="hl-text">More</span> <ChevronDownIcon size={13} strokeWidth={2} aria-hidden="true" /></button>
						{#if lookupOpen}
							<button class="share-backdrop" aria-label="Close" onclick={() => (lookupOpen = false)}></button>
							<div class="lookup-menu" role="menu">
								<div class="lm-group">Borrow or buy elsewhere</div>
								<a role="menuitem" href={borrowLinks.worldcat} target="_blank" rel="noopener noreferrer" onclick={() => (lookupOpen = false)}><GlobeIcon size={15} strokeWidth={1.8} aria-hidden="true" /> Your local library <span class="lm-sub">WorldCat</span></a>
								<a role="menuitem" href={borrowLinks.bookshop} target="_blank" rel="noopener noreferrer" onclick={() => (lookupOpen = false)}><ShoppingBagIcon size={15} strokeWidth={1.8} aria-hidden="true" /> Bookshop.org <span class="lm-sub">buy</span></a>
								<div class="lm-group">Read about it</div>
								<a role="menuitem" href={lookupLinks.wikipedia} target="_blank" rel="noopener noreferrer" onclick={() => (lookupOpen = false)}>Wikipedia <ArrowUpRightIcon size={14} strokeWidth={2} aria-hidden="true" /></a>
								<a role="menuitem" href={lookupLinks.goodreads} target="_blank" rel="noopener noreferrer" onclick={() => (lookupOpen = false)}>Goodreads <ArrowUpRightIcon size={14} strokeWidth={2} aria-hidden="true" /></a>
								<a role="menuitem" href={lookupLinks.librarything} target="_blank" rel="noopener noreferrer" onclick={() => (lookupOpen = false)}>LibraryThing <ArrowUpRightIcon size={14} strokeWidth={2} aria-hidden="true" /></a>
							</div>
						{/if}
					</span>
			</div>
			{/if}
			</div>

						<div class="plot-toolbar">
					<div class="tb-left">
					<div class="mode-toggle" role="group" aria-label="Chart type">
				<button
						type="button"
						class:active={chartMode === "line"}
						onclick={() => {
							// "Total" and "All titles" are lossless VIEW toggles: switching to
							// the total-line view keeps whatever is plotted (the searched work,
							// or the broadened top-titles set, plus any clicked editions) so
							// clicking "All titles" again restores exactly what you had. It no
							// longer collapses the broadened set back to the searched work.
							chartMode = "line";
							activeGroupId = null;
							isolatedKeys = [];
						}}
						title="Total" aria-label="Total"
				>
					<ChartAreaIcon size={17} strokeWidth={2} aria-hidden="true" /><span class="mt-txt">Total</span>
				</button>
				<button
						type="button"
						class:active={chartMode === "area"}
						onclick={() => {
							// Cluster editions into the top works so the stack is colored by
							// work. Do it when nothing is plotted yet, OR in work-search mode
							// where only the single searched work is focused — there "All
							// titles" should broaden to the author's top titles, not just show
							// that one work + "Other".
							// Broaden to the author's top titles only from a clean single-work
							// view — if the user has clicked editions, keep them (don't re-group
							// and wipe the selection); just switch to the stacked view.
							const onlySearchedWork = searchMode === "title" && groups.length <= 1 && singleIdxs.length === 0;
							if (!isOverview && chartMode !== "area" && ((!groups.length && !singleIdxs.length) || onlySearchedWork)) {
								autoGroupByWork({ keepChartMode: true });
							}
							chartMode = "area";
						}}
						title={isOverview ? "By format" : "By book"} aria-label={isOverview ? "By format" : "By book"}
				>
					{#if isOverview}<ChartLineIcon size={17} strokeWidth={2} aria-hidden="true" />{:else}<BookCopyIcon size={17} strokeWidth={2} aria-hidden="true" />{/if}<span class="mt-txt">{isOverview ? "By format" : "By book"}</span>
				</button>
			</div>
			{#if chartLineMode === "line"}
				<label class="smooth-toggle off-phone"><input type="checkbox" bind:checked={smoothOn} /> 3-month average</label>
			{/if}
			{#if chartMode === "area" && (isolatedKeys.length || hiddenKeys.length)}
				<!-- The way back after clicking a line's name to show it alone -->
				<span class="iso-note">Showing {viewSeries.length} of {legendItems.length}<span aria-hidden="true">{" · "}</span><button type="button" class="iso-showall" onclick={() => { clearIsolate(); clearHidden(); }}>Show all</button>{#if soloBook}<span aria-hidden="true">{" · "}</span><button type="button" class="iso-showall iso-book" onclick={() => openTitle(soloBook, currentSlug)} title="Its own page: just this book's trend, editions and formats">Open this book's page →</button>{/if}</span>
			{/if}
					</div>
					<!-- Put another author or book on this chart (the page switches to
					     its compare view, one line each). -->
					{#if onCompare && !isOverview && currentSlug}
						<button type="button" class="compare-btn off-phone" onclick={startCompare} title="Put another author or book on this chart"><PlusIcon size={15} strokeWidth={2.2} aria-hidden="true" /> Compare</button>
					{/if}
					</div>
					<!-- The chart, its slider and source line share one white panel -->
					<div class="chart-panel" style="--hang: {Math.max(0, plotInset - 16)}px">
					<div class="chart-wrap" bind:this={chartWrap}>
				{#if plotTitle && searchMode !== "title"}
					<p class="plot-title">{plotTitle}</p>
				{/if}
				<LineChart bind:plotInset months={viewMonths} series={viewSeries} mode={chartLineMode} smooth={smoothOn && chartLineMode === "line"} markers={bookMarkers} onSeriesClick={chartMode === "area" ? (k) => toggleIsolate(k) : null} grandTotal={current.total} shareOf={isOverview ? "all Seattle checkouts" : `${displayName(current.name)}'s checkouts`} annotations={EVENT_ANNOTATIONS} legendHoverKey={legendHoverKey}/>
			</div>

			<!-- Several lines: a swatch legend under the chart, every book listed
			     (click one to show only it; once some are picked out, the rest show
			     grayed out, click to add them back). -->
			{#if legendItems.length >= 2}
				<div class="format-legend" class:off-phone={chartMode === "area" && !isolatedKeys.length && !hiddenKeys.length}>
					{#each legendItems as it}
						{#if it.key === "other"}
							<span class="fmt-leg other-leg" class:hidden-leg={isHidden("other")} class:dim={isolatedKeys.length}
									onmouseenter={() => (legendHoverKey = "other")} onmouseleave={() => (legendHoverKey = null)}>
								<span class="fmt-sw" style="background:{it.color}"></span>{it.label}
								<button class="leg-x" title={isHidden("other") ? "Show “Other” again" : "Hide “Other”"} onclick={() => toggleHidden("other")}>×</button>
							</span>
						{:else if it.key}
							<button
									class="fmt-leg leg-btn"
									class:on={isIsolated(it.key)}
									class:dim={isolatedKeys.length && !isIsolated(it.key)}
									title={!isolatedKeys.length ? "Show only this" : !isIsolated(it.key) ? "Add this to the chart" : isolatedKeys.length === 1 ? "Show all again" : "Show only this"}
									onclick={() => toggleIsolate(it.key)}
									onmouseenter={() => (legendHoverKey = isolatedKeys.length && !isIsolated(it.key) ? null : it.key)}
									onmouseleave={() => (legendHoverKey = null)}
									onfocus={() => (legendHoverKey = isolatedKeys.length && !isIsolated(it.key) ? null : it.key)}
									onblur={() => (legendHoverKey = null)}
							><span class="fmt-sw" style="background:{it.color}"></span>{it.label}</button>
						{:else}
							<span class="fmt-leg"><span class="fmt-sw" style="background:{it.color}"></span>{it.label}</span>
						{/if}
					{/each}
					{#if isolatedKeys.length || hiddenKeys.length}
						<button class="leg-showall" onclick={() => { clearIsolate(); clearHidden(); }}>Show all</button>
					{/if}
					<!-- Phones (no note above the chart): the way to the book's own page. -->
					{#if soloBook}
						<button class="leg-showall leg-book on-phone" onclick={() => openTitle(soloBook, currentSlug)}>Open this book's page →</button>
					{/if}
				</div>
			{/if}

			{#if months.length - brushStart >= 24}
				<YearBrush {months} values={brushValues} start={brushStart} inset={phone.current ? 0 : plotInset} bind:lo={yearLo} bind:hi={yearHi} />
			{/if}

			<!-- Source on the left; Download and Share as small links on the right -->
			<div class="chart-foot" style="padding-right: {phone.current ? 0 : plotInset}px">
			<p class="chart-source">Source: <a href="https://data.seattle.gov/Community-and-Culture/Checkouts-by-Title/tmmm-ytt6" target="_blank" rel="noopener noreferrer">Seattle Public Library open data</a>.{" "}<DataInfo first={months[0]} last={months[months.length - 1]} />.{#if bookMarkers.length && chartLineMode === "line"}{" "}Book labels mark the month each title was first checked out at SPL.{/if}</p>
			<div class="chart-actions tb-actions foot-actions">
				<div class="dl-wrap">
					<button class="tb-btn" onclick={() => (downloadOpen = !downloadOpen)} title="Download the data or the chart image" aria-haspopup="true" aria-expanded={downloadOpen}>
						<DownloadIcon size={15} strokeWidth={2} aria-hidden="true" /><span class="tb-txt"> Download</span><span class="tb-txt"><ChevronDownIcon size={14} strokeWidth={2} aria-hidden="true" /></span>
					</button>
					{#if downloadOpen}
						<button class="share-backdrop" aria-label="Close download menu" onclick={() => (downloadOpen = false)}></button>
						<div class="share-menu dl-menu" role="menu">
							{#if !isOverview}
								<button role="menuitem" class="share-item" onclick={() => { downloadData(); downloadOpen = false; }}>
									<span class="share-ic dl-ic" aria-hidden="true"><TableIcon size={15} strokeWidth={2} /></span> Data <span class="dl-fmt">CSV</span>
								</button>
							{/if}
							<button role="menuitem" class="share-item" onclick={() => { downloadChart(); downloadOpen = false; }}>
								<span class="share-ic dl-ic" aria-hidden="true"><ImageIcon size={15} strokeWidth={2} /></span> Image <span class="dl-fmt">PNG</span>
							</button>
						</div>
					{/if}
				</div>
				<div class="share-wrap">
					<button class="tb-btn" onclick={() => (shareOpen = !shareOpen)} title="Share this chart" aria-haspopup="true" aria-expanded={shareOpen}>
						<ShareIcon size={15} strokeWidth={2} aria-hidden="true" /><span class="tb-txt"> Share</span>
					</button>
					{#if shareOpen}
						<button class="share-backdrop" aria-label="Close share menu" onclick={() => (shareOpen = false)}></button>
						<div class="share-menu" role="menu">
							<button role="menuitem" class="share-item copyimg" onclick={copyImage}><span class="share-ic" aria-hidden="true"><ImageIcon size={15} strokeWidth={2} /></span> Copy image</button>
							<button role="menuitem" class="share-item copy" onclick={copyShareLink}><span class="share-ic" aria-hidden="true"><LinkIcon size={15} strokeWidth={2} /></span> Copy link</button>
							<button role="menuitem" class="share-item img" onclick={shareImage}><span class="share-ic" aria-hidden="true"><ShareIcon size={15} strokeWidth={2} /></span> Share via…</button>
						</div>
					{/if}
				</div>
				{#if shareMsg}<span class="share-msg" role="status">{shareMsg}</span>{/if}
			</div>
			</div>
			</div><!-- /.chart-panel -->



			<!-- Only while building a "New book": name it and tick editions into it. -->
			{#if !isOverview && activeGroup}
			<div class="groups-panel">
				<div class="groups-header">
					<span class="groups-label">On the chart</span>
				</div>
				{#if autoGroupNote}
					<p class="auto-group-note">{autoGroupNote}</p>
				{/if}

				{#if chartMode === "line" || groups.some((g) => g.idxs.length) || singleIdxs.length}
					<!-- This doubles as the chart legend: every line on the chart is a row
					     here, with its color, an "Only" toggle to isolate it, and controls. -->
					<ul class="group-chips">
						{#if chartMode === "line" && !lineBaseIsWork}
							<li class="group-chip-row" class:dim={!authorTotalShown || isolatedKeys.length}>
								<span class="group-chip static-chip" style="--chip-color: {INK}">
									<span class="chip-sw"></span>
									<span class="chip-name">Author total</span>
								</span>
								<!-- Hiding the total only makes sense when there are overlaid
								     edition lines to see instead; with nothing else it's the whole
								     chart, so we drop the toggle rather than gray a visible series. -->
								{#if singleIdxs.length}
									<button
											class="chip-only end"
											title={showAuthorTotal ? "Hide the author's total line" : "Show the author's total line"}
											onclick={() => (showAuthorTotal = !showAuthorTotal)}
									>{showAuthorTotal ? "Hide" : "Show"}</button>
								{/if}
							</li>
						{/if}
						{#each sortedGroups as g (g.id)}
							<li
									class="group-chip-row"
									class:dim={(chartMode === "line" && !lineBaseIsWork) || (isolatedKeys.length && !isIsolated(`g${g.id}`))}
									class:hl={hlWorkKey === `g${g.id}`}
									onmouseenter={() => (hlWorkKey = `g${g.id}`)}
									onmouseleave={() => (hlWorkKey === `g${g.id}` && (hlWorkKey = null))}
							>
								<button
										type="button"
										class="group-chip work-chip"
										class:active={g.id === activeGroupId}
										class:drag-over={dragOverId === g.id}
										style="--chip-color: {groupColorFor(g)}"
										title="Show only this work — or drag onto another work to merge them"
										draggable="true"
										onclick={() => { if (chartMode === "line") chartMode = "area"; toggleIsolate(`g${g.id}`); }}
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
								</button>
								<button
										class="chip-edit"
										class:on={g.id === activeGroupId}
										aria-label={g.id === activeGroupId ? "Done editing this work" : "Edit which editions are in this work"}
										title={g.id === activeGroupId ? "Done editing" : "Edit which editions are in this work"}
										onclick={() => {
											const editing = activeGroupId !== g.id;
											activeGroupId = editing ? g.id : null;
											// Opening "Edit" should reveal the works table you're editing in.
											if (editing) tableCollapsed = false;
										}}
								>{g.id === activeGroupId ? "✓" : "✎"}</button>
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
									>{titleCase(current.titles[idx].title)}</span>
								</span>
								<button class="chip-remove" title="Remove this title" onclick={() => toggleTitle(idx)}>×</button>
							</li>
						{/each}
					</ul>
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
				{/if}
			</div>
			{/if}
			</div><!-- /.split-main -->

			{#if !isOverview}
			<!-- Books: every work by this author. Reading mode lets you plot books
			     and look inside them; "Edit groupings" adds the tools for fixing
			     how editions are grouped into books. -->
			<section class="books" bind:this={sideEl} aria-label="Books">
				<div class="bk-head">
					<h3 class="bk-title">Books <span class="bk-count">({workGroups.size.toLocaleString()})</span></h3>
					<div class="bk-tools">
						<input class="bk-filter" type="search" placeholder="Filter books" bind:value={titleFilter} autocomplete="off" aria-label="Filter books" />
						<button type="button" class="bk-btn" class:on={editMode} aria-pressed={editMode} onclick={() => (editMode = !editMode)}>{editMode ? "Done editing" : "Edit groupings"}</button>
					</div>
				</div>
				{#if editMode}
					<div class="bk-editbar">
						<p class="bk-editnote">Move editions between books, or split out ones that don't belong. <a class="works-why" href="?tab=about#method-clustering" target="_blank" rel="noopener">Why is this hard?</a></p>
						<div class="bk-editactions">
							<button type="button" class="bk-btn" onclick={newBook}>New book</button>
							<button type="button" class="bk-btn" onclick={clearGroupings}>Reset to automatic</button>
							<button type="button" class="bk-btn bk-primary" onclick={saveGroupings}>Save my groupings</button>
							{#if curator}<button type="button" class="bk-btn" onclick={exportGroupings}>Export groupings</button>{/if}
							{#if savedFlash}<span class="bk-saved" role="status">Saved in this browser</span>{/if}
							{#if exportNote}<span class="bk-saved" role="status">{exportNote}</span>{/if}
						</div>
					</div>
				{/if}
				<!-- Click "Book" or "Checkouts" to sort by it; click again to reverse. -->
				<div class="bk-row bk-colhead">
					<span></span>
					<span><button type="button" class="bk-sort" class:on={workOrder === "name"} aria-label="Sort by title" onclick={() => sortBooks("name")}>Book{#if workOrder === "name"}<span class="bk-arrow" aria-hidden="true">{workOrderFlip ? "↑" : "↓"}</span>{/if}</button></span>
					<span class="bk-sp">{booksYears}</span>
					<span class="bk-num"><button type="button" class="bk-sort" class:on={workOrder === "checkouts"} aria-label="Sort by checkouts" onclick={() => sortBooks("checkouts")}>Checkouts{#if workOrder === "checkouts"}<span class="bk-arrow" aria-hidden="true">{workOrderFlip ? "↑" : "↓"}</span>{/if}</button></span>
				</div>
				<ul class="bk-list">
					{#if editMode}
						{#each emptyCustomBooks as b (b.key)}
							<li class="bk-row bk-book bk-new">
								<span></span>
								<span class="bk-name-cell">
									<input class="bk-rename" value={b.name} aria-label="Name this book" onchange={(e) => renameBook(b.key, e.currentTarget.value)} onfocus={(e) => e.currentTarget.select()} />
									<span class="bk-new-note">0 editions · use “Move to…” on any edition to add it here</span>
								</span>
								<span class="bk-sp"></span>
								<span class="bk-num"><button type="button" class="bk-x" title="Remove this empty book" aria-label="Remove this empty book" onclick={() => dropEmptyBook(b.key)}>×</button></span>
							</li>
						{/each}
					{/if}
					{#each visibleWorkBlocks as w (w.key)}
						{@const wColor = workPlotColor(w)}
						{@const open = isExpanded(w.key) || (titleFilter.trim() && w.matchCount > 0)}
						{#if !w.filteredOut}
						<li class="bk-row bk-book" class:plotted={!!wColor}>
							<input type="checkbox" class="bk-check" checked={isWorkPlotted(w.key)}
								indeterminate={!isWorkPlotted(w.key) && w.editions.some((e) => groupForTitle(e.idx) || isSingleSelected(e.idx))}
								onchange={() => keepTableStill(() => toggleWork(w.key))}
								aria-label="Plot {w.name} on the chart" />
							<span class="bk-name-cell">
								{#if wColor}<span class="bk-swatch" style="background:{wColor}"></span>{/if}
								{#if editMode && isCustomBook(w.key)}
									<input class="bk-rename" value={w.name} aria-label="Name this book" onchange={(e) => renameBook(w.key, e.currentTarget.value)} />
								{:else}
									<span class="bk-name">{#each markMatch(w.name) as p}{#if p.hit}<mark class="t-hit">{p.t}</mark>{:else}{p.t}{/if}{/each}</span>
								{/if}
								<button type="button" class="bk-eds" aria-expanded={!!open} onclick={() => toggleExpand(w.key)}>{w.editions.length} edition{w.editions.length === 1 ? "" : "s"} · details<span class="bk-caret" class:up={open} aria-hidden="true"></span></button>
							</span>
							<svg class="bk-sp bk-spark" width="84" height="20" viewBox="0 0 84 20" aria-hidden="true"><path d={sparkPath(w.editions.map((e) => e.idx), 84, 20)} stroke={wColor || "#b4b2a9"} /></svg>
							<span class="bk-num">{tableNumber(w.total)}</span>
						</li>
						{#if open}
							{@const subj = bookSubjects(w)}
							{#if subj.length}
								<li class="bk-row bk-ed bk-subj"><span></span><span class="bk-subj-list">{#each subj as term, k}{#if k}<span class="hd-sep" aria-hidden="true">{" · "}</span>{/if}{#if genreFor(term)}<button type="button" class="subj-genre" onclick={() => openGenre(genreFor(term))} title="The most-borrowed {genreFor(term)} books">{term}</button>{:else}<a href={splSubjectUrl(term)} target="_blank" rel="noopener noreferrer" title="Find books on “{term}” at the Seattle Public Library">{term}</a>{/if}{/each}</span></li>
							{/if}
							{#each w.editions.slice().sort((a, b) => b.total - a.total) as t (t.idx)}
								<li class="bk-row bk-ed" class:editing={editMode} class:hit={t.match} class:just-moved={movedIdx === t.idx} data-ed={t.idx}>
									<input type="checkbox" class="bk-check"
										checked={activeGroupId ? groupForTitle(t.idx)?.id === activeGroupId : isSingleSelected(t.idx)}
										onchange={() => keepTableStill(() => toggleTitle(t.idx))}
										aria-label="Plot this edition on its own: {t.title}" />
									<span class="bk-ed-title" title={t.title}>{#if isSingleSelected(t.idx) && soloSingleIdxs.includes(t.idx)}<span class="bk-swatch bk-ed-swatch" style="background:{singleColor(soloSingleIdxs.indexOf(t.idx))}"></span>{/if}<span class="bk-ed-fmt">{formatLabel(t.format)}</span>{#each markMatch(titleCase(t.title)) as p}{#if p.hit}<mark class="t-hit">{p.t}</mark>{:else}{p.t}{/if}{/each}</span>
									{#if editMode}
										<span class="bk-ed-tools">
											<select class="bk-move" aria-label="Move this edition to another book" onchange={(e) => { moveEdition(t.idx, e.currentTarget.value); e.currentTarget.value = ""; }}>
												<option value="">Move to…</option>
												{#each moveTargets as mt (mt.key)}{#if mt.key !== w.key}<option value={mt.key}>{mt.name}</option>{/if}{/each}
											</select>
											<button type="button" class="bk-x" title="Split this edition out into its own book" aria-label="Split out this edition" onclick={() => excludeEdition(t.idx)}>×</button>
										</span>
									{/if}
									<span class="bk-num">{t.total.toLocaleString()}</span>
								</li>
							{/each}
						{/if}
						{/if}
					{/each}
				</ul>
				{#if booksCapped && workBlocks.length > BOOKS_PREVIEW}
					<button type="button" class="books-more" onclick={() => (booksShowAll = true)}>Show all {workBlocks.length.toLocaleString()} books</button>
				{:else if booksShowAll && !editMode && !titleFilter.trim() && workBlocks.length > BOOKS_PREVIEW}
					<button type="button" class="books-more" onclick={() => (booksShowAll = false)}>Show fewer</button>
				{:else if hiddenWorkCount > 0}
					<p class="titles-more">Showing the top {visibleWorkBlocks.length.toLocaleString()} books. Type in the filter to find others.</p>
				{/if}
				{#if alsoCredited.length}
					{@const filers = [...new Set(alsoCredited.map((b) => displayName(b[2])))]}
					<!-- Credited, but filed under the first author the library lists, so
					     these checkouts count on that author's page, not this one. -->
					<div class="also-credited">
						<h3 class="ac-title">Also credited on</h3>
						<ul>
							{#each alsoCredited as [title, slug, name, total]}
								<li><button type="button" class="ac-book" onclick={() => openTitle(title, slug)}>{cleanTitleForDisplay(title) || title}</button> <span class="ac-with">with {displayName(name)}</span> <span class="ac-n">{compactNumber(total)} checkouts</span></li>
							{/each}
						</ul>
						<p class="ac-note">The library files {alsoCredited.length === 1 ? "this" : "these"} under {filers.length === 1 ? filers[0] : "the other authors"}, so {alsoCredited.length === 1 ? "its" : "their"} checkouts count there, not in the totals above.</p>
					</div>
				{/if}
			</section>
			{/if}
			</div><!-- /.split -->
		</div>
	{/if}

	{#if moveNote}
		<div class="move-note" role="status">
			<span>{moveNote.text}</span>
			<button type="button" class="move-undo" onclick={undoMove}>Undo</button>
		</div>
	{/if}

	{#if hoverTip}
		<div class="title-tip" style="left:{hoverTip.x + 14}px; top:{hoverTip.y + 16}px">{hoverTip.text}</div>
	{/if}
</div>


<style>
	.viewer {
		width: 100%;
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
	/* The plot checkbox wears the colour its work/edition has on the chart, so the
	   table marker matches the plotted band (blue work, its own hue once an edition
	   is ticked out, back to the work colour when unticked). */
	.tt-plot input[type="checkbox"] {
		accent-color: var(--chip-color, var(--color-fg));
	}

	/* Filter row mirroring the Most Borrowed tab's Show/Genre/Year fields. */
	.search-row {
		display: flex;
		align-items: flex-end;
		gap: 12px;
		flex-wrap: wrap;
		margin: 4px 0 12px;
	}
	.ta-field {
		flex: 1;
		min-width: 130px;
		display: flex;
		flex-direction: column;
		gap: 4px;
		font-family: var(--font-sans);
		font-size: var(--text-sm);
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--color-fg-light);
	}
	.ta-field.grow {
		flex: 2;
	}
	.ta-field select {
		width: 100%;
		font-family: var(--font-sans);
		font-size: var(--text-base);
		font-weight: 500;
		text-transform: none;
		letter-spacing: 0;
		color: var(--color-fg);
		padding: 9px 12px;
		border: 1px solid var(--color-border);
		border-radius: 8px;
		background: var(--color-white);
		cursor: pointer;
		min-width: 0;
	}
	.search {
		position: relative;
	}

	/* A clean white box, matching the field dropdowns' height. */
	.search input {
		width: 100%;
		box-sizing: border-box;
		padding: 9px 12px;
		font-family: var(--font-sans);
		font-size: var(--text-base);
		background: var(--color-white);
		color: var(--color-fg);
		border: 1px solid var(--color-border);
		border-radius: 8px;
		outline: none; /* override the global reset's 1px box outline */
	}

	.search input:focus {
		outline: none;
		border-color: #3f88cc;
		box-shadow: 0 0 0 3px rgba(63, 136, 204, 0.15);
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
		font-size: var(--text-base);
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
		flex: none;
	}
	/* Unified results: name/title + a small "Author"/"Book" tag on one line. */
	.res-line {
		display: inline-flex;
		align-items: baseline;
		gap: 8px;
		min-width: 0;
		flex: 1 1 auto;
	}
	.res-line > :first-child {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.res-kind {
		flex: none;
		font-size: 0.6rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		padding: 1px 6px;
		border-radius: 999px;
		line-height: 1.5;
	}
	.kind-book {
		background: #eaf2fb;
		color: #2f6ea8;
	}
	.kind-author {
		background: var(--color-gray-100);
		color: var(--color-fg-light);
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
		font-size: var(--text-sm);
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
		/* Leave room for the sticky masthead so a search scrolls the title into
		   view just below it, not underneath it. */
		scroll-margin-top: 72px;
		position: relative;
	}
	/* Book cover beside the title and byline (work pages). */
	.hd-main.has-cover {
		display: grid;
		grid-template-columns: 54px minmax(0, 1fr);
		column-gap: 16px;
		align-items: start;
	}
	.hd-main.has-cover > .hd-subjects { grid-column: 1 / -1; }
	.hd-text { min-width: 0; }
	.hd-cover {
		width: 54px;
		height: auto;
		margin-top: 5px;
		border-radius: 2px;
		box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.06), 0 2px 6px rgba(0, 0, 0, 0.16);
	}
	/* Header: name, description, subjects and counts on the left; Borrow and
	   Learn on the right of the name row (they wrap under it on phones). */
	.hd-top {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: var(--space-3) var(--space-5);
		flex-wrap: wrap;
	}
	.hd-main { min-width: 0; flex: 1 1 360px; }
	.hd-top .hdr-actions { margin: 10px 0 0; flex: 0 1 auto; max-width: 100%; gap: 6px 20px; }
	.hd-desc {
		font-family: var(--font-sans);
		font-size: 1.02rem;
		line-height: 1.4;
		color: var(--color-fg);
		margin: 4px 0 0;
	}
	.hd-subjects {
		font-family: var(--font-sans);
		font-size: var(--text-sm);
		line-height: 1.6;
		color: var(--color-fg-light);
		margin: 2px 0 0;
	}
	.hd-subjects a {
		color: var(--color-fg-light);
		text-decoration: underline;
		text-decoration-color: var(--color-border);
		text-underline-offset: 3px;
	}
	.hd-subjects a:hover { color: var(--color-fg); text-decoration-color: currentColor; }
	.hd-sep { color: #aaa; }
	/* "#N in Genre" ranking badges under the work title. */
	.genre-ranks {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
		margin: var(--space-4) 0 var(--space-5);
	}
	.genre-rank {
		font-family: var(--font-sans);
		font-size: var(--text-sm);
		font-weight: 500;
		color: var(--color-fg);
		background: var(--color-gray-100);
		border: 1px solid var(--color-border);
		border-radius: 999px;
		padding: 2px 10px;
		white-space: nowrap;
		cursor: pointer;
		transition: border-color 0.12s, background 0.12s;
	}
	.genre-rank:hover {
		border-color: #3f88cc;
		background: var(--color-white);
	}
	.genre-rank strong {
		font-weight: 700;
		color: #3f88cc;
	}
	/* Subject-tag pills next to the genre-rank badges, near the top. */
	.subj-pill {
		font-family: var(--font-sans);
		font-size: var(--text-sm);
		font-weight: 500;
		color: var(--color-fg-light);
		background: var(--color-white);
		border: 1px solid var(--color-border);
		border-radius: 999px;
		padding: 2px 10px;
		white-space: nowrap;
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
		gap: var(--space-2);
		margin: var(--space-3) 0 var(--space-1);
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
		font-size: var(--text-sm);
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
		font-size: var(--text-sm);
		line-height: 1.5;
		white-space: nowrap;
	}

	/* the author search + "most borrowed" chips, relocated below the chart --
	   in the same gray panel styling as the "on the chart" section below it */
	.picker-below {
		margin: 10px 0 16px;
		padding: 0;
		border: none;
		background: none;
	}
	/* format legend for the overview "by format" area chart */
	/* "By book" / "By format" lines are named at their ends on wide screens; on
	   phones (no room for those names) this legend takes over. */
	.format-legend {
		display: flex;
		justify-content: center;
		flex-wrap: wrap;
		gap: 18px;
		margin: 10px 0 2px;
		font-family: var(--font-sans);
		font-size: var(--text-sm);
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
	/* Not on the chart right now: gray swatch and name (click to add). */
	.leg-btn.dim {
		color: var(--color-fg-light);
		font-weight: 500;
	}
	.leg-btn.dim .fmt-sw {
		background: #d5d8dc !important;
	}
	.leg-btn.on {
		background: var(--color-gray-100);
		box-shadow: inset 0 0 0 1.5px var(--color-border);
	}
	/* A legend entry the user clicked to hide from the chart. */
	.leg-btn.hidden-leg {
		opacity: 0.4;
		text-decoration: line-through;
	}
	.leg-btn.hidden-leg .fmt-sw {
		background: var(--color-gray-300, #ccc) !important;
	}
	/* "Other" band: not isolatable, but has a small × to hide it. */
	.other-leg {
		gap: 4px;
		padding: 2px 2px 2px 4px;
	}
	.other-leg.dim {
		opacity: 0.38;
	}
	.other-leg.hidden-leg {
		opacity: 0.55;
		text-decoration: line-through;
	}
	.other-leg.hidden-leg .fmt-sw {
		background: var(--color-gray-300, #ccc) !important;
	}
	.leg-x {
		border: none;
		background: none;
		padding: 0 3px;
		font-size: 1rem;
		line-height: 1;
		color: var(--color-fg-light);
		cursor: pointer;
		border-radius: 4px;
		text-decoration: none;
		display: inline-block;
	}
	.leg-x:hover {
		background: var(--color-gray-100);
		color: var(--color-fg);
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
		font-size: var(--text-sm);
		font-weight: 600;
		color: var(--color-fg);
		cursor: pointer;
	}
	.leg-showall:hover {
		border-color: var(--color-fg-light);
		background: var(--color-gray-100);
	}

	/* ---- Shared control metrics ----------------------------------------------
	   Every pill control on the page (Total/All titles, Borrow, Learn, Download,
	   Share, Add/edit) shares this box: 0.82rem/600 text, 6px 14px padding, a
	   1.5px border, and a 999px radius, so they all sit at the SAME height. Neutral
	   controls are outlined; the one accent (Borrow) fills blue but keeps a
	   transparent 1.5px border so its height matches. Emphasis comes from fill,
	   never from size. */
	.chart-action {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		font-family: var(--font-sans);
		font-size: var(--text-sm);
		font-weight: 600;
		line-height: 1;
		padding: 6px 14px;
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
	/* OWID-style "Download ▾" dropdown → Data (CSV) / Image (PNG). */
	.dl-wrap {
		position: relative;
		display: inline-flex;
	}
	.dl-caret {
		font-size: 0.7em;
		opacity: 0.7;
	}
	.dl-menu {
		left: 0;
		right: auto;
		min-width: 190px;
	}
	.dl-ic {
		background: none !important;
		color: var(--color-fg-light);
	}
	.dl-ic svg {
		display: block;
	}
	.dl-fmt {
		margin-left: auto;
		font-size: 0.68rem;
		font-weight: 700;
		letter-spacing: 0.04em;
		color: var(--color-fg-light);
		opacity: 0.8;
	}
	/* square icon-only buttons (download / share) */
	.chart-action.square {
		width: 34px;
		height: 34px;
		padding: 0;
		justify-content: center;
		border-radius: 8px;
		font-size: var(--text-lg);
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
		font-size: var(--text-sm);
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
		font-size: var(--text-sm);
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
		font-size: var(--text-xs);
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
	/* The works-panel header is a toggle styled exactly like the "On the chart"
	   panel label (small uppercase sans), at every width. Shown per-breakpoint. */
	.side-desktop-head {
		display: none;
		align-items: center;
		gap: 8px;
		width: 100%;
		padding: 12px 0;
		margin: 0;
		border: none;
		background: none;
		cursor: pointer;
		text-align: left;
	}
	.sdh-label {
		font-family: var(--font-sans);
		font-size: 1.05rem;
		font-weight: 600;
		color: var(--color-fg);
	}
	.sdh-count {
		margin-left: 5px;
		font-weight: 600;
		opacity: 0.7;
	}
	.side-desktop-head:hover .sdh-label {
		color: var(--color-fg);
	}
	.side-chevron {
		margin-left: auto;
		color: var(--color-fg);
		font-size: 1.6rem;
		line-height: 1;
		align-self: center;
		transition: transform 0.15s ease;
	}
	.side-chevron.open {
		transform: rotate(180deg);
	}

	/* On desktop the books table is its own section under the chart: a heading
	   rule, no card. The heading still collapses it. */
	@media (min-width: 861px) {
		.split-side {
			background: none;
			border: 0;
			border-top: 1px solid var(--color-border);
			border-radius: 0;
			padding: 6px 0 0;
		}
		.side-desktop-head {
			display: flex;
		}
		.split-side:not(.collapsed) .side-desktop-head {
			border-bottom: 1px solid var(--color-border);
			margin-bottom: 12px;
		}
		.split-side.collapsed .titles {
			display: none;
		}
	}

	@media (max-width: 860px) {
		/* On phones Download and Share split the full width evenly. */
		.chart-actions {
			gap: 8px;
		}
		.chart-actions > .dl-wrap,
		.chart-actions > .share-wrap {
			flex: 1 1 0;
			min-width: 0;
		}
		.chart-actions > .dl-wrap > .chart-action,
		.chart-actions > .share-wrap > .chart-action {
			width: 100%;
			justify-content: center;
		}
		/* Phones: a smaller cover, still beside the title (never stacked on top). */
		.hd-main.has-cover { grid-template-columns: 40px minmax(0, 1fr); column-gap: 12px; }
		.hd-cover { width: 40px; margin-top: 4px; }
		.split {
			display: block;
		}
		/* By default the works table sits inline at the bottom, below the chart --
		   as one gray card, matching the desktop panel and the "On the chart" box. */
		.split-side {
			margin-top: 24px;
			background: var(--color-gray-100);
			border: 1px solid var(--color-border);
			border-radius: var(--radius-md);
			padding: 4px 14px 14px;
		}
		/* "Add/edit titles" pops the same table up as a full-screen white drawer. */
		.split-side.open {
			position: fixed;
			inset: 0;
			z-index: 60;
			height: 100dvh;
			margin: 0;
			border: none;
			border-radius: 0;
			background: var(--color-white);
			padding: 10px 14px 48px;
			overflow: auto;
			box-shadow: 0 -6px 28px rgba(0, 0, 0, 0.22);
		}
		/* drawer header (with Done) only when popped up... */
		.split-side.open .side-mobile-head {
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
			font-size: var(--text-base);
		}
		/* ...inline, the same small-uppercase toggle as desktop (matching the "On
		   the chart" panel); the underline only appears once the table is open. */
		.split-side:not(.open) .side-desktop-head {
			display: flex;
		}
		.split-side:not(.open):not(.collapsed) .side-desktop-head {
			border-bottom: 1px solid var(--color-border);
			margin-bottom: 12px;
		}
		.split-side:not(.open).collapsed .titles {
			display: none;
		}
		.side-close {
			font-family: var(--font-sans);
			font-weight: 700;
			font-size: var(--text-sm);
			padding: 6px 18px;
			border: none;
			border-radius: 999px;
			background: var(--color-fg);
			color: var(--color-white);
			cursor: pointer;
		}
		/* The floating "Add/edit titles" shortcut is removed on phones — the works
		   table sits inline just below the chart, so the button was redundant clutter. */
		.edit-titles-btn {
			display: none;
		}
	}

	.author h2 {
		font-family: var(--font-serif);
		font-size: var(--text-3xl);
		line-height: 1.1;
		margin: 0;
	}
	/* Heading carries the Wikipedia hover card (author or work). */
	/* Keep the author name and its "i" info icon on the same line — the icon rides
	   at the baseline of the name instead of wrapping onto a lonely next line. */
	.hd-name {
		display: flex;
		align-items: baseline;
		gap: 2px;
	}
	.h2-wrap {
		position: relative;
		display: inline-block;
		min-width: 0;
		max-width: 100%;
	}
	.h2-hoverable {
		cursor: pointer;
		text-decoration: underline dotted;
		text-decoration-color: var(--color-border);
		text-decoration-thickness: 1.5px;
		text-underline-offset: 6px;
	}
	.h2-hoverable:hover {
		text-decoration-color: var(--color-fg-light);
	}
	.wiki-pop {
		position: absolute;
		top: 100%;
		left: 0;
		z-index: 45;
		padding-top: 6px;
		cursor: default;
	}
	.wiki-backdrop {
		position: fixed;
		inset: 0;
		z-index: 40;
		background: rgba(0, 0, 0, 0.12);
		border: none;
		cursor: default;
	}
	@media (hover: none), (max-width: 599px) {
		.wiki-pop {
			position: fixed;
			top: auto;
			left: 12px;
			right: 12px;
			bottom: 16px;
			padding-top: 0;
			z-index: 46;
		}
	}

	/* One compact subhead line: "N checkouts · M works · Learn more ▾ · variants". */
	.hdr-line {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: 3px 8px;
		margin: 4px 0 0;
		font-family: var(--font-sans);
		color: var(--color-fg-light);
	}
	.hdr-line .meta {
		font-family: var(--font-sans);
		color: var(--color-fg-light);
		margin: 0;
	}
	/* Borrow + Learn more sit on their own line under the byline, left-aligned. */
	.hdr-actions {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 8px;
		margin: 0 0 14px;
	}
	/* Author name in the work heading — click to switch to that author's search. */
	.author-link {
		font: inherit;
		color: inherit;
		background: none;
		border: none;
		padding: 0;
		cursor: pointer;
		text-decoration: underline;
		text-decoration-color: var(--color-border);
		text-underline-offset: 2px;
	}
	.author-link:hover {
		color: #3f88cc;
		text-decoration-color: #3f88cc;
	}
	.hdr-sep {
		color: var(--color-fg-light);
		opacity: 0.55;
	}
	/* "Learn" — a neutral outlined pill (secondary), same box as the shared control
	   spec. Borrow is the single accent; Learn stays quiet beside it. */
	.hdr-chip {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		font-family: var(--font-sans);
		font-size: var(--text-sm);
		font-weight: 600;
		line-height: 1;
		padding: 6px 14px;
		border: 1.5px solid var(--color-border);
		border-radius: 999px;
		background: var(--color-white);
		color: var(--color-fg);
		cursor: pointer;
		white-space: nowrap;
		transition: border-color 0.12s, background 0.12s;
	}
	.hdr-chip:hover {
		border-color: var(--color-fg-light);
		background: #f7f7f7;
	}
	.hdr-caret {
		font-size: 0.7em;
		opacity: 0.6;
	}
	/* SPL catalog icon link, sitting just left of "Learn more". */
	.hdr-spl {
		display: inline-flex;
		align-items: center;
		vertical-align: -3px;
		opacity: 0.8;
	}
	.hdr-spl:hover {
		opacity: 1;
	}
	.hdr-spl-ic {
		width: 16px;
		height: 16px;
		object-fit: contain;
		display: block;
	}
	/* SPL icon sitting to the right of the author/work name (after the "i" info). */
	.name-spl {
		align-self: center;
		margin-left: 8px;
		flex: none;
	}
	.hdr-caret {
		font-size: var(--text-xs);
	}
	.lookup-wrap {
		position: relative;
		display: inline-flex;
	}
	.lookup-menu {
		position: absolute;
		top: calc(100% + 6px);
		/* "More" sits at the page's right edge: open the menu leftward. */
		right: 0;
		z-index: 41;
		display: flex;
		flex-direction: column;
		min-width: 230px;
		padding: 5px;
		background: var(--color-white);
		border: 1px solid var(--color-border);
		border-radius: 10px;
		box-shadow: 0 8px 24px rgba(0, 0, 0, 0.16);
	}
	.lookup-menu a {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 14px;
		padding: 8px 10px;
		border-radius: 7px;
		font-family: var(--font-sans);
		font-size: var(--text-sm);
		font-weight: 600;
		color: #3f88cc;
		text-decoration: none;
	}
	.lookup-menu a:hover {
		background: var(--color-gray-100);
	}
	.lookup-menu a.lm-spl {
		color: #1f7a4d;
	}
	.lookup-menu a span {
		color: var(--color-fg-light);
		font-size: var(--text-xs);
	}

	/* Small (i) next to the author name: hover/focus shows the name-variants popover. */
	.name-info {
		position: relative;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		flex: none;
		width: 17px;
		height: 17px;
		margin-left: 7px;
		border-radius: 50%;
		border: 1.5px solid var(--color-border);
		color: var(--color-fg-light);
		font-family: var(--font-sans);
		font-style: normal;
		font-weight: 600;
		font-size: var(--text-xs);
		line-height: 1;
		cursor: help;
		vertical-align: 0.35em;
		outline: none;
	}
	.name-info:hover,
	.name-info:focus-visible {
		border-color: var(--color-fg-light);
		color: var(--color-fg);
	}
	.name-info-pop {
		display: none;
		position: absolute;
		top: calc(100% + 7px);
		left: 0;
		z-index: 45;
		width: 270px;
		max-width: 78vw;
		padding: 11px 13px;
		background: var(--color-white);
		border: 1px solid var(--color-border);
		border-radius: 10px;
		box-shadow: 0 8px 26px rgba(0, 0, 0, 0.16);
		text-align: left;
		cursor: default;
	}
	.name-info:hover .name-info-pop,
	.name-info:focus-within .name-info-pop {
		display: block;
	}
	.ni-head {
		display: block;
		font-family: var(--font-sans);
		font-size: 0.68rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--color-fg-light);
		margin-bottom: 7px;
	}
	.name-info-pop ul {
		margin: 0;
		padding: 0 0 0 16px;
		max-height: 200px;
		overflow-y: auto;
	}
	.name-info-pop li {
		font-family: var(--font-sans);
		font-size: var(--text-sm);
		line-height: 1.5;
		color: var(--color-fg);
	}
	.ni-note {
		display: block;
		margin-top: 8px;
		font-family: var(--font-sans);
		font-size: var(--text-xs);
		line-height: 1.45;
		color: var(--color-fg-light);
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
		font-size: var(--text-sm);
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
		font-size: var(--text-xs);
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
		font-size: var(--text-xs);
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
		font-size: var(--text-sm);
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
		font-size: var(--text-sm);
		color: var(--color-fg);
	}

	.done-btn {
		flex: none;
		font-family: var(--font-sans);
		font-size: var(--text-sm);
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
		font-size: var(--text-base);
	}

	.bundle-name {
		display: flex;
		align-items: center;
		gap: 10px;
		margin: 12px 0 0;
		font-family: var(--font-sans);
		font-size: var(--text-sm);
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
		font-size: var(--text-base);
		background: var(--color-input-bg);
		border: 1.5px solid var(--color-border);
		border-radius: var(--radius-sm);
	}

	.bundle-name input:focus {
		outline: none;
		border-color: #e3120b;
	}

	.groups-panel {
		margin: var(--space-1) 0 var(--space-5);
		padding: var(--space-4);
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
		font-size: var(--text-sm);
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
		font-size: var(--text-sm);
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
		font-size: var(--text-sm);
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
		font-size: var(--text-sm);
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
		align-items: center;
		gap: 0;
	}

	/* linked highlight (see .work-header.hl): ring the WHOLE pill when its work row
	   is hovered, and vice versa. The ring lives on the ROW so it wraps both the
	   name and the pencil as one stadium — not just the name segment (whose square
	   right edge left the pencil sticking out past the ring). */
	.group-chip-row.hl {
		border-radius: 999px;
		box-shadow: 0 0 0 2px #e58a00;
	}
	.group-chip-row.hl .group-chip,
	.group-chip-row.hl .chip-edit {
		border-color: #e58a00;
	}

	/* The name is a self-contained rounded pill; Edit (✎) and × are separate ghost
	   icon buttons that sit just after it — no heavy segment dividers. */
	.group-chip {
		display: flex;
		align-items: center;
		gap: 7px;
		font-family: var(--font-sans);
		font-size: var(--text-sm);
		padding: 6px 12px 6px 8px;
		border-radius: 999px;
		border: 1.5px solid var(--color-border);
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
		/* One line with an ellipsis so every pill stays the same tidy height. Long
		   titles used to wrap to 2-3 lines, making tall lopsided pills and stretching
		   the pencil segment. The full title still shows on hover (hoverTip) and in
		   the works table below. */
		max-width: 230px;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.chip-count {
		flex: none;
		opacity: 0.75;
		font-variant-numeric: tabular-nums;
	}

	/* Work chip: the name and the pencil form ONE seamless pill — the name is the
	   left segment (rounded left, no right border), the pencil the right segment
	   (rounded right, no left border), so nothing floats separately beside it. */
	.group-chip.work-chip {
		border-radius: 999px 0 0 999px;
		border-right: none;
		padding-right: 3px;
	}
	.chip-edit {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 30px;
		align-self: stretch;
		flex: none;
		padding: 0;
		border: 1.5px solid var(--color-border);
		border-left: none;
		border-radius: 0 999px 999px 0;
		background: var(--color-white);
		color: var(--color-fg-light);
		font-size: var(--text-base);
		line-height: 1;
		cursor: pointer;
		transition: background 0.12s, color 0.12s, border-color 0.12s;
	}
	.group-chip.work-chip:hover,
	.group-chip.work-chip:hover + .chip-edit {
		border-color: var(--chip-color, var(--color-fg-light));
	}
	.chip-edit:hover {
		background: var(--color-gray-100);
		color: var(--color-fg);
	}
	/* Editing: the whole pill fills with the work's colour. */
	.group-chip.work-chip.active + .chip-edit,
	.chip-edit.on {
		background: var(--chip-color, var(--color-fg));
		border-color: var(--chip-color, var(--color-fg));
		color: var(--color-white);
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
		font-size: var(--text-xs);
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

	.editing-hint {
		font-family: var(--font-sans);
		font-size: var(--text-sm);
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

	/* subtle hover hint instead of a boxed info panel */
	.title-hint {
		position: relative;
		display: inline-block;
		margin: 10px 0 0;
		font-family: var(--font-sans);
		font-size: var(--text-sm);
		color: var(--color-fg-light);
		cursor: help;
		outline: none;
	}
	.title-hint .th-ic {
		font-style: normal;
	}
	.th-pop {
		display: none;
		position: absolute;
		top: calc(100% + 6px);
		left: 0;
		z-index: 45;
		width: 300px;
		max-width: 82vw;
		padding: 10px 13px;
		background: var(--color-white);
		border: 1px solid var(--color-border);
		border-radius: 10px;
		box-shadow: 0 8px 24px rgba(0, 0, 0, 0.16);
		font-size: var(--text-sm);
		line-height: 1.5;
		color: var(--color-fg);
		cursor: default;
	}
	.title-hint:hover .th-pop,
	.title-hint:focus .th-pop,
	.title-hint:focus-within .th-pop {
		display: block;
	}
	.th-pop strong {
		font-weight: 700;
	}
	/* "?" help badge next to the "Find a work" label — carries the old
	   "Not finding a work?" explanation as a hover/focus tooltip. */
	.nf-hint {
		position: relative;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 15px;
		height: 15px;
		margin-left: 5px;
		border: 1.5px solid var(--color-border);
		border-radius: 50%;
		font-size: 0.62rem;
		font-weight: 700;
		line-height: 1;
		color: var(--color-fg);
		cursor: help;
		vertical-align: middle;
		text-transform: none;
		letter-spacing: 0;
		outline: none;
	}
	.nf-hint:hover {
		border-color: var(--color-fg-light);
	}
	.nf-hint:hover .th-pop,
	.nf-hint:focus .th-pop,
	.nf-hint:focus-within .th-pop {
		display: block;
	}
	/* the tooltip sits inside the uppercase label — reset it to normal text */
	.nf-pop {
		font-weight: 400;
		text-transform: none;
		letter-spacing: 0;
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

	.suggest-row {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 8px;
		margin: 14px 0 4px;
		font-family: var(--font-sans);
	}
	.suggest-btn {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		font-family: var(--font-sans);
		font-size: var(--text-base);
		font-weight: 500;
		color: var(--color-fg);
		padding: 7px 14px;
		border: 1px solid var(--color-border);
		border-radius: 999px;
		background: var(--color-white);
		cursor: pointer;
	}
	.suggest-btn:hover {
		border-color: #b6c2ce;
	}
	/* "Surprise me" keeps its playful purple, but the same size/shape as Suggestions. */
	.surprise-btn {
		color: #6a4c93;
	}
	.surprise-btn:hover {
		background: #6a4c93;
		border-color: #6a4c93;
		color: var(--color-white);
	}
	/* starting points as one quiet line of text links */
	p.suggest-row { margin: 4px 0 6px; gap: 6px; font-size: var(--text-sm); color: var(--color-fg-light); }
	.suggest-lead { margin-right: 2px; }
	.suggest-sep { color: #aaa; }
	p.suggest-row .suggest-btn,
	p.suggest-row .surprise-btn {
		padding: 0;
		border: 0;
		border-radius: 0;
		background: none;
		font-size: var(--text-sm);
		font-weight: 500;
		color: var(--color-fg);
		text-decoration: underline;
		text-decoration-color: var(--color-border);
		text-underline-offset: 3px;
	}
	p.suggest-row .suggest-btn:hover,
	p.suggest-row .surprise-btn:hover { background: none; color: var(--color-fg); text-decoration-color: currentColor; }
	/* Closes the page masthead: the intro + starting points, then the rule. */
	.try-row { display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 7px; margin: 10px 0 0; font-family: var(--font-sans); font-size: 14.5px; color: var(--color-fg-light); }
	.try-lead { margin-right: 1px; }
	.try-lead::after { content: ":"; }
	.try-sep { color: var(--color-gray-300, #c8c8c8); }
	.try-link { padding: 0; border: 0; background: none; font: inherit; color: var(--color-fg); cursor: pointer; text-decoration: underline; text-decoration-color: var(--color-border); text-underline-offset: 3px; }
	.try-link:hover { text-decoration-color: currentColor; }
	.try-link.is-title { font-style: italic; }
	.try-link.try-surprise { color: var(--color-fg-light); }
	/* Phones: one suggestion and "Surprise me". */
	@media (max-width: 600px) { .try-extra { display: none; } }
	.picker-block {
		border-bottom: 3px solid var(--color-fg);
		padding-bottom: 12px;
		margin-bottom: 16px;
	}
	.picker-block p.suggest-row { margin: 8px 0 0; }
	/* Underline the word only, not the caret beside it. */
	p.suggest-row .suggest-btn:not(.surprise-btn) { text-decoration: none; }
	.sb-txt {
		text-decoration: underline;
		text-decoration-color: var(--color-border);
		text-underline-offset: 3px;
	}
	.suggest-btn:hover .sb-txt { text-decoration-color: currentColor; }
	.suggest-caret {
		font-size: var(--text-xs);
		transition: transform 0.15s ease;
	}
	.suggest-caret.open {
		transform: rotate(180deg);
	}
	.suggest-pills {
		margin-top: 8px;
	}

	.quick-label {
		font-size: var(--text-sm);
		font-weight: 600;
		color: var(--color-fg-light);
	}

	.chip {
		font-family: var(--font-sans);
		font-size: var(--text-sm);
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
	/* Phones (OWID-style): just the name over the chart, icon tabs for Total /
	   By book, the rest under "Customize", square Download / Share buttons. */
	.on-phone { display: none !important; }
	.mode-toggle button { display: inline-flex; align-items: center; gap: 6px; }
	.customize-btn { display: inline-flex; align-items: center; gap: 6px; padding: 6px 12px; border: 1px solid var(--color-border); border-radius: 8px; background: #fff; font-family: var(--font-sans); font-size: 14px; font-weight: 500; color: var(--color-fg); cursor: pointer; }
	.customize-btn.on { background: var(--color-gray-100); }
	.customize-panel .compare-btn { width: auto; height: auto; text-align: left; }
	.customize-panel .compare-btn :global(svg), .customize-btn :global(svg), .mode-toggle :global(svg) { width: 16px !important; height: 16px !important; flex: none; }
	.customize-panel { flex-direction: column; align-items: flex-start; gap: 12px; margin: 0 0 14px; padding: 12px 14px; border: 1px solid var(--color-border); border-radius: 8px; background: #fafafa; }
	@media (max-width: 600px) {
		.on-phone { display: inline-flex !important; }
		.customize-panel.on-phone { display: flex !important; }
		.off-phone { display: none !important; }
		/* Name, then just the byline and total ("by Robin Wall Kimmerer · 52.2k
		   total checkouts"), with a book's cover small beside it; no
		   description, subjects or Borrow row. */
		.hd-desc, .hd-subjects, .hdr-actions { display: none !important; }
		.customize-row.on-phone { display: flex !important; justify-content: flex-start; margin: 0 0 10px; }
		.hd-main.has-cover { grid-template-columns: 52px minmax(0, 1fr); column-gap: 12px; }
		.hd-cover { width: 52px; margin-top: 2px; }
		.mode-toggle .mt-txt { display: none; }
		.mode-toggle button { padding: 7px 12px; }
		.chart-foot .tb-txt { display: none; }
		.chart-foot .tb-btn { width: 36px; height: 36px; padding: 0; justify-content: center; }
		.chart-foot .tb-btn :global(svg) { width: 17px; height: 17px; }
		.chart-foot .foot-actions { margin-left: auto !important; }
		.iso-note { display: none !important; }
		.format-legend { justify-content: flex-start; gap: 2px 12px; font-size: 13px; }
	}
	.also-credited { margin: 22px 0 0; padding-top: 14px; border-top: 1px solid var(--color-border); font-family: var(--font-sans); }
	.ac-title { margin: 0 0 8px; font-size: 1rem; font-weight: 600; color: var(--color-fg); }
	.also-credited ul { list-style: none; margin: 0; padding: 0; }
	.also-credited li { display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 8px; padding: 5px 0; }
	.ac-book { padding: 0; border: 0; background: none; font-family: var(--font-serif); font-size: 1.05rem; color: var(--color-fg); cursor: pointer; text-decoration: underline; text-decoration-color: var(--color-border); text-underline-offset: 3px; }
	.ac-book:hover { text-decoration-color: currentColor; }
	.ac-with { font-size: 14px; color: var(--color-fg-light); }
	.ac-n { margin-left: auto; font-size: 14px; font-variant-numeric: tabular-nums; color: var(--color-fg); }
	.ac-note { margin: 8px 0 0; font-size: 13px; color: var(--color-fg-light); }
	.compare-btn { display: inline-flex; align-items: center; gap: 5px; padding: 6px 12px; border: 1px solid var(--color-border); border-radius: 8px; background: #fff; font-family: var(--font-sans); font-size: 14px; font-weight: 500; color: var(--color-fg); cursor: pointer; }
	.compare-btn:hover { border-color: var(--color-fg-light); }
	.plot-toolbar {
		margin-top: var(--space-5) !important;
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-3);
		flex-wrap: wrap;
		margin: 0 0 var(--space-5);
	}
	.plot-toolbar .mode-toggle {
		margin: 0;
	}
	/* The chart's view toggle: two ordinary buttons side by side (no shared
	   pill outline); the selected one is filled. */
	.plot-toolbar .mode-toggle {
		border: 0;
		border-radius: 0;
		overflow: visible;
		gap: 6px;
	}
	.plot-toolbar .mode-toggle button {
		border: 1px solid var(--color-border);
		border-radius: 8px;
		padding: 7px 13px;
		font-weight: 500;
		color: var(--color-fg);
	}
	.plot-toolbar .mode-toggle button + button { border-left: 1px solid var(--color-border); }
	.plot-toolbar .mode-toggle button:hover:not(.active) { border-color: var(--color-fg-light); }
	.plot-toolbar .mode-toggle button.active {
		background: var(--color-fg);
		border-color: var(--color-fg);
		color: var(--color-white);
	}
	.tb-left { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
	.tb-right { display: flex; align-items: center; }
	.chart-actions.tb-actions { margin: 0; }
	.chart-actions.tb-actions > .dl-wrap,
	.chart-actions.tb-actions > .share-wrap { flex: none; min-width: auto; }
	/* One quiet button style for the page: Learn more, Download, Share (Borrow
	   at SPL matches it from BorrowMenu's outline variant). */
	.tb-btn {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		font-family: var(--font-sans);
		font-size: var(--text-sm);
		font-weight: 500;
		line-height: 1;
		padding: 7px 11px;
		border: 1px solid var(--color-border);
		border-radius: 8px;
		background: var(--color-white);
		color: var(--color-fg);
		cursor: pointer;
		white-space: nowrap;
	}
	.tb-btn:hover { border-color: var(--color-fg-light); }
	/* Header links: "Borrow at SPL" (straight to the catalog) and "More". */
	.hd-link { display: inline-flex; align-items: center; gap: 6px; padding: 2px 0; border: 0; background: none; font-family: var(--font-sans); font-size: var(--text-sm); font-weight: 500; color: var(--color-fg); cursor: pointer; white-space: nowrap; }
	.hd-link .hl-text { text-decoration: underline; text-decoration-color: var(--color-border); text-underline-offset: 3px; }
	.hd-link:hover .hl-text { text-decoration-color: currentColor; }
	.hd-link :global(svg) { width: 15px; height: 15px; color: var(--color-fg-light); flex: none; }
	.hd-link :global(svg.lucide-chevron-down), .hd-link :global(svg.lucide-arrow-up-right) { width: 13px; height: 13px; }
	a.hd-link { text-decoration: none; }
	.hd-link .hl-logo { width: 18px; height: 18px; border-radius: 2px; flex: none; }
	.lookup-menu .lm-group { padding: 8px 10px 2px; font-size: 11px; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; color: var(--color-fg-light); }
	.lookup-menu .lm-sub { margin-left: auto; font-size: 12px; color: var(--color-fg-light); }
	/* Menus in the same quiet style as the buttons */
	.share-menu, .lookup-menu {
		min-width: 196px;
		padding: 4px;
		border-radius: 8px;
		box-shadow: 0 6px 20px rgba(0, 0, 0, 0.1);
	}
	.share-menu .share-item, .lookup-menu a {
		gap: 10px;
		padding: 8px 10px;
		border-radius: 6px;
		font-size: var(--text-sm);
		font-weight: 500;
		color: var(--color-fg);
	}
	.share-menu .share-item:hover, .lookup-menu a:hover { background: var(--color-gray-100); }
	.share-menu .share-ic {
		width: 16px;
		height: 16px;
		border-radius: 0;
		background: none !important;
		color: var(--color-fg-light);
	}
	.share-menu .share-ic :global(svg) { display: block; width: 15px; height: 15px; }
	.share-menu .dl-fmt { font-size: 11px; font-weight: 500; letter-spacing: 0.03em; opacity: 1; }
	.lookup-menu a :global(svg) { width: 14px; height: 14px; color: var(--color-fg-light); flex: none; }
	.tb-btn :global(svg) { flex: none; width: 15px; height: 15px; color: var(--color-fg-light); }
	.tb-btn :global(svg.lucide-chevron-down) { width: 14px; height: 14px; }
	.iso-note { font-family: var(--font-sans); font-size: var(--text-sm); color: var(--color-fg-light); }
	.iso-showall { background: none; border: 0; padding: 0; font: inherit; color: var(--color-fg); cursor: pointer; text-decoration: underline; text-underline-offset: 3px; }
	.iso-showall.iso-book { color: #3f88cc; font-weight: 600; }
	.leg-showall.leg-book { color: #3f88cc; border-color: #b9d3ec; }
	.smooth-toggle {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		font-family: var(--font-sans);
		font-size: var(--text-sm);
		color: var(--color-fg-light);
		cursor: pointer;
		user-select: none;
	}
	.smooth-toggle input { margin: 0; accent-color: var(--color-fg); }
	.chart-foot { display: flex; justify-content: space-between; align-items: center; gap: 8px 16px; flex-wrap: wrap; margin: 16px 0 0; }
	.chart-foot .chart-source { margin: 0; flex: 1 1 260px; }
	.chart-foot .foot-actions { display: flex; gap: 8px; align-items: center; flex: none; }
	/* Download / Share: quiet gray buttons (as on Our World in Data), so they
	   read as clickable without competing with the chart. */
	.chart-foot .tb-btn { padding: 5px 10px; border: 0; border-radius: 6px; background: #f1f2f3; font-size: 12.5px; font-weight: 500; color: #555; gap: 5px; }
	.chart-foot .tb-btn:hover { background: #e4e6e8; color: var(--color-fg); }
	.chart-foot .tb-btn :global(svg) { width: 13px; height: 13px; color: currentColor; }
	.chart-foot .tb-btn :global(svg.lucide-chevron-down) { width: 12px; height: 12px; }
	.chart-foot .share-menu { left: auto; right: 0; }
	/* On a phone the links wrap under the source, at the left: open menus rightward. */
	.chart-source a { color: inherit; text-decoration: underline; text-decoration-color: #c9c9c9; text-underline-offset: 2px; }
	.chart-source a:hover { color: var(--color-fg); text-decoration-color: currentColor; }
	.chart-source {
		font-family: var(--font-sans);
		font-size: 12px;
		color: #8a8a8a;
		margin: 6px 0 0;
	}
	.top-works-btn {
		font-family: var(--font-sans);
		font-size: var(--text-sm);
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
		border: 1.5px solid var(--color-border);
		border-radius: 999px;
		overflow: hidden;
		font-family: var(--font-sans);
	}

	.mode-toggle button {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		padding: 6px 14px;
		font-size: var(--text-sm);
		font-weight: 600;
		line-height: 1;
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
		font-size: var(--text-sm);
		line-height: 1.4;
		color: var(--color-fg-light);
		margin: 0 0 10px;
	}
	.works-min-note em {
		font-style: normal;
		font-weight: 600;
		color: #c2255c;
	}
	.works-why {
		color: #3f88cc;
		font-weight: 600;
		text-decoration: none;
		white-space: nowrap;
	}
	.works-why:hover {
		text-decoration: underline;
	}
	/* "How does this work?" — a subtle inline see-more disclosure. */
	.works-more {
		display: inline;
		margin-left: 4px;
	}
	.works-more > summary {
		display: inline;
		list-style: none;
		cursor: pointer;
		color: #3f88cc;
		font-weight: 600;
	}
	.works-more > summary::-webkit-details-marker {
		display: none;
	}
	.works-more > summary::after {
		content: " ▾";
		font-size: 0.85em;
	}
	.works-more[open] > summary::after {
		content: " ▴";
	}
	.works-more > summary:hover {
		text-decoration: underline;
	}
	.works-more-body {
		display: block;
		margin-top: 5px;
	}

	.titles-header {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 10px;
		margin-bottom: 8px;
	}

	/* Wide screens: the line labels hang out into the empty right margin, so the
	   plot itself runs the full width of the column (--hang is the label room;
	   always at least 24px from the window edge). */
	@media (min-width: 1080px) {
		.chart-panel { margin-right: calc(-1 * max(0px, min(var(--hang, 0px), (100vw - 960px) / 2 - 24px))); }
	}
	/* ---- Books table (under the chart) -------------------------------- */
	.books {
		margin: var(--space-6) 0 var(--space-4);
		padding-top: var(--space-4);
		border-top: 1px solid var(--color-border);
		font-family: var(--font-sans);
	}
	.bk-head {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 10px 16px;
		flex-wrap: wrap;
		margin: 0 0 10px;
	}
	.bk-title { font-family: var(--font-sans); font-size: 1.1rem; font-weight: 600; margin: 0; color: var(--color-fg); }
	.bk-count { font-weight: 400; color: var(--color-fg-light); }
	.bk-tools { display: flex; gap: 8px; align-items: center; }
	.bk-filter {
		width: 180px;
		padding: 7px 10px;
		font: inherit;
		font-size: var(--text-sm);
		border: 1px solid var(--color-border);
		border-radius: 8px;
		background: var(--color-white);
	}
	.bk-btn {
		font-family: var(--font-sans);
		font-size: var(--text-sm);
		font-weight: 500;
		padding: 7px 12px;
		border: 1px solid var(--color-border);
		border-radius: 8px;
		background: var(--color-white);
		color: var(--color-fg);
		cursor: pointer;
		white-space: nowrap;
	}
	.bk-btn:hover { border-color: var(--color-fg-light); }
	.bk-btn.on, .bk-btn.bk-primary { background: var(--color-fg); border-color: var(--color-fg); color: var(--color-white); }
	.bk-editbar {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 10px;
		flex-wrap: wrap;
		background: var(--color-gray-100);
		border-radius: 8px;
		padding: 10px 12px;
		margin: 0 0 10px;
	}
	.bk-editnote { margin: 0; font-size: var(--text-sm); color: var(--color-fg-light); }
	.bk-editactions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
	.bk-saved { font-size: var(--text-sm); color: #1f7a4d; }
	.bk-list { list-style: none; margin: 0; padding: 0; }
	.bk-row {
		display: grid;
		grid-template-columns: 22px minmax(0, 1fr) 96px 76px;
		gap: 12px;
		align-items: center;
		padding: 9px 8px;
		border-top: 1px solid var(--color-gray-100, #eee);
	}
	.bk-subj { grid-template-columns: 22px minmax(0, 1fr); padding-block: 8px 2px; }
	/* A subject tag that opens its genre's Most Borrowed list: looks like the
	   other tag links. */
	.subj-genre { padding: 0; border: 0; background: none; font: inherit; color: inherit; cursor: pointer; text-decoration: underline; text-decoration-color: var(--color-border); text-underline-offset: 3px; }
	.subj-genre:hover { color: var(--color-fg); text-decoration-color: currentColor; }
	.bk-subj-list { font-size: var(--text-sm); color: var(--color-fg-light); }
	.bk-subj-list a { color: inherit; text-decoration: underline; text-decoration-color: var(--color-border); text-underline-offset: 3px; }
	.bk-subj-list a:hover { color: var(--color-fg); text-decoration-color: currentColor; }
	/* Hover lights the row, to help trace a title across to its numbers. */
	.bk-book:hover { background: #f6f6f4; }
	.bk-colhead {
		padding: 0 0 6px;
		border-top: 0;
		border-bottom: 1px solid var(--color-border);
		font-size: 12px;
		color: var(--color-fg-light);
	}
	.bk-check { margin: 0; accent-color: var(--color-fg); }
	.bk-name-cell { min-width: 0; display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
	.bk-swatch { display: inline-block; width: 12px; height: 3px; border-radius: 2px; align-self: center; flex: none; }
	.bk-name { font-family: var(--font-serif); font-size: 1rem; color: var(--color-fg); }
	.bk-eds {
		font: inherit;
		font-size: 12px;
		color: var(--color-fg-light);
		background: none;
		border: 0;
		padding: 0;
		cursor: pointer;
		display: inline-flex;
		align-items: center;
		gap: 4px;
	}
	.bk-eds:hover { color: var(--color-fg); text-decoration: underline; text-underline-offset: 3px; }
	.bk-caret { width: 0; height: 0; border-left: 4px solid transparent; border-right: 4px solid transparent; border-top: 5px solid currentColor; }
	.bk-caret.up { border-top: 0; border-bottom: 5px solid currentColor; }
	.bk-fmt { font-size: 12px; color: var(--color-fg-light); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
	.bk-spark { display: block; }
	.bk-spark path { fill: none; stroke-width: 1.5; stroke-linejoin: round; }
	.bk-num { text-align: right; font-size: var(--text-sm); font-variant-numeric: tabular-nums; color: var(--color-fg); white-space: nowrap; }
	.bk-colhead .bk-num, .bk-colhead .bk-sp { color: var(--color-fg-light); }
	.bk-sort { display: inline-flex; align-items: center; gap: 3px; padding: 0; border: 0; background: none; font: inherit; color: inherit; cursor: pointer; }
	.bk-sort:hover, .bk-sort.on { color: var(--color-fg); }
	.bk-arrow { font-size: 11px; }
	/* editions under an open book */
	/* An open book's editions sit on a faint warm panel, so they read as
	   belonging to that book. */
	.bk-ed { grid-template-columns: 22px minmax(0, 1fr) 76px; padding: 5px 8px 5px 30px; border-top: 0; font-size: var(--text-sm); color: var(--color-fg-light); background: #f8f7f3; }
	.bk-ed:hover { background: #f0efea; }
	/* A just-moved edition flashes in its new place, then settles. */
	.bk-ed.just-moved { animation: moved-flash 1.8s ease-out; }
	@keyframes moved-flash {
		0%, 25% { background: #fde8a6; box-shadow: inset 3px 0 0 #e0a100; }
		100% { background: #f8f7f3; box-shadow: inset 3px 0 0 transparent; }
	}
	.move-note {
		position: fixed;
		left: 50%;
		bottom: 22px;
		transform: translateX(-50%);
		z-index: 70;
		display: flex;
		align-items: center;
		gap: 14px;
		max-width: calc(100vw - 32px);
		padding: 10px 14px 10px 16px;
		background: #1f1f1f;
		color: #fff;
		border-radius: 8px;
		box-shadow: 0 6px 20px rgba(0, 0, 0, 0.18);
		font-family: var(--font-sans);
		font-size: var(--text-sm);
		animation: note-in 0.18s ease-out;
	}
	@keyframes note-in { from { opacity: 0; transform: translate(-50%, 8px); } }
	.move-undo { background: none; border: 0; padding: 0; font: inherit; font-weight: 600; color: #9cc8f0; cursor: pointer; white-space: nowrap; }
	.move-undo:hover { text-decoration: underline; text-underline-offset: 3px; }
	@media (prefers-reduced-motion: reduce) { .bk-ed.just-moved, .move-note { animation: none; } .bk-ed.just-moved { background: #fde8a6; } }
	.bk-ed.editing { grid-template-columns: 22px minmax(0, 1fr) auto 76px; }
	.bk-ed .bk-num { color: var(--color-fg-light); }
	.bk-ed-title { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.bk-rename { font-family: var(--font-serif); font-size: 1rem; padding: 4px 8px; border: 1px solid var(--color-border); border-radius: 6px; background: var(--color-white); color: var(--color-fg); min-width: 0; width: 16em; max-width: 100%; }
	.bk-new { background: #fbfaf6; }
	.bk-new-note { font-size: 12px; color: var(--color-fg-light); }
	.bk-ed-swatch { display: inline-block; vertical-align: middle; margin-right: 8px; }
	.bk-ed-fmt { display: inline-block; min-width: 4.2em; margin-right: 8px; color: var(--color-fg); }
	.bk-ed-tools { display: flex; gap: 6px; align-items: center; }
	.bk-move { font: inherit; font-size: 12px; padding: 4px 6px; border: 1px solid var(--color-border); border-radius: 6px; background: var(--color-white); color: var(--color-fg); -webkit-appearance: menulist; appearance: auto; max-width: 190px; }
	.bk-x { font: inherit; font-size: 15px; line-height: 1; padding: 3px 8px; border: 1px solid var(--color-border); border-radius: 6px; background: var(--color-white); color: var(--color-fg-light); cursor: pointer; }
	.bk-x:hover { color: var(--color-fg); border-color: var(--color-fg-light); }
	@media (max-width: 640px) {
		.bk-row { grid-template-columns: 22px minmax(0, 1fr) 60px; }
		.bk-row .bk-fmt, .bk-row .bk-sp { display: none; }
		.bk-ed.editing { grid-template-columns: 22px minmax(0, 1fr) 60px; }
		.bk-ed.editing .bk-ed-tools { grid-column: 2 / -1; grid-row: 2; }
		.bk-filter { width: 140px; }
	}

	/* Edit groupings: a plain button beside the filter; filled while editing. */
	.edit-toggle {
		font-family: var(--font-sans);
		font-size: var(--text-sm);
		font-weight: 500;
		padding: 8px 13px;
		border: 1px solid var(--color-border);
		border-radius: 8px;
		background: var(--color-white);
		color: var(--color-fg);
		cursor: pointer;
		white-space: nowrap;
	}
	.edit-toggle:hover { border-color: var(--color-fg-light); }
	.edit-toggle.on { background: var(--color-fg); border-color: var(--color-fg); color: var(--color-white); }
	.books-more {
		display: block;
		margin: 12px 0 0;
		padding: 7px 12px;
		border: 1px solid var(--color-border);
		border-radius: 8px;
		background: var(--color-white);
		font-family: var(--font-sans);
		font-size: var(--text-sm);
		font-weight: 500;
		color: var(--color-fg);
		cursor: pointer;
	}
	.books-more:hover { border-color: var(--color-fg-light); }
	/* per-book trend line, inside the checkouts cell */
	.work-header .tt-count { display: inline-flex; align-items: center; justify-content: flex-end; gap: 10px; white-space: nowrap; }
	.work-header .tt-count .row-spark { flex: none; display: block; width: 78px; height: 18px; max-width: none; }
	/* view mode: the table is part of the page, not its own scroll box */
	.split-side .title-table.flow { max-height: none; overflow: visible; border: 0; border-top: 1px solid var(--color-border); border-radius: 0; }
	.row-spark path { fill: none; stroke-width: 1.5; stroke-linejoin: round; }
	@media (max-width: 860px) { .row-spark { display: none; } }
	.title-filter {
		flex: 1;
		min-width: 180px;
		padding: 9px 12px;
		font-family: var(--font-sans);
		font-size: var(--text-base);
		background: var(--color-input-bg);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
	}

	.sort-toggle {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		font-family: var(--font-sans);
		font-size: var(--text-sm);
	}

	.sort-label {
		color: var(--color-fg-light);
	}

	.sort-toggle button {
		padding: 5px 10px;
		font-size: var(--text-sm);
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
		/* Work is capped at a fixed max (not an fr) so it never balloons on wide
		   screens and shove the edition titles far to the right; Edition takes all
		   the slack, keeping edition titles anchored just left of center. */
		grid-template-columns: 26px minmax(110px, 300px) minmax(0, 1fr) auto 140px;
		gap: 9px;
		padding: 7px 9px;
		font-size: var(--text-sm);
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
	/* On narrow screens give the Work title the bulk of the width so titles wrap at
	   word boundaries instead of smushing ("read y to play outsi de"). Placed after
	   the base grid rule so it wins on equal specificity. */
	@media (max-width: 860px) {
		.split-side .tt-head,
		.split-side .tt-row,
		.split-side .work-header {
			/* Work title gets all the slack (minmax(0,1fr)); the Edition column here
			   holds only the small "N editions" pill (collapsed rows), so size it to its
			   content (auto) — a fixed fraction clipped the pill's trailing "s".
			   Expanded edition titles span both columns (.span-work), so they're
			   unaffected by this split. */
			grid-template-columns: 22px minmax(0, 1fr) auto minmax(42px, auto);
			gap: 8px;
			padding: 7px 8px;
		}
		/* Format badges are secondary; drop the column on mobile to give the Work
		   title room and keep the Edition column wide enough for its header.
		   Extra specificity so it beats the base `.work-header .tt-format` rule. */
		.split-side .tt-head .tt-format,
		.split-side .tt-row .tt-format,
		.split-side .work-header .tt-format {
			display: none;
		}
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
		font-size: var(--text-base);
		font-weight: 500;
		cursor: pointer;
		/* white rows on the gray panel; multi-edition ".cluster" rows tint over this */
		background: var(--color-white);
		border-top: 1px solid var(--color-gray-100);
	}
	.title-list > li:first-child.work-header {
		border-top: none;
	}
	.work-header:hover {
		background: var(--color-gray-100);
	}
	/* Works that don't match the active filter: kept in the DOM (so a drag can
	   reveal them without inserting nodes mid-drag) but hidden until then. */
	.work-header.filtered-hidden {
		display: none;
	}

	/* a real work cluster (2+ editions) -- highlight it with an accent bar + tint
	   so it stands apart from single-edition rows */
	/* Multi-edition works look like every other book row; the "N editions"
	   pill already says they're clusters. */
	.work-header.cluster:hover {
		background: var(--color-gray-100);
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
		font-size: var(--text-xs);
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
		font-size: var(--text-lg);
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
		font-size: var(--text-sm);
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
		font-size: var(--text-xs);
		padding: 1px 8px;
		border-radius: 999px;
	}
	.ed-single {
		color: var(--color-fg);
		font-size: var(--text-sm);
		font-style: italic;
	}
	/* format column can show several badges for a multi-format work -- stacked
	   vertically so the column stays narrow */
	/* formats read as one quiet line of small gray words, not colored pills */
	.work-header .tt-format .badge {
		background: none;
		border: 0;
		padding: 0;
		color: var(--color-fg-light);
		font-weight: 500;
		text-transform: lowercase;
		letter-spacing: 0;
	}
	.work-header .tt-format {
		display: flex;
		flex-direction: row;
		flex-wrap: nowrap;
		gap: 6px;
		align-items: center;
		justify-content: flex-end;
	}
	/* An expanded work's editions: the title cell spans the Work + Edition columns
	   (exclude button first, then the title) so the title sits far left instead of
	   stranded out past the wide Work column. A slight indent keeps the nesting
	   legible under the parent work. */
	.tt-edition.span-work {
		grid-column: 2 / 4;
		padding-left: 8px;
		gap: 10px;
	}

	.tt-head {
		position: sticky;
		top: 0;
		z-index: 1;
		font-family: var(--font-sans);
		font-size: var(--text-xs);
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
		font-size: var(--text-base);
		background: var(--color-white);
	}

	.tt-row:hover {
		background: var(--color-gray-100);
	}

	.tt-row.selected {
		/* white, not gray -- the colored left bar + bold text carry the selection */
		background: var(--color-white);
		font-weight: 600;
		box-shadow: inset 3px 0 0 0 var(--chip-color, var(--color-fg));
	}
	.tt-row.selected:hover {
		background: var(--color-gray-100);
	}
	/* A plotted work's header gets the same coloured left bar as a selected edition,
	   in its band's colour, so the table mirrors the chart. */
	.work-header.plotted {
		box-shadow: inset 3px 0 0 0 var(--chip-color, var(--color-fg));
	}

	/* Editions matching the table filter: the matching text is highlighted inline
	   (see <mark class="t-hit">), so the row itself stays un-tinted. */
	.t-hit {
		background: #ffec99;
		color: inherit;
		border-radius: 3px;
		padding: 0 1px;
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
		font-size: var(--text-sm);
		color: var(--color-fg-light);
		margin: 8px 2px 0;
	}

	.table-hint {
		font-family: var(--font-sans);
		font-size: var(--text-sm);
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
	/* Save / Reset / Make a custom work — the shared neutral control box. */
	.wa-btn {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		font-family: var(--font-sans);
		font-size: var(--text-sm);
		font-weight: 600;
		line-height: 1;
		padding: 6px 14px;
		border: 1.5px solid var(--color-border);
		border-radius: 999px;
		background: var(--color-white);
		color: var(--color-fg);
		cursor: pointer;
		transition: border-color 0.12s, background 0.12s;
	}
	.wa-btn:hover { border-color: var(--color-fg-light); background: #f7f7f7; }
	.wa-reset { color: var(--color-fg-light); }
	.wa-saved {
		font-family: var(--font-sans);
		font-size: var(--text-sm);
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
		font-size: var(--text-sm);
		line-height: 1.35;
		border-radius: 6px;
		box-shadow: 0 6px 18px rgba(0, 0, 0, 0.18);
		pointer-events: none;
		word-break: break-word;
	}

	.load-error {
		font-family: var(--font-sans);
		font-size: var(--text-base);
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
		font-size: var(--text-base);
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
			/* Give the panel room below the Download / Share row on phones. */
			margin-top: var(--space-5);
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
