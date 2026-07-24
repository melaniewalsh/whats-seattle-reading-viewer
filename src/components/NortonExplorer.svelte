<script>
	import { onMount } from "svelte";
	import LineChart from "$components/StackedAreaChart.svelte";
	import { getNortonData } from "$utils/nortonData.js";
	import { titleCase } from "$utils/titleCase.js";
	import { compactNumber } from "$utils/format.js";

	let data = $state(null);
	let loadError = $state("");
	let kind = $state("author"); // "author" | "title"
	let selAuthor = $state(null);
	let selTitle = $state(null);
	let query = $state("");
	let nortonOnly = $state(false);
	let chartWrap = $state(null);

	onMount(async () => {
		try {
			data = await getNortonData();
			selAuthor = data.authors.find((a) => /octavia/i.test(a.name)) || data.authors[0];
		} catch (e) {
			loadError = "Couldn't load the Norton checkout data. Please try again.";
		}
	});

	const nameOf = (t) => titleCase(t.title);
	const results = $derived.by(() => {
		if (!data) return [];
		const q = query.trim().toLowerCase();
		if (q.length < 1) return [];
		return kind === "author"
			? data.authors.filter((a) => a.name.toLowerCase().includes(q)).slice(0, 8)
			: data.titles.filter((t) => t.title.toLowerCase().includes(q)).slice(0, 8);
	});
	const current = $derived(kind === "author" ? selAuthor : selTitle);
	const heading = $derived(current ? (kind === "author" ? current.name : nameOf(current)) : "");
	const subhead = $derived.by(() => {
		if (!current) return "";
		if (kind === "author") return `${compactNumber(current.total)} checkouts · ${current.titleIdxs.length} works`;
		return `by ${current.author} · ${compactNumber(current.total)} checkouts`;
	});
	const series = $derived(current ? [{ label: heading, color: "#3f88cc", values: current.values }] : []);

	const topAuthors = $derived(data ? (nortonOnly ? data.authors.filter((a) => a.norton) : data.authors) : []);
	const topTitles = $derived(data ? (nortonOnly ? data.titles.filter((t) => t.norton) : data.titles) : []);
	// A handful of well-known names to seed exploration.
	const suggestions = $derived(data ? data.authors.slice(0, 7) : []);

	function pickAuthor(a) { kind = "author"; selAuthor = a; query = ""; scrollToChart(); }
	function pickTitle(t) { kind = "title"; selTitle = t; query = ""; scrollToChart(); }
	function scrollToChart() {
		requestAnimationFrame(() => chartWrap?.scrollIntoView?.({ block: "nearest", behavior: "smooth" }));
	}
</script>

