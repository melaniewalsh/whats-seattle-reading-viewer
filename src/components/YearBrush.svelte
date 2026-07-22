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
	const TRACK_Y = 8; // vertical center of the slider line
	const R = 6; // radius of the draggable dots
	const PAD = 10; // horizontal padding so the dots never clip
	const height = TRACK_Y * 2;

	// Set the range from a typed-in year (reverts the field if it's not a year
	// in this author's data).
	function setYearInput(e, which) {
		const y = String(e.target.value).trim();
		const yi = years.findIndex((yr) => yr.year === y);
		if (yi < 0) {
			e.target.value = which === "lo" ? years[loYear]?.year : years[hiYear]?.year;
			return;
		}
		if (which === "lo") lo = years[Math.min(yi, hiYear)].start;
		else hi = years[Math.max(yi, loYear)].end;
	}

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

<div class="brush">
	<div class="brush-row">
		<input
			class="year-input"
			type="text"
			inputmode="numeric"
			aria-label="First year shown"
			value={years[loYear]?.year ?? ""}
			onchange={(e) => setYearInput(e, "lo")}
		/>

		<div class="brush-track" bind:clientWidth={width}>
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
				<!-- the full track -->
				<line class="track" x1={PAD} x2={width - PAD} y1={TRACK_Y} y2={TRACK_Y} />
				<!-- the selected segment, in the site accent -->
				<line class="track-sel" x1={xOf(lo)} x2={xOf(hi)} y1={TRACK_Y} y2={TRACK_Y} />

				<!-- the two draggable dots (focusable, arrow keys move by a year) -->
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
				<circle class="dot" cx={xOf(idx)} cy={TRACK_Y} r={R} />
			</g>
				{/each}
			</svg>
		</div>

		<input
			class="year-input"
			type="text"
			inputmode="numeric"
			aria-label="Last year shown"
			value={years[hiYear]?.year ?? ""}
			onchange={(e) => setYearInput(e, "hi")}
		/>
	</div>

	{#if isFiltered}
		<div class="brush-foot">
			<button class="brush-reset" onclick={reset}>All years ×</button>
		</div>
	{/if}
</div>

<style>
	.brush {
		margin: 8px 0 16px;
	}

	/* the year inputs flank the slider line, OWID-timeline style */
	.brush-row {
		display: flex;
		align-items: center;
		gap: 12px;
	}

	.brush-track {
		flex: 1 1 auto;
		min-width: 0;
	}

	.year-input {
		flex: none;
		width: 3.6em;
		padding: 2px 4px;
		font-family: var(--font-sans);
		font-size: 0.75rem;
		font-weight: 600;
		text-align: center;
		color: var(--color-fg-light);
		background: var(--color-white);
		border: 1px solid var(--color-border);
		border-radius: 6px;
	}
	.year-input:hover {
		border-color: var(--color-fg-light);
	}
	.year-input:focus {
		outline: none;
		border-color: var(--color-fg);
	}

	.brush-foot {
		display: flex;
		justify-content: flex-end;
		margin-top: 4px;
	}

	.brush-reset {
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
		touch-action: none; /* so dragging the dots works on phones */
		cursor: pointer;
	}

	svg.dragging {
		cursor: grabbing;
	}

	/* the full track: a thin gray line */
	.track {
		stroke: var(--color-gray-300);
		stroke-width: 2;
		stroke-linecap: round;
	}

	/* the selected span: a slightly stronger muted line */
	.track-sel {
		stroke: var(--color-fg-light);
		stroke-width: 2;
		stroke-linecap: round;
	}

	.handle {
		cursor: grab;
		outline: none;
	}

	/* a solid dot you slide along the line */
	.dot {
		fill: var(--color-fg-light);
		stroke: var(--color-white);
		stroke-width: 2;
		transition: r 0.1s ease;
	}

	.handle:hover .dot,
	.handle:focus-visible .dot {
		r: 7.5;
	}

	.handle:focus-visible .dot {
		stroke: var(--chip-color, #6a4c93);
		stroke-width: 3;
	}
</style>
