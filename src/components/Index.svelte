<script>
	import { getContext, onMount } from "svelte";
	import { base } from "$app/paths";
	import Viewer from "$components/StackedViewer.svelte";
	import GenreTrends from "$components/GenreTrends.svelte";
	import TopAuthors from "$components/TopAuthors.svelte";

	const copy = getContext("copy");
	let tab = $state("authors"); // "authors" | "titles" | "genres" | "top"

	// A shared ?tab= makes the Top-authors / By-genre views linkable.
	onMount(() => {
		try {
			const t = new URLSearchParams(window.location.search).get("tab");
			if (t === "top" || t === "genres" || t === "titles") tab = t;
		} catch {}
	});

	// Clicking an author in the Top-authors table jumps to the By-author view
	// with that author loaded (the Viewer reads ?author= when it mounts).
	function openAuthor(slug) {
		try {
			const url = new URL(window.location);
			url.searchParams.set("author", slug);
			["tab", "genre", "year"].forEach((k) => url.searchParams.delete(k));
			window.history.replaceState({}, "", url);
		} catch {}
		tab = "authors";
	}
</script>

<svelte:boundary onerror={(e) => console.error(e)}>
	<article>
		<header class="headline">
			<img class="logo" src="{base}/favicon.png" alt="" width="88" height="88" />
			<h1>{copy.title}</h1>
			<p class="dek">{copy.dek}</p>
		</header>

		<div class="tab-groups">
			<div class="tab-group">
				<span class="tab-group-label">Explore</span>
				<div class="main-tabs" role="tablist" aria-label="Explore">
					<button role="tab" aria-selected={tab === "authors"} class:active={tab === "authors"} onclick={() => (tab = "authors")}>By author</button>
					<button role="tab" aria-selected={tab === "titles"} class:active={tab === "titles"} onclick={() => (tab = "titles")}>By title</button>
				</div>
			</div>
			<div class="tab-group">
				<span class="tab-group-label">Browse</span>
				<div class="main-tabs" role="tablist" aria-label="Browse">
					<button role="tab" aria-selected={tab === "genres"} class:active={tab === "genres"} onclick={() => (tab = "genres")}>By genre</button>
					<button role="tab" aria-selected={tab === "top"} class:active={tab === "top"} onclick={() => (tab = "top")}>Top authors</button>
				</div>
			</div>
		</div>

		{#if tab === "genres"}
			<GenreTrends />
		{:else if tab === "top"}
			<TopAuthors {openAuthor} />
		{:else}
			<Viewer searchMode={tab === "titles" ? "title" : "author"} />
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
		font-family: var(--font-display);
		/* Fraunces is a variable font with real weights, so use a semibold weight
		   for the display headline instead of faking it with a text-stroke. */
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
		font-size: 1.1rem;
		line-height: 1.5;
		color: var(--color-fg-light);
		margin: 0;
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
	/* top-level view tabs: pill group of buttons */
	.main-tabs {
		display: flex;
		justify-content: center;
		gap: 4px;
		margin: 0;
		padding: 4px;
		width: fit-content;
		background: var(--color-gray-100);
		border-radius: 999px;
	}
	.main-tabs button {
		border: none;
		background: none;
		padding: 8px 22px;
		border-radius: 999px;
		font-family: var(--font-sans);
		font-size: 0.95rem;
		font-weight: 600;
		color: var(--color-fg-light);
		cursor: pointer;
		transition: background 0.12s, color 0.12s;
	}
	.main-tabs button.active {
		background: var(--color-fg);
		color: var(--color-white);
	}
	.main-tabs button:not(.active):hover {
		color: var(--color-fg);
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