<div class="norton">
	{#if loadError}
		<p class="ne-error">{loadError}</p>
	{:else if !data}
		<p class="ne-loading"><span class="ne-spinner" aria-hidden="true"></span>Loading two decades of checkout data…</p>
	{:else}
		<!-- Search + select -->
		<div class="ne-controls">
			<label class="ne-field">
				<span>Search by</span>
				<select bind:value={kind} onchange={() => (query = "")}>
					<option value="author">Author</option>
					<option value="title">Work</option>
				</select>
			</label>
			<label class="ne-field grow">
				<span>Find {kind === "author" ? "an author" : "a work"}</span>
				<div class="ne-search">
					<input type="search" placeholder={kind === "author" ? "Search an author" : "Search a work"} bind:value={query} autocomplete="off" />
					{#if results.length}
						<ul class="ne-results">
							{#each results as r}
								<li>
									{#if kind === "author"}
										<button onclick={() => pickAuthor(r)}><span>{r.name}</span><span class="ne-count">{compactNumber(r.total)}</span></button>
									{:else}
										<button onclick={() => pickTitle(r)}><span class="ne-rtitle">{nameOf(r)}</span><span class="ne-count">{r.author}</span></button>
									{/if}
								</li>
							{/each}
						</ul>
					{:else if query.trim().length >= 1}
						<p class="ne-noresults">No {kind === "author" ? "authors" : "works"} found for “{query.trim()}”.</p>
					{/if}
				</div>
			</label>
		</div>
		<div class="ne-pills">
			{#each suggestions as a}
				<button class="ne-pill" onclick={() => pickAuthor(a)}>{a.name}</button>
			{/each}
		</div>

		<!-- Selected trend -->
		{#if current}
			<div class="ne-chartblock" bind:this={chartWrap}>
				<h3 class="ne-heading">{heading}</h3>
				<p class="ne-sub">{subhead}</p>
				<LineChart months={data.months} {series} mode="line" />
			</div>
		{/if}

		<!-- Top authors / titles -->
		<div class="ne-toprow">
			<label class="ne-toggle"><input type="checkbox" bind:checked={nortonOnly} /> Only works in the Norton Anthology</label>
		</div>
		<div class="ne-tables">
			<div class="ne-table">
				<h4 class="ne-th">Most-borrowed authors <span class="ne-th-n">{topAuthors.length}</span></h4>
				<ol class="ne-list">
					{#each topAuthors as a}
						<li><button onclick={() => pickAuthor(a)}><span class="ne-name">{a.name}</span><span class="ne-num">{compactNumber(a.total)}</span></button></li>
					{/each}
				</ol>
			</div>
			<div class="ne-table">
				<h4 class="ne-th">Most-borrowed works <span class="ne-th-n">{topTitles.length}</span></h4>
				<ol class="ne-list">
					{#each topTitles as t}
						<li><button onclick={() => pickTitle(t)}><span class="ne-name">{nameOf(t)}<span class="ne-by">·&nbsp;{t.author}</span></span><span class="ne-num">{compactNumber(t.total)}</span></button></li>
					{/each}
				</ol>
			</div>
		</div>
	{/if}
</div>

<style>
	.norton { font-family: var(--font-sans); margin: 8px 0 0; }
	.ne-loading, .ne-error { font-family: var(--font-sans); color: var(--color-fg-light); display: flex; align-items: center; gap: 10px; padding: 30px 0; }
	.ne-spinner { width: 16px; height: 16px; border: 2px solid var(--color-border); border-top-color: var(--color-fg-light); border-radius: 50%; animation: ne-spin 0.8s linear infinite; }
	@keyframes ne-spin { to { transform: rotate(360deg); } }

	.ne-controls { display: flex; align-items: flex-end; gap: 12px; }
	.ne-field { flex: 1; min-width: 130px; display: flex; flex-direction: column; gap: 4px; font-family: var(--font-sans); font-size: 0.78rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; color: var(--color-fg-light); }
	.ne-field.grow { flex: 2; }
	.ne-field select, .ne-search input { width: 100%; box-sizing: border-box; font-family: var(--font-sans); font-size: 0.95rem; font-weight: 500; text-transform: none; letter-spacing: 0; color: var(--color-fg); padding: 9px 12px; border: 1px solid var(--color-border); border-radius: 8px; background: var(--color-white); outline: none; }
	.ne-search { position: relative; }
	.ne-search input:focus { border-color: #3f88cc; box-shadow: 0 0 0 3px rgba(63,136,204,0.15); }
	.ne-results { list-style: none; margin: 6px 0 0; padding: 6px; border: 1px solid var(--color-border); border-radius: var(--radius-md); background: var(--color-white); max-height: 320px; overflow-y: auto; position: absolute; width: 100%; z-index: 20; box-shadow: 0 6px 20px rgba(0,0,0,0.08); }
	.ne-results button { width: 100%; display: flex; justify-content: space-between; gap: 12px; padding: 9px 12px; background: none; border: none; border-radius: var(--radius-sm); font-family: var(--font-sans); font-size: 0.95rem; font-weight: 500; text-align: left; cursor: pointer; color: var(--color-fg); }
	.ne-results button:hover { background: var(--color-gray-100); }
	.ne-count { color: var(--color-fg-light); font-variant-numeric: tabular-nums; white-space: nowrap; }
	.ne-rtitle { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.ne-noresults { position: absolute; margin: 6px 0 0; padding: 9px 12px; font-size: 0.9rem; color: var(--color-fg-light); }

	.ne-pills { display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0 0; }
	.ne-pill { font-family: var(--font-sans); font-size: 0.82rem; font-weight: 500; color: var(--color-fg); background: var(--color-white); border: 1px solid var(--color-border); border-radius: 999px; padding: 5px 13px; cursor: pointer; }
	.ne-pill:hover { border-color: #b6c2ce; }

	.ne-chartblock { margin: 30px 0 10px; }
	.ne-heading { font-family: var(--font-display, var(--font-serif)); font-size: clamp(1.6rem, 3.2vw, 2.2rem); font-weight: 700; color: var(--color-fg); margin: 0; line-height: 1.1; }
	.ne-sub { font-family: var(--font-sans); font-size: 0.95rem; color: var(--color-fg-light); margin: 4px 0 14px; }

	.ne-toprow { margin: 26px 0 10px; }
	.ne-toggle { display: inline-flex; align-items: center; gap: 8px; font-size: 0.9rem; color: var(--color-fg); cursor: pointer; }
	.ne-toggle input { width: 15px; height: 15px; accent-color: var(--color-fg); cursor: pointer; }
	.ne-tables { display: grid; grid-template-columns: minmax(0, 1fr); gap: 30px; }
	@media (max-width: 640px) { .ne-field.grow { flex: 1.4; } }
	.ne-th { font-family: var(--font-display, var(--font-serif)); font-size: 1.15rem; font-weight: 700; color: var(--color-fg); margin: 0 0 6px; padding-bottom: 6px; border-bottom: 2px solid var(--color-fg); }
	.ne-th-n { font-family: var(--font-sans); font-size: 0.72rem; font-weight: 700; color: var(--color-fg-light); vertical-align: middle; margin-left: 4px; }
	.ne-list { list-style: none; margin: 0; padding: 0 4px 0 0; counter-reset: ne; max-height: 440px; overflow-y: auto; }
	.ne-list li { counter-increment: ne; }
	.ne-list button { width: 100%; display: flex; justify-content: space-between; align-items: baseline; gap: 12px; padding: 7px 4px 7px 26px; position: relative; background: none; border: none; border-top: 1px solid var(--color-gray-100); font-family: var(--font-sans); font-size: 0.92rem; text-align: left; cursor: pointer; color: var(--color-fg); }
	.ne-list li:first-child button { border-top: none; }
	.ne-list button::before { content: counter(ne); position: absolute; left: 0; top: 7px; font-size: 0.78rem; font-variant-numeric: tabular-nums; color: var(--color-fg-light); }
	.ne-list button:hover .ne-name { color: #3f88cc; }
	.ne-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.ne-by { color: var(--color-fg-light); margin-left: 5px; }
	.ne-num { flex: none; color: var(--color-fg-light); font-variant-numeric: tabular-nums; white-space: nowrap; }
</style>
