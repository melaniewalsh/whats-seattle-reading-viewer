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
		annotations = [],  // [{ month, end, label, short, blurb, url }] — shaded event bands
		peak = null,      // { idx, value, month } — a static callout pointing at the peak
		legendHoverKey = null,  // key of the legend entry being hovered -> light up its band(s)
		unit = 'checkouts a month', // appended to the top y-axis label only (NYT style)
		smooth = false,   // line mode: draw 3-month averages, with the raw monthly
		                  // values of the main series as faint bars behind
		markers = [],     // [{ month, label, sub }] — labelled moments on the main line
		endLabels = true, // line mode: label each line at its right end
		onSeriesClick = null, // click an end label: (key) => … (e.g. isolate that line)
		percent = false,  // values are percentages (the genre shares), not counts
		plotInset = $bindable(0) // out: the plot's right margin, so a page can align to its edge
	} = $props();

	// Numbers on the axis, end labels and tooltip: counts ("1,200") or, with
	// `percent`, shares with just enough decimals ("12%", "2.5%", "0.15%").
	function fmtVal(v) {
		if (!percent) return Math.round(v).toLocaleString();
		const a = Math.abs(v);
		return `${parseFloat(v.toFixed(a < 1 ? 2 : a < 10 ? 1 : 0))}%`;
	}
	// End labels: big counts abbreviated ("289k"), so they stay short.
	function fmtEnd(v) {
		if (percent || Math.abs(v) < 10000) return fmtVal(v);
		const k = v / 1000;
		return `${k >= 100 ? Math.round(k) : parseFloat(k.toFixed(1))}k`;
	}
	// Axis numbers abbreviated: 500, 1k, 1.5k, 2M.
	const fmtTick = (t) => (percent ? fmtVal(t) : abbrevNum(t));
	// The unit after the top y label; a phone gets only its first word ("1,200
	// checkouts"), or none for a percentage ("12%").
	const unitText = (w) => (!unit ? '' : w >= 560 ? unit : percent ? '' : unit.split(' ')[0]);

	// Measured from the container (bind:clientWidth) so the chart fits any
	// screen -- without this the SVG renders at a fixed 720px and pushes the
	// whole page sideways on phones.
	let width = $state(720);
	const height = $derived(width < 520 ? 300 : 380);
	// Month-tick mode (narrow year window) draws a second axis row for the
	// year, so it needs a little more room at the bottom.
	const monthTickMode = $derived(months.length > 0 && months.length <= 48);
	// Margins. The y-axis labels sit INSIDE the plot (on their gridlines), so the
	// left margin is ~0. The top grows to fit book markers or event labels; the
	// right grows to fit end-of-line labels.
	const markerCount = $derived((markers || []).filter((mk) => months.includes(mk.month)).length);
	const hasMarkers = $derived(mode === 'line' && (markers || []).some((mk) => months.includes(mk.month)));
	const endLabelW = $derived.by(() => {
		if (mode !== 'line' || !endLabels || !series.length || width < 560) return 0;
		const shown = series.filter((s) => s.values?.length);
		// A single total line has no end label (the peak gets one instead).
		if (shown.length <= 1 && (shown[0]?.isAggregate || !shown.length)) return 0;
		// Several named lines: labels wrap onto two lines, so the margin only
		// needs to fit about half the longest name (wider charts get more room).
		const longest = Math.max(...shown.map((s) => fullName(s.label).length + 1));
		const cap = width < 520 ? 124 : 200;
		return Math.min(cap, Math.max(84, Math.round(Math.min(longest, longest / 2 + 6) * 6.6 + 45)));
	});
	const margin = $derived({
		// Room for label rows above the plot: one row for a single label (e.g.
		// just the peak), two when several might need to stagger.
		top: hasMarkers ? (markerCount > 1 ? (width < 560 ? 66 : 92) : (width < 560 ? 50 : 56)) : annotations?.length ? 30 : 16,
		right: Math.max(16, endLabelW),
		bottom: monthTickMode ? 42 : 28,
		left: 2
	});
	$effect(() => { plotInset = margin.right; });
	// Line labels: cut a long work title at its subtitle, then hard-cap it.
	function shortName(label) {
		let t = String(label || '');
		// keep a short trailing qualifier like "(ebook)" and shorten the rest
		const q = t.match(/\s(\([^()]{1,12}\))$/);
		if (q) t = t.slice(0, q.index);
		if (t.length > 18) t = t.split(/[:,(]/)[0].trim();
		if (t.length > 20) t = t.slice(0, 19).trimEnd() + '…';
		return q ? `${t} ${q[1]}` : t;
	}
	// A line's name for end labels: the title without a long subtitle.
	function fullName(label) {
		let t = String(label || '');
		const q = t.match(/\s(\([^()]{1,12}\))$/);
		let base = q ? t.slice(0, q.index) : t;
		if (base.length > 30) base = base.split(/[:]/)[0].trim();
		return q ? `${base} ${q[1]}` : base;
	}
	// Greedy word-wrap into at most three lines of `n` characters; the last
	// line is cut with an ellipsis only if the name still doesn't fit.
	function wrapName(label, n, max = 3) {
		const words = fullName(label).split(/\s+/);
		const lines = [''];
		for (const w of words) {
			const cur = lines[lines.length - 1];
			if (!cur || (cur + ' ' + w).length <= n) lines[lines.length - 1] = cur ? cur + ' ' + w : w;
			else if (lines.length < max) lines.push(w);
			else lines[lines.length - 1] = cur + ' ' + w;
		}
		const k = lines.length - 1;
		if (lines[k].length > n) lines[k] = lines[k].slice(0, n - 1).trimEnd() + '…';
		return lines;
	}

	// Centered 3-month moving average (2 points at the ends).
	function avg3(a) {
		return a.map((_, i) => {
			let sum = 0, n = 0;
			for (let k = i - 1; k <= i + 1; k++) if (k >= 0 && k < a.length) { sum += a[k] || 0; n++; }
			return n ? sum / n : 0;
		});
	}

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

	// Event bands (COVID, ransomware): shade the affected months and put a short
	// two-line label at the top of the band. Both events are DIPS, so the top of
	// the band is always clear of the line. The label sits outside the band on
	// whichever side has room; hovering/focusing it shows the full note.
	const halfStep = $derived(months.length > 1 ? (x(1) - x(0)) / 2 : 0);
	const annotationMarks = $derived.by(() => {
		if (!annotations?.length || months.length < 2) return [];
		return annotations
			.map((a) => {
				const end = a.end || a.month;
				const i0 = months.findIndex((m) => m >= a.month);
				let i1 = -1;
				for (let k = months.length - 1; k >= 0; k--) if (months[k] <= end) { i1 = k; break; }
				if (i0 < 0 || i1 < i0) return null;
				const x0 = x(i0) - halfStep, x1 = x(i1) + halfStep;
				const anchor = x0 > (width - margin.right) * 0.6 ? 'end' : 'start';
				const lx = anchor === 'end' ? x0 - 5 : x1 + 5;
				// If the label would sit on the top y-axis label ("1,200 checkouts a
				// month", drawn at the left edge), drop it just below that label.
				const lw = Math.max(...(a.short || [a.label]).map((t) => t.length)) * 6.2;
				const [la, lb] = anchor === 'end' ? [lx - lw, lx] : [lx, lx + lw];
				const topTxt = yTopTick != null ? `${fmtTick(yTopTick)}${unitText(width) ? ' ' + unitText(width) : ''}` : '';
				const unitR = margin.left + topTxt.length * 6.6 + 8;
				const ty = yTopTick != null ? y(yTopTick) : margin.top;
				const clash = la < unitR && lb > margin.left && ty - 18 < margin.top + 22;
				const top = clash ? ty + 4 : margin.top - 10;
				// Dropped down among the tick numbers? Keep clear of them too.
				const tickW = Math.max(0, ...yTicks.filter((t) => t > 0 && t !== yTopTick).map((t) => fmtTick(t).length * 6.6)) + 8;
				const lx2 = clash && anchor === 'start' ? Math.max(lx, margin.left + tickW) : lx;
				const pad = 8;
				const avail = anchor === 'end' ? lx - pad : width - lx - pad;
				const maxw = Math.max(200, Math.min(320, Math.round(avail)));
				const [ra, rb] = anchor === 'end' ? [lx2 - lw, lx2] : [lx2, lx2 + lw];
				return { ...a, x0, x1, lx: lx2, anchor, maxw, top, ra, rb, lines: a.short || [a.label] };
			})
			.filter(Boolean)
			// On a narrow or zoomed-out chart two event labels can land on each
			// other (Covid and Ransomware on a phone): drop the later one a row.
			.map((m, k, all) => {
				for (const o of all.slice(0, k)) {
					if (o.top === m.top && m.ra < o.rb + 6 && m.rb > o.ra - 6) m.top += m.lines.length * 14 + 4;
				}
				return m;
			});
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

	// Line mode: with `smooth`, every line shows its 3-month average; the raw
	// monthly values stay on each layer as `raw` for the tooltip (and the bars).
	const lineLayers = $derived(
		series.map((s) => {
			const v = smooth ? avg3(s.values) : s.values;
			return { ...s, raw: s.values, values: v, bottom: null, top: v };
		})
	);
	// The series whose raw months are drawn as faint bars: the aggregate line
	// (author / work total), or the only line.
	const barLayer = $derived(
		smooth && mode === 'line'
			? lineLayers.find((s) => s.isAggregate) || (lineLayers.length === 1 ? lineLayers[0] : null)
			: null
	);

	const layers = $derived(mode === 'line' ? lineLayers : stackedSeries);

	const yMax = $derived.by(() => {
		if (!layers.length) return 1;
		if (mode === 'line') {
			let m = 0;
			for (const s of layers) for (const v of s.values) if (v > m) m = v;
			if (barLayer) for (const v of barLayer.raw) if (v > m) m = v;
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

	// Hovering a legend entry in the stacked view spotlights that series: it's
	// redrawn (summed across its editions) from baseline 0, so you read its REAL
	// values instead of its elevated position in the stack — which would otherwise
	// make a band look like it has checkouts in months where it has none.
	const spotlightArea = $derived.by(() => {
		if (!legendHoverKey || mode !== 'area' || !stackedSeries.length) return null;
		const matched = stackedSeries.filter((s) => (s.legendKey ?? s.key) === legendHoverKey);
		if (!matched.length) return null;
		const n = matched[0].values.length;
		const vals = Array.from({ length: n }, (_, i) => matched.reduce((sum, s) => sum + (s.values[i] || 0), 0));
		return {
			color: matched[0].color,
			fill: d3area().x((_, i) => x(i)).y0(() => y(0)).y1((_, i) => y(vals[i]))(vals),
			line: d3line().x((_, i) => x(i)).y((_, i) => y(vals[i]))(vals)
		};
	});

	const yTicks = $derived(y.ticks(5));
	// The topmost labelled gridline carries the unit ("1,200 checkouts a month").
	const yTopTick = $derived(yTicks.length ? yTicks[yTicks.length - 1] : null);

	// Monthly bars behind the average line (only with `smooth`).
	const barW = $derived(Math.max(0.6, Math.min(24, (months.length > 1 ? x(1) - x(0) : 8) - (months.length > 60 ? 1 : 2))));

	// Book markers: a dot on the main line at the given month, a thin leader up
	// to an italic title, staggered across two rows so neighbours don't collide.
	const markerMarks = $derived.by(() => {
		if (mode !== 'line' || !markers?.length) return [];
		const main = lineLayers.find((s) => s.isAggregate) || lineLayers[0];
		if (!main) return [];
		// Place each label in one of two rows, on whichever side of its dot fits
		// without colliding with labels already placed; on a narrow chart drop the
		// sub-line and shorten long titles. A label that fits nowhere keeps only
		// its dot.
		const narrow = width < 560;
		// Two label rows, a full label (title + sub-line) apart so a row-1 sub
		// never runs into a row-2 title.
		const rows = narrow ? [24, 44] : [24, 58];
		const placed = [[], []];
		const fits = (r, a, b) => a >= 0 && b <= width && placed[r].every(([p, q]) => b + 8 <= p || a >= q + 8);
		return markers
			.map((mk) => ({ ...mk, i: months.indexOf(mk.month) }))
			.filter((mk) => mk.i >= 0)
			.sort((a, b) => a.i - b.i)
			.map((mk) => {
				const lx = x(mk.i);
				const label = narrow ? shortName(mk.label) : mk.label;
				const sub = narrow ? '' : mk.sub || '';
				const w = Math.max(label.length * 7.2, sub.length * 6);
				const sides = lx + w > width - 4 ? ['end', 'start'] : ['start', 'end'];
				let spot = null;
				for (const r of [0, 1]) {
					for (const side of sides) {
						const a = side === 'start' ? lx - 4 : lx + 4 - w;
						if (fits(r, a, a + w)) { spot = { r, side, a }; break; }
					}
					if (spot) break;
				}
				if (spot) placed[spot.r].push([spot.a, spot.a + w]);
				return {
					...mk, label, sub, lx, ly: y(main.values[mk.i] || 0),
					ty: spot ? rows[spot.r] : null, end: spot?.side === 'end', hideText: !spot
				};
			});
	});

	// End-of-line labels. One line: its last value and month. Several lines: the
	// name and value of each, nudged apart vertically with a small leader line.
	const endMarks = $derived.by(() => {
		// Phones: no end labels; the page shows a swatch legend under the chart.
		if (mode !== 'line' || !endLabels || !lineLayers.length || months.length < 2 || width < 560) return [];
		const last = months.length - 1;
		// A total line gets no "latest month" label: it read as the book's size
		// ("1 in July"). Only named lines (books, formats, genres) are labelled.
		if (lineLayers.some((s) => s.isAggregate)) return [];
		const shown = lineLayers;
		const n = Math.max(10, Math.floor((margin.right - 45) / 6.6));
		const items = shown.map((s) => ({ s, v: s.values[last] || 0, ey: y(s.values[last] || 0), lines: wrapName(s.label, n) }));
		items.sort((a, b) => a.ey - b.ey);
		const lh = 14;
		// Each label needs (lines × line height) + a little air below it.
		items.forEach((it, k) => {
			const prev = items[k - 1];
			it.ty = k ? Math.max(it.ey, prev.ty + prev.lines.length * lh + 3) : it.ey;
		});
		const floor = height - margin.bottom - 2;
		for (let k = items.length - 1; k >= 0; k--) {
			const h = (items[k].lines.length - 1) * lh;
			const cap = k === items.length - 1 ? floor - h : items[k + 1].ty - items[k].lines.length * lh - 3;
			if (items[k].ty > cap) items[k].ty = cap;
		}
		return items;
	});
	// AP-style month for the end label: "in July." / "in Aug." / "in Sept."
	const AP_MONTHS = ['Jan.', 'Feb.', 'March', 'April', 'May', 'June', 'July', 'Aug.', 'Sept.', 'Oct.', 'Nov.', 'Dec.'];
	// A line's end label being hovered: highlights that line like a legend hover.
	let endHoverKey = $state(null);
	const focusKey = $derived(legendHoverKey ?? endHoverKey);
	const keyOf = (s) => s.legendKey ?? s.key ?? s.label;
	const lastMonthLabel = $derived(months.length ? AP_MONTHS[Number(months[months.length - 1].slice(5, 7)) - 1] : '');

	// Abbreviate axis numbers: 700000 -> "700k", 1200000 -> "1.2M", 1500 -> "1.5k".
	function abbrevNum(n) {
		const a = Math.abs(n);
		if (a >= 1e6) { const v = n / 1e6; return (Number.isInteger(v) ? v : v.toFixed(1)) + "M"; }
		if (a >= 1e3) { const v = n / 1e3; return (Number.isInteger(v) ? v : v.toFixed(1)) + "k"; }
		return String(n);
	}
	// In month-tick mode, one label per year centered under that year's months;
	// a year with too little room (a sliver at the window's edge) is skipped.
	const yearSpans = $derived.by(() => {
		if (!monthTickMode || !months.length) return [];
		const spans = [];
		months.forEach((m, i) => {
			const yr = m.slice(0, 4);
			const last = spans[spans.length - 1];
			if (last && last.year === yr) last.i1 = i;
			else spans.push({ year: yr, i0: i, i1: i });
		});
		const multi = spans.length > 1;
		return spans
			.map((sp) => ({ year: sp.year, x0: x(sp.i0), x1: x(sp.i1), cx: (x(sp.i0) + x(sp.i1)) / 2, multi }))
			.filter((sp) => !multi || sp.x1 - sp.x0 >= 34);
	});
	// X-axis ticks. Over a long window: one tick per January, thinned so year
	// labels never collide on a narrow screen (~44px per label). Once the year
	// brush narrows the window to a few years, years alone are too coarse (a
	// two-year window would get two labels), so switch to month ticks, spaced
	// 1/2/3/4/6 months apart to fit, with the year shown on each January.
	const xTicks = $derived.by(() => {
		const innerW = width - margin.left - margin.right;
		if (monthTickMode) {
			const maxLabels = Math.max(2, Math.floor(innerW / 40));
			const step = [1, 2, 3, 4, 6].find((st) => Math.ceil(months.length / st) <= maxLabels) || 12;
			const ticks = months
				.map((m, i) => ({ i, year: m.slice(0, 4), mo: Number(m.slice(5, 7)) }))
				.filter((d) => (d.mo - 1) % step === 0);
			// Month on the first row; the year on a second row under each January
			// (and under the first tick, so the year is never off-screen).
			return ticks.map((d, k) => ({
				i: d.i,
				label: MONTH_NAMES[d.mo - 1].slice(0, 3),
				yearLabel: d.mo === 1 || k === 0 ? d.year : null
			}));
		}
		const all = months
			.map((m, i) => ({ i, year: m.slice(0, 4), isJan: m.endsWith('-01') }))
			.filter((d) => d.isJan);
		const maxLabels = Math.max(2, Math.floor(innerW / 40));
		const step = Math.ceil(all.length / maxLabels);
		// The first year in full, then abbreviated: 2017, '18, '19 ...
		return all
			.filter((_, i) => i % step === 0)
			.map((d, k) => ({ i: d.i, label: k === 0 ? d.year : `’${d.year.slice(2)}`, yearLabel: null }));
	});

	let hoverIndex = $state(null);
	let hoveredSeriesKey = $state(null); // Track the active book layer
	let pointerY = $state(0); // cursor height (viewBox units), for a steady tooltip
	let svgEl; // the plot <svg>, for hit-testing taps outside it
	// On touch there's no hover: a tap PINS the tooltip so it survives the finger
	// lifting, and it's placed away from the finger (see tooltipTop). Mouse keeps
	// the live hover behaviour (pinned stays false).
	let pinned = $state(false);

	// Shared hit-test: set hoverIndex (month) + hoveredSeriesKey (layer) from a
	// pointer position over the plot.
	function locate(event) {
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
				// near the drawn (average) line, or the raw month's bar top
				const d = Math.min(Math.abs(y(s.values[hoverIndex]) - py), Math.abs(y((s.raw ?? s.values)[hoverIndex]) - py));
				if (d < bestDist) { bestDist = d; best = s; }
			}
			// A mouse far from every line shows nothing; a tap is deliberate.
			if (!pinned && event.pointerType !== 'touch' && bestDist > 32) { hoverIndex = null; hoveredSeriesKey = null; return; }
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

	function onMove(event) {
		// Touch moves only matter once a tap has pinned (drag to scrub); ignore the
		// browser's synthetic touch-hover noise otherwise.
		if (event.pointerType === 'touch' && !pinned) return;
		locate(event);
	}

	function onDown(event) {
		if (event.pointerType !== 'touch') return; // mouse uses hover, not tap
		event.preventDefault(); // don't let the tap turn into text selection / a click
		pinned = true;
		locate(event);
	}

	function onLeave() {
		if (pinned) return; // a pinned (touch) tooltip stays put when the finger lifts
		hoverIndex = null;
		hoveredSeriesKey = null;
	}

	function dismiss() {
		pinned = false;
		hoverIndex = null;
		hoveredSeriesKey = null;
	}

	// While pinned, a tap anywhere outside the plot dismisses the tooltip.
	$effect(() => {
		if (!pinned) return;
		const handler = (e) => { if (!svgEl || !svgEl.contains(e.target)) dismiss(); };
		document.addEventListener('pointerdown', handler, true);
		return () => document.removeEventListener('pointerdown', handler, true);
	});

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

	// Mouse: the card sits BESIDE the hovered point (right of it, or left in the
	// chart's right half), never on top of the point or the cursor.
	const tooltipSide = $derived(hoverIndex !== null && x(hoverIndex) > width * 0.55 ? 'left' : 'right');
	const tooltipLeft = $derived(
		hoverIndex === null ? 0 : pinned ? Math.min(Math.max(x(hoverIndex), 100), width - 100) : x(hoverIndex)
	);

	// Float the tooltip at the cursor's height (not the data point's) so it tracks
	// the mouse smoothly instead of bouncing up and down a spiky line. The dot and
	// dashed guide still mark the exact data point.
	// When pinned (touch), park the card on the OPPOSITE vertical half from the
	// finger so the finger never covers it: finger in the lower half → card at top,
	// finger in the upper half → card at bottom.
	const tooltipTop = $derived(
		hoverIndex === null ? margin.top
			: pinned ? (pointerY < height / 2 ? height - margin.bottom : margin.top)
			: Math.min(Math.max(pointerY, margin.top + 50), height - margin.bottom - 50)
	);
	const tooltipBelow = $derived(
		hoverIndex !== null && (pinned ? pointerY >= height / 2 : tooltipTop < 90)
	);

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
        // Hovering a legend entry lights up its band(s) and dims the rest hard — this
        // takes precedence over the cursor-driven hover highlight.
        if (focusKey) {
            const lk = p.legendKey ?? p.key;
            // In area mode the matched band is redrawn from baseline 0 (spotlightArea),
            // so hide its stacked copy; in line mode the lines are already from 0.
            if (lk === focusKey) return mode === 'area' ? 0 : 0.95;
            return 0.08;
        }
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

    // The crisp top-edge outlines read stronger than a faded fill at the same
    // opacity, so during a legend hover fade the non-hovered outlines almost to
    // nothing — otherwise they "pop" over the dimmed areas.
    function topLineOpacity(p) {
        if (focusKey) {
            const lk = p.legendKey ?? p.key;
            if (lk === focusKey) return mode === 'area' ? 0 : 0.95;
            return 0.03;
        }
        return pathOpacity(p);
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
		bind:this={svgEl}
		class="plot-svg"
		viewBox="0 0 {width} {height}"
		role="img"
		aria-label="Checkouts over time"
		onpointerdown={onDown}
		onpointermove={onMove}
		onpointerleave={onLeave}
	>
		<!-- Event bands (COVID, ransomware): shaded months behind everything -->
		{#each annotationMarks as a}
			<rect class="ev-band" x={a.x0} width={Math.max(2, a.x1 - a.x0)} y={margin.top - 12} height={height - margin.bottom - margin.top + 12} />
		{/each}

		<!-- Horizontal gridlines only; the labels sit inside the plot on their line -->
		{#each yTicks as tick}
			<line class="gridline" class:zero={tick === 0} x1={margin.left} x2={width - margin.right + 4} y1={y(tick)} y2={y(tick)} />
		{/each}


		<!-- X axis: small ticks under the baseline, no vertical gridlines -->
		{#each xTicks as tick}
			<g class="tick x-tick" transform="translate({x(tick.i)}, 0)">
				<line class="x-tickmark" y1={height - margin.bottom} y2={height - margin.bottom + 5} />
				<text y={height - margin.bottom + 18} text-anchor="middle">{tick.label}</text>
			</g>
		{/each}
		<!-- Month ticks: each year's label sits centered under its run of months
		     (not off the left edge under January). -->
		{#each yearSpans as ys}
			<text class="x-year" x={ys.cx} y={height - margin.bottom + 37} text-anchor="middle">{ys.year}</text>
		{/each}

		<!-- Layers: overlaid lines (line mode) or stacked areas (area mode) -->
		{#if mode === 'line'}
			{#if barLayer}
				<g class="month-bars" fill={barLayer.color}>
					{#each barLayer.raw as v, i}
						{#if v > 0}<rect x={x(i) - barW / 2} width={barW} y={y(v)} height={Math.max(0, y(0) - y(v))} />{/if}
					{/each}
				</g>
			{/if}
			{#each linePaths as p}
				<path
					d={p.d}
					fill="none"
					stroke={p.color}
					stroke-width={p.isAggregate ? 2.25 : 2}
					stroke-linejoin="round"
					stroke-linecap="round"
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
					opacity={topLineOpacity(p)}
					class="area-top"
				/>
			{/each}
			{#if spotlightArea}
				<!-- Legend-hovered series, redrawn from baseline 0 to show its real values -->
				<path d={spotlightArea.fill} fill={spotlightArea.color} fill-opacity="0.78" stroke="none" opacity="0.95" class="area-path spotlight" />
				<path d={spotlightArea.line} fill="none" stroke={spotlightArea.color} stroke-width="1.75" stroke-linejoin="round" opacity="0.95" class="area-top spotlight" />
			{/if}
		{/if}

		<!-- Static peak callout: a dot on the peak + its month and checkouts -->
		{#if peak}
			{@const px = x(peak.idx)}
			{@const py = y(peak.value)}
			{@const rightSide = px < width * 0.6}
			<g class="peak-callout" pointer-events="none">
				<circle cx={px} cy={py} r="3.5" fill="#3f88cc" stroke="#fff" stroke-width="1.5" />
				<text
						x={rightSide ? px + 8 : px - 8}
						y={py + 4}
						text-anchor={rightSide ? 'start' : 'end'}
						class="peak-label"
				>Peak: {formatMonth(peak.month)} · {peak.value.toLocaleString()} checkouts</text>
			</g>
		{/if}

		<!-- Book markers: dot on the main line, leader up to an italic title -->
		{#each markerMarks as mk}
			<g class="marker" pointer-events="none">
				{#if !mk.hideText}
					<line class="marker-leader" x1={mk.lx} x2={mk.lx} y1={mk.ty + (mk.sub ? 20 : 6)} y2={mk.ly - 6} />
					<text class="marker-title" class:peak={mk.kind === 'peak'} x={mk.end ? mk.lx + 4 : mk.lx - 4} y={mk.ty} text-anchor={mk.end ? 'end' : 'start'}>{mk.label}</text>
					{#if mk.sub}
						<text class="marker-sub" x={mk.end ? mk.lx + 4 : mk.lx - 4} y={mk.ty + 14} text-anchor={mk.end ? 'end' : 'start'}>{mk.sub}</text>
					{/if}
				{/if}
				<circle class="marker-dot" cx={mk.lx} cy={mk.ly} r="3" />
			</g>
		{/each}

		<!-- End-of-line labels -->
		{#each endMarks as it}
			{@const ex = x(months.length - 1)}
			<circle class="end-dot" cx={ex} cy={it.ey} r="4" fill={it.s.color} />
			{#if endMarks.length === 1 && it.s.isAggregate}
				<text class="end-value" x={ex + 8} y={it.ey - 2}>{fmtEnd(it.v)}</text>
				<text class="end-sub" x={ex + 8} y={it.ey + 12}>in {lastMonthLabel}</text>
			{:else}
				<!-- A thin connector in the line's color runs to a swatch before the
				     name, like the legend (the text stays dark to read well). -->
				<path class="end-leader" class:dim={focusKey && focusKey !== keyOf(it.s)} stroke={it.s.color} d="M{ex + 5},{it.ey} L{ex + 9},{it.ey} L{ex + 15},{it.ty - 4}" />
				<rect class="end-swatch" class:dim={focusKey && focusKey !== keyOf(it.s)} fill={it.s.color} x={ex + 15} y={it.ty - 9} width="9" height="9" rx="2" />
				<text class="end-name" class:dim={focusKey && focusKey !== keyOf(it.s)} class:clickable={!!onSeriesClick}
					x={ex + 29} y={it.ty} role={onSeriesClick ? 'button' : undefined} tabindex={onSeriesClick ? 0 : undefined}
					onmouseenter={() => (endHoverKey = keyOf(it.s))} onmouseleave={() => (endHoverKey = null)}
					onfocus={() => (endHoverKey = keyOf(it.s))} onblur={() => (endHoverKey = null)}
					onclick={() => onSeriesClick?.(keyOf(it.s))}
					onkeydown={(e) => { if ((e.key === 'Enter' || e.key === ' ') && onSeriesClick) { e.preventDefault(); onSeriesClick(keyOf(it.s)); } }}>{#each it.lines as ln, k}<tspan x={ex + 29} dy={k ? 14 : 0}>{ln}</tspan>{/each}</text>
			{/if}
		{/each}

		<!-- y-axis labels, drawn last with a halo so lines never cover them -->
		{#each yTicks as tick}
			{#if tick > 0}
				<text class="y-label" x={margin.left + 6} y={y(tick) - 5}>{fmtTick(tick)}{tick === yTopTick && unitText(width) ? ` ${unitText(width)}` : ''}</text>
			{/if}
		{/each}

		<!-- Hover marker: a thin vertical rule plus a dot on the hovered line(s) -->
		{#if hoverIndex !== null}
			<line class="hover-guide" x1={x(hoverIndex)} x2={x(hoverIndex)} y1={margin.top - 12} y2={height - margin.bottom} />
			{#if selectedItem && selectedItem.values[hoverIndex] > 0}
				<circle class="hover-dot" cx={x(hoverIndex)} cy={y(selectedItem.top[hoverIndex])} r="5" fill={selectedItem.color} />
			{/if}
		{/if}
	</svg>
	<!-- Event labels: short text at the top of each band; hover/focus for the note -->
	{#each annotationMarks as a}
		<div class="ev-wrap align-{a.anchor}" style="left: {a.lx}px; top: {a.top}px;">
			<span class="ev-label" tabindex="0" role="button" aria-label="{a.label}: about this dip">{#each a.lines as ln}<span class="ev-line">{ln}</span>{/each}</span>
			<div class="qmark-pop" role="tooltip" style="max-width: {a.maxw}px;">
				<p class="qmark-body"><strong>{a.label}.</strong> {a.blurb} <a href={a.url} target="_blank" rel="noopener noreferrer">Read more</a></p>
			</div>
		</div>
	{/each}
	{#if hoverIndex !== null && selectedItem}
        <div class="tooltip {pinned ? '' : 'side-' + tooltipSide}" class:below={pinned && tooltipBelow} style="left: {tooltipLeft}px; top: {tooltipTop}px;">
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
                <div class="tt-value">{percent ? fmtVal((selectedItem.raw ?? selectedItem.values)[hoverIndex]) : (selectedItem.raw ?? selectedItem.values)[hoverIndex].toLocaleString()}<span class="tt-value-unit">{percent ? "of checkouts" : "checkouts"}</span></div>
                {#if smooth && mode === 'line'}<div class="tt-avg">3-month avg. {fmtVal(selectedItem.values[hoverIndex])}</div>{/if}
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
            {:else if mode !== 'line'}
                <div class="tooltip-total">
                    <span>Overall month total</span>
                    <span>{Math.round(hoveredTotal).toLocaleString()}</span>
                </div>
            {/if}
        </div>
    {/if}
</div>

<style>
	/* Event bands + labels (COVID, ransomware). The label sits beside the band
	   at its top; hovering or focusing it reveals the note. */
	.ev-band { fill: rgba(0, 0, 0, 0.045); }
	.ev-wrap {
		position: absolute;
		z-index: 7;
	}
	.ev-wrap.align-end { transform: translateX(-100%); text-align: right; }
	.ev-label {
		display: inline-flex;
		flex-direction: column;
		font-family: var(--font-sans, system-ui, sans-serif);
		font-size: 11px;
		line-height: 1.25;
		color: #858585;
		cursor: help;
		text-shadow: 0 0 3px #fff, 0 0 3px #fff, 0 0 2px #fff;
	}
	.ev-line { border-bottom: 1px dotted transparent; }
	.ev-label:hover .ev-line,
	.ev-label:focus .ev-line { color: var(--color-fg, #1a1a1a); }
	.ev-label:focus { outline: none; }
	.ev-label:focus-visible { outline: 2px solid #3f88cc; outline-offset: 2px; border-radius: 2px; }
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
	.ev-wrap.align-end .qmark-pop { left: auto; right: 0; transform: none; text-align: left; }
	.ev-wrap.align-start .qmark-pop { left: 0; transform: none; }
	.ev-wrap:hover .qmark-pop,
	.ev-wrap:focus-within .qmark-pop { display: block; }

	/* Axes: horizontal hairlines, a darker zero baseline, labels inside the plot */
	.gridline { stroke: #e8e7e2; stroke-width: 1; }
	.gridline.zero { stroke: #555; }
	.x-tickmark { stroke: #555; stroke-width: 1; }
	.y-label {
		font-family: var(--font-sans, system-ui, sans-serif);
		font-size: 12px;
		fill: #7a7a7a;
		paint-order: stroke;
		stroke: #fff;
		stroke-width: 3px;
		stroke-linejoin: round;
	}
	.month-bars { opacity: 0.28; }

	/* Book markers */
	.marker-leader { stroke: #8a8a8a; stroke-width: 0.75; }
	.marker-dot { fill: #1a1a1a; stroke: #fff; stroke-width: 1.5; }
	.marker-title {
		font-family: var(--font-serif, Georgia, serif);
		font-style: italic;
		font-size: 13.5px;
		fill: #1a1a1a;
		paint-order: stroke;
		stroke: #fff;
		stroke-width: 3px;
	}
	.marker-sub {
		font-family: var(--font-sans, system-ui, sans-serif);
		font-size: 11px;
		fill: #858585;
		paint-order: stroke;
		stroke: #fff;
		stroke-width: 3px;
	}

	/* End-of-line labels */
	.end-dot { stroke: #fff; stroke-width: 2; }
	.end-value { font-family: var(--font-sans, system-ui, sans-serif); font-size: 12px; font-weight: 600; fill: #1a1a1a; }
	.end-sub { font-family: var(--font-sans, system-ui, sans-serif); font-size: 11px; fill: #858585; }
	.end-leader { fill: none; stroke-width: 1; transition: opacity 0.12s; }
	.end-swatch { transition: opacity 0.12s; }
	.end-leader.dim, .end-swatch.dim { opacity: 0.2; }
	.end-name { font-family: var(--font-sans, system-ui, sans-serif); font-size: 12px; fill: #1a1a1a; transition: opacity 0.12s; }
	.end-name.clickable { cursor: pointer; }
	.end-name.clickable:hover { text-decoration: underline; }
	.end-name.dim { opacity: 0.3; }
	.end-name:focus { outline: none; }
	.end-num { fill: #858585; }

	/* Hover */
	.hover-guide { stroke: #9a9a9a; stroke-width: 0.75; }
	.hover-dot { stroke: #fff; stroke-width: 2; }
	.tt-avg { font-size: 12px; color: #858585; margin-top: 2px; }
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
	/* Let a vertical swipe scroll the page as normal, but capture horizontal drags
	   for scrubbing the tooltip; a plain tap pins it. */
	.plot-svg {
		touch-action: pan-y;
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
	.peak-label {
		font-family: var(--font-sans);
		font-size: 0.72rem;
		font-weight: 700;
		fill: var(--color-fg);
		/* white halo so it reads over the filled area */
		paint-order: stroke;
		stroke: var(--color-bg, #fff);
		stroke-width: 3.5px;
		stroke-linejoin: round;
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

	text.x-year { font-size: 11px; font-weight: 600; fill: #555; }
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
	/* Mouse: beside the point, vertically centered on the pointer */
	.tooltip.side-right { transform: translate(18px, -50%); }
	.tooltip.side-left { transform: translate(calc(-100% - 18px), -50%); }

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
		color: var(--color-fg);
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
		color: var(--color-fg);
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
		color: var(--color-fg);
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