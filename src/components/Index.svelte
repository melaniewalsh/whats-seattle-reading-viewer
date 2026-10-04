<script>
	import { getContext, onMount } from "svelte";
	import { base } from "$app/paths";
	import Viewer from "$components/StackedViewer.svelte";
	import GenreTrends from "$components/GenreTrends.svelte";
	import Compare from "$components/Compare.svelte";
	import TopAuthors from "$components/TopAuthors.svelte";
	import TopWorks from "$components/TopWorks.svelte";
	import NortonExplorer from "$components/NortonExplorer.svelte";
	import BacklistBoomerangs from "$components/BacklistBoomerangs.svelte";
	import TrendingUp from "@lucide/svelte/icons/trending-up";
	import LineChart from "$components/StackedAreaChart.svelte";
	import SiteSearch from "$components/SiteSearch.svelte";
	import { cleanTitleForDisplay } from "$utils/workTitle.js";
	import { displayName } from "$utils/displayName.js";
	import { MediaQuery } from "svelte/reactivity";
	import { getMonths, getAuthor, searchTitles, searchAll, densify, randomAuthor } from "$components/db.js";
	import { coverUrl } from "$utils/covers.js";
	import { lookupUrls } from "$utils/lookup.js";
	import { compactNumber } from "$utils/format.js";
	import { publications } from "$data/publications.js";
	import { EVENT_ANNOTATIONS } from "$data/eventAnnotations.js";

	const copy = getContext("copy");
	// Four top-level views. "search" and "rankings" carry a sub-kind toggle.
	let tab = $state("home"); // "home" (landing hub) | "overview" (all-checkouts plot) | "search" | "genres" | "rankings" | "about"
	let searchKind = $state("author"); // Search tab: "author" | "title"
	let rankKind = $state("works"); // Rankings tab: "authors" | "works"
	let menuOpen = $state(false); // the slide-out hamburger menu

	// "Featured trend of the month" on the home hub: this month, The Odyssey.
	// "Last updated" = the most recent month present in the data.
	let lastUpdated = $state("");
	onMount(async () => {
		try {
			const months = await getMonths();
			const last = months[months.length - 1];
			if (last) {
				const [y, mo] = last.split("-");
				const names = ["January", "February", "March", "April", "May", "June",
					"July", "August", "September", "October", "November", "December"];
				lastUpdated = `${names[Number(mo) - 1]} ${y}`;
			}
		} catch {}
	});

	let featured = $state(null);
	const MONTHS_FULL = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
	const fmtMonthYear = (m) => `${MONTHS_FULL[Number(m.slice(5, 7)) - 1]} ${m.slice(0, 4)}`;
	let featuredLoaded = false;
	$effect(() => {
		if (tab === "home" && !featuredLoaded) {
			featuredLoaded = true;
			loadFeatured();
		}
	});
	async function loadFeatured() {
		try {
			const [months, hits] = await Promise.all([getMonths(), searchTitles("The Odyssey", 30)]);
			const hit = hits.find((h) => /odyssey/i.test(h.title) && /homer/i.test(h.author)) || hits.find((h) => /odyssey/i.test(h.title));
			if (!hit) return;
			const author = await getAuthor(hit.slug);
			if (!author) return;
			const monthCount = months.length;
			const want = author.titles.filter((t) => /odyssey/i.test(t.title));
			const sum = new Array(monthCount).fill(0);
			for (const t of want) {
				const dense = densify(t.series, monthCount);
				for (let i = 0; i < monthCount; i++) sum[i] += dense[i] || 0;
			}
			// The all-time peak month, to annotate on the chart.
			let peakIdx = 0;
			for (let i = 1; i < monthCount; i++) if (sum[i] > sum[peakIdx]) peakIdx = i;
			featured = {
				months,
				series: [{ key: "featured", label: "The Odyssey", color: "#3f88cc", values: sum, isAggregate: true }],
				title: hit.title,
				authorSlug: hit.slug,
				checkouts: sum.reduce((s, v) => s + v, 0),
				peak: sum[peakIdx] > 0 ? { idx: peakIdx, value: sum[peakIdx], month: months[peakIdx] } : null,
				cover: null
			};
			// Fetch the book cover (Open Library, cached) and slot it in when ready.
			coverUrl(hit.title, hit.author).then((u) => {
				if (u && featured) featured = { ...featured, cover: u };
			});
		} catch {}
	}

	// Go to a tab and close the hamburger menu (used by the menu + pills).
	function go(t) {
		tab = t;
		compareMode = false;
		searchText = "";
		menuOpen = false;
		// Reset the URL to this tab so a stale ?title/?author from a previous
		// drilldown doesn't linger (and hijack the view on reload / Back).
		try {
			const url = new URL(window.location);
			["author", "title", "genre", "year", "kind", "c"].forEach((k) => url.searchParams.delete(k));
			leaveMethod(url);
			if (t === "home") url.searchParams.delete("tab");
			else url.searchParams.set("tab", t === "rankings" ? (rankKind === "authors" ? "top" : "works") : t);
			window.history.pushState({}, "", url);
		} catch {}
		// Heading to Search puts the cursor in the page's search field.
		// A new page starts at the top, not wherever the last one was scrolled.
		window.scrollTo({ top: 0 });
		if (t === "search") focusSearch();
	}

	// Publications, grouped by year for the Publications view.
	const pubGroups = (() => {
		const groups = [];
		let cur = null;
		for (const p of publications) {
			if (!cur || cur.year !== p.year) { cur = { year: p.year, items: [] }; groups.push(cur); }
			cur.items.push(p);
		}
		return groups;
	})();
	// Figures for the Top-500 case study are the static plots rendered on the
	// project's Quarto essay (hotlinked from GitHub Pages).
	const spl500Fig = "https://melaniewalsh.github.io/whats-seattle-reading/posts/spl-500-novels/index_files/figure-html/";
	let copiedBib = $state(null);
	function copyBib(p) {
		try {
			navigator.clipboard.writeText(p.bibtex);
			copiedBib = p.title;
			setTimeout(() => (copiedBib === p.title && (copiedBib = null)), 2000);
		} catch {}
	}

	// The Data & Methodology section is a collapsed <details>; deep links to its
	// subheadings (#method-…, from e.g. the works table) open it and scroll to them.
	let methodOpen = $state(false);
	// Moving to another page closes the section and drops its #anchor, so a
	// section left open doesn't pull every later page down to the footer.
	function leaveMethod(url) {
		methodOpen = false;
		if (url && /^#(data-methodology|method-)/.test(url.hash)) url.hash = "";
	}
	function scrollToMethod() {
		const h = (window.location.hash || "").slice(1);
		if (h === "data-methodology" || h.startsWith("method-")) {
			methodOpen = true;
			setTimeout(() => document.getElementById(h)?.scrollIntoView({ behavior: "smooth", block: "start" }), 60);
		}
	}

	// Derive the current view from the URL params. Used on first load AND on
	// browser Back/Forward (popstate) so history navigation restores the view.
	function applyUrlState() {
		try {
			const params = new URLSearchParams(window.location.search);
			// ?c=… (or ?tab=compare): the trends page's compare view.
			compareMode = params.getAll("c").length > 0 || params.get("tab") === "compare";
			if (compareMode) { tab = "search"; return; }
			const t = params.get("tab");
			const kind = params.get("kind");
			if (t === "genres") tab = "genres";
			else if (t === "rankings" || t === "top" || t === "works") {
				tab = "rankings";
				rankKind = t === "top" || kind === "authors" ? "authors" : "works";
			} else if (t === "search" || t === "authors" || t === "titles") {
				tab = "search";
				searchKind = t === "titles" || kind === "title" ? "title" : "author";
			} else if (params.get("title")) { tab = "search"; searchKind = "title"; }
			else if (params.get("author")) { tab = "search"; searchKind = "author"; }
			else if (t === "about") tab = "about";
			else if (t === "publications") tab = "publications";
			else if (t === "norton") tab = "norton";
			else if (t === "spl500") tab = "spl500";
			else if (t === "backlist" || t === "boomers" || t === "boomerangs") tab = "backlist";
			else if (t === "overview" || t === "all") tab = "overview";
			else tab = "home";
		} catch {}
	}

	// Back/Forward between two trend pages (a book, then its author) stays on the
	// search tab, so remount the viewer to load whatever the URL now names.
	function onPopState() {
		applyUrlState();
		if (tab === "search") searchNonce++;
	}

	// A shared ?tab= / ?author= makes each view linkable (old tab names still work).
	onMount(() => {
		applyUrlState();
		// A plain ?tab=search link (nothing picked yet) also gets the cursor.
		try {
			const sp = new URLSearchParams(window.location.search);
			if (tab === "search" && !sp.get("author") && !sp.get("title")) focusSearch();
		} catch {}
		scrollToMethod();
		window.addEventListener("hashchange", scrollToMethod);
		window.addEventListener("popstate", onPopState);
		return () => {
			window.removeEventListener("hashchange", scrollToMethod);
			window.removeEventListener("popstate", onPopState);
		};
	});

	// Clear any deep-link params so a freshly-mounted view isn't hijacked by a
	// stale ?author/?title/?genre.
	function clearParams() {
		try {
			const url = new URL(window.location);
			["author", "title", "genre", "year", "tab", "kind", "c"].forEach((k) => url.searchParams.delete(k));
			window.history.replaceState({}, "", url);
		} catch {}
	}
	// The logo goes to the landing hub.
	function goHome() {
		clearParams();
		tab = "home";
		menuOpen = false;
	}
	// The "Overview" card / menu item goes to the library-wide checkouts plot.
	function goOverview() {
		clearParams();
		tab = "overview";
		menuOpen = false;
	}

	// Switch the Search tab between author and title, clearing any loaded ?author/
	// ?title so the fresh search box isn't hijacked by a stale deep link.
	function setSearchKind(kind) {
		try {
			const url = new URL(window.location);
			["author", "title"].forEach((k) => url.searchParams.delete(k));
			window.history.replaceState({}, "", url);
		} catch {}
		searchKind = kind;
		tab = "search";
	}

	// Switch the Rankings tab between the Works and Authors lists (the "Show"
	// dropdown in the rankings control bar). Genre/year persist via the URL, which
	// the newly-mounted ranking component reads on mount.
	function setRankKind(kind) {
		rankKind = kind;
	}

	// Bumped on every openAuthor/openTitle so the search Viewer (keyed on it) remounts
	// and re-reads the URL — needed when you're ALREADY on the search view and pick a
	// new author/work (e.g. from the header search), since the Viewer only reads
	// ?author/?title on mount.
	let searchNonce = $state(0);

	// Clicking an author (from Rankings, or a card's "See checkout trend") opens the
	// Search view with that author loaded (Viewer reads ?author on mount).
	function openAuthor(slug) {
		try {
			const url = new URL(window.location);
			leaveMethod(url);
			window.scrollTo({ top: 0 });
			url.searchParams.set("author", slug);
			["tab", "kind", "genre", "year", "title", "c"].forEach((k) => url.searchParams.delete(k));
			window.history.pushState({}, "", url);
		} catch {}
		searchKind = "author";
		compareMode = false;
		searchNonce++;
		tab = "search";
	}

	// Clicking a work title opens the Search view for that title (reads ?title).
	// authorSlug (optional) pins the title to its author, so a work whose name is
	// shared with (or contained in) a more-borrowed book — Patchett's "Whistler"
	// vs Grisham's "The Whistler" — opens the right one.
	function openTitle(title, authorSlug = null) {
		try {
			const url = new URL(window.location);
			leaveMethod(url);
			window.scrollTo({ top: 0 });
			url.searchParams.set("title", title);
			["tab", "kind", "genre", "year", "author", "c"].forEach((k) => url.searchParams.delete(k));
			if (authorSlug) url.searchParams.set("author", authorSlug);
			window.history.pushState({}, "", url);
		} catch {}
		searchKind = "title";
		compareMode = false;
		searchNonce++;
		tab = "search";
	}

	// --- Search (the field on the Checkout Trends page) ------------------------
	let pageSearch = $state(null);
	const phone = new MediaQuery("max-width: 600px"); // shorter placeholder on phones
	let homeSearch = $state(null);
	// Starting points under the home page's search field.
	const HOME_TRY = [
		{ label: "Sally Rooney", slug: "sally-rooney" },
		{ label: "Wuthering Heights", slug: "emily-bronte-1818", title: "Wuthering Heights" },
		{ label: "Colleen Hoover", slug: "colleen-hoover" },
		{ label: "Becoming", slug: "michelle-obama-1964", title: "Becoming" },
	];
	// The home search box's starting comparison (Enter to run it), a nod to
	// the Ngram Viewer's default. A different pair on each visit.
	const HOME_PAIRS = [
		[["Ulysses", "w~james-joyce-1882~Ulysses"], ["Mrs. Dalloway", "w~virginia-woolf-1882~Mrs. Dalloway"]],
		[["Parable of the Sower", "w~octavia-e-butler~Parable of the Sower"], ["Neuromancer", "w~william-gibson-1948~Neuromancer"]],
		[["Wuthering Heights", "w~emily-bronte-1818~Wuthering Heights"], ["Pride and Prejudice", "w~jane-austen-1775~Pride and Prejudice"]],
		[["Sally Rooney", "a~sally-rooney"], ["Ben Lerner", "a~ben-lerner-1979"]],
		[["Beverly Cleary", "a~beverly-cleary"], ["Judy Blume", "a~judy-blume"]],
	];
	let HOME_COMPARE = $state(HOME_PAIRS[0].map(([label]) => label).join(", "));
	onMount(() => {
		const pair = HOME_PAIRS[Math.floor(Math.random() * HOME_PAIRS.length)];
		HOME_COMPARE = pair.map(([label]) => label).join(", ");
	});
	async function homeSurprise() {
		const a = await randomAuthor();
		if (a) openAuthor(a.slug);
	}
	let cmp = $state(null); // the compare view, when it's showing
	let compareMode = $state(false);

	// The Checkout Trends search field works like the Ngram Viewer: it shows
	// what's on the chart ("Sally Rooney"), and a comma-separated list
	// ("Sally Rooney, Colleen Hoover") puts them all on one chart.
	let searchText = $state("");
	const knownIds = new Map(); // lowercased name -> pick id ("a~slug" / "w~slug~title")
	const idOf = (res) => (res.kind === "work" ? `w~${res.slug}~${res.title}` : `a~${res.slug}`);
	function remember(label, id) {
		if (label && id) knownIds.set(label.trim().toLowerCase(), id);
	}
	// The home box's starter pairs resolve to these exact books.
	HOME_PAIRS.flat().forEach(([label, id]) => remember(label, id));
	const labelOfRes = (r) => (r.kind === "work" ? cleanTitleForDisplay(r.title) || r.title : displayName(r.name));
	// Split on commas, but not inside a name we already know has one.
	function splitNames(text) {
		let t = text;
		const kept = [];
		[...knownIds.keys()].filter((k) => k.includes(",")).sort((a, b) => b.length - a.length).forEach((k) => {
			const re = new RegExp(k.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi");
			t = t.replace(re, (m) => { kept.push(m); return `\u0000${kept.length - 1}\u0000`; });
		});
		return t.split(",").map((n) => n.replace(/\u0000(\d+)\u0000/g, (_, i) => kept[i]).trim()).filter(Boolean);
	}
	function openId(id) {
		const [k, slug, ...rest] = id.split("~");
		if (k === "w") openTitle(rest.join("~"), slug);
		else openAuthor(slug);
	}
	function pickSearch(res) {
		remember(labelOfRes(res), idOf(res));
		openId(idOf(res));
	}
	// Enter (or a suggestion) with the field's whole list: one name opens its
	// page; two or more put them side by side.
	async function submitSearch(text, last) {
		if (last) remember(labelOfRes(last), idOf(last));
		const ids = [];
		for (const name of splitNames(text)) {
			let id = knownIds.get(name.toLowerCase());
			if (!id) {
				const hit = (await searchAll(name, 1).catch(() => []))[0];
				if (hit) { id = idOf(hit); remember(name, id); }
			}
			if (id && !ids.includes(id)) ids.push(id);
		}
		if (ids.length === 1) return openId(ids[0]);
		if (ids.length > 1) showCompare(ids);
	}
	function showCompare(ids) {
		if (compareMode && cmp) return cmp.setPicksFromIds(ids);
		try {
			const url = new URL(window.location);
			["tab", "kind", "genre", "year", "author", "title", "c"].forEach((k) => url.searchParams.delete(k));
			ids.forEach((id) => url.searchParams.append("c", id));
			window.history.pushState({}, "", url);
		} catch {}
		compareMode = true;
		searchNonce++;
		tab = "search";
	}
	// What's on the chart, reported by the trends page / the compare view.
	function onLoaded({ id, label }) {
		remember(label, id);
		searchText = label;
	}
	function onPicks(list) {
		list.forEach((p) => remember(p.label, p.id));
		searchText = list.map((p) => p.label).join(", ");
	}
	// "+ Compare": a comma after the current name, cursor ready for the next.
	function startCompare() {
		window.scrollTo({ top: 0 });
		pageSearch?.focus(true, searchText ? `${searchText}, ` : "");
	}
	// The menu's "Compare": the compare view with a starter matchup.
	function openCompare() {
		menuOpen = false;
		try {
			const url = new URL(window.location);
			["kind", "genre", "year", "author", "title", "c"].forEach((k) => url.searchParams.delete(k));
			url.searchParams.set("tab", "compare");
			window.history.pushState({}, "", url);
		} catch {}
		compareMode = true;
		searchNonce++;
		tab = "search";
		window.scrollTo({ top: 0 });
	}
	// Heading to Search: put the cursor in the page's search field and briefly
	// ring it, so it's clear that's where to type.
	function focusSearch() {
		setTimeout(() => {
			window.scrollTo({ top: 0 });
			pageSearch?.focus(true);
		}, 60);
	}
	// The nav's magnifying glass: go to the search page, or if already there,
	// jump to its field.
	function navSearch() {
		menuOpen = false;
		if (tab === "home" && homeSearch) {
			window.scrollTo({ top: 0 });
			return homeSearch.focus(true);
		}
		if (tab === "search") focusSearch();
		else go("search");
	}


	// Open the Most Borrowed works ranking filtered to a genre, all-time (used by
	// the "#N in Genre" badges on a searched work).
	function openGenre(genre) {
		try {
			const url = new URL(window.location);
			url.searchParams.set("tab", "works");
			url.searchParams.set("genre", genre);
			url.searchParams.set("year", "all");
			["kind", "author", "title"].forEach((k) => url.searchParams.delete(k));
			window.history.pushState({}, "", url);
		} catch {}
		rankKind = "works";
		tab = "rankings";
		try { window.scrollTo({ top: 0 }); } catch {}
	}
</script>

<svelte:boundary onerror={(e) => console.error(e)}>
	<article>
		<div class="masthead">
			<div class="masthead-top">
				<button class="mast-home" class:here={tab === "home"} onclick={goHome} aria-label="{copy.title} — home">
					<img class="mast-logo" src="{base}/favicon.png" alt="" width="30" height="30" />
					<span class="mast-title">{copy.title}</span>
				</button>
				<!-- Search lives on the Checkout Trends page; this takes you there (or,
				     if you're already on it, puts the cursor in its search field). -->
				<button class="mast-search-btn" onclick={navSearch} aria-label="Search authors or books" title="Search authors or books">
					<svg viewBox="0 0 20 20" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
						<circle cx="9" cy="9" r="6" /><line x1="13.5" y1="13.5" x2="18" y2="18" />
					</svg>
				</button>
				<nav class="mast-meta" aria-label="Site">
					<button class="mast-metalink" class:active={tab === "about"} aria-current={tab === "about" ? "page" : undefined} onclick={() => go("about")}>About</button>
					<button class="mast-burger" aria-label="Open menu" aria-expanded={menuOpen} aria-controls="site-menu" onclick={() => (menuOpen = true)}>
						<span aria-hidden="true"></span><span aria-hidden="true"></span><span aria-hidden="true"></span>
					</button>
				</nav>
			</div>
		</div>

		<!-- Slide-out hamburger menu (Pudding-style): quick links to every section
		     plus the broader project's Publications / Data / feedback. -->
		{#if menuOpen}
			<button class="menu-backdrop" aria-label="Close menu" onclick={() => (menuOpen = false)}></button>
		{/if}
		<nav id="site-menu" class="site-menu" class:open={menuOpen} aria-label="Menu" aria-hidden={!menuOpen}>
			<button class="menu-close" aria-label="Close menu" onclick={() => (menuOpen = false)}>×</button>
			<div class="menu-group">
				<h3 class="menu-h">Explore</h3>
				<button class="menu-link" onclick={goHome}>Home</button>
				<button class="menu-link" onclick={goOverview}>Overview</button>
				<button class="menu-link" onclick={() => go("rankings")}>Most Borrowed</button>
				<button class="menu-link" onclick={() => go("backlist")}>Backlist Boomerangs</button>
				<button class="menu-link" onclick={() => go("search")}>Search</button>
				<button class="menu-link" onclick={() => go("genres")}>Genres</button>
				<button class="menu-link" onclick={openCompare}>Compare</button>
			</div>
			<div class="menu-group">
				<h3 class="menu-h">Case Studies</h3>
				<button class="menu-link" onclick={() => go("norton")}>Canonical American Authors</button>
				<button class="menu-link" onclick={() => go("spl500")}>Top 500 “Greatest” Novels</button>
			</div>
			<div class="menu-group">
				<h3 class="menu-h">The Project</h3>
				<button class="menu-link" onclick={() => go("about")}>About</button>
				<button class="menu-link" onclick={() => go("publications")}>Publications</button>
				<a class="menu-link" href="https://data.seattle.gov/Community-and-Culture/Checkouts-by-Title/tmmm-ytt6" target="_blank" rel="noopener noreferrer">Data ↗</a>
				<a class="menu-link" href="https://docs.google.com/forms/d/e/1FAIpQLSfHWbWEj1H4NltjSp3ixjelJKSu2VMQgEkTF3CpjWtWhwARfA/viewform?usp=dialog" target="_blank" rel="noopener noreferrer">Feedback ↗</a>
			</div>
		</nav>

		{#if tab === "search"}
			<!-- The rule under this masthead is drawn by the viewer, below its
			     "Not sure where to start?" line, which belongs with the intro. -->
			<header class="section-masthead no-rule">
				<h2 class="sec-title">Seattle's Checkout Trends</h2>
				<p class="sec-sub">Look up any author or title's borrowing trend at the Seattle Public Library.</p>
				<div class="page-search"><SiteSearch bind:this={pageSearch} multi value={searchText} onPick={pickSearch} onSubmit={submitSearch} placeholder={phone.current ? "Search authors or books" : "Search authors or books (use commas to compare)"} /></div>
			</header>
		{/if}


		{#if tab === "genres"}
			<GenreTrends />
		{:else if tab === "rankings"}
			{#if rankKind === "works"}
				<TopWorks {openAuthor} {openTitle} {rankKind} {setRankKind} />
			{:else}
				<TopAuthors {openAuthor} {rankKind} {setRankKind} />
			{/if}
		{:else if tab === "backlist"}
			<BacklistBoomerangs {openAuthor} {openTitle} />
		{:else if tab === "home"}
			<header class="hero">
				<div class="hero-title">
					<img class="hero-logo" src="{base}/favicon.png" alt="" width="56" height="56" />
					<h1>{copy.title}</h1>
				</div>
				<p class="dek">{copy.dek}</p>
				<p class="byline">By the <a href="https://melaniewalsh.github.io/whats-seattle-reading/" target="_blank" rel="noopener noreferrer">What's Seattle Reading?</a> project</p>
			</header>
			<!-- The most eye-catching thing up top: what Seattle borrowed most last
			     month, with a link into the full Most Borrowed view. -->
			<!-- Looking something up is what most people come to do, so the search
			     field leads the home page (the Explore cards follow). -->
			<div class="home-search">
				<!-- Starts with a comparison, a nod to the Google Books Ngram Viewer's
				     default: press Enter to see it, or type over it. -->
				<SiteSearch bind:this={homeSearch} multi value={HOME_COMPARE} selectOnFocus onPick={pickSearch} onSubmit={submitSearch} placeholder="Search any author or book (commas compare)" />
				<p class="home-try">
					<span class="ht-lead">Try</span>
					{#each HOME_TRY as t, k}{#if k}<span class="ht-sep ht-extra" aria-hidden="true">·</span>{/if}<button class="ht-link" class:ht-extra={k > 0} class:is-title={!!t.title} onclick={() => (t.title ? openTitle(t.title, t.slug) : openAuthor(t.slug))}>{t.label}</button>{/each}
					<span class="ht-sep" aria-hidden="true">·</span>
					<button class="ht-link ht-surprise" onclick={homeSurprise}>Surprise me</button>
				</p>
			</div>
			<section class="home-topworks" aria-label="Most borrowed last month">
				<TopWorks {openAuthor} {openTitle} embedded onSeeAll={() => go("rankings")} />
			</section>
			<nav class="hub" aria-label="Explore">
				<button class="hub-card" onclick={goOverview}>
					<img class="hub-emoji hub-img" src="{base}/hub-overview.png" alt="" width="34" height="34" />
					<span class="hub-h">Overview</span>
					<span class="hub-d">The big picture — total checkouts across the whole library, over time and by format.</span>
					<span class="hub-go">Explore →</span>
				</button>
				<button class="hub-card" onclick={() => go("rankings")}>
					<img class="hub-emoji hub-img" src="{base}/hub-borrowed.png" alt="" width="34" height="34" />
					<span class="hub-h">Most Borrowed</span>
					<span class="hub-d">The books and authors checked out most — all-time and year by year, by genre.</span>
					<span class="hub-go">Explore →</span>
				</button>
				<button class="hub-card" onclick={() => go("backlist")}>
					<span class="hub-emoji hub-lucide" aria-hidden="true"><TrendingUp size={32} strokeWidth={2.2} /></span>
					<span class="hub-h">Backlist Boomerangs</span>
					<span class="hub-d">Books that sat quietly for years, then suddenly took off — adaptations, BookTok, the news.</span>
					<span class="hub-go">Explore →</span>
				</button>
				<button class="hub-card" onclick={() => go("genres")}>
					<span class="hub-emoji hub-icons" aria-hidden="true">
						<img class="hub-img" src="{base}/hub-genres.png" alt="" width="34" height="34" />
						<img class="hub-img hub-img-sm" src="{base}/hub-heart.png" alt="" width="34" height="34" />
						<img class="hub-img hub-img-ghost" src="{base}/hub-ghost.png" alt="" width="34" height="34" />
					</span>
					<span class="hub-h">Genres</span>
					<span class="hub-d">How Seattle's taste in romance, mystery, fantasy and more has shifted over the years.</span>
					<span class="hub-go">Explore →</span>
				</button>
			</nav>

			{#if featured}
				<section class="featured" aria-label="Featured trend">
					<p class="featured-eyebrow">Featured trend of the month</p>
					<div class="featured-head">
						{#if featured.cover}
							<button class="featured-cover" onclick={() => openTitle(featured.title, featured.authorSlug)} title="See the full trend">
								<img src={featured.cover} alt="The Odyssey" loading="lazy" />
							</button>
						{/if}
						<div class="featured-headtext">
							<h2 class="featured-title">
								<button class="flink" onclick={() => openTitle(featured.title, featured.authorSlug)}>The Odyssey</button>
								<span class="featured-by">by <button class="flink" onclick={() => openAuthor(featured.authorSlug)}>Homer</button></span>
							</h2>
							<p class="featured-sub">{compactNumber(featured.checkouts)} checkouts at the Seattle Public Library, 2006–2026</p>
						</div>
					</div>
					<div class="featured-chart">
						<!-- Same style as the trend pages. -->
						<LineChart months={featured.months} series={featured.series} mode="line" smooth
							annotations={EVENT_ANNOTATIONS} />
					</div>
					<div class="featured-actions">
						<button class="featured-cta" onclick={() => openTitle(featured.title, featured.authorSlug)}>Explore the full trend →</button>
						<a class="featured-spl" href={lookupUrls("The Odyssey Homer").spl} target="_blank" rel="noopener noreferrer" title="Find The Odyssey in the Seattle Public Library catalog"><img src="{base}/spl-logo.png" alt="" width="18" height="18" /> Find at SPL</a>
					</div>
				</section>
			{/if}
		{:else if tab === "overview"}
			<Viewer searchMode="author" landing="overview" />
		{:else if tab === "about"}
			<section class="about-page">
				<h2 class="about-title">About</h2>
				<p>The <strong>What's Seattle Reading?</strong> project explores contemporary reading trends with unique open data provided by the Seattle Public Library.</p>
				<p>The project is directed by <a href="https://melaniewalsh.org/" target="_blank" rel="noopener noreferrer">Melanie Walsh</a>, Assistant Professor in the Information School and Adjunct Assistant Professor in the English Department at the University of Washington.</p>

				<h3 class="about-h">Team</h3>
				<ul class="about-list">
					<li><a href="https://melaniewalsh.org/" target="_blank" rel="noopener noreferrer">Melanie Walsh</a> — Assistant Professor, Information School, University of Washington</li>
					<li>Neel Gupta — PhD Student, Information School, University of Washington</li>
				</ul>

				<h3 class="about-h">Students</h3>
				<p>We've worked with several undergraduate students at the University of Washington, primarily through the <a href="https://humanitiesdatalab.ds.lib.uw.edu/hdssi/" target="_blank" rel="noopener noreferrer">Humanities Data Science Summer Institute</a>: Hongyuan (Tony) Dong, Em Backstrom, Karalee Harris, and Daniella Maor.</p>
				<p>This summer, we worked with Alexis Martin, Bob, Tiago Ramos, and Karalee Harris.</p>

				<h3 class="about-h">Acknowledgments</h3>
				<p>We are thankful to David Christensen, who spearheads the SPL's open data effort and has been a very helpful collaborator and guide.</p>

				<p class="about-more">This is a work-in-progress — we'd love your <a href="https://docs.google.com/forms/d/e/1FAIpQLSfHWbWEj1H4NltjSp3ixjelJKSu2VMQgEkTF3CpjWtWhwARfA/viewform?usp=dialog" target="_blank" rel="noopener noreferrer">feedback</a>. For how the data is sourced and how works are clustered, see <a href="#data-methodology" onclick={() => (methodOpen = true)}>Data &amp; Methodology</a> below.</p>
			</section>
		{:else if tab === "publications"}
			<section class="pubs-page">
				<h2 class="about-title">Publications</h2>
				<p class="pubs-intro">Check out our publications related to checkout data from the Seattle Public Library.</p>
				{#each pubGroups as g}
					<h3 class="pub-year">{g.year}</h3>
					{#each g.items as p}
						{#if p.month}<h4 class="pub-month">{p.month}</h4>{/if}
						<article class="pub">
							<a class="pub-title" href={p.url} target="_blank" rel="noopener noreferrer">{p.title}</a>
							<p class="pub-cite">{p.citation}{#if p.doi}&nbsp;<a href={p.doi} target="_blank" rel="noopener noreferrer">DOI</a>.{/if}</p>
							{#if p.links?.length}
								<p class="pub-links">{#each p.links as l, i}{#if i > 0}<span class="pub-sep"> · </span>{/if}<a href={l.url} target="_blank" rel="noopener noreferrer">{l.label}</a>{/each}</p>
							{/if}
							{#if p.bibtex}
								<details class="pub-bib">
									<summary>BibTeX</summary>
									<div class="pub-bib-body">
										<button class="pub-copy" onclick={() => copyBib(p)}>{copiedBib === p.title ? "Copied!" : "Copy"}</button>
										<pre>{p.bibtex}</pre>
									</div>
								</details>
							{/if}
						</article>
					{/each}
				{/each}
			</section>
		{:else if tab === "norton"}
			<article class="study">
				<p class="study-kicker">Case Study</p>
				<h2 class="study-title">Which Canonical American Authors Are People Reading?</h2>
				<p class="study-p">This interactive explorer invites you to dive into nearly two decades of Seattle Public Library checkout data for the 90+ authors included in Volume E of <a href="https://wwnorton.com/books/9780393884432" target="_blank" rel="noopener noreferrer"><em>The Norton Anthology of American Literature</em></a> (1945 to the Present). The data covers 2005–2025 and lets you see which authors and works have circulated most heavily in Seattle during this period.</p>
				<p class="study-p">You can trace spikes of attention after major life events, like an author's death, or explore how adaptations and cultural conversations bring older works back into circulation. You can also <a href="https://docs.google.com/spreadsheets/d/1a_ifxeHJ_5MlaBo-34sEWwqBMAqhZLLX47xaSDkpzc4/edit?usp=sharing" target="_blank" rel="noopener noreferrer">download and explore the data directly</a>.</p>
				<h3 class="study-h">Explore Trends</h3>
				<NortonExplorer />
			</article>
		{:else if tab === "spl500"}
			<article class="study">
				<p class="study-kicker">Case Study</p>
				<h2 class="study-title">Library Checkouts for the Top 500 “Greatest” Novels</h2>
				<p class="study-byline">Neel Gupta · February 2026</p>
				<div class="study-callout">Originally published as part of the <a href="https://www.responsible-datasets-in-context.com/posts/spl-500-novels/" target="_blank" rel="noopener noreferrer">Responsible Datasets in Context</a> project, which pairs datasets with critical essays for more ethical, humanistic data education.</div>
				<p class="study-p">This case study looks at Seattle Public Library circulation for the <a href="https://www.responsible-datasets-in-context.com/posts/top-500-novels/top-500-novels.html" target="_blank" rel="noopener noreferrer">Top 500 “Greatest” Novels</a> — the novels most widely held in libraries worldwide, according to the library consortium OCLC. The Seattle Public Library's <a href="https://data.seattle.gov/Community-and-Culture/Checkouts-by-Title/tmmm-ytt6/about_data" target="_blank" rel="noopener noreferrer">open checkout data</a> is one of the only publicly available sources of book-reception data in the country, recording checkouts from 2005 to 2025.</p>

				<h3 class="study-h">Authorial Death</h3>
				<p class="study-p">In <a href="https://doi.org/10.63744/P6qPH135jhY2" target="_blank" rel="noopener noreferrer">prior work</a>, we found that an author's death leads to a temporary boost in library checkouts — at least if they're famous. Plotting the checkout time series for authors who died in the last two decades bears this out.</p>
				<figure class="study-fig"><img src="{spl500Fig}cell-5-output-1.png" alt="Checkout time series for authors who died in the last 20 years, showing spikes around each author's death" loading="lazy" /></figure>

				<h3 class="study-h">Backlist Titles</h3>
				<p class="study-p">Do works by the same author rise and fall together? The Top 500 has 89 authors with multiple titles, so we tested whether their books get checked out at similar rates over time — the “backlist” effect, where attention to one book lifts interest in an author's earlier work. On average, books by the same author correlate at 0.42 — almost 3× higher than two random books in the dataset (0.16).</p>
				<figure class="study-fig"><img src="{spl500Fig}cell-8-output-1.png" alt="Correlation matrix of J.K. Rowling's Harry Potter books" loading="lazy" /><figcaption>The middle four <em>Harry Potter</em> books move almost in lockstep; the first book and the final two have their own dynamics.</figcaption></figure>
				<p class="study-p">The time-series plots show what's going on with those edge books:</p>
				<figure class="study-fig"><img src="{spl500Fig}cell-9-output-1.png" alt="Prisoner of Azkaban vs Chamber of Secrets checkouts over time" loading="lazy" /><figcaption><em>Prisoner of Azkaban</em> and <em>Chamber of Secrets</em> track almost perfectly — a correlation of 0.97.</figcaption></figure>
				<figure class="study-fig"><img src="{spl500Fig}cell-10-output-1.png" alt="Prisoner of Azkaban vs Sorcerer's Stone checkouts over time" loading="lazy" /><figcaption><em>Azkaban</em> and <em>Sorcerer's Stone</em> track well too — until a huge 2020 spike for <em>Sorcerer's Stone</em> throws off the correlation.</figcaption></figure>
				<figure class="study-fig"><img src="{spl500Fig}cell-11-output-1.png" alt="Deathly Hallows vs Half-Blood Prince checkouts over time" loading="lazy" /><figcaption>Apart from their release-date peaks, the final two books follow the same dynamics.</figcaption></figure>

				<h3 class="study-h">Genres</h3>
				<p class="study-p">The dataset's genre metadata lets us run the same correlation test across genres — seeing which genres are the most internally correlated in their patterns of reception over time.</p>

				<p class="study-more"><a href="https://melaniewalsh.github.io/whats-seattle-reading/posts/spl-500-novels/index.html" target="_blank" rel="noopener noreferrer">Read the full data essay →</a> with the interactive explorer, the complete dataset browser, and reproducible code.</p>
			</article>
		{:else}
			{#if compareMode}
				<!-- Two or more authors/books: one line each (the page's search adds more). -->
				{#key searchNonce}
					<Compare bind:this={cmp} {openAuthor} {openTitle} {onPicks} onSingle={(p) => (p.kind === "work" ? openTitle(p.title, p.slug) : openAuthor(p.slug))} onEmpty={() => go("search")} />
				{/key}
			{:else}
				{#key `${searchKind}-${searchNonce}`}
					<Viewer searchMode={searchKind} landing="search" {setSearchKind} {openGenre} {openAuthor} {openTitle} onCompare={startCompare} {onLoaded} onCompareIds={showCompare} />
				{/key}
			{/if}
		{/if}

		<footer class="chart-footer">
		<details class="about" id="data-methodology" bind:open={methodOpen}>
			<summary>Data &amp; Methodology</summary>
			<div class="about-body">
				<h3 id="method-checkouts">What counts as a checkout</h3>
				<p>
					This tool charts <strong>checkouts</strong> logged by the Seattle Public Library —
					physical books, ebooks, and audiobooks. Each point is how many times an author's or
					work's titles were borrowed in that month. It counts checkouts, not unique readers or
					holds, so a single popular book can be borrowed thousands of times.
				</p>

				<h3 id="method-clustering">Why is clustering by work so hard?</h3>
				<p>
					A single <em>work</em> — say, one novel — appears in the catalog as many separate
					records: print, ebook, and audiobook editions; reprints and reissues; large-print and
					translated editions; and re-cataloged copies with slightly different title strings.
					There's no shared identifier tying them together — the library only began recording
					ISBNs consistently around 2021, and even those differ per edition — so we cluster by
					<strong>normalizing and matching the title text</strong>, which is inherently fuzzy.
					Punctuation, subtitles, series names, and inconsistent cataloging all trip it up, and
					two genuinely different books can share a title. So clustering is automatic and
					<strong>approximate</strong>: in the works table you can drag editions between works,
					split one off, or merge two, and save your grouping.
				</p>

				<h3 id="method-caveats">Caveats</h3>
				<p>
					Author and title names come straight from library catalog records, which are
					inconsistently formatted and occasionally merged or misspelled, so an author's
					per-title breakdown includes long-tail variants of the same work. Genres are inferred
					from catalog subject headings, which are themselves imperfect. Read the trends as
					indicative, not exact.
				</p>

				<h3 id="method-ack">Acknowledgements</h3>
				<p>
					Thanks to <strong>David Christensen</strong>, the <strong>Seattle Public Library</strong>,
					and the <strong>HDSSI</strong> for making this project possible.
				</p>
			</div>
		</details>

			<!-- Pages with a chart already credit (and link) the data under it. -->
			{#if !["search", "overview", "genres"].includes(tab)}
			<p class="cf-source">
				Data source:
				<a
					href="https://data.seattle.gov/Community-and-Culture/Checkouts-by-Title/tmmm-ytt6"
					target="_blank"
					rel="noopener"
				>Seattle Public Library — Checkouts by Title</a>
				(2006–2026)
			</p>
			{/if}
			<p class="cf-attr">
				What’s Seattle Reading?
				<span class="cf-sep">·</span>
				<a href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noopener license">CC BY 4.0</a>
				{#if lastUpdated}<span class="cf-sep">·</span> Last updated: {lastUpdated}{/if}
			</p>
		</footer>
	</article>
</svelte:boundary>

<style>
	/* One shared content width for every tab, so Search / Genres / Most Borrowed
	   all line up at the same width and left edge. */
	article {
		max-width: 1008px;
		margin: 0 auto;
		padding: 0 24px 80px;
	}
	/* Home search: centered under the title, the page's first thing to do. */
	.home-search { max-width: 600px; margin: 22px auto 34px; }
	.home-search :global(.ss) { max-width: none; height: 52px; }
	.home-try { display: flex; flex-wrap: wrap; justify-content: center; align-items: baseline; gap: 4px 7px; margin: 12px 0 0; font-family: var(--font-sans); font-size: 14.5px; color: var(--color-fg-light); }
	.ht-lead::after { content: ":"; }
	.ht-sep { color: var(--color-gray-300, #c8c8c8); }
	.ht-link { padding: 0; border: 0; background: none; font: inherit; color: var(--color-fg); cursor: pointer; text-decoration: underline; text-decoration-color: var(--color-border); text-underline-offset: 3px; }
	.ht-link:hover { text-decoration-color: currentColor; }
	.ht-link.is-title { font-style: italic; }
	.ht-link.ht-surprise { color: var(--color-fg-light); }
	/* Phones: one suggestion and "Surprise me". */
	@media (max-width: 600px) { .ht-extra { display: none; } }
	/* Landing hub — title / subtitle / byline, then a grid of section cards. */
	.hero {
		max-width: 720px;
		margin: 46px auto 10px;
		text-align: center;
	}
	.hero-title {
		display: flex;
		align-items: center;
		justify-content: center;
		flex-wrap: wrap;
		gap: 16px;
		margin: 0 0 var(--space-4);
	}
	.hero-logo {
		flex: none;
		width: clamp(60px, 12vw, 92px);
		height: auto;
	}
	.hero h1 {
		font-family: var(--font-display, var(--font-serif));
		font-weight: 700;
		font-size: clamp(2.3rem, 6vw, 3.6rem);
		line-height: 1.08;
		letter-spacing: -0.005em;
		margin: 0;
		color: var(--color-fg);
	}
	.dek {
		font-family: var(--font-sans);
		font-size: clamp(1.05rem, 2.2vw, 1.25rem);
		line-height: 1.4;
		color: var(--color-fg-light);
		margin: 0;
	}
	.byline {
		font-family: var(--font-sans);
		font-size: var(--text-base);
		color: var(--color-fg-light);
		margin: 12px 0 0;
	}
	.byline a { color: #3f88cc; font-weight: 600; text-decoration: underline; }
	.featured {
		max-width: 880px;
		margin: 40px auto 10px;
		padding: 22px 24px 24px;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md, 12px);
		background: var(--color-white);
	}
	.featured-eyebrow {
		font-family: var(--font-sans);
		font-size: var(--text-xs);
		font-weight: 700;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: #3f88cc;
		margin: 0 0 4px;
	}
	.featured-head {
		display: flex;
		align-items: center;
		gap: 16px;
	}
	.featured-cover {
		flex: none;
		padding: 0;
		border: none;
		background: none;
		cursor: pointer;
		line-height: 0;
	}
	.featured-cover img {
		width: 64px;
		height: auto;
		border-radius: 4px;
		box-shadow: 0 2px 8px rgba(0, 0, 0, 0.18);
	}
	.featured-headtext {
		min-width: 0;
	}
	.featured-title {
		font-family: var(--font-display, var(--font-serif));
		font-size: clamp(1.6rem, 4vw, 2.2rem);
		font-weight: 700;
		line-height: 1.1;
		margin: 0 0 4px;
		color: var(--color-fg);
	}
	.featured-by {
		font-family: var(--font-sans);
		font-size: var(--text-base);
		font-weight: 500;
		color: var(--color-fg-light);
	}
	.flink {
		font: inherit;
		color: inherit;
		background: none;
		border: none;
		padding: 0;
		cursor: pointer;
		text-decoration: underline;
		text-decoration-color: var(--color-border);
		text-underline-offset: 3px;
	}
	.flink:hover {
		color: #3f88cc;
		text-decoration-color: #3f88cc;
	}
	.featured-sub {
		font-family: var(--font-sans);
		font-size: var(--text-base);
		color: var(--color-fg-light);
		margin: 0 0 var(--space-4);
	}
	.featured-chart {
		margin: 0 0 var(--space-2);
	}
	.featured-cta {
		font-family: var(--font-sans);
		font-size: var(--text-base);
		font-weight: 600;
		color: #3f88cc;
		background: none;
		border: none;
		padding: 4px 0 0;
		cursor: pointer;
	}
	.featured-cta:hover {
		text-decoration: underline;
	}
	.featured-actions {
		display: flex;
		align-items: center;
		gap: 18px;
		flex-wrap: wrap;
		margin-top: 6px;
	}
	.featured-spl {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		font-family: var(--font-sans);
		font-size: var(--text-base);
		font-weight: 600;
		color: var(--color-fg-light);
		text-decoration: none;
	}
	.featured-spl img {
		display: block;
		object-fit: contain;
	}
	.featured-spl:hover {
		color: #3f88cc;
		text-decoration: underline;
	}
	/* Home "most borrowed last month" strip, above the hub cards — boxed like the
	   featured-trend card. */
	.home-topworks {
		max-width: 880px;
		margin: 40px auto 10px;
		padding: 22px 24px 24px;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md, 12px);
		background: var(--color-white);
	}
	.hub {
		max-width: 880px;
		margin: 28px auto 10px;
		display: grid;
		grid-template-columns: repeat(2, 1fr);
		gap: 16px;
	}
	/* With an odd number of cards, let the last one span the row. */
	.hub-card:last-child:nth-child(odd) { grid-column: 1 / -1; }
	@media (max-width: 620px) {
		.hub { grid-template-columns: 1fr; }
	}
	.hub-card {
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		gap: 6px;
		text-align: left;
		padding: 22px;
		border: 1px solid var(--color-border);
		border-radius: 14px;
		background: var(--color-white);
		cursor: pointer;
		font-family: var(--font-sans);
		transition: border-color 0.12s, box-shadow 0.12s, transform 0.12s;
	}
	.hub-card:hover {
		border-color: var(--color-fg-light);
		box-shadow: 0 8px 22px rgba(0, 0, 0, 0.08);
		transform: translateY(-2px);
	}
	.hub-emoji { font-size: 1.7rem; line-height: 1; }
	.hub-lucide { display: inline-flex; color: #e3120b; }
	.hub-img { width: 2rem; height: 2rem; object-fit: contain; }
	.hub-icons { display: inline-flex; align-items: center; gap: 0.35rem; }
	.hub-img-sm { width: 1.4rem; height: 1.4rem; }
	.hub-img-ghost { width: 1.7rem; height: 1.7rem; }
	.hub-h {
		font-family: var(--font-display, var(--font-serif));
		font-size: 1.4rem;
		font-weight: 700;
		color: var(--color-fg);
	}
	.hub-d { font-size: var(--text-base); line-height: 1.45; color: var(--color-fg-light); }
	.hub-go { margin-top: 4px; font-size: var(--text-sm); font-weight: 700; color: #3f88cc; }
	/* About page — project details, moved off the landing. */
	.about-page {
		max-width: 680px;
		margin: 34px auto 12px;
		font-family: var(--font-sans);
	}
	.about-title {
		font-family: var(--font-display, var(--font-serif));
		font-weight: 700;
		font-size: clamp(1.7rem, 3.4vw, 2.5rem);
		color: var(--color-fg);
		margin: 0 0 var(--space-5);
	}
	.about-page p {
		font-size: var(--text-lg);
		line-height: 1.6;
		color: var(--color-fg);
		margin: 0 0 var(--space-4);
	}
	.about-page a {
		color: #3f88cc;
		font-weight: 600;
		text-decoration: underline;
	}
	.about-page .about-h {
		font-family: var(--font-display, var(--font-serif));
		font-size: 1.35rem;
		font-weight: 700;
		color: var(--color-fg);
		margin: 26px 0 8px;
	}
	.about-list {
		margin: 0 0 var(--space-4);
		padding-left: 20px;
	}
	.about-list li {
		font-size: 1.02rem;
		line-height: 1.55;
		margin: 0 0 5px;
		color: var(--color-fg);
	}
	.about-list a { color: #3f88cc; font-weight: 600; text-decoration: underline; }
	.about-page .about-more {
		font-size: var(--text-base);
		color: var(--color-fg-light);
		margin-top: 22px;
	}
	/* Publications list */
	.pubs-page {
		max-width: 720px;
		margin: 34px auto 12px;
		font-family: var(--font-sans);
	}
	.pubs-intro {
		font-size: var(--text-lg);
		line-height: 1.5;
		color: var(--color-fg-light);
		margin: 0 0 var(--space-2);
	}
	.pub-year {
		font-family: var(--font-display, var(--font-serif));
		font-size: var(--text-2xl);
		font-weight: 700;
		color: var(--color-fg);
		margin: 30px 0 4px;
		padding-bottom: 6px;
		border-bottom: 2px solid var(--color-fg);
	}
	.pub-month {
		font-family: var(--font-sans);
		font-size: var(--text-xs);
		font-weight: 800;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--color-fg-light);
		margin: 20px 0 6px;
	}
	.pub {
		margin: 0 0 22px;
	}
	.pub-title {
		display: inline-block;
		font-family: var(--font-display, var(--font-serif));
		font-size: 1.2rem;
		font-weight: 700;
		line-height: 1.25;
		color: var(--color-fg);
		text-decoration: none;
		margin-bottom: 5px;
	}
	.pub-title:hover { color: #3f88cc; text-decoration: underline; }
	.pub-cite {
		font-size: 0.98rem;
		line-height: 1.5;
		color: var(--color-fg);
		margin: 0 0 5px;
	}
	.pub-cite a, .pub-links a { color: #3f88cc; font-weight: 600; text-decoration: underline; }
	.pub-links {
		font-size: var(--text-base);
		margin: 0;
	}
	.pub-sep { color: var(--color-fg-light); }
	.pub-bib {
		margin-top: 8px;
		font-size: var(--text-base);
	}
	.pub-bib summary {
		cursor: pointer;
		width: fit-content;
		font-weight: 600;
		color: var(--color-fg-light);
	}
	.pub-bib summary:hover { color: var(--color-fg); }
	.pub-bib-body { position: relative; margin-top: 8px; }
	.pub-copy {
		position: absolute;
		top: 8px;
		right: 8px;
		font-family: var(--font-sans);
		font-size: var(--text-xs);
		font-weight: 600;
		color: var(--color-fg);
		background: var(--color-white);
		border: 1px solid var(--color-border);
		border-radius: 6px;
		padding: 3px 10px;
		cursor: pointer;
	}
	.pub-copy:hover { border-color: var(--color-fg-light); }
	.pub-bib pre {
		margin: 0;
		padding: 12px 14px;
		background: var(--color-gray-100);
		border: 1px solid var(--color-border);
		border-radius: 8px;
		overflow-x: auto;
		font-family: var(--font-mono, monospace);
		font-size: var(--text-sm);
		line-height: 1.5;
		color: var(--color-fg);
		white-space: pre;
	}
	/* Case-study article layout */
	.study {
		max-width: 760px;
		margin: 30px auto 0;
		font-family: var(--font-sans);
	}
	.study-kicker {
		font-family: var(--font-sans);
		font-size: var(--text-xs);
		font-weight: 800;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: #3f88cc;
		margin: 0 0 var(--space-2);
	}
	.study-title {
		font-family: var(--font-display, var(--font-serif));
		font-size: clamp(1.7rem, 3.4vw, 2.5rem); /* = the site's standard page/section title */
		font-weight: 700;
		line-height: 1.1;
		color: var(--color-fg);
		margin: 0 0 12px;
	}
	.study-h {
		font-family: var(--font-display, var(--font-serif));
		font-size: var(--text-2xl);
		font-weight: 700;
		color: var(--color-fg);
		margin: 32px 0 4px;
		padding-bottom: 8px;
		border-bottom: 2px solid var(--color-fg);
	}
	.study-p {
		font-family: var(--font-sans);
		font-size: var(--text-lg);
		line-height: 1.65;
		color: var(--color-fg);
		margin: 0 0 16px;
	}
	.study a { color: #3f88cc; font-weight: 600; text-decoration: underline; }
	.study-byline {
		font-family: var(--font-sans);
		font-size: var(--text-base);
		color: var(--color-fg-light);
		margin: 0 0 16px;
	}
	.study-callout {
		font-family: var(--font-sans);
		font-size: var(--text-base);
		line-height: 1.5;
		color: var(--color-fg-light);
		background: var(--color-gray-100);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		padding: 12px 16px;
		margin: 0 0 20px;
	}
	.study-fig {
		margin: 4px 0 22px;
	}
	.study-fig img {
		display: block;
		width: 100%;
		height: auto;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-white);
	}
	.study-fig figcaption {
		font-family: var(--font-sans);
		font-size: var(--text-base);
		line-height: 1.5;
		color: var(--color-fg-light);
		margin: 8px 2px 0;
	}
	.study-more {
		font-family: var(--font-sans);
		font-size: 1rem;
		line-height: 1.6;
		color: var(--color-fg-light);
		margin: 30px 0 0;
		padding-top: 20px;
		border-top: 1px solid var(--color-border);
	}
	/* Pudding-style sticky masthead: a slim top strip (wordmark + About) over a
	   centered row of little section pills. Breaks out to the full viewport width
	   so it reads as a real site header. */
	.masthead {
		position: sticky;
		top: 0;
		z-index: 50;
		width: 100vw;
		margin-left: calc(50% - 50vw);
		background: #fff;
		border-bottom: 1px solid var(--color-border);
	}
	.masthead-top {
		max-width: 1008px;
		margin: 0 auto;
		/* A little more height, centered, with the search icon, About and the
		   menu evenly spaced at the right. */
		min-height: 58px;
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 22px;
		padding: 0 24px;
	}
	.mast-home {
		display: inline-flex;
		align-items: center;
		gap: 9px;
		background: none;
		border: none;
		padding: 0;
		cursor: pointer;
	}
	.mast-logo {
		display: block;
		width: 30px;
		height: 30px;
	}
	.mast-title {
		font-family: var(--font-sans);
		font-weight: 800;
		font-size: var(--text-base);
		line-height: 1;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: #3f88cc;
		white-space: nowrap;
	}
	/* Nav search: just a magnifying glass. It takes you to a search field (the
	   home page's, or the Checkout Trends page's). */
	.mast-search-btn {
		margin-left: auto;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 36px;
		height: 36px;
		padding: 0;
		background: none;
		border: 0;
		border-radius: 8px;
		font-family: var(--font-sans);
		font-size: 14px;
		font-weight: 500;
		color: var(--color-fg);
		cursor: pointer;
		transition: border-color 0.12s, color 0.12s;
	}
	.mast-search-btn:hover { color: #3f88cc; }
	.mast-search-btn svg { width: 20px; height: 20px; flex: none; }
	.page-search { margin: 18px 0 0; }
	/* Top-right meta links (About, …) — small and understated. */
	.mast-meta {
		display: flex;
		align-items: center;
		gap: 22px;
	}
	.mast-metalink {
		font-family: var(--font-sans);
		font-size: var(--text-xs);
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--color-fg);
		background: none;
		border: none;
		padding: 4px 2px;
		cursor: pointer;
		transition: color 0.12s;
		outline: none;
	}
	.mast-metalink:hover { color: var(--color-fg); }
	.mast-metalink.active { color: #3f88cc; }
	.mast-metalink:focus-visible {
		outline: 2px solid rgba(63, 136, 204, 0.5);
		outline-offset: 2px;
		border-radius: 4px;
	}
	/* Hamburger button */
	.mast-burger {
		display: inline-flex;
		flex-direction: column;
		justify-content: center;
		gap: 4px;
		width: 30px;
		height: 30px;
		padding: 6px 4px;
		background: none;
		border: none;
		cursor: pointer;
		outline: none;
	}
	.mast-burger span {
		display: block;
		height: 2px;
		width: 100%;
		background: var(--color-fg);
		border-radius: 2px;
	}
	.mast-burger:hover span { background: #3f88cc; }
	.mast-burger:focus-visible { outline: 2px solid rgba(63, 136, 204, 0.5); outline-offset: 2px; border-radius: 4px; }

	/* Slide-out menu + backdrop */
	.menu-backdrop {
		position: fixed;
		inset: 0;
		z-index: 90;
		background: rgba(20, 28, 38, 0.32);
		border: none;
		cursor: pointer;
		animation: menu-fade 0.15s ease;
	}
	@keyframes menu-fade { from { opacity: 0; } to { opacity: 1; } }
	.site-menu {
		position: fixed;
		top: 0;
		right: 0;
		z-index: 100;
		height: 100dvh;
		width: min(320px, 82vw);
		box-sizing: border-box;
		background: #fff;
		border-left: 1px solid var(--color-border);
		box-shadow: -12px 0 40px rgba(0, 0, 0, 0.14);
		padding: 58px 26px 28px;
		transform: translateX(100%);
		transition: transform 0.22s cubic-bezier(0.22, 1, 0.36, 1);
		overflow-y: auto;
	}
	.site-menu.open { transform: translateX(0); }
	.menu-close {
		position: absolute;
		top: 14px;
		right: 16px;
		width: 34px;
		height: 34px;
		font-size: var(--text-2xl);
		line-height: 1;
		color: var(--color-fg-light);
		background: none;
		border: none;
		border-radius: 999px;
		cursor: pointer;
	}
	.menu-close:hover { background: var(--color-gray-100); color: var(--color-fg); }
	.menu-group { margin-bottom: 22px; }
	.menu-h {
		font-family: var(--font-sans);
		font-size: var(--text-xs);
		font-weight: 800;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--color-fg);
		margin: 0 0 var(--space-2);
	}
	.menu-link {
		display: block;
		width: 100%;
		text-align: left;
		font-family: var(--font-display, var(--font-serif));
		font-size: var(--text-xl);
		font-weight: 600;
		color: var(--color-fg);
		background: none;
		border: none;
		padding: 5px 0;
		cursor: pointer;
		text-decoration: none;
	}
	.menu-link:hover { color: #3f88cc; }
	@media (max-width: 600px) {
		/* One row on phones: wordmark, the search icon and the menu button. */
		.masthead-top { flex-wrap: nowrap; gap: 4px; padding: 6px 10px 6px 14px; }
		.mast-title { font-size: var(--text-sm); }
		/* About is in the hamburger menu on phones — drop the standalone link so the
		   wordmark has room. */
		.mast-metalink { display: none; }
	}

	/* segmented sub-toggle (Author/Title, Authors/Works) beneath the main tabs */
	/* Section masthead — identical to the Most Borrowed / Genres tabs. */
	.section-masthead {
		border-bottom: 3px solid var(--color-fg);
		padding-bottom: 12px;
		margin: 34px 0 16px;
	}
	.sec-title {
		font-family: var(--font-display, var(--font-serif));
		font-weight: 700;
		font-size: clamp(1.7rem, 3.4vw, 2.5rem);
		line-height: 1.05;
		color: var(--color-fg);
		margin: 0;
	}
	.section-masthead.no-rule { border-bottom: 0; padding-bottom: 0; margin-bottom: 0; }
	.sec-sub {
		font-family: var(--font-sans);
		font-size: var(--text-base);
		line-height: 1.4;
		color: var(--color-fg-light);
		margin: 6px 0 0;
	}
	/* "Search by" field — mirrors the Most Borrowed tab's Show/Genre/Year dropdowns. */
	.search-controls {
		margin-top: 2px;
	}
	.filter-field {
		display: inline-flex;
		flex-direction: column;
		gap: 4px;
		font-size: var(--text-sm);
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--color-fg-light);
	}
	.filter-field select {
		font-family: var(--font-sans);
		font-size: var(--text-base);
		font-weight: 500;
		text-transform: none;
		letter-spacing: 0;
		color: var(--color-fg);
		padding: 8px 12px;
		border: 1px solid var(--color-border);
		border-radius: 8px;
		background: var(--color-white);
		cursor: pointer;
		min-width: 180px;
	}
	.subtabs {
		display: inline-flex;
		gap: 2px;
		margin-top: 2px;
		padding: 3px;
		border-radius: 999px;
		background: var(--color-gray-100, #f0f0f0);
	}
	.subtab {
		font-family: var(--font-sans);
		font-size: var(--text-sm);
		font-weight: 600;
		padding: 5px 18px;
		border: none;
		border-radius: 999px;
		background: none;
		color: var(--color-fg-light);
		cursor: pointer;
	}
	.subtab.active {
		background: var(--color-white);
		color: var(--color-fg);
		box-shadow: 0 1px 3px rgba(0, 0, 0, 0.14);
	}
	/* OurWorldinData-style source + attribution footer */
	.chart-footer {
		margin: 40px 0 0;
		font-family: var(--font-sans);
		font-size: var(--text-sm);
		line-height: 1.5;
		color: var(--color-fg-light);
	}
	.chart-footer p {
		margin: 0;
	}
	.cf-attr {
		margin-top: 2px;
	}
	.cf-sep {
		margin: 0 4px;
	}
	.chart-footer a {
		color: #3f88cc;
		text-decoration: underline;
	}
	.chart-footer a:hover {
		color: #26597f;
	}

	.about {
		max-width: none;
		margin: 0 0 10px;
		padding: 0 0 10px;
		border: none;
		border-bottom: 1px solid var(--color-border);
		background: none;
		font-family: var(--font-sans);
	}
	.about summary {
		cursor: pointer;
		padding: 8px 0;
		font-weight: 600;
		font-size: var(--text-base);
		color: var(--color-fg-light);
		list-style-position: inside;
	}
	.about summary:hover {
		color: var(--color-fg);
	}
	.about summary:focus-visible {
		outline: 2px solid var(--color-focus);
		outline-offset: 2px;
	}
	.about-body {
		padding: 0 0 16px;
	}
	.about-body p {
		font-size: var(--text-base);
		line-height: 1.55;
		color: var(--color-fg);
		margin: 0 0 12px;
	}
	.about-body p:last-child {
		margin-bottom: 0;
	}
	.about-body h3 {
		font-family: var(--font-sans);
		font-size: var(--text-base);
		font-weight: 700;
		color: var(--color-fg);
		margin: 18px 0 6px;
		scroll-margin-top: 12px;
	}
	.about-body h3:first-child {
		margin-top: 4px;
	}
	/* brief highlight when a deep link jumps to a subheading */
	.about-body h3:target {
		background: #fff3bf;
		box-shadow: 0 0 0 4px #fff3bf;
		border-radius: 2px;
	}
</style>
