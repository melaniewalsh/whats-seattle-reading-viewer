<script>
	// GenreChart.svelte
	// Multi-line chart of each genre's SHARE (%) of checkouts over time (monthly,
	// same axis as the author charts). Hovering shows the nearest line's share
	// for that month. Isolation (from the legend) hides the non-isolated lines
	// entirely and rescales the y-axis to the ones left visible.
	//
	// Props:
	//   months  : string[]                       "YYYY-MM" x-axis
	//   series  : [{ key, name, color, values }] values aligned to `months`, in %
	//   isolatedKeys : string[]                  when non-empty, only these stay bold
	//   annotations  : [{ month, label, blurb, url }]  a "?" marker above each event
	let { months = [], series = [], isolatedKeys = [], annotations = [] } = $props();

	const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
	function fmtMonth(ym) {
		if (!ym) return "";
		const [y, m] = ym.split("-");
		return m ? `${MONTH_NAMES[Number(m) - 1]} ${y}` : y;
	}

	let width = $state(760);
	const height = 380;
	const margin = { top: 12, right: 16, bottom: 28, left: 42 };

	const innerW = $derived(Math.max(1, width - margin.left - margin.right));
	const innerH = height - margin.top - margin.bottom;

	const n = $derived(Math.max(months.length - 1, 1));
	const xOf = (i) => margin.left + (i / n) * innerW;
	const isActive = (key) => !isolatedKeys.length || isolatedKeys.includes(key);
	// Scale the y-axis to whatever is currently visible: isolating a genre both
	// hides the others AND zooms the axis so the lone line fills the chart.
	const yMax = $derived.by(() => {
		const vals = series.filter((s) => isActive(s.key)).flatMap((s) => s.values);
		const m = vals.length ? Math.max(...vals) : 0;
		// Scale to the actual peak so isolating a tiny genre (e.g. 0.1%) zooms right
		// in; only fall back to 1 when everything is 0 (avoids a 0-height axis).
		return (m > 0 ? m : 1) * 1.08;
	});
	// Clamp to [0, yMax]: "Other" is a residual (total − overlapping genres) and can
	// go slightly negative in some months; without this the line would spill below
	// the x-axis (the SVG is overflow:visible) down onto the legend.
	const yOf = (v) => margin.top + innerH - (Math.max(0, Math.min(v, yMax)) / yMax) * innerH;

	const yTicks = $derived.by(() => {
		const step = yMax > 40 ? 10 : yMax > 16 ? 5 : yMax > 8 ? 2 : yMax > 4 ? 1
			: yMax > 2 ? 0.5 : yMax > 0.8 ? 0.2 : yMax > 0.4 ? 0.1 : yMax > 0.15 ? 0.05 : 0.02;
		const out = [];
		// Round to the step's precision so floating-point sums don't yield labels
		// like "0.150000002%".
		const dp = step < 0.1 ? 2 : step < 1 ? 1 : 0;
		for (let v = 0; v <= yMax + 1e-9; v += step) out.push(Number(v.toFixed(dp)));
		return out;
	});
	// one tick per January, thinned to ~one label per 60px
	const xTicks = $derived.by(() => {
		const jans = months.map((m, i) => ({ y: m.slice(0, 4), i })).filter((_, i) => months[i].endsWith("-01"));
		const step = Math.max(1, Math.ceil(jans.length / Math.max(2, Math.floor(innerW / 60))));
		return jans.filter((_, i) => i % step === 0);
	});

	const pathOf = (s) => s.values.map((v, i) => `${i ? "L" : "M"} ${xOf(i)} ${yOf(v)}`).join(" ");

	// "?" markers for the event dips (COVID, ransomware), same as the line
	// charts: resolve each to an x position, and anchor the popover away from
	// whichever edge it's near so it can't run off a narrow chart.
	const annotationMarks = $derived.by(() => {
		if (!annotations?.length || months.length < 2) return [];
		return annotations
			.map((a) => {
				const i = months.findIndex((m) => m === a.month || m.startsWith(a.month));
				if (i < 0) return null;
				const px = xOf(i);
				const align = px > width * 0.62 ? "end" : px < width * 0.38 ? "start" : "center";
				const pad = 8;
				const avail =
					align === "end" ? px + 10 - pad
					: align === "start" ? width - (px - 10) - pad
					: 2 * Math.min(px, width - px) - 2 * pad;
				const maxw = Math.max(180, Math.min(320, Math.round(avail)));
				return { ...a, x: px, align, maxw };
			})
			.filter(Boolean);
	});

	let hoverI = $state(null);
	let hoverKey = $state(null);
	function onMove(e) {
		const r = e.currentTarget.getBoundingClientRect();
		const px = (e.clientX - r.left) * (width / r.width);
		const py = (e.clientY - r.top) * (height / r.height);
		const i = Math.round(((px - margin.left) / innerW) * n);
		hoverI = Math.min(Math.max(i, 0), months.length - 1);
		let best = null, bestD = Infinity;
		for (const s of series) {
			if (!isActive(s.key)) continue;
			const d = Math.abs(yOf(s.values[hoverI]) - py);
			if (d < bestD) { bestD = d; best = s; }
		}
		hoverKey = best ? best.key : null;
	}
	function onLeave() { hoverI = null; hoverKey = null; }

	const hovered = $derived(hoverKey ? series.find((s) => s.key === hoverKey) : null);
	// Pin the tooltip to the data point, then ANCHOR it away from whichever edge
	// the point is near — extend left near the right side, right near the left,
	// below near the top — so it never runs off or gets squished against a side.
	const tipX = $derived(hoverI === null ? 0 : xOf(hoverI));
	const tipY = $derived(hovered && hoverI !== null ? yOf(hovered.values[hoverI]) : margin.top);
	const tipTX = $derived(tipX < width * 0.3 ? "8px" : tipX > width * 0.7 ? "calc(-100% - 8px)" : "-50%");
	const tipTY = $derived(tipY < 96 ? "16px" : "calc(-100% - 16px)");
