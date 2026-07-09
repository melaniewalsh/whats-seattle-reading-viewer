<script>
	import { getContext } from "svelte";
	import { base } from "$app/paths";
	import Viewer from "$components/StackedViewer.svelte";

	const copy = getContext("copy");
</script>

<svelte:boundary onerror={(e) => console.error(e)}>
	<article>
		<header class="headline">
			<img class="logo" src="{base}/favicon.png" alt="" width="88" height="88" />
			<h1>{copy.title}</h1>
			<p class="dek">{copy.dek}</p>
		</header>

		<Viewer />

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
					Titles borrowed fewer than 50 times are left out of an author's per-title breakdown
					(their total still counts them). Read the trends as indicative, not exact.
				</p>
			</div>
		</details>

		<p class="note">
			Data source:
			<a
				href="https://data.seattle.gov/Community-and-Culture/Checkouts-by-Title/tmmm-ytt6"
				target="_blank"
				rel="noopener"
			>
				Seattle Public Library — Checkouts by Title
			</a>
			(2006–2026).
		</p>
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
		font-family: "Recoleta", var(--font-serif);
		font-weight: 400;
		font-size: clamp(2.3rem, 6vw, 3.6rem);
		line-height: 1.08;
		letter-spacing: -0.005em;
		margin: 0 0 16px;
		/* Slightly deeper blue than the old #6aa9dd so the big title clears WCAG
		   large-text contrast (~3:1) on white while keeping the light-blue look. */
		color: #3f88cc;
		/* Recoleta only ships one weight here, so fatten the strokes a touch and
		   add a soft drop shadow for a bit more presence. */
		-webkit-text-stroke: 0.6px #3f88cc;
		text-shadow: 1.5px 2px 0 rgba(53, 122, 189, 0.16);
	}
	.dek {
		font-family: var(--font-sans);
		font-size: 1.1rem;
		line-height: 1.5;
		color: var(--color-fg-light);
		margin: 0;
	}
	.note {
		max-width: 720px;
		margin: 40px auto 0;
		font-family: var(--font-sans);
		font-size: 0.85rem;
		color: var(--color-fg-light);
		text-align: center;
	}
	.note a {
		color: #357abd;
		text-decoration: underline;
	}
	.note a:hover {
		color: #26597f;
	}

	.about {
		max-width: 640px;
		margin: 48px auto 0;
		font-family: var(--font-sans);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-gray-100);
		padding: 0 16px;
	}
	.about summary {
		cursor: pointer;
		padding: 14px 0;
		font-weight: 600;
		font-size: 0.95rem;
		color: var(--color-fg);
		list-style-position: inside;
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
