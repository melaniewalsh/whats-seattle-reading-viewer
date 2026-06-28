<script>
	// Viewer.svelte
	// =============
	// Search an author -> see a line of their total checkouts -> tick individual
	// titles to chart them. You can also:
	//   • "Bundle" the ticked titles into ONE line (treat every edition / format
	//     of a work as a single thing), and
	//   • hide the author-total line to show only what you've ticked.
	import { onMount } from "svelte";
	import { base } from "$app/paths";
	import debounce from "lodash.debounce";
	import LineChart from "$components/LineChart.svelte";

	// Colors for individual title lines. The author-total line is ink-black,
	// and a bundle is drawn in the accent red.
	const TITLE_COLORS = [
		"#e3120b", "#1f7a4d", "#e58a00", "#6a4c93",
		"#0b7285", "#c2255c", "#5c940d", "#7048e8"
	];
	const BUNDLE_COLOR = "#e3120b";
	const INK = "var(--color-fg)";

	let authors = $state([]); // the search index
	let months = $state([]); // the shared month axis (from meta.json)
	let query = $state("");
	let results = $state([]);
	let current = $state(null); // the loaded author object

	// View controls
	let selectedIdxs = $state([]); // indices into current.titles that are ticked
	let titleFilter = $state(""); // text filter for the title list
	let bundleMode = $state(false); // sum ticked titles into one line?
	let showAuthorLine = $state(true); // show the author-total line?
	let bundleName = $state(""); // optional user-typed name for the bundle

	onMount(async () => {
		// Load the search index and the shared month axis together.
		const [a, m] = await Promise.all([
			fetch(`${base}/data/authors.json`).then((r) => r.json()),
			fetch(`${base}/data/meta.json`).then((r) => r.json())
		]);
		authors = a;
		months = m.months;
		// Show the most-borrowed author by default, so the page isn't empty.
		if (authors.length) await selectAuthor(authors[0]);
	});

	// Expand a sparse series ([[monthIndex, count], ...]) into a full array of
	// length months.length, filling the gaps with 0.
	function densify(sparse) {
		const arr = new Array(months.length).fill(0);
		for (const [i, v] of sparse) arr[i] = v;
		return arr;
	}

	// Filter the author list as the user types (debounced so it stays snappy).
	const runSearch = debounce((q) => {
		const needle = q.trim().toLowerCase();
		results =
			needle.length < 2
				? []
				: authors.filter((a) => a.name.toLowerCase().includes(needle)).slice(0, 25);
	}, 120);
	$effect(() => runSearch(query));

	async function selectAuthor(a) {
		const res = await fetch(`${base}/data/authors/${a.slug}.json`);
		const data = await res.json();
		// expand the sparse series the ETL produced into full arrays
		data.months = months;
		data.series = densify(data.series);
		data.titles.forEach((t) => {
			t.series = densify(t.series);
			t.format = t.fmt; // the ETL stores the short field name "fmt"
		});
		current = data;
		// reset the controls for the new author
		selectedIdxs = [];
		titleFilter = "";
		bundleMode = false;
		showAuthorLine = true;
		bundleName = "";
		query = "";
		results = [];
	}

	// Short label shown in a title's format badge.
	function formatLabel(f) {
		return { ebook: "ebook", audiobook: "audio", print: "print", other: "other" }[f] || f;
	}

	function toggleTitle(idx) {
		selectedIdxs = selectedIdxs.includes(idx)
			? selectedIdxs.filter((i) => i !== idx)
			: [...selectedIdxs, idx];
	}

	// How many titles of each format this author has (for the quick-pick buttons).
	const formatCounts = $derived.by(() => {
		const c = { ebook: 0, audiobook: 0, print: 0 };
		current?.titles.forEach((t) => {
			if (c[t.format] !== undefined) c[t.format]++;
		});
		return c;
	});

	// Select the top N titles by checkouts — optionally only of one format.
	// Titles are already sorted most-borrowed first, so we just take the first matches.
	function selectTop(formatKey, n = 10) {
		if (!current) return;
		const idxs = [];
		for (let i = 0; i < current.titles.length && idxs.length < n; i++) {
			if (!formatKey || current.titles[i].format === formatKey) idxs.push(i);
		}
		selectedIdxs = idxs;
	}

	// The title list, filtered by the little search box (keeps original index).
	const filteredTitles = $derived(
		current
			? current.titles
					.map((t, idx) => ({ ...t, idx }))
					.filter(
						(t) => !titleFilter.trim() || t.title.toLowerCase().includes(titleFilter.trim().toLowerCase())
					)
			: []
	);

	// Add up the series of every ticked title, month by month (the "bundle").
	function sumSelected() {
		return current.months.map((_, i) =>
			selectedIdxs.reduce((acc, idx) => acc + current.titles[idx].series[i], 0)
		);
	}

	// Name the bundle after its first title in the list (titles are sorted
	// most-checked-out first), plus a count of the rest.
	const bundleLabel = $derived.by(() => {
		if (!current || !selectedIdxs.length) return "";
		const firstIdx = Math.min(...selectedIdxs);
		const firstTitle = current.titles[firstIdx].title;
		const extra = selectedIdxs.length - 1;
		return extra > 0 ? `${firstTitle}  +${extra} more` : firstTitle;
	});

	// The name actually shown: whatever the user typed, otherwise the auto label.
	const effectiveBundleLabel = $derived(bundleName.trim() || bundleLabel);

	// When the author line is toggled off, use the bundle name as the chart's title.
	const plotTitle = $derived(
		!showAuthorLine && bundleMode && selectedIdxs.length ? effectiveBundleLabel : ""
	);

	// What the chart draws.
	const chartSeries = $derived.by(() => {
		if (!current) return [];
		const out = [];

		if (showAuthorLine) {
			out.push({ label: "Author total", color: INK, values: current.series, width: 2.75 });
		}

		if (selectedIdxs.length) {
			if (bundleMode) {
				// every ticked edition/variant collapsed into one line
				out.push({
					label: effectiveBundleLabel,
					color: BUNDLE_COLOR,
					values: sumSelected(),
					width: 2.75
				});
			} else {
				selectedIdxs.forEach((idx, n) => {
					out.push({
						label: current.titles[idx].title,
						color: TITLE_COLORS[n % TITLE_COLORS.length],
						values: current.titles[idx].series,
						width: 1.9
					});
				});
			}
		}

		// never leave the chart empty: fall back to the author line
		if (out.length === 0) {
			out.push({ label: "Author total", color: INK, values: current.series, width: 2.75 });
		}
		return out;
	});