</script>

<div class="gchart" bind:clientWidth={width}>
	<svg viewBox="0 0 {width} {height}" role="img" aria-label="Genre share over time"
		onpointermove={onMove} onpointerleave={onLeave}>
		{#each yTicks as t}
			<line class="grid" class:zero={t === 0} x1={margin.left} x2={width - margin.right} y1={yOf(t)} y2={yOf(t)} />
			<text class="ylabel" x={margin.left - 6} y={yOf(t)} dy="0.32em" text-anchor="end">{t}%</text>
		{/each}
		{#each xTicks as t}
			<text class="xlabel" x={xOf(t.i)} y={height - 8} text-anchor="middle">{t.y}</text>
		{/each}
		{#each series as s (s.key)}
			{#if isActive(s.key)}
				<path class="gline" class:hot={hoverKey === s.key} d={pathOf(s)} stroke={s.color} fill="none" />
			{/if}
		{/each}
		{#if hoverI !== null && hovered}
			<circle cx={xOf(hoverI)} cy={yOf(hovered.values[hoverI])} r="4.5" fill={hovered.color} stroke="#fff" stroke-width="2" />
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

	{#if hoverI !== null && hovered}
		<div class="gtip" style="left:{tipX}px; top:{tipY}px; transform: translate({tipTX}, {tipTY});">
			<div class="gtip-title"><span class="gtip-dot" style="background:{hovered.color}"></span>{hovered.name}</div>
			<div class="gtip-date">{fmtMonth(months[hoverI])}</div>
			<div class="gtip-val">{hovered.values[hoverI].toFixed(1)}<span class="gtip-unit">% of checkouts</span></div>
			{#if hovered.terms?.length || hovered.ficTerms?.length}
				<div class="gtip-terms"><span class="gtip-lbl">Terms</span>{hovered.terms.join(", ")}{#if hovered.ficTerms?.length}<span class="gtip-fic">{hovered.terms?.length ? " + " : ""}{hovered.ficTerms.join(", ")} <em>(only with a fiction tag)</em></span>{/if}</div>
			{/if}
			{#if hovered.examples?.length}
				<div class="gtip-lbl gtip-lbl-ex">Top titles</div>
				<ul class="gtip-ex">{#each hovered.examples as t}<li>{t}</li>{/each}</ul>
			{/if}
		</div>
	{/if}
</div>

<style>
	.gchart { position: relative; width: 100%; }
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
	.qmark-body a { color: #3f88cc; font-weight: 600; text-decoration: underline; white-space: nowrap; }
	.qmark-body a:hover { color: #26597f; }
	svg { display: block; width: 100%; height: auto; overflow: visible; }
	.grid { stroke: #eee; stroke-width: 1; }
	.grid.zero { stroke: #bbb; }
	.ylabel, .xlabel { font-family: var(--font-sans, sans-serif); font-size: 11px; fill: #888; }
	.gline { stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; transition: opacity 0.12s; }
	.gline.hot { stroke-width: 3.2; opacity: 1; }
	.gtip {
		position: absolute;
		transition: left 0.04s linear, top 0.04s linear;
		background: #fff; border: 1px solid #e4e4e4; border-radius: 12px;
		padding: 12px 16px 13px; font-family: var(--font-sans, sans-serif);
		pointer-events: none; box-shadow: 0 12px 32px rgba(0, 0, 0, 0.17);
		/* width:max-content sizes the box to its content (capped by max-width) rather
		   than to the space left of `left` — otherwise it collapses to min-width and
		   wraps when the anchor point is near the container's right edge. */
		width: max-content; min-width: 150px; max-width: 300px; z-index: 10;
	}
	.gtip-title {
		display: flex; align-items: baseline; gap: 8px;
		font-family: var(--font-serif, Georgia, serif); font-size: 1.05rem; font-weight: 600; color: #1a1a1a;
	}
	.gtip-dot { width: 11px; height: 11px; border-radius: 50%; flex: none; align-self: center; }
	.gtip-date { margin: 3px 0 8px 19px; font-size: 11px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: var(--color-fg); }
	.gtip-val { margin-left: 19px; font-size: 1.3rem; font-weight: 700; color: #1a1a1a; }
	.gtip-unit { font-size: 0.68rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; color: var(--color-fg); margin-left: 4px; }
	.gtip-lbl { font-size: 10px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; color: var(--color-fg); }
	.gtip-terms { margin: 10px 0 0 19px; font-size: 12px; color: #444; line-height: 1.4; }
	.gtip-terms .gtip-lbl { display: block; margin-bottom: 2px; }
	.gtip-fic { color: #6a4c93; }
	.gtip-fic em { color: var(--color-fg); font-size: 11px; }
	.gtip-lbl-ex { display: block; margin: 10px 0 3px 19px; }
	.gtip-ex { margin: 0 0 0 19px; padding-left: 15px; list-style: disc; }
	.gtip-ex li { font-size: 12px; color: #333; line-height: 1.45; }
</style>
