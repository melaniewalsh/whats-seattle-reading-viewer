<script>
    // StackedAreaChart.svelte
	import { scaleLinear, area as d3area, line as d3line, max as d3max } from 'd3';
	import { getMonths, searchAuthors, getAuthor, densify } from './db.js';

	// Both props are now optional. Pass explicitly for pre-fetched/
	// embedded/test use.
	// `mode` picks the chart type: 'area' stacks the series by title, 'line'
	// overlays each series as its own (unstacked) line -- used for the default
	// single "author's total checkouts" view.
	let {
		months: monthsProp = null,
		series: seriesProp = null,
		slug: initialSlug = null,
		topTitles = 8,
		mode = 'area'
	} = $props();

	// Measured from the container (bind:clientWidth) so the chart fits any
	// screen -- without this the SVG renders at a fixed 720px and pushes the
	// whole page sideways on phones.
	let width = $state(720);
	const height = $derived(width < 520 ? 300 : 380);
	const margin = { top: 16, right: 16, bottom: 28, left: 44 };

	const PALETTE = [
		'#4e79a7', '#f28e2b', '#e15759', '#76b7b2', '#59a14f',
		'#edc948', '#b07aa1', '#ff9da7', '#9c755f', '#bab0ac'
	];

	let loadedMonths = $state([]);
	let query = $state('');
	let searchResults = $state([]);
	// svelte-ignore state_referenced_locally: initialSlug only
	// seeds the starting value, activeSlug is the source after that
	let activeSlug = $state(initialSlug);
	let activeAuthor = $state(null);
	let dbLoading = $state(false);
	let dbError = $state(null);
	let searchTimer;

	// Shared x-axis: one query, cached in db.js, reused by every instance.
	$effect(() => {
		if (monthsProp) return;
		getMonths()
			.then((m) => (loadedMonths = m))
			.catch((e) => (dbError = e?.message ?? String(e)));
	});

	// Shows before anyone has searched: the top authors by
	// total checkouts (same "no query -> top N" behavior searchAuthors
	// uses server-side). Auto-select the #1 author.
	$effect(() => {
		if (seriesProp || activeSlug) return;
		searchAuthors('', 10)
			.then((r) => {
				searchResults = r;
				if (r.length > 0) activeSlug = r[0].slug;
			})
			.catch((e) => (dbError = e?.message ?? String(e)));
	});

	// Load the selected author's own series + qualifying titles the moment
	// activeSlug changes. 
	// One query for the author row, one for their titles (see db.js:getAuthor)
	$effect(() => {
		if (seriesProp) return;
		const slugToLoad = activeSlug;
		if (!slugToLoad) return;
		dbLoading = true;
		dbError = null;
		getAuthor(slugToLoad)
			.then((a) => {
				activeAuthor = a;
				dbLoading = false;
			})
			.catch((e) => {
				dbError = e?.message ?? String(e);
				dbLoading = false;
			});
	});

	function onSearchInput(event) {
		query = event.target.value;
		clearTimeout(searchTimer);
		searchTimer = setTimeout(async () => {
			try {
				searchResults = await searchAuthors(query, 12);
			} catch (e) {
				dbError = e?.message ?? String(e);
			}
		}, 200);
	}

	function selectAuthor(slug) {
		activeSlug = slug;
		searchResults = [];
		query = '';
	}

	// Turn the loaded author into stacked layers: one per qualifying title,
	// plus a catch-all "Other titles" layer covering the gap between the
	// author's real total and the shown titles since build_data.py only keeps
	// per-title series for titles checked out >= MIN_TITLE_CHECKOUTS times,
	// so without this the stack would silently under-count the long tail.
	const derivedSeries = $derived.by(() => {
		if (!activeAuthor || !loadedMonths.length) return [];
		const monthCount = loadedMonths.length;
		const shown = activeAuthor.titles.slice(0, topTitles);
		const layers = shown.map((t, i) => ({
			label: t.title,
			values: densify(t.series, monthCount),
			color: PALETTE[i % PALETTE.length],
			groupIndex: 0
		}));
		const authorTotals = densify(activeAuthor.series, monthCount);
		const otherValues = authorTotals.map((total, i) => {
			const shownSum = layers.reduce((sum, l) => sum + l.values[i], 0);
			return Math.max(0, total - shownSum);
		});
		if (otherValues.some((v) => v > 0)) {
			layers.push({ label: 'Other titles', values: otherValues, color: '#ccc', groupIndex: -1 });
		}
		return layers;
	});

	const months = $derived(monthsProp ?? loadedMonths);
	const series = $derived(seriesProp ?? derivedSeries);

	const x = $derived(
		scaleLinear()
			.domain([0, Math.max(months.length - 1, 1)])
			.range([margin.left, width - margin.right])
	);

	// Area mode stacks the series; line mode overlays them from a zero baseline.
	// `layers` is the mode-appropriate render list -- each carries a `top` array
	// used by the hover dot (the running stacked total in area mode, or just the
	// series' own values in line mode).
	const stackedSeries = $derived.by(() => {
		let currentBottom = new Array(months.length || 0).fill(0);
		return series.map(s => {
			const bottom = [...currentBottom];
			const top = s.values.map((v, i) => {
				const newTotal = currentBottom[i] + v;
				currentBottom[i] = newTotal;
				return newTotal;
			});
			return { ...s, bottom, top };
		});
	});

	const lineLayers = $derived(series.map((s) => ({ ...s, bottom: null, top: s.values })));

	const layers = $derived(mode === 'line' ? lineLayers : stackedSeries);

	const yMax = $derived.by(() => {
		if (!layers.length) return 1;
		if (mode === 'line') {
			let m = 0;
			for (const s of layers) for (const v of s.values) if (v > m) m = v;
			return m || 1;
		}
		return d3max(layers[layers.length - 1].top) || 1;
	});

	const y = $derived(
		scaleLinear()
			.domain([0, yMax])
			.nice()
			.range([height - margin.bottom, margin.top])
	);

	const areaPaths = $derived(
		stackedSeries.map((s) => ({
			...s,
			d: d3area()
				.x((_, i) => x(i))
				.y0((_, i) => y(s.bottom[i]))
				.y1((_, i) => y(s.top[i]))(s.values)
		}))
	);

	const linePaths = $derived(
		lineLayers.map((s) => ({
			...s,
			d: d3line()
				.x((_, i) => x(i))
				.y((_, i) => y(s.values[i]))(s.values)
		}))
	);

	const yTicks = $derived(y.ticks(5));

	// Abbreviate axis numbers: 700000 -> "700k", 1200000 -> "1.2M", 1500 -> "1.5k".
	function abbrevNum(n) {
		const a = Math.abs(n);
		if (a >= 1e6) { const v = n / 1e6; return (Number.isInteger(v) ? v : v.toFixed(1)) + "M"; }
		if (a >= 1e3) { const v = n / 1e3; return (Number.isInteger(v) ? v : v.toFixed(1)) + "k"; }
		return String(n);
	}
	// One tick per January, thinned so year labels never collide on a
	// narrow screen (~44px per label).
	const xTicks = $derived.by(() => {
		const all = months
			.map((m, i) => ({ i, year: m.slice(0, 4), isJan: m.endsWith('-01') }))
			.filter((d) => d.isJan);
		const maxLabels = Math.max(2, Math.floor((width - margin.left - margin.right) / 44));
		const step = Math.ceil(all.length / maxLabels);
		return all.filter((_, i) => i % step === 0);
	});

	let hoverIndex = $state(null);
	let hoveredSeriesKey = $state(null); // Track the active book layer

	function onMove(event) {
		const svg = event.currentTarget.ownerSVGElement || event.currentTarget;
		const r = svg.getBoundingClientRect();
		
		// horizontal index (Month)
		const px = (event.clientX - r.left) * (width / r.width);
		const i = Math.round(x.invert(px));
		hoverIndex = Math.min(Math.max(i, 0), months.length - 1);

		// vertical data value corresponding to cursor height
		const py = (event.clientY - r.top) * (height / r.height);
		const dataY = y.invert(py);

		if (mode === 'line') {
			// pick the line whose value at this month sits closest to the cursor
			let best = null, bestDist = Infinity;
			for (const s of layers) {
				const d = Math.abs(y(s.values[hoverIndex]) - py);
				if (d < bestDist) { bestDist = d; best = s; }
			}
			hoveredSeriesKey = best ? best.label : null;
		} else {
			// specific stacked layer whose band contains this Y data value
			const activeLayer = stackedSeries.find(s => {
				const bottomVal = s.bottom[hoverIndex];
				const topVal = s.top[hoverIndex];
				return dataY >= bottomVal && dataY <= topVal;
			});
			hoveredSeriesKey = activeLayer ? activeLayer.label : null;
		}
	}

	function onLeave() {
		hoverIndex = null;
		hoveredSeriesKey = null;
	}

	const MONTH_NAMES = [
		'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 
		'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'
	];

	function formatMonth(ym) {
		if (!ym) return '';
		const parts = ym.split('-');
		if (parts.length < 2) return ym;
		return `${MONTH_NAMES[Number(parts[1]) - 1]} ${parts[0]}`;
	}

	const FMT_LABEL = { ebook: 'ebook', audiobook: 'audio', print: 'print', other: 'other' };

	const tooltipLeft = $derived(
		hoverIndex === null ? 0 : Math.min(Math.max(x(hoverIndex), 100), width - 100)
	);

	// Float the tooltip near the dot on the hovered line (rather than pinned to
	// the top with a crosshair). Follows the point's height, flipping below it
	// when the point sits near the top edge.
	const tooltipTop = $derived(
		hoverIndex === null || !selectedItem ? margin.top : y(selectedItem.top[hoverIndex])
	);
	const tooltipBelow = $derived(hoverIndex !== null && !!selectedItem && tooltipTop < 90);

	// The big tooltip heading: the work title (in area mode) or the line's name.
	const tooltipTitle = $derived(
		!selectedItem ? ""
			: (mode !== "line" && selectedItem.groupName) ? selectedItem.groupName
			: selectedItem.label
	);

	// Get overall total for the hovered month. In area mode that's the top of
	// the stack; in line mode it's the aggregate ("author total") line if one is
	// present, else the largest line value.
	const hoveredTotal = $derived.by(() => {
		if (hoverIndex === null || !layers.length) return 0;
		if (mode === 'line') {
			const agg = layers.find((s) => s.isAggregate);
			return agg ? agg.values[hoverIndex] : Math.max(...layers.map((s) => s.values[hoverIndex]));
		}
		return stackedSeries[stackedSeries.length - 1].top[hoverIndex];
	});

	// Extract the single selected book series object matching user hover
	const selectedItem = $derived(
		(hoverIndex !== null && hoveredSeriesKey)
			? layers.find(s => s.label === hoveredSeriesKey)
			: null
	);


    // Other books that belong to the same selection group as the hovered book
    // (a stacked-area concept only; lines don't stack).
    const groupSiblings = $derived(
        mode !== 'line' && selectedItem && selectedItem.groupIndex !== undefined && selectedItem.groupIndex !== -1
            ? stackedSeries.filter(s => s.groupIndex === selectedItem.groupIndex)
            : []
    );

    // Sum of just the hovered book's own group, for the hovered month (for monthly totals)
    const groupTotal = $derived(
        hoverIndex !== null && groupSiblings.length > 0
            ? groupSiblings.reduce((sum, s) => sum + s.values[hoverIndex], 0)
            : 0
    );

    // opacity for a given area layer, given the current hover state
    function pathOpacity(p) {
        if (!hoveredSeriesKey) return 0.9;
        if (p.label === hoveredSeriesKey) return 0.95;
        if (
            selectedItem &&
            p.groupIndex !== undefined &&
            p.groupIndex !== -1 &&
            p.groupIndex === selectedItem.groupIndex
        ) {
            return 0.7;
        }
        return 0.3;
    }