</script>

<div class="viewer">
	<!-- ===== Search ===== -->
	<div class="search">
		<input
			type="search"
			placeholder="Search an author — try Octavia Butler, or Mo Willems"
			bind:value={query}
			autocomplete="off"
		/>
		{#if results.length}
			<ul class="results">
				{#each results as a}
					<li>
						<button onclick={() => selectAuthor(a)}>
							<span>{a.name}</span>
							<span class="count">{a.total.toLocaleString()}</span>
						</button>
					</li>
				{/each}
			</ul>
		{/if}
	</div>

	<!-- ===== Selected author ===== -->
	{#if current}
		<div class="author">
			<h2>{current.name}</h2>
			<p class="meta">
				{current.total.toLocaleString()} checkouts · {current.titles.length} titles
			</p>

			{#if plotTitle}
				<p class="plot-title">{plotTitle}</p>
			{/if}
			<LineChart months={current.months} series={chartSeries} />

			<!-- legend -->
			<ul class="legend">
				{#each chartSeries as s}
					<li><span class="sw" style="background:{s.color}"></span>{s.label}</li>
				{/each}
			</ul>

			<!-- options -->
			<div class="options">
				<button
					class="toggle toggle-bundle"
					class:active={bundleMode}
					aria-pressed={bundleMode}
					disabled={selectedIdxs.length === 0}
					onclick={() => (bundleMode = !bundleMode)}
				>
					{bundleMode ? "✓ " : ""}Bundle selected
				</button>
				<button
					class="toggle toggle-author"
					class:active={showAuthorLine}
					aria-pressed={showAuthorLine}
					onclick={() => (showAuthorLine = !showAuthorLine)}
				>
					{showAuthorLine ? "👁 Hide" : "＋ Show"} author total trend
				</button>
				{#if selectedIdxs.length}
					<button class="clear" onclick={() => (selectedIdxs = [])}>
						Clear {selectedIdxs.length} selected
					</button>
				{/if}
			</div>

			<!-- rename the bundle (used for both its legend entry and, when the
			     author line is hidden, the chart title) -->
			{#if bundleMode && selectedIdxs.length}
				<div class="bundle-name">
					<label for="bundle-name-input">Name this bundle</label>
					<input
						id="bundle-name-input"
						type="text"
						bind:value={bundleName}
						placeholder={bundleLabel}
					/>
					{#if bundleName.trim()}
						<button class="reset-name" onclick={() => (bundleName = "")}>reset</button>
					{/if}
				</div>
			{/if}

			<!-- title list with filter -->
			<div class="titles">
				<!-- quick-pick: select this author's top 10 titles, by format or overall -->
				<div class="quick">
					<span class="quick-label">Quick-pick top 10:</span>
					<button class="chip" onclick={() => selectTop(null)}>all titles</button>
					{#if formatCounts.ebook}
						<button class="chip" onclick={() => selectTop("ebook")}>ebooks</button>
					{/if}
					{#if formatCounts.audiobook}
						<button class="chip" onclick={() => selectTop("audiobook")}>audiobooks</button>
					{/if}
					{#if formatCounts.print}
						<button class="chip" onclick={() => selectTop("print")}>print</button>
					{/if}
				</div>
				<input
					class="title-filter"
					type="search"
					placeholder="Filter titles…"
					bind:value={titleFilter}
					autocomplete="off"
				/>
				<ul class="title-list">
					{#each filteredTitles as t}
						<li>
							<label class:selected={selectedIdxs.includes(t.idx)}>
								<input
									type="checkbox"
									checked={selectedIdxs.includes(t.idx)}
									onchange={() => toggleTitle(t.idx)}
								/>
								<span class="t-name">{t.title}</span>
								<span class="badge badge-{t.format}">{formatLabel(t.format)}</span>
								<span class="t-count">{t.total.toLocaleString()}</span>
							</label>
						</li>
					{/each}
				</ul>
			</div>
		</div>
	{:else}
		<p class="hint">Start typing an author's name above.</p>
	{/if}
</div>

<style>
	.viewer {
		max-width: 720px;
		margin: 0 auto;
	}

	/* The starter's reset hides native checkboxes (appearance: none); turn them
	   back on so the ticked/unticked state is clearly visible. */
	.viewer input[type="checkbox"] {
		appearance: auto;
		-webkit-appearance: auto;
		width: 17px;
		height: 17px;
		accent-color: var(--color-fg);
		background: none;
		flex: none;
		cursor: pointer;
	}

	/* search box */
	.search {
		position: relative;
	}
	.search input {
		width: 100%;
		padding: 14px 16px;
		font-family: var(--font-sans);
		font-size: 1.05rem;
		background: var(--color-input-bg);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
	}
	.search input:focus {
		outline: 2px solid var(--color-focus);
		outline-offset: 1px;
	}
	.results {
		list-style: none;
		margin: 6px 0 0;
		padding: 6px;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-white);
		max-height: 340px;
		overflow-y: auto;
		position: absolute;
		width: 100%;
		z-index: var(--z-top);
		box-shadow: 0 6px 20px rgba(0, 0, 0, 0.08);
	}
	.results button {
		width: 100%;
		display: flex;
		justify-content: space-between;
		gap: 12px;
		padding: 9px 12px;
		background: none;
		border: none;
		border-radius: var(--radius-sm);
		font-family: var(--font-sans);
		font-size: 0.95rem;
		text-align: left;
		cursor: pointer;
		color: var(--color-fg);
	}
	.results button:hover {
		background: var(--color-gray-100);
	}
	.results .count {
		color: var(--color-fg-light);
		font-variant-numeric: tabular-nums;
	}

	/* selected author */
	.author {
		margin-top: 36px;
	}
	.author h2 {
		font-family: var(--font-serif);
		font-size: 2rem;
		line-height: 1.1;
		margin: 0;
	}
	.author .meta {
		font-family: var(--font-sans);
		color: var(--color-fg-light);
		margin: 4px 0 20px;
	}
	.plot-title {
		font-family: var(--font-serif);
		font-size: 1.3rem;
		line-height: 1.2;
		text-align: center;
		margin: 0 0 8px;
	}

	/* legend */
	.legend {
		list-style: none;
		display: flex;
		flex-wrap: wrap;
		gap: 6px 18px;
		margin: 12px 0 0;
		padding: 0;
		font-family: var(--font-sans);
		font-size: 0.82rem;
	}
	.legend li {
		display: flex;
		align-items: center;
		gap: 6px;
		max-width: 320px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.legend .sw {
		width: 12px;
		height: 12px;
		border-radius: 2px;
		flex: none;
	}

	/* options row */
	.options {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 10px;
		margin: 18px 0 14px;
		font-family: var(--font-sans);
		font-size: 0.9rem;
	}
	.toggle {
		font-family: var(--font-sans);
		font-size: 0.88rem;
		font-weight: 600;
		padding: 8px 16px;
		border-radius: 999px;
		border: 1.5px solid var(--color-border);
		background: var(--color-white);
		color: var(--color-fg);
		cursor: pointer;
		transition: background 0.12s, border-color 0.12s, color 0.12s;
	}
	.toggle:hover:not(:disabled) {
		border-color: var(--color-fg-light);
	}
	.toggle:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}
	/* "on" states get a filled, colored background */
	.toggle-author.active {
		background: var(--color-fg);
		border-color: var(--color-fg);
		color: var(--color-white);
	}
	.toggle-bundle.active {
		background: #e3120b;
		border-color: #e3120b;
		color: var(--color-white);
	}
	.bundle-name {
		display: flex;
		align-items: center;
		gap: 10px;
		margin: 0 0 16px;
		font-family: var(--font-sans);
		font-size: 0.85rem;
	}
	.bundle-name label {
		font-weight: 600;
		white-space: nowrap;
	}
	.bundle-name input {
		flex: 1;
		min-width: 0;
		padding: 8px 12px;
		font-family: var(--font-sans);
		font-size: 0.9rem;
		background: var(--color-input-bg);
		border: 1.5px solid var(--color-border);
		border-radius: var(--radius-sm);
	}
	.bundle-name input:focus {
		outline: none;
		border-color: #e3120b;
	}
	.bundle-name .reset-name {
		background: none;
		border: none;
		color: var(--color-fg-light);
		text-decoration: underline;
		cursor: pointer;
		font-family: var(--font-sans);
		font-size: 0.82rem;
	}

	.options .clear {
		margin-left: auto;
		background: none;
		border: none;
		color: var(--color-fg-light);
		text-decoration: underline;
		cursor: pointer;
		font-family: var(--font-sans);
		font-size: 0.85rem;
	}

	/* quick-pick chips */
	.quick {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 8px;
		margin-bottom: 10px;
		font-family: var(--font-sans);
	}
	.quick-label {
		font-size: 0.82rem;
		font-weight: 600;
		color: var(--color-fg-light);
	}
	.chip {
		font-family: var(--font-sans);
		font-size: 0.82rem;
		padding: 4px 12px;
		border-radius: 999px;
		border: 1px solid var(--color-border);
		background: var(--color-white);
		color: var(--color-fg);
		cursor: pointer;
	}
	.chip:hover {
		background: var(--color-gray-100);
		border-color: var(--color-fg-light);
	}

	/* title list */
	.title-filter {
		width: 100%;
		padding: 9px 12px;
		font-family: var(--font-sans);
		font-size: 0.9rem;
		background: var(--color-input-bg);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		margin-bottom: 8px;
	}
	.title-list {
		list-style: none;
		margin: 0;
		padding: 0;
		max-height: 280px;
		overflow-y: auto;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
	}
	.title-list li + li label {
		border-top: 1px solid var(--color-gray-100);
	}
	.title-list label {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 9px 12px;
		cursor: pointer;
		font-family: var(--font-sans);
		font-size: 0.9rem;
	}
	.title-list label:hover {
		background: var(--color-gray-100);
	}
	.title-list label.selected {
		background: var(--color-gray-100);
		font-weight: 600;
	}
	.title-list .t-name {
		flex: 1;
		min-width: 0;
	}
	.title-list .t-count {
		color: var(--color-fg-light);
		font-variant-numeric: tabular-nums;
	}

	/* format badges */
	.badge {
		flex: none;
		font-size: 0.66rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		padding: 2px 8px;
		border-radius: 999px;
		white-space: nowrap;
	}
	.badge-ebook {
		background: #e7f0ff;
		color: #1c4ed8;
	}
	.badge-audiobook {
		background: #f3eafe;
		color: #7048e8;
	}
	.badge-print {
		background: #eaf6ee;
		color: #1f7a4d;
	}
	.badge-other {
		background: var(--color-gray-100);
		color: var(--color-fg-light);
	}
	.hint {
		font-family: var(--font-sans);
		color: var(--color-fg-light);
		text-align: center;
		margin-top: 28px;
	}
</style>
