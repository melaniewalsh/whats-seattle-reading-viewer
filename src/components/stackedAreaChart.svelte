<script>
    // StackedAreaChart.svelte
	import { scaleLinear, area as d3area, max as d3max } from 'd3';
	import { getMonths, searchAuthors, getAuthor, densify } from './db.js';

	// Both props are now optional. Pass explicitly for pre-fetched/
	// embedded/test use.
	let {
		months: monthsProp = null,
		series: seriesProp = null,
		slug: initialSlug = null,
		topTitles = 8
	} = $props();

	let width = $state(720);
	const height = 380;
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
	// uses server-side). Auto-select the #1 author too, so the chart shows
	// something immediately.
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
	// activeSlug changes. One query for the author row, one for their
	// titles (see db.js:getAuthor), both satisfied by a couple of indexed
	// page reads rather than downloading the whole database.
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

	// Stacks data and map top/bottom boundaries
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

	const yMax = $derived.by(() => {
		if (!stackedSeries.length) return 1;
		const lastSeries = stackedSeries[stackedSeries.length - 1];
		return d3max(lastSeries.top) || 1;
	});

	const y = $derived(
		scaleLinear()
			.domain([0, yMax])
			.nice()
			.range([height - margin.bottom, margin.top])
	);

	const paths = $derived(
		stackedSeries.map((s) => ({
			...s,
			d: d3area()
				.x((_, i) => x(i))
				.y0((_, i) => y(s.bottom[i]))
				.y1((_, i) => y(s.top[i]))(s.values)
		}))
	);

	const yTicks = $derived(y.ticks(5));
	const xTicks = $derived(
		months
			.map((m, i) => ({ i, year: m.slice(0, 4), isJan: m.endsWith('-01') }))
			.filter((d) => d.isJan)
	);

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

		// specific layer bounding box contains this Y data value
		const activeLayer = stackedSeries.find(s => {
			const bottomVal = s.bottom[hoverIndex];
			const topVal = s.top[hoverIndex];
			return dataY >= bottomVal && dataY <= topVal;
		});

		hoveredSeriesKey = activeLayer ? activeLayer.label : null;
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

	const tooltipLeft = $derived(
		hoverIndex === null ? 0 : Math.min(Math.max(x(hoverIndex), 100), width - 100)
	);

	// Get overall total for the hovered month
	const hoveredTotal = $derived(
		hoverIndex !== null && stackedSeries.length > 0 
			? stackedSeries[stackedSeries.length - 1].top[hoverIndex] 
			: 0
	);

	// Extract the single selected book series object matching user hover
	const selectedItem = $derived(
		(hoverIndex !== null && hoveredSeriesKey)
			? stackedSeries.find(s => s.label === hoveredSeriesKey)
			: null
	);


    // stackedAreaChart.svelte
    // Other books that belong to the same selection group as the hovered book
    const groupSiblings = $derived(
        selectedItem && selectedItem.groupIndex !== undefined && selectedItem.groupIndex !== -1
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

<div class="chart-container">
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
		{width}
		{height}
		viewBox="0 0 {width} {height}"
		role="img"
		aria-label="Checkouts over time, stacked by title"
		onpointermove={onMove}
		onpointerleave={onLeave}
	>
		<!-- Y Axis Ticks & Gridlines -->
		{#each yTicks as tick}
			<g class="tick y-tick" transform="translate(0, {y(tick)})">
				<line x1={margin.left} x2={width - margin.right} stroke="#eee" />
				<text x={margin.left - 8} dx="-4" dy="4" text-anchor="end">{tick}</text>
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

		<!-- Area Layers -->
		{#each paths as p}
			<path 
				d={p.d} 
				fill={p.color} 
				stroke="var(--color-bg, #fff)" 
				stroke-width="0.5" 
				opacity={pathOpacity(p)} 
				class="area-path"
			/>
		{/each}

		<!-- Hover Target Markers -->
		{#if hoverIndex !== null}
			<line 
				class="hover-line" 
				x1={x(hoverIndex)} 
				x2={x(hoverIndex)} 
				y1={margin.top} 
				y2={height - margin.bottom} 
				stroke="#444"
				stroke-width="1"
			/>
			
			<!-- Highlight dot only on the selected active layer stack point -->
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
        <div class="tooltip" style="left: {tooltipLeft}px; top: {margin.top}px;">
            <div class="tooltip-date">{formatMonth(months[hoverIndex])}</div>
            
            <div class="tooltip-items">
                <div class="tooltip-row selected-highlight">
                    <span class="swatch" style="background-color: {selectedItem.color}"></span>
                    <span class="label">{selectedItem.label}</span>
                    <span class="value">{selectedItem.values[hoverIndex]}</span>
                </div>
            </div>

            {#if groupSiblings.length > 1}
                <div class="tooltip-total" style="border-top: 1px dashed #ccc; color: {selectedItem.color};">
                    <span>Group Total</span>
                    <span>{groupTotal}</span>
                </div>
            {/if}

            <div class="tooltip-total">
                <span>Overall Month Total</span>
                <span>{hoveredTotal}</span>
            </div>
        </div>
    {/if}
</div>

<style>
	.chart-container {
		position: relative;
		width: max-content;
		font-family: sans-serif;
	}

	svg {
		display: block;
		overflow: visible;
	}

	.area-path {
		transition: opacity 0.15s ease;
	}

	.tick text {
		font-size: 11px;
		fill: #666;
	}

	.tooltip {
		position: absolute;
		transform: translateX(-50%);
		background: rgba(255, 255, 255, 0.98);
		border: 1px solid #bbb;
		border-radius: 4px;
		padding: 10px 14px;
		font-size: 12px;
		color: #333;
		pointer-events: none;
		box-shadow: 0 6px 16px rgba(0,0,0,0.12);
		min-width: 165px;
		z-index: 10;
	}

	.tooltip-date {
		font-weight: bold;
		border-bottom: 1px solid #eee;
		padding-bottom: 4px;
		margin-bottom: 6px;
		color: #111;
	}

	.tooltip-row {
		display: flex;
		align-items: center;
		margin-bottom: 3px;
		padding: 2px 0;
	}

	.swatch {
		width: 10px;
		height: 10px;
		border-radius: 2px;
		margin-right: 8px;
		display: inline-block;
	}

	.label {
		flex-grow: 1;
		margin-right: 16px;
		color: #444;
	}

	.value {
		font-weight: bold;
	}

	.tooltip-total {
		display: flex;
		justify-content: space-between;
		border-top: 1px solid #eee;
		margin-top: 8px;
		padding-top: 5px;
		font-weight: bold;
		color: #666;
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