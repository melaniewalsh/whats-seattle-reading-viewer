<script>
	import { wikiSummary, wikiWork } from "$utils/wiki.js";

	// query:  the name/title to look up on Wikipedia.
	// kind:   "author" | "work". Works resolve through Wikidata (book/author aware).
	// author: the work's author, used to disambiguate the Wikidata match.
	// links:  { wikipedia } search URL (fallback when there's no article match).
	// onTrend: called when the "See SPL trend" button is clicked.
	// quiet:  for the trend-page heading, where Borrow / Learn more buttons sit
	//         alongside: no catalog link, no repeat of the header's photo or
	//         cover, and Wikipedia shown as a small source credit.
	let { query, kind = "author", author = "", links = {}, onTrend, quiet = false } = $props();

	let status = $state({ loading: true, data: null });

	$effect(() => {
		let alive = true;
		status = { loading: true, data: null };
		const p = kind === "work" ? wikiWork(query, author) : wikiSummary(query);
		p.then((d) => {
			if (alive) status = { loading: false, data: d };
		});
		return () => {
			alive = false;
		};
	});

	// Prefer the real article URL when we have it, else a Wikipedia search.
	const wikiHref = $derived(status.data?.url || links.wikipedia || "#");

	// Trim the extract to a couple of sentences so the card stays compact.
	function trim(t) {
		if (!t) return "";
		if (t.length <= 280) return t;
		const s = t.slice(0, 280);
		const cut = s.lastIndexOf(". ");
		return cut > 150 ? s.slice(0, cut + 1) : s.trim() + "…";
	}
</script>

<div class="wiki-card">
	{#if status.loading}
		<div class="wiki-skel">
			<div class="wiki-skel-thumb"></div>
			<div class="wiki-skel-lines"><span></span><span></span><span></span></div>
		</div>
	{:else if status.data}
		{#if status.data.thumbnail && !quiet}
			<img class="wiki-thumb" src={status.data.thumbnail} alt="" />
		{/if}
		<p class="wiki-extract">{trim(status.data.extract)}</p>
	{:else}
		<p class="wiki-none">No Wikipedia summary found for this {kind}.</p>
	{/if}

	{#if quiet}
		{#if !status.loading}
			<a class="wiki-credit" href={wikiHref} target="_blank" rel="noopener noreferrer"
				>{status.data ? "From Wikipedia" : "Search Wikipedia"} <span aria-hidden="true">↗</span></a
			>
		{/if}
	{:else}
	<div class="wiki-act">
		{#if onTrend}
			<button class="wiki-trend" onclick={onTrend}>
				See checkout trend at Seattle Public Library <span aria-hidden="true">📈 →</span>
			</button>
		{/if}
		{#if links.spl}
			<a class="wiki-spl" href={links.spl} target="_blank" rel="noopener noreferrer"
				>Find in the Seattle Public Library catalog <span aria-hidden="true">↗</span></a
			>
		{/if}
		{#if !status.loading}
			<a class="wiki-wiki" href={wikiHref} target="_blank" rel="noopener noreferrer"
				>{status.data ? "Read on Wikipedia" : "Search Wikipedia"} <span aria-hidden="true">↗</span></a
			>
		{/if}
	</div>
	{/if}
</div>

<style>
	.wiki-card {
		width: 300px;
		max-width: 100%;
		box-sizing: border-box;
		padding: 13px 14px;
		background: var(--color-white);
		border: 1px solid var(--color-border);
		border-radius: 12px;
		box-shadow: 0 10px 30px rgba(0, 0, 0, 0.16);
		text-align: left;
	}
	/* On touch / narrow screens the card fills its (bottom-sheet) container. */
	@media (hover: none), (max-width: 599px) {
		.wiki-card {
			width: 100%;
		}
	}
	.wiki-thumb {
		float: right;
		width: 76px;
		height: auto;
		max-height: 110px;
		object-fit: cover;
		border-radius: 6px;
		margin: 2px 0 6px 12px;
	}
	.wiki-extract {
		margin: 0 0 10px;
		font-family: var(--font-sans);
		font-size: 0.82rem;
		font-weight: 400;
		line-height: 1.45;
		color: var(--color-fg);
	}
	.wiki-none {
		margin: 0 0 10px;
		font-family: var(--font-sans);
		font-size: 0.82rem;
		color: var(--color-fg-light);
	}
	.wiki-act {
		clear: both;
		border-top: 1px solid var(--color-border);
		padding-top: 10px;
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		gap: 8px;
	}
	.wiki-trend {
		border: none;
		background: none;
		padding: 0;
		cursor: pointer;
		font-family: var(--font-sans);
		font-size: 0.82rem;
		font-weight: 600;
		color: #6a4c93;
		text-align: left;
	}
	.wiki-trend:hover {
		text-decoration: underline;
	}
	.wiki-credit {
		display: inline-block;
		font-family: var(--font-sans);
		font-size: 0.78rem;
		color: var(--color-fg-light);
		text-decoration: underline;
		text-decoration-color: var(--color-border);
		text-underline-offset: 3px;
	}
	.wiki-credit:hover { color: var(--color-fg); text-decoration-color: currentColor; }
	.wiki-wiki {
		display: inline-block;
		font-family: var(--font-sans);
		font-size: 0.82rem;
		font-weight: 600;
		color: #3f88cc;
		text-decoration: none;
	}
	.wiki-wiki:hover {
		text-decoration: underline;
	}
	.wiki-spl {
		display: inline-block;
		font-family: var(--font-sans);
		font-size: 0.82rem;
		font-weight: 600;
		color: #1f7a4d;
		text-decoration: none;
	}
	.wiki-spl:hover {
		text-decoration: underline;
	}
	.wiki-skel {
		display: flex;
		gap: 12px;
		margin-bottom: 10px;
	}
	.wiki-skel-thumb {
		flex: none;
		width: 76px;
		height: 100px;
		border-radius: 6px;
		background: var(--color-gray-100);
		animation: wiki-pulse 1.1s ease-in-out infinite;
	}
	.wiki-skel-lines {
		flex: 1;
		display: flex;
		flex-direction: column;
		gap: 8px;
		padding-top: 4px;
	}
	.wiki-skel-lines span {
		height: 10px;
		border-radius: 5px;
		background: var(--color-gray-100);
		animation: wiki-pulse 1.1s ease-in-out infinite;
	}
	.wiki-skel-lines span:nth-child(2) {
		width: 85%;
	}
	.wiki-skel-lines span:nth-child(3) {
		width: 60%;
	}
	@keyframes wiki-pulse {
		0%,
		100% {
			opacity: 1;
		}
		50% {
			opacity: 0.45;
		}
	}
</style>
