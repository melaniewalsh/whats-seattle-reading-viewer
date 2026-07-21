<script>
	import { wikiSummary } from "$utils/wiki.js";

	// query: the name/title to look up. kind: "author" | "work" (wording only).
	let { query, kind = "author" } = $props();

	let status = $state({ loading: true, data: null });

	$effect(() => {
		let alive = true;
		status = { loading: true, data: null };
		wikiSummary(query).then((d) => {
			if (alive) status = { loading: false, data: d };
		});
		return () => {
			alive = false;
		};
	});

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
		{#if status.data.thumbnail}
			<img class="wiki-thumb" src={status.data.thumbnail} alt="" />
		{/if}
		<p class="wiki-extract">{trim(status.data.extract)}</p>
		<a class="wiki-link" href={status.data.url} target="_blank" rel="noopener noreferrer"
			>Read on Wikipedia <span aria-hidden="true">↗</span></a
		>
	{:else}
		<p class="wiki-none">No Wikipedia summary found for this {kind}.</p>
	{/if}
</div>

<style>
	.wiki-card {
		width: 290px;
		padding: 13px 14px;
		background: var(--color-white);
		border: 1px solid var(--color-border);
		border-radius: 12px;
		box-shadow: 0 10px 30px rgba(0, 0, 0, 0.16);
		text-align: left;
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
		margin: 0 0 9px;
		font-family: var(--font-sans);
		font-size: 0.82rem;
		font-weight: 400;
		line-height: 1.45;
		color: var(--color-fg);
	}
	.wiki-link {
		font-family: var(--font-sans);
		font-size: 0.8rem;
		font-weight: 600;
		color: #357abd;
		text-decoration: none;
	}
	.wiki-link:hover {
		text-decoration: underline;
	}
	.wiki-none {
		margin: 0;
		font-family: var(--font-sans);
		font-size: 0.82rem;
		color: var(--color-fg-light);
	}
	.wiki-skel {
		display: flex;
		gap: 12px;
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
