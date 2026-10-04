<script>
	// The site's search field: a live autocomplete over authors AND books. It
	// lives on the Checkout Trends page; the nav's magnifying glass brings you
	// to it (Index.svelte calls focus()).
	import { searchAll } from "$components/db.js";
	import { titleCase } from "$utils/titleCase.js";
	import { cleanWorkTitle } from "$utils/cleanTitle.js";
	import { displayName } from "$utils/displayName.js";

	let { onPick = () => {}, placeholder = "Search authors or books" } = $props();

	let q = $state("");
	let results = $state([]);
	let open = $state(false);
	let flash = $state(false);
	let inputEl;
	let timer;

	function onInput() {
		open = true;
		clearTimeout(timer);
		const needle = q.trim();
		timer = setTimeout(async () => {
			if (needle.length < 2) { results = []; return; }
			try { results = await searchAll(needle, 8); } catch { results = []; }
		}, 140);
	}
	function pick(res) {
		open = false;
		q = "";
		results = [];
		onPick(res);
	}
	// We render our own × (the native one on <input type="search"> fires a
	// `search` event, not `input`, so the results never cleared).
	function clear() {
		clearTimeout(timer);
		q = "";
		results = [];
		open = false;
		inputEl?.focus();
	}
	function onKey(e) {
		if (e.key === "Enter" && results.length) { e.preventDefault(); pick(results[0]); }
		else if (e.key === "Escape") open = false;
	}
	// Put the cursor here; with ring=true, also pulse a blue ring around the
	// field so it's clear where to type.
	export function focus(ring = false) {
		inputEl?.focus({ preventScroll: true });
		if (!ring) return;
		flash = false;
		setTimeout(() => (flash = true), 20);
		setTimeout(() => (flash = false), 1900);
	}
</script>

<div class="ss" class:flash>
	<svg class="ss-ic" viewBox="0 0 20 20" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
		<circle cx="9" cy="9" r="6" /><line x1="13.5" y1="13.5" x2="18" y2="18" />
	</svg>
	<input
		bind:this={inputEl}
		class="ss-input"
		type="search"
		{placeholder}
		aria-label="Search authors or books"
		autocomplete="off"
		spellcheck="false"
		bind:value={q}
		oninput={onInput}
		onfocus={() => (open = true)}
		onkeydown={onKey}
	/>
	{#if q}
		<button class="ss-clear" aria-label="Clear search" onclick={clear}>×</button>
	{/if}
	{#if open && (results.length || q.trim().length >= 2)}
		<button class="ss-backdrop" aria-label="Close search" onclick={() => (open = false)}></button>
		<ul class="ss-results" role="listbox">
			{#each results as r}
				<li>
					<button class="ss-result" onclick={() => pick(r)}>
						<span class="ss-name">{r.kind === "work" ? titleCase(cleanWorkTitle(r.title)) : displayName(r.name)}</span>
						<span class="ss-kind {r.kind === 'work' ? 'kind-book' : 'kind-author'}">{r.kind === "work" ? "Book" : "Author"}</span>
					</button>
				</li>
			{/each}
			{#if !results.length}
				<li><p class="ss-none">Nothing found for “{q.trim()}”.</p></li>
			{/if}
		</ul>
	{/if}
</div>

<style>
	/* A plain white field with a crisp edge; a blue ring while typing. */
	.ss {
		position: relative;
		display: flex;
		align-items: center;
		gap: 10px;
		width: 100%;
		max-width: 560px;
		height: 46px;
		padding: 0 14px;
		background: #fff;
		border: 1.5px solid var(--color-border);
		border-radius: 8px;
		transition: border-color 0.12s, box-shadow 0.12s;
	}
	.ss:hover { border-color: var(--color-fg-light); }
	.ss:focus-within {
		border-color: #3f88cc;
		box-shadow: 0 0 0 3px rgba(63, 136, 204, 0.18);
	}
	.ss.flash { animation: ss-ring 1.6s ease-out; }
	@keyframes ss-ring {
		0% { box-shadow: 0 0 0 0 rgba(63, 136, 204, 0.55); }
		35% { box-shadow: 0 0 0 7px rgba(63, 136, 204, 0.22); }
		100% { box-shadow: 0 0 0 10px rgba(63, 136, 204, 0); }
	}
	@media (prefers-reduced-motion: reduce) {
		.ss.flash { animation: none; box-shadow: 0 0 0 3px rgba(63, 136, 204, 0.3); }
	}
	.ss-ic { width: 17px; height: 17px; flex: none; color: var(--color-fg-light); }
	.ss-input {
		flex: 1 1 auto;
		min-width: 0;
		border: none;
		background: none;
		outline: none;
		font-family: var(--font-sans);
		font-size: 17px;
		font-weight: 500;
		color: var(--color-fg);
	}
	.ss-input::placeholder { color: var(--color-placeholder); font-weight: 400; }
	.ss-input::-webkit-search-cancel-button,
	.ss-input::-webkit-search-decoration { -webkit-appearance: none; appearance: none; }
	.ss-clear {
		flex: none;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 20px;
		height: 20px;
		padding: 0;
		border: none;
		border-radius: 50%;
		background: var(--color-gray-300);
		color: var(--color-white);
		font-size: 14px;
		line-height: 1;
		cursor: pointer;
	}
	.ss-clear:hover { background: var(--color-fg-light); }
	.ss-backdrop {
		position: fixed;
		inset: 0;
		z-index: 60;
		background: none;
		border: none;
		cursor: default;
	}
	.ss-results {
		position: absolute;
		top: calc(100% + 6px);
		left: 0;
		right: 0;
		z-index: 61;
		list-style: none;
		margin: 0;
		padding: 6px;
		max-height: min(60vh, 420px);
		overflow-y: auto;
		background: var(--color-white);
		border: 1px solid var(--color-border);
		border-radius: 10px;
		box-shadow: 0 10px 30px rgba(0, 0, 0, 0.16);
	}
	.ss-result {
		width: 100%;
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 10px;
		padding: 9px 10px;
		border: none;
		border-radius: 7px;
		background: none;
		font-family: var(--font-sans);
		font-size: 15px;
		text-align: left;
		color: var(--color-fg);
		cursor: pointer;
	}
	.ss-result:hover { background: var(--color-gray-100); }
	.ss-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.ss-kind {
		flex: none;
		font-size: 0.62rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		padding: 1px 6px;
		border-radius: 999px;
		line-height: 1.5;
	}
	.ss-kind.kind-book { background: #eaf2fb; color: #2f6ea8; }
	.ss-kind.kind-author { background: var(--color-gray-100); color: var(--color-fg-light); }
	.ss-none {
		margin: 0;
		padding: 8px 10px;
		font-family: var(--font-sans);
		font-size: var(--text-sm);
		color: var(--color-fg-light);
	}
</style>
