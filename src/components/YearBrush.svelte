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
	//   start  : first month index the slider covers (skips the empty years
	//            before a book or author first circulated)
	//   inset  : the chart's right margin, so the slider stops at the plot's edge
	let { months = [], values = [], start = 0, inset = 0, lo = $bindable(0), hi = $bindable(0) } = $props();

	const uid = $props.id();

	let width = $state(680); // measured from the container
	const AREA_H = 28; // height of the gray silhouette
	const PAD = 6; // horizontal padding so the edge handles never clip
	const height = AREA_H + 18; // silhouette + the year labels under it

	// The whole history as a small gray silhouette (the context you zoom into).
	const areaPath = $derived.by(() => {
		const vs = (values || []).slice(start);
		if (vs.length < 2) return "";
		const mx = Math.max(1, ...vs);
		const pts = vs.map((v, k) => `${xOf(start + k).toFixed(1)},${(AREA_H - ((v || 0) / mx) * (AREA_H - 4)).toFixed(1)}`);
		return `M${xOf(start).toFixed(1)},${AREA_H} L${pts.join(" L")} L${xOf(values.length - 1).toFixed(1)},${AREA_H} Z`;
	});
	// A few year labels under the silhouette: every 1, 2 or 5 years, whichever
	// keeps them ~70px apart, on round years.
	const yearTicks = $derived.by(() => {
		if (!years.length) return [];
		const fit = Math.max(2, Math.floor((width - PAD * 2) / 70));
		const step = [1, 2, 5, 10].find((s) => years.length / s <= fit) || 10;
		return years.filter((y) => Number(y.year) % step === 0).map((y) => ({ x: xOf(y.start), label: y.year }));
	});

	// The months grouped into years: [{ year, start, end }] (month indices).
	const years = $derived.by(() => {
		const out = [];
		for (let i = start; i < months.length; i++) {
			const yr = months[i].slice(0, 4);
			if (!out.length || out[out.length - 1].year !== yr) out.push({ year: yr, start: i, end: i });
			else out[out.length - 1].end = i;
		}
		return out;
	});

	const n = $derived(Math.max(months.length - 1 - start, 1));
	const xOf = (i) => PAD + ((i - start) / n) * (width - PAD * 2);
	const idxAt = (px) => start + Math.round(((px - PAD) / (width - PAD * 2)) * n);

	// The year bucket a month index falls in.
	function yearIndexOf(idx) {
		if (!years.length) return 0;
		const i = Math.max(start, Math.min(idx, months.length - 1));
		for (let yi = 0; yi < years.length; yi++) if (i <= years[yi].end) return yi;
		return years.length - 1;
	}
	const loYear = $derived(yearIndexOf(lo));
	const hiYear = $derived(yearIndexOf(hi));
	const isFiltered = $derived(months.length > 0 && (lo > start || hi < months.length - 1));

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
		lo = start;
		hi = Math.max(months.length - 1, 0);
	}
</script>

<div class="brush" class:zoomed={isFiltered} class:active={drag !== null} style="padding-right: {Math.max(0, inset - 6)}px">
	<div class="brush-track" bind:clientWidth={width} title="Drag to choose which years the chart shows">
		<svg
			viewBox="0 0 {width} {height}"
			class:dragging={drag !== null}
			role="application"
			aria-label="Choose which years the chart shows"
			onpointerdown={onPointerDown}
			onpointermove={onPointerMove}
			onpointerup={onPointerUp}
			onpointercancel={onPointerUp}
		>
			<path class="hist" d={areaPath} />
			<line class="base" x1={PAD} x2={width - PAD} y1={AREA_H} y2={AREA_H} />
			<!-- the selected years: a light window over the silhouette -->
			<rect class="window" x={xOf(lo)} y="0" width={Math.max(2, xOf(hi) - xOf(lo))} height={AREA_H} />
			<!-- draggable edge handles (focusable; arrow keys move a year) -->
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
					<rect class="grip-hit" x={xOf(idx) - 9} y="0" width="18" height={AREA_H} />
					<rect class="grip" x={xOf(idx) - 2.5} y="4" width="5" height={AREA_H - 8} rx="2" />
				</g>
			{/each}
			{#each yearTicks as t}
				<text class="yr" x={t.x} y={AREA_H + 14} text-anchor={t.x < 20 ? "start" : "middle"}>{t.label}</text>
			{/each}
		</svg>
	</div>
	{#if isFiltered}<button class="brush-reset" onclick={reset}>Show all years</button>{/if}
</div>

<style>
	/* Tucked right under the chart's axis labels. */
	.brush { margin: 2px 0 0; font-family: var(--font-sans); }
	.brush-reset {
		display: block;
		margin: 4px 0 0 auto;
		background: none;
		border: 0;
		padding: 0;
		font: inherit;
		font-size: 12px;
		color: var(--color-fg-light);
		text-decoration: underline;
		text-underline-offset: 3px;
		cursor: pointer;
	}
	.brush-reset:hover { color: var(--color-fg); }
	.brush-track { min-width: 0; }
	svg {
		display: block;
		width: 100%;
		height: auto;
		overflow: visible;
		touch-action: none; /* so dragging works on phones */
		cursor: pointer;
	}
	svg.dragging { cursor: grabbing; }
	/* Quiet at rest (gray, no outline) while it shows every year; blue once
	   you hover, focus or drag it, and whenever it's zoomed in. */
	.hist { fill: #dddbd4; }
	.base { stroke: #b5b5b5; stroke-width: 1; }
	.window { fill: transparent; stroke: transparent; stroke-width: 1; transition: fill 0.15s, stroke 0.15s; }
	.handle { cursor: ew-resize; outline: none; }
	.grip-hit { fill: transparent; }
	.grip { fill: #b9b9b9; transition: fill 0.15s; }
	.brush:hover .window, .brush:focus-within .window, .brush.zoomed .window, .brush.active .window { fill: rgba(63, 136, 204, 0.12); stroke: #3f88cc; }
	.brush:hover .grip, .brush:focus-within .grip, .brush.zoomed .grip, .brush.active .grip { fill: #3f88cc; }
	.handle:hover .grip { fill: #26597f; }
	.handle:focus-visible .grip { fill: #26597f; stroke: #fff; stroke-width: 1.5; }
	.yr { font-size: 11px; fill: #8a8a8a; }
</style>
