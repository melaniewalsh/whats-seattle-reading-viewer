<script>
	// The site's search field: a live autocomplete over authors AND books.
	//
	// With `multi` (the Checkout Trends page), it works like the Google Books
	// Ngram Viewer: the field keeps what's on the chart ("Sally Rooney"), and a
	// comma adds another ("Sally Rooney, Colleen Hoover") -- the suggestions are
	// for whatever comes after the last comma. Enter (or a suggestion) hands the
	// whole list to onSubmit(text, lastPick).
	import { searchAll } from "$components/db.js";
	import { cleanTitleForDisplay } from "$utils/workTitle.js";
	import { displayName } from "$utils/displayName.js";

	let {
		onPick = () => {},
		onSubmit = null,
		multi = false,
		value = "",
		selectOnFocus = false, // a starter value: clicking in selects it, so typing replaces it
		placeholder = "Search authors or books"
	} = $props();

	let q = $state("");
	let results = $state([]);
	let open = $state(false);
	let flash = $state(false);
	let inputEl;
	let timer;
	let justFocused = false;

	// The page tells us what's on the chart; show it (unless mid-typing).
	$effect(() => {
		const v = value;
		if (document.activeElement !== inputEl) q = v;
	});

	export const labelOf = (r) => (r.kind === "work" ? cleanTitleForDisplay(r.title) || r.title : displayName(r.name));
	// In the list: two books that would read the same ("Brave New World" twice,
	// the novel and a BBC radio drama of it) show their full titles instead.
	const listLabels = $derived.by(() => {
		const key = (r) => `${r.kind}|${labelOf(r)}|${r.author ?? ""}`;
		const seen = new Map();
		for (const r of results) seen.set(key(r), (seen.get(key(r)) || 0) + 1);
		return results.map((r) => (r.kind === "work" && seen.get(key(r)) > 1 ? r.title : labelOf(r)));
	});
	// The part being typed: after the last comma (multi), else everything.
	const segment = () => (multi ? q.split(",").pop() : q).trim();
	const hasList = () => multi && q.split(",").filter((t) => t.trim()).length > 1;

	function onInput() {
		open = true;
		clearTimeout(timer);
		const needle = segment();
		timer = setTimeout(async () => {
			if (needle.length < 2) { results = []; return; }
			try { results = await searchAll(needle, 8); } catch { results = []; }
		}, 140);
	}
	function pick(res) {
		open = false;
		results = [];
		if (multi) {
			// Swap the typed bit for the chosen name, and hand over the list.
			const parts = q.split(",");
			parts[parts.length - 1] = (parts.length > 1 ? " " : "") + labelOf(res);
			q = parts.join(",");
			if (onSubmit && hasList()) { inputEl?.blur(); return onSubmit(q, res); }
			return onPick(res);
		}
		q = "";
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
		if (e.key === "Escape") { open = false; return; }
		if (e.key !== "Enter") return;
		e.preventDefault();
		const seg = segment();
		// A half-typed name with suggestions showing: take the top one.
		const typedNew = seg && results.length && open && !results.some((r) => labelOf(r).toLowerCase() === seg.toLowerCase());
		if (typedNew) return pick(results[0]);
		open = false;
		// Let go of the field so it can show the list as the page settles it
		// (proper spellings: "wuthering heights" -> "Wuthering Heights").
		if (multi && onSubmit && q.trim()) { inputEl?.blur(); return onSubmit(q, null); }
		if (results.length) pick(results[0]);
	}
	// Put the cursor here (at the end); with ring=true, also pulse a blue ring
	// around the field so it's clear where to type. `text` replaces the value.
	export function focus(ring = false, text = null) {
		if (text != null) q = text;
		inputEl?.focus({ preventScroll: true });
		try { inputEl?.setSelectionRange(q.length, q.length); } catch {}
		if (!ring) return;
		flash = false;
		setTimeout(() => (flash = true), 20);
		setTimeout(() => (flash = false), 1900);
	}
</script>

<!-- A real search form (role="search", search keyboard hints) so phones treat
     it as a search box, not a sign-in or address form: iOS then mostly skips
     its password / card / address AutoFill bar. -->
<form class="ss" class:flash role="search" onsubmit={(e) => e.preventDefault()}>
	<svg class="ss-ic" viewBox="0 0 20 20" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
		<circle cx="9" cy="9" r="6" /><line x1="13.5" y1="13.5" x2="18" y2="18" />
	</svg>
	<input
		bind:this={inputEl}
		class="ss-input"
		type="search"
		{placeholder}
		aria-label="Search authors or books"
		name="site-search"
		autocomplete="off"
		autocorrect="off"
		autocapitalize="off"
		inputmode="search"
		enterkeyhint="search"
		data-1p-ignore
		data-lpignore="true"
		data-form-type="other"
		spellcheck="false"
		bind:value={q}
		oninput={onInput}
		onfocus={() => {
			open = results.length > 0;
			if (selectOnFocus && q === value) { justFocused = true; setTimeout(() => inputEl?.select(), 0); }
		}}
		onmouseup={(e) => {
			// The click that focused the field would otherwise drop the caret
			// in and undo the selection.
			if (justFocused) { e.preventDefault(); justFocused = false; }
		}}
		onkeydown={onKey}
	/>
	{#if q}
		<button type="button" class="ss-clear" aria-label="Clear search" onclick={clear}>×</button>
	{/if}
	{#if open && (results.length || segment().length >= 2)}
		<button type="button" class="ss-backdrop" aria-label="Close search" onclick={() => (open = false)}></button>
		<ul class="ss-results" role="listbox">
			{#each results as r, k}
				<li>
					<button type="button" class="ss-result" class:ss-sub={!!r.under} onclick={() => pick(r)}>
						<span class="ss-name">{listLabels[k]}{#if r.kind === "work" && !r.under && r.author}<span class="ss-by">{" · "}{displayName(r.author)}</span>{/if}</span>
						<span class="ss-kind {r.kind === 'work' ? 'kind-book' : 'kind-author'}">{r.kind === "work" ? "Book" : "Author"}</span>
					</button>
				</li>
			{/each}
			{#if !results.length}
				<li><p class="ss-none">Nothing found for “{segment()}”.</p></li>
			{/if}
		</ul>
	{/if}
</form>

<style>
	/* A plain white field with a crisp edge; a blue ring while typing. */
	.ss {
		position: relative;
		margin: 0;
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
		font-size: 16px; /* any smaller and iPhones zoom in on focus */
		font-weight: 400;
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
	/* An author's own books, listed under them: indented, a little smaller. */
	.ss-sub { padding: 6px 10px 6px 26px; font-size: 14px; color: var(--color-fg-light); }
	.ss-sub .ss-name { font-style: italic; }
	.ss-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	/* Which author a suggested book is by ("Ulysses · James Joyce"). */
	.ss-by { color: var(--color-fg-light); font-size: 0.92em; }
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
