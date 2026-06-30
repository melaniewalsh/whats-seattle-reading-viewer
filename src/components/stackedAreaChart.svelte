<script>
    // StackedAreaChart.svelte
	import { scaleLinear, area as d3area, max as d3max } from 'd3';

	let { months = [], series = [] } = $props();
	
	let width = $state(720);
	const height = 380;
	const margin = { top: 16, right: 16, bottom: 28, left: 44 };

	const x = $derived(
		scaleLinear()
			.domain([0, Math.max(months.length - 1, 1)])
			.range([margin.left, width - margin.right])
	);

	// Stack data and map top/bottom boundaries
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
		
		// 1. Find the horizontal index (Month)
		const px = (event.clientX - r.left) * (width / r.width);
		const i = Math.round(x.invert(px));
		hoverIndex = Math.min(Math.max(i, 0), months.length - 1);

		// 2. Find the vertical data value corresponding to cursor height
		const py = (event.clientY - r.top) * (height / r.height);
		const dataY = y.invert(py);

		// 3. Find which specific layer bounding box contains this Y data value
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
    // Calculate the total checkouts of ONLY the selected/grouped items
    const groupedTotal = $derived(
        hoverIndex !== null && stackedSeries.length > 0
            ? stackedSeries.reduce((sum, s) => s.isSelected ? sum + s.values[hoverIndex] : sum, 0)
            : 0
    );

    // Check if we have more than one selected item to warrant showing a bundle total
    const selectedCount = $derived(
        stackedSeries.filter(s => s.isSelected).length
    );
</script>

<div class="chart-container">
	<svg {width} {height} viewBox="0 0 {width} {height}" onpointermove={onMove} onpointerleave={onLeave}>
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
				opacity={hoveredSeriesKey && hoveredSeriesKey !== p.label ? 0.35 : 0.9} 
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

	<!-- Fixed Isolated Tooltip Element -->
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

            {#if selectedCount > 1}
                <div class="tooltip-total" style="border-top: 1px dashed #ccc; color: #e3120b;">
                    <span>Grouped Total</span>
                    <span>{groupedTotal}</span>
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
    /* stackedAreaChart.svelte */
    .area-path {
        /* Add 'd' and 'fill' to the transition for fluid sorting and bundling */
        transition: opacity 0.15s ease, fill 0.4s ease, d 0.5s cubic-bezier(0.4, 0, 0.2, 1);
    }
</style>
