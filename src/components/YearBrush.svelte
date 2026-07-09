<script>
	// YearBrush.svelte
	// =================
	// A Pudding-style year-range slider that sits under the main chart: the
	// author's whole history drawn as a small gray area chart, with two
	// handles that snap to whole years. Drag a handle to trim the range, drag
	// the highlighted window to slide it, or use the arrow keys when a handle
	// is focused. The parent binds `lo`/`hi` (month indices, inclusive) and
	// slices its own data to match.
	//
	// Props:
	//   months : string[]  full shared month axis, e.g. ["2006-01", ...]
	//   values : number[]  same length -- the series drawn as context
	//   lo, hi : bindable month indices of the selected window (inclusive)
	let { months = [], values = [], lo = $bindable(0), hi = $bindable(0) } = $props();

	const uid = $props.id();

	let width = $state(680); // measured from the container
	const H = 48; // sparkline height
	const LABEL_H = 20; // room for the year labels
	const PAD = 12; // horizontal padding so the handles never clip
	const height = H + LABEL_H;

	// The months grouped into years: [{ year, start, end }] (month indices).
	const years = $derived.by(() => {
		const out = [];
		for (let i = 0; i < months.length; i++) {
			const yr = months[i].slice(0, 4);
			if (!out.length || out[out.length - 1].year !== yr) out.push({ year: yr, start: i, end: i });
			else out[out.length - 1].end = i;
		}
		return out;
	});

	const n = $derived(Math.max(months.length - 1, 1));
	const xOf = (i) => PAD + (i / n) * (width - PAD * 2);
	const idxAt = (px) => Math.round(((px - PAD) / (width - PAD * 2)) * n);

	// The year bucket a month index falls in.
	function yearIndexOf(idx) {
		if (!years.length) return 0;
		const i = Math.max(0, Math.min(idx, months.length - 1));
		for (let yi = 0; yi < years.length; yi++) if (i <= years[yi].end) return yi;
		return years.length - 1;
	}
	const loYear = $derived(yearIndexOf(lo));
	const hiYear = $derived(yearIndexOf(hi));
	const isFiltered = $derived(months.length > 0 && (lo > 0 || hi < months.length - 1));

	// The context sparkline (a hand-built area path -- no d3 needed here).
	const vMax = $derived(Math.max(1, ...values));
	const yOf = (v) => H - 2 - (v / vMax) * (H - 10);
	const areaPath = $derived.by(() => {
		if (!values.length) return "";
		let d = `M ${xOf(0)} ${H - 2}`;
		for (let i = 0; i < values.length; i++) d += ` L ${xOf(i)} ${yOf(values[i])}`;
		d += ` L ${xOf(values.length - 1)} ${H - 2} Z`;
		return d;
	});

	// Thin the year labels so they never collide (~40px per label).
	const labelStep = $derived(
		Math.max(1, Math.ceil(years.length / Math.max(2, Math.floor((width - PAD * 2) / 40))))
	);

	// ---- Dragging (handles snap live to whole years) -----------------------
	let drag = $state(null); // { type: 'lo'|'hi'|'win', grabYear, loYear0, hiYear0 }

	function onPointerDown(e) {
		if (!years.length) return;
		const rect = e.currentTarget.getBoundingClientRect();
		const px = e.clientX - rect.left;
		const xLo = xOf(lo);
		const xHi = xOf(hi);
		let type;
		if (Math.abs(px - xLo) < 14 && Math.abs(px - xLo) <= Math.abs(px - xHi)) type = "lo";
		else if (Math.abs(px - xHi) < 14) type = "hi";
		else if (px > xLo && px < xHi) type = "win";
		else type = Math.abs(px - xLo) < Math.abs(px - xHi) ? "lo" : "hi";
		drag = { type, grabYear: yearIndexOf(idxAt(px)), loYear0: loYear, hiYear0: hiYear };
		e.currentTarget.setPointerCapture(e.pointerId);
		onPointerMove(e); // a click outside the window jumps the nearest handle
	}

	function onPointerMove(e) {
		if (!drag) return;
		const rect = e.currentTarget.getBoundingClientRect();
		const yi = yearIndexOf(idxAt(e.clientX - rect.left));
		if (drag.type === "lo") {
			lo = years[Math.min(yi, hiYear)].start;
		} else if (drag.type === "hi") {
			hi = years[Math.max(yi, loYear)].end;
		} else {
			// slide the whole window, keeping its width in years
			const span = drag.hiYear0 - drag.loYear0;
			let s = drag.loYear0 + (yi - drag.grabYear);
			s = Math.max(0, Math.min(s, years.length - 1 - span));
			lo = years[s].start;
			hi = years[s + span].end;
		}
	}

	function onPointerUp() {
		drag = null;
	}

	// Arrow keys nudge a focused handle one year at a time.
	function onHandleKey(e, which) {
		const delta =
			e.key === "ArrowLeft" || e.key === "ArrowDown"
				? -1
				: e.key === "ArrowRight" || e.key === "ArrowUp"
					? 1
					: 0;
		if (!delta) return;
		e.preventDefault();
		if (which === "lo") {
			lo = years[Math.max(0, Math.min(loYear + delta, hiYear))].start;
		} else {
			hi = years[Math.max(loYear, Math.min(hiYear + delta, years.length - 1))].end;
		}
	}

	function reset() {
		lo = 0;
		hi = Math.max(months.length - 1, 0);
	}
</script>

