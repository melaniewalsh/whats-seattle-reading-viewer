<script>
	import { getContext, onMount } from "svelte";
	import { base } from "$app/paths";
	import Viewer from "$components/StackedViewer.svelte";
	import GenreTrends from "$components/GenreTrends.svelte";
	import TopAuthors from "$components/TopAuthors.svelte";
	import TopWorks from "$components/TopWorks.svelte";

	const copy = getContext("copy");
	// Four top-level views. "search" and "rankings" carry a sub-kind toggle.
	let tab = $state("overview"); // "overview" | "search" | "genres" | "rankings"
	let searchKind = $state("author"); // Search tab: "author" | "title"
	let rankKind = $state("works"); // Rankings tab: "authors" | "works"

	// The Data & Methodology section is a collapsed <details>; deep links to its
	// subheadings (#method-…, from e.g. the works table) open it and scroll to them.
	let methodOpen = $state(false);
	function scrollToMethod() {
		const h = (window.location.hash || "").slice(1);
		if (h === "data-methodology" || h.startsWith("method-")) {
			methodOpen = true;
			setTimeout(() => document.getElementById(h)?.scrollIntoView({ behavior: "smooth", block: "start" }), 60);
		}
	}

	// A shared ?tab= / ?author= makes each view linkable (old tab names still work).
	onMount(() => {
		try {
			const params = new URLSearchParams(window.location.search);
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
			else if (t === "overview" || t === "all") tab = "overview";
		} catch {}
		scrollToMethod();
		window.addEventListener("hashchange", scrollToMethod);
		return () => window.removeEventListener("hashchange", scrollToMethod);
	});

	// "Overview" resets to the library-wide total — clear any ?author/?title so the
	// freshly-mounted Viewer loads the all-checkouts line, not a saved deep link.
	function goOverview() {
		try {
			const url = new URL(window.location);
			["author", "title", "genre", "year", "tab", "kind"].forEach((k) => url.searchParams.delete(k));
			window.history.replaceState({}, "", url);
		} catch {}
		tab = "overview";
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

	// When you open a trend from the Rankings tab, remember where you were so a
	// "Back to rankings" link can restore that exact list (kind + genre + year).
	let rankReturn = $state(null);
	function rememberRankings() {
		if (tab !== "rankings") return;
		try {
			const url = new URL(window.location);
			rankReturn = { rankKind, genre: url.searchParams.get("genre"), year: url.searchParams.get("year") };
		} catch {
			rankReturn = { rankKind, genre: null, year: null };
		}
	}
	function backToRankings() {
		const r = rankReturn;
		rankReturn = null;
		try {
			const url = new URL(window.location);
			["author", "title", "kind"].forEach((k) => url.searchParams.delete(k));
			if (r?.genre) url.searchParams.set("genre", r.genre);
			else url.searchParams.delete("genre");
			if (r?.year) url.searchParams.set("year", r.year);
			else url.searchParams.delete("year");
			url.searchParams.set("tab", r?.rankKind === "authors" ? "top" : "works");
			window.history.replaceState({}, "", url);
		} catch {}
		rankKind = r?.rankKind || "works";
		tab = "rankings";
	}
	// Drop the return link once you navigate away from the trend view.
	$effect(() => {
		if (tab !== "search") rankReturn = null;
	});

	// Clicking an author (from Rankings, or a card's "See checkout trend") opens the
	// Search view with that author loaded (Viewer reads ?author on mount).
	function openAuthor(slug) {
		rememberRankings();
		try {
			const url = new URL(window.location);
			url.searchParams.set("author", slug);
			["tab", "kind", "genre", "year", "title"].forEach((k) => url.searchParams.delete(k));
			window.history.replaceState({}, "", url);
		} catch {}
		searchKind = "author";
		tab = "search";
	}

	// Clicking a work title opens the Search view for that title (reads ?title).
	function openTitle(title) {
		rememberRankings();
		try {
			const url = new URL(window.location);
			url.searchParams.set("title", title);
			["tab", "kind", "genre", "year", "author"].forEach((k) => url.searchParams.delete(k));
			window.history.replaceState({}, "", url);
		} catch {}
		searchKind = "title";
		tab = "search";
	}
</script>

<svelte:boundary onerror={(e) => console.error(e)}>
	<article>
		{#if tab === "overview"}
			<header class="headline">
				<img class="logo" src="{base}/favicon.png" alt="" width="88" height="88" />
				<h1>{copy.title}</h1>
				<p class="dek">{copy.dek}</p>
				<p class="byline">
					By the <a href="https://melaniewalsh.github.io/whats-seattle-reading/" target="_blank" rel="noopener noreferrer">What's Seattle Reading?</a> project<br />
					from the University of Washington Information School
				</p>
				<p class="wip">
					This is a work-in-progress. We would love your <a href="https://docs.google.com/forms/d/e/1FAIpQLSfHWbWEj1H4NltjSp3ixjelJKSu2VMQgEkTF3CpjWtWhwARfA/viewform?usp=dialog" target="_blank" rel="noopener noreferrer">feedback</a>!
				</p>
			</header>
		{:else}
			<header class="banner">
				<button class="banner-home" onclick={goOverview} aria-label="{copy.title} — home">
					<img class="banner-logo" src="{base}/favicon.png" alt="" width="46" height="46" />
					<span class="banner-title">{copy.title}</span>
				</button>
			</header>
		{/if}

		<div class="tab-groups">
			<div class="main-tabs" role="tablist" aria-label="Views">
				<button class="tab" role="tab" aria-selected={tab === "search"} class:active={tab === "search"} onclick={() => (tab = "search")}>Search</button>
				<button class="tab" role="tab" aria-selected={tab === "genres"} class:active={tab === "genres"} onclick={() => (tab = "genres")}>Genres</button>
				<button class="tab" role="tab" aria-selected={tab === "rankings"} class:active={tab === "rankings"} onclick={() => (tab = "rankings")}>Rankings</button>
			</div>
			{#if tab === "search"}
				<div class="subtabs" role="tablist" aria-label="Search by">
					<button class="subtab" class:active={searchKind === "author"} aria-selected={searchKind === "author"} onclick={() => setSearchKind("author")}>Author</button>
					<button class="subtab" class:active={searchKind === "title"} aria-selected={searchKind === "title"} onclick={() => setSearchKind("title")}>Title</button>
				</div>
			{/if}
		</div>

		{#if rankReturn && tab === "search"}
			<div class="back-bar">
				<button class="back-rankings" onclick={backToRankings}>← Back to rankings</button>
			</div>
		{/if}

		{#if tab === "genres"}
			<GenreTrends />
		{:else if tab === "rankings"}
			{#if rankKind === "works"}
				<TopWorks {openAuthor} {openTitle} {rankKind} {setRankKind} />
			{:else}
				<TopAuthors {openAuthor} {rankKind} {setRankKind} />
			{/if}
		{:else if tab === "overview"}
			<Viewer searchMode="author" landing="overview" />
		{:else}
			{#key searchKind}
				<Viewer searchMode={searchKind} landing="search" />
			{/key}
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
					inconsistently formatted and occasionally merged or misspelled. Titles borrowed fewer
					than 25 times are left out of an author's per-title breakdown (their total still counts
					them). Genres are inferred from catalog subject headings, which are themselves
					imperfect. Read the trends as indicative, not exact.
				</p>

				<h3 id="method-ack">Acknowledgements</h3>
				<p>
					Thanks to <strong>David Christensen</strong>, the <strong>Seattle Public Library</strong>,
					and the <strong>HDSSI</strong> for making this project possible.
				</p>
			</div>
		</details>

			<p class="cf-source">
				Data source:
				<a
					href="https://data.seattle.gov/Community-and-Culture/Checkouts-by-Title/tmmm-ytt6"
					target="_blank"
					rel="noopener"
				>Seattle Public Library — Checkouts by Title</a>
				(2006–2026)
			</p>
			<p class="cf-attr">
				What Is Seattle Reading? · University of Washington Information School
				<span class="cf-sep">·</span>
				<a href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noopener license">CC BY 4.0</a>
			</p>
		</footer>
	</article>
</svelte:boundary>

<style>
	article {
		max-width: 760px;
		margin: 0 auto;
		padding: 0 20px 80px;
	}
	.headline {
		max-width: 720px;
		margin: 8px auto 32px;
		text-align: center;
	}
	.logo {
		display: block;
		width: 88px;
		height: 88px;
		margin: 0 auto 12px;
	}
	.headline h1 {
		/* Fraunces display face — matches the rankings masthead title. */
		font-family: var(--font-display, var(--font-serif));
		font-weight: 700;
		font-size: clamp(2.3rem, 6vw, 3.6rem);
		line-height: 1.08;
		letter-spacing: -0.005em;
		margin: 0 0 16px;
		/* Slightly deeper blue than the old #6aa9dd so the big title clears WCAG
		   large-text contrast (~3:1) on white while keeping the light-blue look. */
		color: #3f88cc;
		/* soft drop shadow for a bit more presence */
		text-shadow: 1.5px 2px 0 rgba(53, 122, 189, 0.16);
	}
	.dek {
		font-family: var(--font-sans);
		font-size: 1.15rem;
		line-height: 1.4;
		color: var(--color-fg);
		margin: 0;
	}
	.byline {
		font-family: var(--font-sans);
		font-size: 0.9rem;
		line-height: 1.5;
		color: var(--color-fg);
		margin: 10px 0 0;
	}
	.byline a {
		color: inherit;
		font-weight: 600;
		text-decoration: underline;
	}
	.wip {
		font-family: var(--font-sans);
		font-size: 0.9rem;
		line-height: 1.5;
		color: var(--color-fg);
		margin: 12px 0 0;
	}
	.wip a {
		color: #357abd;
		font-weight: 600;
	}
	/* Compact banner header on non-Overview pages: logo + project title, clickable
	   to return home. */
	.banner {
		text-align: center;
		margin: 6px auto 0;
	}
	.banner-home {
		display: inline-flex;
		align-items: center;
		gap: 12px;
		background: none;
		border: none;
		padding: 4px 6px;
		cursor: pointer;
	}
	.banner-logo {
		display: block;
		width: 46px;
		height: 46px;
	}
	.banner-title {
		font-family: var(--font-display, var(--font-serif));
		font-weight: 700;
		font-size: clamp(1.4rem, 3.2vw, 1.9rem);
		line-height: 1;
		color: #3f88cc;
	}

	/* Four evenly-spread view tabs across the width, tab-bar style. */
	.tab-groups {
		display: flex;
		flex-direction: column;
		align-items: center;
		max-width: 720px;
		margin: 18px auto 26px;
	}
	.main-tabs {
		display: flex;
		width: 100%;
		border-bottom: 2px solid var(--color-border);
	}
	.tab {
		flex: 1;
		padding: 11px 8px;
		background: none;
		border: none;
		border-bottom: 3px solid transparent;
		margin-bottom: -2px;
		font-family: var(--font-sans);
		font-size: 1rem;
		font-weight: 600;
		color: var(--color-fg-light);
		cursor: pointer;
		transition: color 0.12s, border-color 0.12s;
	}
	.tab:hover {
		color: var(--color-fg);
	}
	.tab.active {
		color: var(--color-fg);
		border-bottom-color: #357abd;
	}
	/* "Back to rankings" shown after you open a trend from the Rankings tab. */
	.back-bar {
		max-width: 720px;
		margin: 0 auto 10px;
	}
	.back-rankings {
		font-family: var(--font-sans);
		font-size: 0.85rem;
		font-weight: 600;
		color: var(--color-fg);
		background: none;
		border: none;
		padding: 4px 0;
		cursor: pointer;
	}
	.back-rankings:hover {
		text-decoration: underline;
		text-underline-offset: 2px;
	}
	/* segmented sub-toggle (Author/Title, Authors/Works) beneath the main tabs */
	.subtabs {
		display: inline-flex;
		gap: 2px;
		margin-top: 12px;
		padding: 3px;
		border-radius: 999px;
		background: var(--color-gray-100, #f0f0f0);
	}
	.subtab {
		font-family: var(--font-sans);
		font-size: 0.85rem;
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
		max-width: 720px;
		margin: 28px auto 0;
		padding-top: 12px;
		border-top: 1px solid var(--color-border);
		font-family: var(--font-sans);
		font-size: 0.8rem;
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
		color: #357abd;
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
		font-size: 0.95rem;
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
		font-size: 0.9rem;
		line-height: 1.55;
		color: var(--color-fg);
		margin: 0 0 12px;
	}
	.about-body p:last-child {
		margin-bottom: 0;
	}
	.about-body h3 {
		font-family: var(--font-sans);
		font-size: 0.92rem;
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
