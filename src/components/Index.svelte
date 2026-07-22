<script>
	import { getContext, onMount } from "svelte";
	import { base } from "$app/paths";
	import Viewer from "$components/StackedViewer.svelte";
	import GenreTrends from "$components/GenreTrends.svelte";
	import TopAuthors from "$components/TopAuthors.svelte";
	import TopWorks from "$components/TopWorks.svelte";

	const copy = getContext("copy");
	// "all" (library-wide overview) | "authors" | "titles" | "genres" | "top" | "works"
	let tab = $state("all");

	// A shared ?tab= / ?author= makes each view linkable.
	onMount(() => {
		try {
			const params = new URLSearchParams(window.location.search);
			const t = params.get("tab");
			if (["top", "works", "genres", "titles", "authors", "all"].includes(t)) tab = t;
			else if (params.get("author")) tab = "authors";
			else if (params.get("title")) tab = "titles";
		} catch {}
	});

	// Clicking an author (Top authors, or the "by author" on Top works) jumps to
	// the By-author view with that author loaded (Viewer reads ?author on mount).
	function openAuthor(slug) {
		try {
			const url = new URL(window.location);
			url.searchParams.set("author", slug);
			["tab", "genre", "year", "title"].forEach((k) => url.searchParams.delete(k));
			window.history.replaceState({}, "", url);
		} catch {}
		tab = "authors";
	}

	// Clicking a work title on Top works opens the By-title view for that title
	// (Viewer reads ?title on mount).
	function openTitle(title) {
		try {
			const url = new URL(window.location);
			url.searchParams.set("title", title);
			["tab", "genre", "year", "author"].forEach((k) => url.searchParams.delete(k));
			window.history.replaceState({}, "", url);
		} catch {}
		tab = "titles";
	}
</script>

<svelte:boundary onerror={(e) => console.error(e)}>
	<article>
		<header class="headline">
			<img class="logo" src="{base}/favicon.png" alt="" width="88" height="88" />
			<h1>{copy.title}</h1>
			<p class="dek">{copy.dek}</p>
			<p class="byline">
				By the <a href="https://melaniewalsh.github.io/whats-seattle-reading/" target="_blank" rel="noopener noreferrer">What's Seattle Reading?</a> project<br />
				from the University of Washington Information School
			</p>
		</header>

		<div class="tab-groups">
			<div class="tab-group">
				<span class="tab-group-label">Explore trends</span>
				<div class="sticker-tabs trends" role="tablist" aria-label="Explore trends">
					<button class="sticker-tab" role="tab" aria-selected={tab === "all"} class:active={tab === "all"} onclick={() => (tab = "all")}>All</button>
					<div class="bys">
						<button class="sticker-tab" role="tab" aria-selected={tab === "authors"} class:active={tab === "authors"} onclick={() => (tab = "authors")}>By author</button>
						<button class="sticker-tab" role="tab" aria-selected={tab === "titles"} class:active={tab === "titles"} onclick={() => (tab = "titles")}>By title</button>
						<button class="sticker-tab" role="tab" aria-selected={tab === "genres"} class:active={tab === "genres"} onclick={() => (tab = "genres")}>By genre</button>
					</div>
				</div>
			</div>
			<div class="tab-group">
				<span class="tab-group-label">Rankings</span>
				<div class="sticker-tabs rankings" role="tablist" aria-label="Rankings">
					<button class="sticker-tab" role="tab" aria-selected={tab === "top"} class:active={tab === "top"} onclick={() => (tab = "top")}>Top authors</button>
					<button class="sticker-tab" role="tab" aria-selected={tab === "works"} class:active={tab === "works"} onclick={() => (tab = "works")}>Top works</button>
				</div>
			</div>
		</div>

		{#if tab === "genres"}
			<GenreTrends />
		{:else if tab === "top"}
			<TopAuthors {openAuthor} />
		{:else if tab === "works"}
			<TopWorks {openAuthor} {openTitle} />
		{:else if tab === "all"}
			<Viewer searchMode="author" landing="overview" />
		{:else}
			<Viewer searchMode={tab === "titles" ? "title" : "author"} landing="search" />
		{/if}

		<details class="about">
			<summary>About this data &amp; how to read it</summary>
			<div class="about-body">
				<p>
					This tool charts <strong>checkouts</strong> logged by the Seattle Public Library —
					physical books, ebooks, and audiobooks. Each point is how many times an author's
					titles were borrowed in that month.
				</p>
				<p>
					<strong>Works vs. editions.</strong> The same book appears many times in the catalog
					(print, ebook, audiobook, reprints, translations). Use <em>“Show work groups”</em> to
					cluster editions of one work into a single line. Clustering is automatic and
					approximate — drag titles between groups to correct it.
				</p>
				<p>
					<strong>Caveats.</strong> Author and title names come straight from library catalog
					records, which are inconsistently formatted and occasionally merged or misspelled.
					Titles borrowed fewer than 25 times are left out of an author's per-title breakdown
					(their total still counts them). Read the trends as indicative, not exact.
				</p>
			</div>
		</details>

		<footer class="chart-footer">
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
		/* Match the plot-title font (Source Serif 4) rather than the Fraunces display. */
		font-family: var(--font-serif);
		font-weight: 600;
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
	/* Two labeled groups of tabs: Explore (search a thing) | Browse (aggregates). */
	.tab-groups {
		display: flex;
		justify-content: center;
		align-items: flex-end;
		flex-wrap: wrap;
		gap: 10px 24px;
		margin: 22px auto 26px;
	}
	.tab-group {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 6px;
	}
	.tab-group-label {
		font-family: var(--font-sans);
		font-size: 0.66rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--color-fg-light);
	}
	/* top-level view tabs: bold "sticker" buttons with a hard offset shadow */
	.sticker-tabs {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 10px;
		flex-wrap: wrap;
	}
	/* the three "By ..." tabs are grouped so "All" can sit apart from them */
	.bys {
		display: flex;
		gap: 10px;
		flex-wrap: wrap;
		justify-content: center;
	}
	/* On narrow screens the Explore-trends group stacks: "All" on its own line,
	   the three "By ..." tabs centered beneath it (instead of a wonky wrap). */
	@media (max-width: 560px) {
		.sticker-tabs.trends {
			flex-direction: column;
		}
	}
	.sticker-tab {
		--sh: var(--color-fg);
		font-family: var(--font-sans);
		font-size: 0.95rem;
		font-weight: 600;
		padding: 9px 16px;
		border-radius: 8px;
		background: var(--color-white);
		color: var(--color-fg);
		border: 2px solid var(--sh);
		box-shadow: 3px 3px 0 var(--sh);
		cursor: pointer;
		transition: transform 0.08s ease, box-shadow 0.08s ease;
	}
	.sticker-tab:hover {
		transform: translate(-1px, -1px);
		box-shadow: 4px 4px 0 var(--sh);
	}
	.sticker-tab:active {
		transform: translate(2px, 2px);
		box-shadow: 1px 1px 0 var(--sh);
	}
	.trends .sticker-tab.active {
		--sh: #16324f;
		background: #357abd;
		color: var(--color-white);
	}
	.rankings .sticker-tab.active {
		--sh: #33224a;
		background: #6a4c93;
		color: var(--color-white);
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
		max-width: 640px;
		margin: 40px auto 0;
		font-family: var(--font-sans);
		border: none;
		background: none;
		padding: 0;
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
</style>