<div class="brush" bind:clientWidth={width}>
	<div class="brush-head">
		<span class="brush-label">Years</span>
		<span class="brush-range">
			{years[loYear]?.year}<span class="dash">–</span>{years[hiYear]?.year}
		</span>
		{#if isFiltered}
			<button class="brush-reset" onclick={reset}>All years ×</button>
		{/if}
	</div>

	<svg
		viewBox="0 0 {width} {height}"
		class:dragging={drag !== null}
		role="application"
		aria-label="Filter the chart to a range of years"
		onpointerdown={onPointerDown}
		onpointermove={onPointerMove}
		onpointerup={onPointerUp}
		onpointercancel={onPointerUp}
	>
		<defs>
			<clipPath id="{uid}-sel">
				<rect x={xOf(lo)} y="0" width={Math.max(xOf(hi) - xOf(lo), 0)} height={H} />
			</clipPath>
		</defs>

		<!-- context: the full history, dimmed -->
		<path class="area-bg" d={areaPath} />
		<!-- the selected window, in the site accent -->
		<path class="area-sel" d={areaPath} clip-path="url(#{uid}-sel)" />

		<!-- window outline -->
		<rect
			class="win"
			x={xOf(lo)}
			y="1"
			width={Math.max(xOf(hi) - xOf(lo), 0)}
			height={H - 2}
			rx="3"
		/>

		<!-- baseline -->
		<line class="base" x1={PAD} x2={width - PAD} y1={H - 2} y2={H - 2} />

		<!-- year labels -->
		{#each years as yr, yi}
			{#if yi % labelStep === 0}
				<text
					class="yr"
					class:in={yi >= loYear && yi <= hiYear}
					x={xOf((yr.start + yr.end) / 2)}
					y={H + 14}
					text-anchor="middle">{yr.year}</text
				>
			{/if}
		{/each}

		<!-- handles (focusable, arrow keys move by a year) -->
		{#each [["lo", lo, loYear], ["hi", hi, hiYear]] as [which, idx, yi] (which)}
			<g
				class="handle"
				role="slider"
				tabindex="0"
				aria-label={which === "lo" ? "First year shown" : "Last year shown"}
				aria-valuemin={Number(years[0]?.year ?? 0)}
				aria-valuemax={Number(years[years.length - 1]?.year ?? 0)}
				aria-valuenow={Number(years[yi]?.year ?? 0)}
				aria-valuetext={years[yi]?.year}
				onkeydown={(e) => onHandleKey(e, which)}
			>
				<line class="handle-line" x1={xOf(idx)} x2={xOf(idx)} y1="1" y2={H - 1} />
				<rect
					class="handle-grip"
					x={xOf(idx) - 4}
					y={H / 2 - 11}
					width="8"
					height="22"
					rx="4"
				/>
				<line class="grip-tick" x1={xOf(idx)} x2={xOf(idx)} y1={H / 2 - 5} y2={H / 2 + 5} />
			</g>
		{/each}
	</svg>
</div>

<style>
	.brush {
		margin: 6px 0 16px;
	}

	.brush-head {
		display: flex;
		align-items: baseline;
		gap: 10px;
		font-family: var(--font-sans);
		margin-bottom: 2px;
	}

	.brush-label {
		font-size: 0.7rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--color-fg-light);
	}

	.brush-range {
		font-size: 0.82rem;
		font-weight: 600;
		font-variant-numeric: tabular-nums;
		color: var(--color-fg);
	}

	.brush-range .dash {
		margin: 0 3px;
		color: var(--color-fg-light);
	}

	.brush-reset {
		margin-left: auto;
		background: none;
		border: none;
		padding: 0;
		font-family: var(--font-sans);
		font-size: 0.78rem;
		color: var(--color-fg-light);
		text-decoration: underline;
		cursor: pointer;
	}

	.brush-reset:hover {
		color: var(--color-fg);
	}

	svg {
		display: block;
		width: 100%;
		height: auto;
		overflow: visible;
		touch-action: none; /* so dragging the handles works on phones */
		cursor: crosshair;
	}

	svg.dragging {
		cursor: grabbing;
	}

	.area-bg {
		fill: var(--color-gray-200);
	}

	.area-sel {
		fill: #6aa9dd; /* the site's headline blue */
		fill-opacity: 0.75;
	}

	.win {
		fill: none;
		stroke: #357abd;
		stroke-width: 1;
		stroke-opacity: 0.5;
	}

	.base {
		stroke: var(--color-gray-300);
		stroke-width: 1;
	}

	.yr {
		font-family: var(--font-sans);
		font-size: 11px;
		fill: var(--color-gray-400);
	}

	.yr.in {
		fill: var(--color-fg-light);
		font-weight: 600;
	}

	.handle {
		cursor: ew-resize;
		outline: none;
	}

	.handle-line {
		stroke: #357abd;
		stroke-width: 1;
	}

	.handle-grip {
		fill: var(--color-white);
		stroke: #357abd;
		stroke-width: 1.5;
	}

	.grip-tick {
		stroke: #357abd;
		stroke-width: 1.5;
	}

	.handle:hover .handle-grip,
	.handle:focus-visible .handle-grip {
		fill: #357abd;
	}

	.handle:hover .grip-tick,
	.handle:focus-visible .grip-tick {
		stroke: var(--color-white);
	}

	.handle:focus-visible .handle-grip {
		stroke: var(--color-fg);
	}
</style>
