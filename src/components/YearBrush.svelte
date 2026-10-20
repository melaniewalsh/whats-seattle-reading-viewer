<script>
	// YearBrush.svelte
	// =================
	// A plain year-range slider under the main chart: a thin track with two
	// round handles that snap to whole years, the first and last years shown
	// at either end. Drag a handle to trim the range, drag between them to
	// slide it, or use the arrow keys when a handle is focused. The parent
	// binds `lo`/`hi` (month indices, inclusive) and slices its own data.
	//
	// Props:
	//   months : string[]  full shared month axis, e.g. ["2006-01", ...]
	//   lo, hi : bindable month indices of the selected window (inclusive)
	//   start  : first month index the slider covers (skips the empty years
	//            before a book or author first circulated)
	//   inset  : the chart's right margin, so the slider stops at the plot's edge
	let { months = [], start = 0, inset = 0, lo = $bindable(0), hi = $bindable(0) } = $props();

	const uid = $props.id();

	let width = $state(680); // measured from the container
	const PAD = 10; // room for the round handles at either end
	const PLOT_LEFT = 2; // the chart's left margin (its plot starts 2px in)
	const TRACK_Y = 12;
	const height = 24;

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

	// Year labels sit under their handles (kept inside the track's ends). When
	// the two would touch they merge into one "2019–2021" label. "All years"
	// goes in the widest free stretch: left of, between, or right of them.
	const YW = 32; // a four-digit year at 12.5px
	const RW = 58; // the "All years" link
	const labels = $derived.by(() => {
		const loX = xOf(lo), hiX = xOf(hi);
		const loLeft = Math.max(PAD, loX - YW / 2);
		const hiLeft = Math.min(width - PAD - YW, hiX - YW / 2);
		const lyr = years[loYear]?.year, hyr = years[hiYear]?.year;
		let items;
		if (hiLeft - (loLeft + YW) < 10) {
			const text = lyr === hyr ? lyr : `${lyr}–${hyr}`;
			const w = lyr === hyr ? YW : YW * 2 + 8;
			const left = Math.max(PAD, Math.min(width - PAD - w, (loX + hiX) / 2 - w / 2));
			items = [{ text, left, w }];
		} else {
			items = [{ text: lyr, left: loLeft, w: YW }, { text: hyr, left: hiLeft, w: YW }];
		}
		// Free stretches between the labels and the track's ends.
		const edges = [PAD, ...items.flatMap((it) => [it.left, it.left + it.w]), width - PAD];
		let best = null;
		for (let i = 0; i < edges.length; i += 2) {
			const gap = edges[i + 1] - edges[i];
			if (!best || gap > best.gap) best = { gap, a: edges[i], b: edges[i + 1], i };
		}
		const last = edges.length - 2;
		const resetLeft = best.i === 0 ? PAD : best.i === last ? width - PAD - RW : (best.a + best.b) / 2 - RW / 2;
		return { items, resetLeft };
	});

	function reset() {
		lo = start;
		hi = Math.max(months.length - 1, 0);
	}
</script>

<!-- A plain range slider: a thin track exactly as wide as the plot above it
     (the handles' centers land on the plot's first and last months), with the
     years shown printed under its two ends. Drag a handle, drag the darker
     stretch between them, or use the arrow keys. -->
<div class="brush" class:active={drag !== null}>
	<div class="brush-track" style="margin: 0 {inset - PAD}px 0 {PLOT_LEFT - PAD}px" bind:clientWidth={width} title="Drag to choose which years the chart shows">
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
			<rect class="hit" x="0" y="0" width={width} height={height} />
			<line class="track" x1={PAD} x2={width - PAD} y1={TRACK_Y} y2={TRACK_Y} />
			<line class="range" x1={xOf(lo)} x2={xOf(hi)} y1={TRACK_Y} y2={TRACK_Y} />
			{#each [["lo", lo, loYear], ["hi", hi, hiYear]] as [which, idx, yi] (which)}
				<circle
					class="knob"
					cx={xOf(idx)} cy={TRACK_Y} r="8"
					role="slider"
					tabindex="0"
					aria-label={which === "lo" ? "First year shown" : "Last year shown"}
					aria-valuemin={Number(years[0]?.year ?? 0)}
					aria-valuemax={Number(years[years.length - 1]?.year ?? 0)}
					aria-valuenow={Number(years[yi]?.year ?? 0)}
					aria-valuetext={years[yi]?.year}
					onkeydown={(e) => onHandleKey(e, which)}
				/>
			{/each}
		</svg>
		<div class="brush-years">
			{#each labels.items as it}<span class="yr" style="left: {it.left}px; width: {it.w}px" aria-hidden="true">{it.text}</span>{/each}
			{#if isFiltered}<button class="brush-reset" style="left: {labels.resetLeft}px; width: {RW}px" onclick={reset}>All years</button>{/if}
		</div>
	</div>
</div>

<style>
	.brush { margin: 6px 0 0; font-family: var(--font-sans); }
	.brush-years { position: relative; height: 18px; margin-top: 1px; }
	.yr { position: absolute; top: 0; font-size: 12.5px; line-height: 18px; text-align: center; white-space: nowrap; font-variant-numeric: tabular-nums; color: var(--color-fg-light); }
	svg { display: block; width: 100%; height: auto; overflow: visible; touch-action: none; cursor: pointer; }
	svg.dragging { cursor: grabbing; }
	.hit { fill: transparent; }
	.track { stroke: #dcdedf; stroke-width: 3; stroke-linecap: round; }
	.range { stroke: #9aa3ad; stroke-width: 3; stroke-linecap: round; }
	.knob { fill: #c4c8cd; stroke: #fff; stroke-width: 2; cursor: ew-resize; outline: none; transition: fill 0.12s; }
	.knob:hover, .brush.active .knob { fill: #8d959f; }
	.knob:focus-visible { fill: #6b7480; stroke: #3f88cc; stroke-width: 2.5; }
	.brush-reset { position: absolute; top: 0; line-height: 18px; text-align: center; white-space: nowrap; background: none; border: 0; padding: 0; font: inherit; font-size: 12.5px; color: var(--color-fg-light); text-decoration: underline; text-underline-offset: 3px; cursor: pointer; }
	.brush-reset:hover { color: var(--color-fg); }
</style>
