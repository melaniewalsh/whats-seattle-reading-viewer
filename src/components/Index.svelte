<script>
	import { getContext, onMount } from "svelte";
	import { base } from "$app/paths";
	import Viewer from "$components/StackedViewer.svelte";
	import GenreTrends from "$components/GenreTrends.svelte";
	import TopAuthors from "$components/TopAuthors.svelte";
	import TopWorks from "$components/TopWorks.svelte";
	import NortonExplorer from "$components/NortonExplorer.svelte";
	import { publications } from "$data/publications.js";

	const copy = getContext("copy");
	// Four top-level views. "search" and "rankings" carry a sub-kind toggle.
	let tab = $state("home"); // "home" (landing hub) | "overview" (all-checkouts plot) | "search" | "genres" | "rankings" | "about"
	let searchKind = $state("author"); // Search tab: "author" | "title"
	let rankKind = $state("works"); // Rankings tab: "authors" | "works"
	let menuOpen = $state(false); // the slide-out hamburger menu

	// Go to a tab and close the hamburger menu (used by the menu + pills).
	function go(t) {
		tab = t;
		menuOpen = false;
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
			else if (t === "about") tab = "about";
			else if (t === "publications") tab = "publications";
			else if (t === "norton") tab = "norton";
			else if (t === "spl500") tab = "spl500";
			else if (t === "overview" || t === "all") tab = "overview";
			else if (t === "home") tab = "home";
		} catch {}
		scrollToMethod();
		window.addEventListener("hashchange", scrollToMethod);
		return () => window.removeEventListener("hashchange", scrollToMethod);
	});

	// Clear any deep-link params so a freshly-mounted view isn't hijacked by a
	// stale ?author/?title/?genre.
	function clearParams() {
		try {
			const url = new URL(window.location);
			["author", "title", "genre", "year", "tab", "kind"].forEach((k) => url.searchParams.delete(k));
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
		<div class="masthead">
			<div class="masthead-top">
				<button class="mast-home" class:here={tab === "home"} onclick={goHome} aria-label="{copy.title} — home">
					<img class="mast-logo" src="{base}/favicon.png" alt="" width="30" height="30" />
					<span class="mast-title">{copy.title}</span>
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
				<button class="menu-link" onclick={() => go("search")}>Search</button>
				<button class="menu-link" onclick={() => go("genres")}>Genres</button>
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
			<header class="section-masthead">
				<h2 class="sec-title">{searchKind === "title" ? "Seattle's Work Trends" : "Seattle's Author Trends"}</h2>
				<p class="sec-sub">Look up any author or title's borrowing trend at the Seattle Public Library.</p>
			</header>
		{/if}

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
		{:else if tab === "home"}
			<header class="hero">
				<div class="hero-title">
					<img class="hero-logo" src="{base}/favicon.png" alt="" width="56" height="56" />
					<h1>{copy.title}</h1>
				</div>
				<p class="dek">{copy.dek}</p>
				<p class="byline">By the <a href="https://melaniewalsh.github.io/whats-seattle-reading/" target="_blank" rel="noopener noreferrer">What's Seattle Reading?</a> project</p>
			</header>
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
				<button class="hub-card" onclick={() => go("genres")}>
					<span class="hub-emoji" aria-hidden="true">📈</span>
					<span class="hub-h">Genres</span>
					<span class="hub-d">How Seattle's taste in romance, mystery, fantasy and more has shifted over the years.</span>
					<span class="hub-go">Explore →</span>
				</button>
				<button class="hub-card" onclick={() => go("search")}>
					<img class="hub-emoji hub-img" src="{base}/hub-search.png" alt="" width="34" height="34" />
					<span class="hub-h">Search</span>
					<span class="hub-d">Look up any author or title and see its checkout trend at the Seattle Public Library.</span>
					<span class="hub-go">Explore →</span>
				</button>
			</nav>
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
			{#key searchKind}
				<Viewer searchMode={searchKind} landing="search" {setSearchKind} />
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
				What Is Seattle Reading?
				<span class="cf-sep">·</span>
				<a href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noopener license">CC BY 4.0</a>
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
		margin: 0 0 14px;
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
		font-size: 0.92rem;
		color: var(--color-fg-light);
		margin: 12px 0 0;
	}
	.byline a { color: #357abd; font-weight: 600; text-decoration: underline; }
	.hub {
		max-width: 880px;
		margin: 36px auto 10px;
		display: grid;
		grid-template-columns: repeat(2, 1fr);
		gap: 16px;
	}
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
	.hub-img { width: 2rem; height: 2rem; object-fit: contain; }
	.hub-h {
		font-family: var(--font-display, var(--font-serif));
		font-size: 1.4rem;
		font-weight: 700;
		color: var(--color-fg);
	}
	.hub-d { font-size: 0.92rem; line-height: 1.45; color: var(--color-fg-light); }
	.hub-go { margin-top: 4px; font-size: 0.85rem; font-weight: 700; color: #357abd; }
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
		margin: 0 0 18px;
	}
	.about-page p {
		font-size: 1.05rem;
		line-height: 1.6;
		color: var(--color-fg);
		margin: 0 0 14px;
	}
	.about-page a {
		color: #357abd;
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
		margin: 0 0 14px;
		padding-left: 20px;
	}
	.about-list li {
		font-size: 1.02rem;
		line-height: 1.55;
		margin: 0 0 5px;
		color: var(--color-fg);
	}
	.about-list a { color: #357abd; font-weight: 600; text-decoration: underline; }
	.about-page .about-more {
		font-size: 0.95rem;
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
		font-size: 1.05rem;
		line-height: 1.5;
		color: var(--color-fg-light);
		margin: 0 0 8px;
	}
	.pub-year {
		font-family: var(--font-display, var(--font-serif));
		font-size: 1.5rem;
		font-weight: 700;
		color: var(--color-fg);
		margin: 30px 0 4px;
		padding-bottom: 6px;
		border-bottom: 2px solid var(--color-fg);
	}
	.pub-month {
		font-family: var(--font-sans);
		font-size: 0.75rem;
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
	.pub-title:hover { color: #357abd; text-decoration: underline; }
	.pub-cite {
		font-size: 0.98rem;
		line-height: 1.5;
		color: var(--color-fg);
		margin: 0 0 5px;
	}
	.pub-cite a, .pub-links a { color: #357abd; font-weight: 600; text-decoration: underline; }
	.pub-links {
		font-size: 0.92rem;
		margin: 0;
	}
	.pub-sep { color: var(--color-fg-light); }
	.pub-bib {
		margin-top: 8px;
		font-size: 0.9rem;
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
		font-size: 0.72rem;
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
		font-size: 0.78rem;
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
		font-size: 0.72rem;
		font-weight: 800;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: #3f88cc;
		margin: 0 0 8px;
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
		font-size: 1.5rem;
		font-weight: 700;
		color: var(--color-fg);
		margin: 32px 0 4px;
		padding-bottom: 8px;
		border-bottom: 2px solid var(--color-fg);
	}
	.study-p {
		font-family: var(--font-sans);
		font-size: 1.05rem;
		line-height: 1.65;
		color: var(--color-fg);
		margin: 0 0 16px;
	}
	.study a { color: #357abd; font-weight: 600; text-decoration: underline; }
	.study-byline {
		font-family: var(--font-sans);
		font-size: 0.9rem;
		color: var(--color-fg-light);
		margin: 0 0 16px;
	}
	.study-callout {
		font-family: var(--font-sans);
		font-size: 0.92rem;
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
		font-size: 0.9rem;
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
		min-height: 46px;
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 16px;
		padding: 6px 24px 0;
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
		font-size: 0.92rem;
		line-height: 1;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: #3f88cc;
		white-space: nowrap;
	}
	/* Top-right meta links (About, …) — small and understated. */
	.mast-meta {
		display: flex;
		align-items: center;
		gap: 14px;
	}
	.mast-metalink {
		font-family: var(--font-sans);
		font-size: 0.72rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: #97a2ad;
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
		font-size: 1.5rem;
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
		font-size: 0.7rem;
		font-weight: 800;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: #97a2ad;
		margin: 0 0 8px;
	}
	.menu-link {
		display: block;
		width: 100%;
		text-align: left;
		font-family: var(--font-display, var(--font-serif));
		font-size: 1.25rem;
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
		.masthead-top { padding: 6px 14px 0; }
		.mast-title { font-size: 0.82rem; }
		/* About is in the hamburger menu on phones — drop the standalone link so the
		   wordmark has room. */
		.mast-metalink { display: none; }
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
	.sec-sub {
		font-family: var(--font-sans);
		font-size: 0.95rem;
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
		font-size: 0.78rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--color-fg-light);
	}
	.filter-field select {
		font-family: var(--font-sans);
		font-size: 0.95rem;
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
		margin: 40px 0 0;
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