</script>

<div class="chart-container" bind:clientWidth={width}>
	{#if !seriesProp}
		<div class="author-search">
			<input
				type="text"
				placeholder="Search authors..."
				value={query}
				oninput={onSearchInput}
			/>
			{#if searchResults.length > 0}
				<ul class="search-results">
					{#each searchResults as r (r.slug)}
						<li>
							<button type="button" onclick={() => selectAuthor(r.slug)}>
								<span class="result-name">{r.name}</span>
								<span class="result-total">{r.total.toLocaleString()}</span>
							</button>
						</li>
					{/each}
				</ul>
			{/if}
		</div>

		{#if dbError}
			<p class="db-status db-error">Couldn't load data: {dbError}</p>
		{:else if dbLoading}
			<p class="db-status">Loading…</p>
		{:else if activeAuthor}
			<h3 class="author-heading">
				{activeAuthor.name}
				<span class="author-total">{activeAuthor.total.toLocaleString()} checkouts</span>
			</h3>
		{:else if !activeSlug}
			<p class="db-status">Search for an author, or pick one below, to see checkouts over time.</p>
		{/if}
	{/if}

	<svg
		viewBox="0 0 {width} {height}"
		role="img"
		aria-label="Checkouts over time"
		onpointermove={onMove}
		onpointerleave={onLeave}
	>
		<!-- Y Axis Ticks & Gridlines -->
		{#each yTicks as tick}
			<g class="tick y-tick" transform="translate(0, {y(tick)})">
				<line x1={margin.left} x2={width - margin.right} stroke="#eee" />
				<text x={margin.left - 8} dx="-4" dy="4" text-anchor="end">{abbrevNum(tick)}</text>
			</g>
		{/each}

		<!-- X Axis Ticks -->
		{#each xTicks as tick}
			<g class="tick x-tick" transform="translate({x(tick.i)}, 0)">
				<line y1={margin.top} y2={height - margin.bottom} stroke="#eee" stroke-dasharray="2 2" />
				<text y={height - margin.bottom + 16} text-anchor="middle">{tick.year}</text>
			</g>
		{/each}

		<line x1={margin.left} x2={width - margin.right} y1={height - margin.bottom} y2={height - margin.bottom} stroke="#ccc" />

		<!-- Layers: overlaid lines (line mode) or stacked areas (area mode) -->
		{#if mode === 'line'}
			{#each linePaths as p}
				<path
					d={p.d}
					fill="none"
					stroke={p.color}
					stroke-width={p.isAggregate ? 2.5 : 1.75}
					opacity={pathOpacity(p)}
					class="line-path"
				/>
			{/each}
		{:else}
			{#each areaPaths as p}
				<path
					d={p.d}
					fill={p.color}
					stroke="var(--color-bg, #fff)"
					stroke-width="0.5"
					opacity={pathOpacity(p)}
					class="area-path"
				/>
			{/each}
		{/if}

		<!-- Hover marker: just a dot on the hovered line (no tethering crosshair) -->
		{#if hoverIndex !== null}
			{#if selectedItem && selectedItem.values[hoverIndex] > 0}
				<circle 
					cx={x(hoverIndex)} 
					cy={y(selectedItem.top[hoverIndex])} 
					r="5" 
					fill={selectedItem.color} 
					stroke="white" 
					stroke-width="2" 
				/>
			{/if}
		{/if}
	</svg>
	{#if hoverIndex !== null && selectedItem}
        <div class="tooltip" class:below={tooltipBelow} style="left: {tooltipLeft}px; top: {tooltipTop}px;">
            <div class="tt-title">
                <span class="tt-dot" style="background-color: {selectedItem.color}"></span>
                <span class="tt-title-text">{tooltipTitle}</span>
            </div>
            <div class="tt-date">{formatMonth(months[hoverIndex])}</div>

            {#if mode !== 'line' && groupSiblings.length > 1}
                <!-- one "medium pill" per edition of the hovered work -->
                <div class="tooltip-editions">
                    {#each groupSiblings.filter((s) => s.values[hoverIndex] > 0) as sib}
                        <span class="ed-pill" class:on={sib.titleIdx === selectedItem.titleIdx} style="--pc: {sib.color}">
                            <span class="ed-pill-fmt">{FMT_LABEL[sib.format] ?? sib.format ?? 'edition'}</span>
                            <span class="ed-pill-val">{sib.values[hoverIndex].toLocaleString()}</span>
                        </span>
                    {/each}
                </div>
                <div class="tooltip-total accent" style="color: {selectedItem.color};">
                    <span>Work total</span>
                    <span>{groupTotal.toLocaleString()}</span>
                </div>
            {:else}
                <div class="tt-value">{selectedItem.values[hoverIndex].toLocaleString()}<span class="tt-value-unit">checkouts</span></div>
            {/if}

            <div class="tooltip-total">
                <span>Overall month total</span>
                <span>{hoveredTotal.toLocaleString()}</span>
            </div>
        </div>
    {/if}
</div>

<style>
	.chart-container {
		position: relative;
		width: 100%;
		font-family: sans-serif;
	}

	svg {
		display: block;
		width: 100%;
		height: auto;
		overflow: visible;
	}

	.area-path {
		transition: opacity 0.15s ease;
	}

	.line-path {
		fill: none;
		stroke-linejoin: round;
		stroke-linecap: round;
		transition: opacity 0.15s ease;
	}

	.tick text {
		font-size: 11px;
		fill: #666;
	}

	.tooltip {
		position: absolute;
		/* float just above the dot on the line; a hair of easing so it doesn't
		   jitter, but snappy enough not to feel bouncy */
		transform: translate(-50%, calc(-100% - 18px));
		transition: left 0.04s linear, top 0.04s linear;
		background: #fff;
		border: 1px solid #e4e4e4;
		border-radius: 12px;
		padding: 14px 18px 15px;
		font-family: var(--font-sans, system-ui, -apple-system, "Segoe UI", sans-serif);
		font-size: 13px;
		color: #333;
		pointer-events: none;
		box-shadow: 0 12px 32px rgba(0, 0, 0, 0.17);
		min-width: 210px;
		max-width: 330px;
		z-index: 10;
	}
	/* when the point is near the top edge, drop the tooltip below the dot */
	.tooltip.below {
		transform: translate(-50%, 18px);
	}

	.tt-title {
		display: flex;
		align-items: baseline;
		gap: 8px;
		font-family: var(--font-serif, Georgia, "Times New Roman", serif);
		font-size: 1.05rem;
		font-weight: 600;
		line-height: 1.15;
		color: #1a1a1a;
	}
	.tt-dot {
		width: 11px;
		height: 11px;
		border-radius: 50%;
		flex: none;
		align-self: center;
	}
	.tt-title-text {
		word-break: break-word;
	}
	.tt-date {
		margin: 3px 0 10px 19px;
		font-size: 11px;
		font-weight: 700;
		letter-spacing: 0.04em;
		text-transform: uppercase;
		color: #9a9a9a;
	}
	.tt-value {
		display: flex;
		align-items: baseline;
		gap: 6px;
		margin: 0 0 2px 19px;
		font-size: 1.3rem;
		font-weight: 700;
		color: #1a1a1a;
	}
	.tt-value-unit {
		font-size: 0.68rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: #9a9a9a;
	}

	/* medium pills, one per edition of the hovered work (area mode) */
	.tooltip-editions {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		margin: 4px 0 10px;
		max-width: 290px;
	}
	.ed-pill {
		display: inline-flex;
		align-items: baseline;
		gap: 6px;
		padding: 4px 11px;
		border-radius: 999px;
		border: 1.5px solid var(--pc, #ccc);
		background: #fff;
		font-size: 12px;
		font-weight: 600;
		line-height: 1.4;
	}
	.ed-pill-fmt {
		color: #666;
		text-transform: capitalize;
	}
	.ed-pill-val {
		color: #111;
	}
	/* the edition/format band the cursor is actually over is filled in */
	.ed-pill.on {
		background: var(--pc, #333);
		border-color: var(--pc, #333);
	}
	.ed-pill.on .ed-pill-fmt,
	.ed-pill.on .ed-pill-val {
		color: #fff;
	}

	.tooltip-total {
		display: flex;
		justify-content: space-between;
		gap: 16px;
		border-top: 1px solid #eee;
		margin-top: 10px;
		padding-top: 8px;
		font-size: 12px;
		font-weight: 600;
		color: #808080;
	}
	.tooltip-total.accent {
		border-top: 1px dashed #ddd;
		font-weight: 700;
	}
	.tooltip-total span:last-child {
		color: #222;
	}

	.author-search {
		position: relative;
		margin-bottom: 10px;
		max-width: 320px;
	}

	.author-search input {
		width: 100%;
		box-sizing: border-box;
		padding: 8px 10px;
		font-size: 14px;
		border: 1px solid #ccc;
		border-radius: 4px;
	}

	.search-results {
		position: absolute;
		z-index: 20;
		top: 100%;
		left: 0;
		right: 0;
		margin: 4px 0 0;
		padding: 4px;
		list-style: none;
		background: #fff;
		border: 1px solid #ccc;
		border-radius: 4px;
		box-shadow: 0 6px 16px rgba(0, 0, 0, 0.12);
		max-height: 260px;
		overflow-y: auto;
	}

	.search-results li button {
		display: flex;
		justify-content: space-between;
		width: 100%;
		padding: 6px 8px;
		background: none;
		border: none;
		border-radius: 3px;
		font-size: 13px;
		text-align: left;
		cursor: pointer;
	}

	.search-results li button:hover {
		background: #f2f2f2;
	}

	.result-total {
		color: #888;
		font-variant-numeric: tabular-nums;
	}

	.db-status {
		font-size: 13px;
		color: #666;
		margin: 6px 0 10px;
	}

	.db-error {
		color: #b00020;
	}

	.author-heading {
		display: flex;
		align-items: baseline;
		gap: 10px;
		font-size: 16px;
		margin: 0 0 10px;
	}

	.author-total {
		font-size: 13px;
		font-weight: normal;
		color: #666;
	}
    /* stackedAreaChart.svelte */
    .area-path {
    	transition: opacity 0.15s ease, fill 0.4s ease;
	}
</style>