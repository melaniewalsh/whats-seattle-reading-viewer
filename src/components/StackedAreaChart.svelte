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
		mode = 'area',
		grandTotal = 0,   // the author's (or overview's) all-time total, for the share line
		shareOf = '',     // phrase after "% of ", e.g. "J. K. Rowling's checkouts"
		annotations = []  // [{ month, label, blurb, url }] — a "?" marker above each dip
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

	// "?" markers for the event dips (COVID, ransomware): resolve each to an x
	// position; a horizontal anchor keeps near-edge popovers from overflowing.
	const annotationMarks = $derived.by(() => {
		if (!annotations?.length || months.length < 2) return [];
		return annotations
			.map((a) => {
				const i = months.findIndex((m) => m === a.month || m.startsWith(a.month));
				if (i < 0) return null;
				const px = x(i);
				const align = px > width * 0.62 ? 'end' : px < width * 0.38 ? 'start' : 'center';
				// Cap the popover width to the space actually available on that side
				// so it never runs off the edge on a narrow (mobile) chart. The wrap
				// sits at px (±10px for the button); leave an 8px gutter.
				const pad = 8;
				const avail =
					align === 'end' ? px + 10 - pad
					: align === 'start' ? width - (px - 10) - pad
					: 2 * Math.min(px, width - px) - 2 * pad;
				const maxw = Math.max(180, Math.min(320, Math.round(avail)));
				return { ...a, x: px, align, maxw };
			})
			.filter(Boolean);
	});

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

	// The top edge of each stacked band, drawn as a line so every area gets a crisp
	// outline in its own colour (the fill sits just under it).
	const areaTopLines = $derived(
		stackedSeries.map((s) => ({
			...s,
			d: d3line()
				.x((_, i) => x(i))
				.y((_, i) => y(s.top[i]))(s.values)
		}))
	);

	// In line ("Total") mode, fill the area under the aggregate/total line so the
	// default view reads as a filled area chart (comparison lines still overlay).
	const aggregateArea = $derived.by(() => {
		if (mode !== 'line') return null;
		const agg = lineLayers.find((s) => s.isAggregate);
		if (!agg) return null;
		return {
			color: agg.color,
			d: d3area()
				.x((_, i) => x(i))
				.y0(() => y(0))
				.y1((_, i) => y(agg.values[i]))(agg.values)
		};
	});

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
	let pointerY = $state(0); // cursor height (viewBox units), for a steady tooltip

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
		// Track the cursor's own height so the tooltip card glides with the mouse
		// instead of bouncing along the spiky data line.
		pointerY = py;

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

	const FMT_LABEL = { ebook: 'ebook', audiobook: 'audio', print: 'print', largeprint: 'large print', other: 'other' };

	const tooltipLeft = $derived(
		hoverIndex === null ? 0 : Math.min(Math.max(x(hoverIndex), 100), width - 100)
	);

	// Float the tooltip at the cursor's height (not the data point's) so it tracks
	// the mouse smoothly instead of bouncing up and down a spiky line. The dot and
	// dashed guide still mark the exact data point.
	const tooltipTop = $derived(
		hoverIndex === null ? margin.top : Math.min(Math.max(pointerY, margin.top), height - margin.bottom)
	);
	const tooltipBelow = $derived(hoverIndex !== null && tooltipTop < 90);

	// The big tooltip heading: the work title (in area mode) or the line's name.
	const tooltipTitle = $derived(
		!selectedItem ? ""
			: (mode !== "line" && selectedItem.groupName) ? selectedItem.groupName
			: selectedItem.label
	);

	// The hovered work's share of the author's (or overview's) all-time checkouts.
	const workSharePct = $derived(
		selectedItem && grandTotal && selectedItem.workTotal ? (selectedItem.workTotal / grandTotal) * 100 : null
	);
	function fmtPct(p) {
		if (p >= 9.95) return Math.round(p) + "%";
		if (p >= 0.1) return p.toFixed(1) + "%";
		return "<0.1%";
	}

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

    // Consolidate the work's editions by FORMAT so the tooltip shows one pill per
    // format (audio / print / ebook), not one per edition — a work can have several
    // audiobook or print editions.
    const formatPills = $derived.by(() => {
        if (hoverIndex === null || !groupSiblings.length) return [];
        const byFmt = new Map();
        for (const s of groupSiblings) {
            const v = s.values[hoverIndex];
            if (!v) continue;
            const key = s.format ?? 'other';
            const cur = byFmt.get(key) || { format: key, value: 0, color: s.color, hit: false };
            cur.value += v;
            if (s.titleIdx === selectedItem?.titleIdx) cur.hit = true;
            byFmt.set(key, cur);
        }
        return [...byFmt.values()].sort((a, b) => b.value - a.value);
    });

    // The hovered thing's share of THAT MONTH's total checkouts. In the format
    // overview each layer is a format, so this reads "38% of this month's
    // checkouts are audiobook"; for a multi-edition work it's the whole work's
    // share (all its formats), not a single edition.
    const monthShareNum = $derived(groupSiblings.length > 1 ? groupTotal : (selectedItem ? selectedItem.values[hoverIndex] : 0));
    const monthSharePct = $derived(
        mode !== 'line' && hoverIndex !== null && selectedItem && hoveredTotal
            ? (monthShareNum / hoveredTotal) * 100 : null
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
			{#if aggregateArea}
				<path d={aggregateArea.d} fill={aggregateArea.color} opacity="0.13" class="agg-area" />
			{/if}
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
					fill-opacity="0.78"
					stroke="none"
					opacity={pathOpacity(p)}
					class="area-path"
				/>
			{/each}
			{#each areaTopLines as p}
				<path
					d={p.d}
					fill="none"
					stroke={p.color}
					stroke-width="1.75"
					stroke-linejoin="round"
					opacity={pathOpacity(p)}
					class="area-top"
				/>
			{/each}
		{/if}

		<!-- Hover marker: a faint vertical guide plus a dot on the hovered line -->
		{#if hoverIndex !== null}
			{#if selectedItem && selectedItem.values[hoverIndex] > 0}
				<line
					class="hover-guide"
					x1={x(hoverIndex)}
					x2={x(hoverIndex)}
					y1={y(selectedItem.top[hoverIndex])}
					y2={height - margin.bottom}
					stroke="#c9c9c9"
					stroke-width="1"
					stroke-dasharray="3 3"
				/>
				<circle
					class="hover-dot"
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
	<!-- "?" markers above the event dips; hover/focus for the explanation -->
	{#each annotationMarks as a}
		<div class="qmark-wrap align-{a.align}" style="left: {a.x}px;">
			<button class="qmark" aria-label="Why the drop here?">?</button>
			<div class="qmark-pop" role="tooltip" style="max-width: {a.maxw}px;">
				<p class="qmark-body"><strong>{a.label}.</strong> {a.blurb} <a href={a.url} target="_blank" rel="noopener noreferrer">Read more</a></p>
			</div>
		</div>
	{/each}
	{#if hoverIndex !== null && selectedItem}
        <div class="tooltip" class:below={tooltipBelow} style="left: {tooltipLeft}px; top: {tooltipTop}px;">
            <div class="tt-title">
                <span class="tt-dot" style="background-color: {selectedItem.color}"></span>
                <span class="tt-title-text">{tooltipTitle}</span>
            </div>
            <div class="tt-date">{formatMonth(months[hoverIndex])}</div>

            {#if mode !== 'line' && formatPills.length > 1}
                <!-- one "medium pill" per FORMAT of the hovered work (editions of the
                     same format are summed together) -->
                <div class="tooltip-editions">
                    {#each formatPills as fp}
                        <span class="ed-pill" class:on={fp.hit} style="--pc: {fp.color}">
                            <span class="ed-pill-fmt">{FMT_LABEL[fp.format] ?? fp.format ?? 'edition'}</span>
                            <span class="ed-pill-val">{groupTotal ? `${Math.round((fp.value / groupTotal) * 100)}%` : fp.value.toLocaleString()}</span>
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

            {#if selectedItem.otherTitles?.length}
                <div class="tt-others">
                    {#each selectedItem.otherTitles.slice(0, 8) as name}
                        <div class="tt-other">{name}</div>
                    {/each}
                    {#if selectedItem.otherTitles.length > 8}
                        <div class="tt-other-more">+{selectedItem.otherTitles.length - 8} more</div>
                    {/if}
                </div>
            {/if}

            {#if monthSharePct !== null}
                <div class="tooltip-total"><span class="tt-share" style="color: {selectedItem.color};">{fmtPct(monthSharePct)} of this month's checkouts</span></div>
            {:else if workSharePct !== null && shareOf}
                <div class="tooltip-total">
                    <span class="tt-share">{fmtPct(workSharePct)} of {shareOf}</span>
                </div>
            {:else}
                <div class="tooltip-total">
                    <span>Overall month total</span>
                    <span>{hoveredTotal.toLocaleString()}</span>
                </div>
            {/if}
        </div>
    {/if}
</div>

<style>
	/* "?" markers for event dips (COVID, ransomware) — hover reveals the note. */
	.qmark-wrap {
		position: absolute;
		top: 4px;
		z-index: 7;
	}
	.qmark-wrap.align-center { transform: translateX(-50%); }
	.qmark-wrap.align-end { transform: translateX(-50%); }
	.qmark-wrap.align-start { transform: translateX(-50%); }
	.qmark {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 20px;
		height: 20px;
		font-family: var(--font-sans, system-ui, sans-serif);
		font-size: 0.78rem;
		font-weight: 700;
		color: var(--color-fg-light, #667);
		background: rgba(255, 255, 255, 0.95);
		border: 1.5px solid var(--color-border, #d5d9e0);
		border-radius: 50%;
		cursor: help;
		padding: 0;
		box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
	}
	.qmark-wrap:hover .qmark,
	.qmark-wrap:focus-within .qmark {
		color: #fff;
		background: #3f88cc;
		border-color: #3f88cc;
	}
	.qmark-pop {
		display: none;
		position: absolute;
		top: calc(100% + 6px);
		left: 50%;
		transform: translateX(-50%);
		z-index: 8;
		width: max-content;
		padding: 12px 14px;
		background: var(--color-white, #fff);
		border: 1px solid var(--color-border, #d5d9e0);
		border-radius: 10px;
		box-shadow: 0 8px 26px rgba(0, 0, 0, 0.16);
	}
	/* keep the near-edge popovers from overflowing the chart */
	.qmark-wrap.align-end .qmark-pop { left: auto; right: 0; transform: none; }
	.qmark-wrap.align-start .qmark-pop { left: 0; transform: none; }
	.qmark-wrap:hover .qmark-pop,
	.qmark-wrap:focus-within .qmark-pop { display: block; }
	.qmark-body {
		margin: 0;
		font-family: var(--font-sans, system-ui, sans-serif);
		font-size: 0.86rem;
		line-height: 1.5;
		color: var(--color-fg, #1a1a1a);
	}
	.qmark-body strong { font-weight: 700; }
	.qmark-body a { color: #357abd; font-weight: 600; text-decoration: underline; white-space: nowrap; }
	.qmark-body a:hover { color: #26597f; }

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

	/* Glide the hover dot and guide between points, in step with the tooltip. */
	.hover-dot {
		transition: cx 0.18s cubic-bezier(0.22, 1, 0.36, 1),
			cy 0.18s cubic-bezier(0.22, 1, 0.36, 1);
	}
	.hover-guide {
		opacity: 0.9;
		transition: x1 0.18s cubic-bezier(0.22, 1, 0.36, 1),
			x2 0.18s cubic-bezier(0.22, 1, 0.36, 1),
			y1 0.18s cubic-bezier(0.22, 1, 0.36, 1);
	}

	.tick text {
		font-size: 11px;
		fill: #666;
	}

	.tooltip {
		position: absolute;
		/* float just above the dot on the line; glide between points with a gentle
		   ease so it tracks the cursor smoothly instead of snapping */
		transform: translate(-50%, calc(-100% - 18px));
		/* glide horizontally between month positions; vertical tracks the cursor
		   directly (no transition) so it never lags or bounces */
		transition: left 0.12s cubic-bezier(0.22, 1, 0.36, 1);
		background: rgba(255, 255, 255, 0.98);
		-webkit-backdrop-filter: saturate(1.8) blur(6px);
		backdrop-filter: saturate(1.8) blur(6px);
		border: 1px solid rgba(0, 0, 0, 0.06);
		border-radius: 12px;
		padding: 14px 18px 15px;
		font-family: var(--font-sans, system-ui, -apple-system, "Segoe UI", sans-serif);
		font-size: 13px;
		color: #333;
		pointer-events: none;
		box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04),
			0 6px 16px rgba(0, 0, 0, 0.08),
			0 18px 40px rgba(0, 0, 0, 0.10);
		min-width: 210px;
		max-width: 330px;
		z-index: 10;
		animation: tt-fade 0.14s ease-out;
	}
	@keyframes tt-fade {
		from { opacity: 0; }
		to { opacity: 1; }
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
	/* The titles rolled into an "Other titles" band, listed in its tooltip. */
	.tt-others {
		margin: 4px 0 2px 19px;
		display: flex;
		flex-direction: column;
		gap: 1px;
	}
	.tt-other {
		font-size: 0.8rem;
		color: #444;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		max-width: 240px;
	}
	.tt-other-more {
		font-size: 0.74rem;
		font-weight: 600;
		color: #888;
		margin-top: 1px;
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