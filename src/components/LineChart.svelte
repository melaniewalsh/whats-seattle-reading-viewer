<script>
	// LineChart.svelte
	// =================
	// A small, readable line chart built with d3 scales + the SVG we draw by hand.
	// (The Pudding usually reaches for LayerCake, but a hand-rolled chart is easier
	//  to read and edit when you're learning.)
	//
	// Props:
	//   months : string[]   e.g. ["2018-01", "2018-02", ...]  (the x-axis)
	//   series : Array of { label, color, values, width? }
	//            values is a number[] the same length as months.
	import { scaleLinear, line as d3line, max as d3max } from "d3";

	let { months = [], series = [] } = $props();

	// We measure the container so the chart is crisp and responsive.
	let width = $state(720);
	const height = 380;
	const margin = { top: 16, right: 16, bottom: 28, left: 44 };

	// x is just the position in the months array (0, 1, 2, …).
	const x = $derived(
		scaleLinear()
			.domain([0, Math.max(months.length - 1, 1)])
			.range([margin.left, width - margin.right])
	);

	// y goes from 0 up to the largest value across every visible series.
	const yMax = $derived(
		d3max(series.flatMap((s) => s.values)) || 1
	);
	const y = $derived(
		scaleLinear()
			.domain([0, yMax])
			.nice()
			.range([height - margin.bottom, margin.top])
	);

	// Build the "d" attribute for each series' path.
	const paths = $derived(
		series.map((s) => ({
			...s,
			d: d3line()
				.x((_, i) => x(i))
				.y((v) => y(v))(s.values)
		}))
	);

	// y-axis tick values, and x-axis labels at each January (every 12th month).
	const yTicks = $derived(y.ticks(5));
	const xTicks = $derived(
		months
			.map((m, i) => ({ i, year: m.slice(0, 4), isJan: m.endsWith("-01") }))
			.filter((d) => d.isJan)
	);

	// ---- Hover: find the nearest month and show its values in a tooltip ----
	let hoverIndex = $state(null);
	function onMove(event) {
		// Measure against the <svg> (not the inner rect) and rescale screen pixels
		// to the chart's coordinate system, so the dot lands under the cursor.
		const svg = event.currentTarget.ownerSVGElement;
		const r = svg.getBoundingClientRect();
		const px = (event.clientX - r.left) * (width / r.width);
		const i = Math.round(x.invert(px));
		hoverIndex = Math.min(Math.max(i, 0), months.length - 1);
	}

	// "2020-09" -> "Sep 2020"
	const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
	function formatMonth(ym) {
		const [yr, mo] = ym.split("-");
		return `${MONTH_NAMES[Number(mo) - 1]} ${yr}`;
	}

	// Keep the tooltip from spilling off the chart edges.
	const tooltipLeft = $derived(
		hoverIndex === null ? 0 : Math.min(Math.max(x(hoverIndex), 80), width - 80)
	);
</script>

<div class="chart" bind:clientWidth={width}>
	<svg viewBox="0 0 {width} {height}" role="img" aria-label="Checkouts over time">
		<!-- horizontal gridlines + y labels -->
		{#each yTicks as t}
			<line class="grid" x1={margin.left} x2={width - margin.right} y1={y(t)} y2={y(t)} />
			<text class="axis" x={margin.left - 8} y={y(t)} dy="0.32em" text-anchor="end">
				{t.toLocaleString()}
			</text>
		{/each}

		<!-- x labels (one per year) -->
		{#each xTicks as t}
			<text class="axis" x={x(t.i)} y={height - 8} text-anchor="middle">{t.year}</text>
		{/each}

		<!-- the lines -->
		{#each paths as p}
			<path d={p.d} fill="none" stroke={p.color} stroke-width={p.width || 2} />
		{/each}

		<!-- hover guideline + dots -->
		{#if hoverIndex !== null}
			<line class="hover-line" x1={x(hoverIndex)} x2={x(hoverIndex)} y1={margin.top} y2={height - margin.bottom} />
			{#each series as s}
				<circle
					cx={x(hoverIndex)}
					cy={y(s.values[hoverIndex])}
					r="4.5"
					fill={s.color}
					stroke="white"
					stroke-width="2"
				/>
			{/each}
		{/if}

		<!-- transparent layer that catches the mouse -->
		<rect
			x={margin.left}
			y={margin.top}
			width={Math.max(width - margin.left - margin.right, 0)}
			height={height - margin.top - margin.bottom}
			fill="transparent"
			onmousemove={onMove}
			onmouseleave={() => (hoverIndex = null)}
		/>
	</svg>

	<!-- tooltip -->
	{#if hoverIndex !== null}
		<div class="tooltip" style="left: {tooltipLeft}px;">
			<div class="tt-head">
				<strong>{formatMonth(months[hoverIndex])}</strong>
				<span class="tt-unit">checkouts</span>
			</div>
			{#each series as s}
				<div class="row">
					<span class="swatch" style="background:{s.color}"></span>
					<span class="lbl">{s.label}</span>
					<span class="val">{s.values[hoverIndex].toLocaleString()}</span>
				</div>
			{/each}
		</div>
	{/if}
</div>

<style>
	.chart {
		position: relative;
		width: 100%;
	}
	svg {
		width: 100%;
		height: auto;
		display: block;
		overflow: visible;
	}
	.grid {
		stroke: var(--color-gray-200);
		stroke-width: 1;
	}
	.axis {
		font-family: var(--font-sans);
		font-size: 12px;
		fill: var(--color-fg-light);
	}
	.hover-line {
		stroke: var(--color-gray-400);
		stroke-width: 1;
		stroke-dasharray: 3 3;
	}
	.tooltip {
		position: absolute;
		top: 0;
		transform: translateX(-50%);
		background: var(--color-white);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		padding: 8px 10px;
		font-family: var(--font-sans);
		font-size: 12px;
		pointer-events: none;
		box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
		white-space: nowrap;
		max-width: 280px;
	}
	.tooltip .tt-head {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: 12px;
		margin-bottom: 5px;
		padding-bottom: 4px;
		border-bottom: 1px solid var(--color-gray-100);
	}
	.tooltip .tt-unit {
		color: var(--color-fg-light);
		font-size: 10px;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
	.tooltip .row {
		display: flex;
		align-items: center;
		gap: 6px;
	}
	.tooltip .swatch {
		width: 10px;
		height: 10px;
		border-radius: 2px;
		flex: none;
	}
	.tooltip .lbl {
		overflow: hidden;
		text-overflow: ellipsis;
		max-width: 170px;
	}
	.tooltip .val {
		margin-left: auto;
		font-variant-numeric: tabular-nums;
		font-weight: 600;
	}
</style>
