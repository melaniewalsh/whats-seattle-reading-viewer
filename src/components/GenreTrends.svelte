<script>
	// GenreTrends.svelte — the "Genres" tab.
	//
	// Each genre's raw share of checkouts, precomputed by build_partition.py
	// (books are multi-tagged, so the shares overlap).
	import { onMount } from "svelte";
	import { avg3 } from "$utils/avg3.js";
	import { HIDDEN_GENRES } from "$utils/rankGenres.js";
	import { MediaQuery } from "svelte/reactivity";
	import ImageIcon from "@lucide/svelte/icons/image";
	import LinkIcon from "@lucide/svelte/icons/link";
	import ShareIcon from "@lucide/svelte/icons/share-2";
	import { base } from "$app/paths";
	import { drawChartLogo, chartLogoWidth } from "$utils/chartLogo.js";
	import { compactNumber } from "$utils/format.js";
	import DownloadIcon from "@lucide/svelte/icons/download";
	import ChevronDownIcon from "@lucide/svelte/icons/chevron-down";
	import TableIcon from "@lucide/svelte/icons/table";
	import LineChart from "$components/StackedAreaChart.svelte";
	import DataInfo from "$components/DataInfo.svelte";
	import { EVENT_ANNOTATIONS } from "$data/eventAnnotations.js";
	import YearBrush from "$components/YearBrush.svelte";

	// Phones: the year slider and the Download/Share row run the full width
	// (the plot itself is narrower, beside the line names).
	const phone = new MediaQuery("max-width: 600px");

	// Which table section each genre belongs to.
	const GROUPS = [
		["Fiction", ["Comics & Graphic Novels", "Romance", "Fantasy", "Science Fiction", "Horror",
			"Mystery", "Thriller & Suspense", "Historical Fiction", "Western", "Mythology & Folklore",
			"Humor", "LGBTQIA+ Fiction", "African American Fiction", "Asian Fiction",
			"Hispanic & Latino Fiction", "Native American Fiction", "Indigenous Fiction",
			"Jewish Fiction", "Literary & Classic Fiction", "General Fiction", "Poetry", "Fiction"]],
		["Kids & Young Adult", ["Picture Books & Early Readers", "Young Adult", "Juvenile Fiction",
			"Juvenile Nonfiction"]],
		["Nonfiction", ["Memoir & Biography", "True Crime", "Cooking & Food", "Self-Help",
			"Business & Economics", "Health & Fitness", "Psychology", "Politics & Government", "History",
			"Science & Nature", "Religion & Spirituality", "Travel", "Sports & Recreation",
			"Parenting & Family", "Art & Photography", "Art", "Crafts & Hobbies", "Home & Garden",
			"Computers & Technology", "Philosophy", "Drama & Performing Arts", "Reference & Study",
			"Essays & Society", "Literary Criticism", "Illustrated Works", "Informational Works",
			"Instructional & Educational Works", "Readers Publications", "Nonfiction"]],
	];

	const PALETTE = [
		"#e3120b", "#1f7a4d", "#e58a00", "#4c6a9c", "#8e44ad", "#16a085",
		"#c0392b", "#2e86de", "#d35400", "#6a4c93", "#27ae60", "#b7950b",
		"#7f8c8d", "#e84393", "#2c3e50", "#d63031", "#00868b", "#a4508b",
		"#5b7c99", "#b8860b", "#8b4513", "#008080", "#9b2226", "#40534c",
		"#7d5ba6", "#c1666b", "#4d908e", "#996633", "#577590", "#a53860",
	];
	const DEFAULT_SHOWN = 6; // how many genres to plot on first load

	let raw = $state.raw(null);
	const data = $derived(raw);
	const fmtNoun = "book";
	// "By format": one genre split into print, ebook and audiobook lines, each a
	// share of ALL book checkouts, so the three add up to the genre's line.
	// (genres.json splits each genre's count by format.)
	let byFmt = $state(false);
	const FMT_LINES = [["print", "Print", "#3f88cc"], ["ebook", "Ebook", "#e58a00"], ["audiobook", "Audiobook", "#1f7a4d"]];
	let loadError = $state("");
	let shown = $state(new Set());  // genre names currently plotted
	let showOther = $state(false);  // the "Other / Unclassified" partition line
	let expanded = $state(new Set());
	let genreFilter = $state(""); // search box: filter the table by genre name OR subject term
	// Long sections start collapsed to their top few rows so the table isn't a wall of rows.
	const PREVIEW = 5;
	const COLLAPSIBLE = new Set(["Kids & Young Adult", "Nonfiction"]);
	let collapsedGroups = $state(new Set(COLLAPSIBLE));
	function toggleGroup(name) {
		const s = new Set(collapsedGroups);
		s.has(name) ? s.delete(name) : s.add(name);
		collapsedGroups = s;
	}
	// A section holding a genre that's on the chart opens, so you can see it
	// (you can still close it again). Called whenever `shown` changes.
	function openGroupsFor(names) {
		const open = GROUPS.filter(([g, list]) => collapsedGroups.has(g) && list.some((n) => names.has(n))).map(([g]) => g);
		if (open.length) collapsedGroups = new Set([...collapsedGroups].filter((g) => !open.includes(g)));
	}
	let isolatedKeys = $state([]);
	let genreOrder = $state([]);     // stable display order (by size, for colors)
	let genreByName = $state.raw({});
	let lo = $state(0);              // time-slider window (month indices, inclusive)
	let hi = $state(0);
	let chartWrap = $state(null);    // ref to the chart container, for the PNG export
	let shareOpen = $state(false);   // whether the share popover is open
	let shareMsg = $state("");       // transient toast after copy/save
	// One timer for the toast, so a second message isn't cleared early by the first one's timer.
	let flashTimer;
	function flash(msg, ms = 2600) {
		clearTimeout(flashTimer);
		shareMsg = msg;
		flashTimer = setTimeout(() => (shareMsg = ""), ms);
	}
	let dlOpen = $state(false);      // Download menu (Data / Image)
	let smoothOn = $state(true);     // 3-month averages, as on the author pages
	let legendHoverKey = $state(null);
	let plotInset = $state(0); // the chart's right margin, to line the footer up with the plot's edge

	onMount(async () => {
		try {
			const res = await fetch(`${base}/genres.json`);
			if (!res.ok) throw new Error(String(res.status));
			const d = await res.json();
			const by = {};
			for (const g of d.genres) by[g.name] = g;
			const order = [...d.genres].filter((g) => !HIDDEN_GENRES.has(g.name)).sort((a, b) => sum(b.overlap) - sum(a.overlap)).map((g) => g.name);
			genreByName = by;
			genreOrder = order;
			// Plot five genres but isolate Romance: only Romance's line shows, the
			// other four stay in the legend, greyed out (click to bring them back).
			const romance = by["Romance"] ? "Romance" : order[0];
			shown = new Set([romance, ...order.filter((n) => n !== romance)].slice(0, 5));
			isolatedKeys = [`g:${romance}`];
			// A shared link names its format and genres (?format=ebook&genres=Romance,Fantasy).
			try {
				const sp = new URLSearchParams(window.location.search);
				if (sp.get("view") === "format") byFmt = true;
				const want = (sp.get("genres") || "").split(",").map((x) => x.trim()).filter((x) => by[x] || x === "Other");
				if (want.length) {
					shown = new Set(want.filter((x) => x !== "Other"));
					showOther = want.includes("Other");
					isolatedKeys = [];
				}
			} catch {}
			openGroupsFor(shown);
			lo = 0;
			hi = d.months.length - 1;
			raw = d;
		} catch (e) {
			loadError = "Couldn't load genre data.";
		}
	});

	// Keep the format and the plotted genres in the link.
	// (What's on the chart: the isolated genres when some are, else all the ticked
	// ones.) The default view leaves the link bare.
	let defaultSig = null;
	$effect(() => {
		if (!raw) return;
		const iso = isolatedKeys.map((k) => k.replace(/^g:/, "")).map((n) => (n === "__other" ? "Other" : n));
		const names = iso.length ? iso : [...shown, ...(showOther ? ["Other"] : [])];
		const sig = `${byFmt}|${names.join(",")}`;
		if (defaultSig === null) defaultSig = sig;
		if (sig === defaultSig && !window.location.search.includes("genres=")) return;
		try {
			const url = new URL(window.location.href);
			if (byFmt) url.searchParams.set("view", "format");
			else url.searchParams.delete("view");
			if (names.length) url.searchParams.set("genres", names.join(","));
			else url.searchParams.delete("genres");
			if (url.href !== window.location.href) window.history.replaceState({}, "", url);
		} catch {}
	});

	function sum(a) { let s = 0; for (const v of a || []) s += v; return s; }
	// A share of almost nothing is noise: in spring 2020 the closed branches
	// lent about 70 print books a month, so a few picture books were "70%" of
	// print. Months with fewer than MIN_BASE checkouts in the format are gaps.
	const MIN_BASE = 1000;
	const share = (arr) => arr.map((v, i) => (data.total[i] >= MIN_BASE ? (100 * v) / data.total[i] : null));
	const overall = (arr) => (data ? (100 * sum(arr)) / Math.max(1, sum(data.total)) : 0);
	const seriesArr = (g) => g.overlap;
	const colorIdx = (name) => genreOrder.indexOf(name);
	// Romance, the genre the page opens on, gets the palette's red (as in the
	// tour) rather than a blue like an author's line; whichever genre had the
	// red takes Romance's color instead.
	const colorOf = (name) => {
		const r = colorIdx("Romance");
		const i = name === "Romance" ? 0 : r >= 0 && colorIdx(name) === 0 ? r : colorIdx(name);
		return PALETTE[i % PALETTE.length];
	};

	function cleanTitle(t) {
		return (t || "").split(" / ")[0]
			.replace(/\s*[:(]?\s*\bunabridged\b\s*\)?/gi, "")
			.replace(/\s*\[(videorecording|sound recording|electronic resource)\]/gi, "")
			.replace(/\s*[.,;/:]\s*$/, "").trim();
	}
	function cleanExamples(list) {
		const seen = new Set(), out = [];
		for (const raw of list || []) {
			const t = cleanTitle(raw), k = t.toLowerCase();
			if (t && !seen.has(k)) { seen.add(k); out.push(t); }
		}
		return out;
	}

	// months + series sliced to the time-slider window [lo..hi].
	const viewMonths = $derived(data ? data.months.slice(lo, hi + 1) : []);
	const series = $derived.by(() => {
		if (!data) return [];
		const clip = (arr) => share(arr).slice(lo, hi + 1);
		const out = [];
		for (const name of genreOrder) {
			if (!shown.has(name)) continue;
			const g = genreByName[name];
			out.push({ key: `g:${name}`, name, color: colorOf(name), values: clip(seriesArr(g)),
				terms: g.terms, ficTerms: g.ficTerms, examples: cleanExamples(g.examples).slice(0, 4) });
		}
		if (showOther) {
			// "Other" is a residual (total − the overlapping genres). Because a book
			// can be tagged with several genres at once, the genres sometimes sum to
			// more than 100% and push this residual slightly negative — a data
			// artifact, not a real negative share. Clamp to 0 so the line and the
			// tooltip both read 0% rather than e.g. −10%.
			out.push({ key: "g:__other", name: "Other / Unclassified", color: "#b0b0b0", values: clip(data.other).map((v) => Math.max(0, v)) });
		}
		return out;
	});

	function toggleShown(name) {
		const n = new Set(shown);
		const adding = !n.has(name);
		adding ? n.add(name) : n.delete(name);
		shown = n;
		openGroupsFor(n);
		const k = `g:${name}`;
		// Keep whatever is currently on the plot and just add/remove this one. If a
		// focused subset is showing (isolatedKeys), add the ticked genre TO that
		// subset rather than clearing the focus and revealing every plotted genre.
		if (adding) {
			if (isolatedKeys.length) isolatedKeys = [...isolatedKeys, k];
		} else {
			isolatedKeys = isolatedKeys.filter((x) => x !== k);
		}
	}
	function toggleExpand(name) {
		const n = new Set(expanded); n.has(name) ? n.delete(name) : n.add(name); expanded = n;
	}
	// Clicking a line's name (legend or line end): one of several picked out ->
	// show only it; the only one showing -> bring everything back; grayed out ->
	// add it. (Taking a picked line OFF on click read as "it jumped to the other
	// book".)
	function toggleIsolate(k) {
		if (!isolatedKeys.includes(k)) isolatedKeys = [...isolatedKeys, k];
		else isolatedKeys = isolatedKeys.length === 1 ? [] : [k];
	}
	const isIsolated = (k) => isolatedKeys.includes(k);
	const hideAll = () => { shown = new Set(); isolatedKeys = []; };

	// Genre-table search: match the query against the genre name OR any of its
	// subject terms (so "vampire" finds Fantasy, "cooking" finds Cooking & Food).
	function genreMatches(name) {
		const q = genreFilter.trim().toLowerCase();
		if (!q) return true;
		if (name.toLowerCase().includes(q)) return true;
		const g = genreByName[name];
		if (!g) return false;
		return (g.terms || []).some((t) => t.toLowerCase().includes(q))
			|| (g.ficTerms || []).some((t) => t.toLowerCase().includes(q));
	}

	// When exactly one genre is on the plot (isolated, or the only one shown), name
	// it as a serif title above the chart — matching the other views' plot titles.
	// The genres currently featured on the plot: the isolated ones if any, else all shown.
	const plotGenres = $derived(
		isolatedKeys.length ? isolatedKeys.map((k) => (k === "g:__other" ? "Other / Unclassified" : k.replace(/^g:/, ""))) : [...shown],
	);
	// Clicking a genre's name plots it alone (like isolating a line).
	function pickGenre(name) {
		if (!name) { isolatedKeys = []; return; }
		if (!shown.has(name)) {
			shown = new Set(shown).add(name);
			openGroupsFor(shown);
		}
		isolatedKeys = [`g:${name}`];
	}
	const yearRange = $derived(
		viewMonths.length ? `${viewMonths[0].slice(0, 4)}–${viewMonths[viewMonths.length - 1].slice(0, 4)}` : "",
	);
	// A genre's share of all book checkouts over the years in view.
	function windowShare(arr) {
		let a = 0, t = 0;
		for (let i = lo; i <= hi; i++) { a += arr[i] || 0; t += data.total[i] || 0; }
		return t ? (100 * a) / t : 0;
	}
	function fmtShare(p) {
		if (p >= 10) return `${Math.round(p)}%`;
		if (p >= 0.1) return `${p.toFixed(1)}%`;
		return p > 0 ? "<0.1%" : "0%";
	}
	const sparkMax = $derived.by(() => {
		if (!data) return 1;
		let mx = 1e-9;
		for (const name of genreOrder) {
			const seg = share(seriesArr(genreByName[name])).slice(lo, hi + 1);
			for (const v of avg3(seg)) if (v > mx) mx = v;
		}
		return mx;
	});
	// Small trend line for the table: the monthly share over the years in view,
	// as a 3-month average, scaled to its own peak.
	function sparkPath(arr, w = 84, h = 20) {
		const seg = share(arr).slice(lo, hi + 1);
		if (seg.length < 2) return "";
		const avg = avg3(seg);
		// One scale for every genre row (small genres draw flatter lines).
		const mx = Math.max(1e-9, sparkMax);
		// A gap (null) lifts the pen; the next point starts a new stroke.
		return avg.map((v, i) => (v == null ? "" : `${i && avg[i - 1] != null ? "L" : "M"}${(1 + (i * (w - 2)) / (avg.length - 1)).toFixed(1)},${(h - 1 - (v / mx) * (h - 3)).toFixed(1)}`)).join("");
	}

	// What the chart draws: the plotted genres, or only the isolated ones; or,
	// by format, the one genre's print / ebook / audiobook lines.
	const canByFmt = $derived(!!(headGenre?.fmt && raw?.byFormat));
	const showByFmt = $derived(byFmt && canByFmt);
	const chartSeries = $derived(
		showByFmt
			? FMT_LINES.map(([f, label, color]) => ({ key: `f:${f}`, name: label, label, color, values: share(headGenre.fmt[f]).slice(lo, hi + 1) }))
			: (isolatedKeys.length ? series.filter((s) => isolatedKeys.includes(s.key)) : series).map((s) => ({ ...s, label: s.name })),
	);

	// Header over the chart, like an author page: one genre gets its name, its
	// share and its subject headings; several get a short comparison title.
	const headName = $derived(plotGenres.length === 1 ? plotGenres[0] : null);
	const headGenre = $derived(headName ? genreByName[headName] || null : null);
	const headTitle = $derived(
		headGenre ? headName
			: plotGenres.length === 0 ? "Pick genres to compare"
			: plotGenres.length <= 3 ? plotGenres.filter((n) => genreByName[n]).join(" vs. ")
			: `Comparing ${plotGenres.length} genres`,
	);
	// "Romance, Fantasy and Mystery"
	function listGenres(names) {
		const n = names.filter((x) => genreByName[x] || x === "Other / Unclassified");
		return n.length < 3 ? n.join(" and ") : `${n.slice(0, -1).join(", ")} and ${n[n.length - 1]}`;
	}
	const headTerms = $derived(headGenre ? [...(headGenre.terms || []), ...(headGenre.ficTerms || [])].map(termText).slice(0, 4) : []);
	// Terms are stored as match rules ("=fiction" means exactly "fiction"); show
	// just the words.
	const termText = (t) => String(t || "").replace(/^=/, "");
	const splSubjectUrl = (t) => `https://seattle.bibliocommons.com/v2/search?query=${encodeURIComponent(t.replace(/[()]/g, ""))}&searchType=subject`;

	// The plotted genres' monthly shares as a spreadsheet.
	function downloadCSV() {
		dlOpen = false;
		const cols = chartSeries;
		const rows = [["month", ...cols.map((c) => `${c.name} (% of ${fmtNoun} checkouts)`)]];
		viewMonths.forEach((m, i) => rows.push([`${m}-01`, ...cols.map((c) => (c.values[i] == null ? "" : c.values[i].toFixed(3)))]));
		const cell = (v) => { const t = String(v ?? ""); return /[",\n\r]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t; };
		const blob = new Blob(["\ufeff" + rows.map((r) => r.map(cell).join(",")).join("\r\n")], { type: "text/csv;charset=utf-8" });
		saveBlob(blob, "seattle-reading-genres.csv");
	}

	// --- Share / download (mirrors the "By author" tab exactly) --------------
	const plotTitle = $derived(`Share of ${fmtNoun} checkouts · a book can count toward several genres`);
	const legendItems = $derived(series.map((s) => ({ label: s.name, color: s.color, key: s.key })));

	// A shareable link (reopens the genre tab) plus a caption.
	function shareTarget() {
		let link = window.location.href;
		try {
			const url = new URL(window.location.href);
			link = url.toString();
		} catch {}
		const text = "What’s Seattle Reading? — What genres is Seattle checking out?";
		return { link, text };
	}

	// Open a platform's composer, having copied the chart image to the clipboard
	// so it can be pasted in (share URLs can't attach an image directly). The
	// promise-valued ClipboardItem keeps the write inside the click gesture, and
	// window.open runs in the same tick so the popup isn't blocked.
	function shareTo(platform) {
		const { link, text } = shareTarget();
		let copied = false;
		try {
			if (navigator.clipboard && window.ClipboardItem) {
				navigator.clipboard.write([new ClipboardItem({ "image/png": renderChartBlob() })]).catch(() => {});
				copied = true;
			}
		} catch {}
		const u = encodeURIComponent(link);
		const t = encodeURIComponent(text);
		const urls = {
			facebook: `https://www.facebook.com/sharer/sharer.php?u=${u}`,
			twitter: `https://twitter.com/intent/tweet?url=${u}&text=${t}`,
			bluesky: `https://bsky.app/intent/compose?text=${encodeURIComponent(text + " " + link)}`,
			linkedin: `https://www.linkedin.com/sharing/share-offsite/?url=${u}`,
		};
		if (urls[platform]) window.open(urls[platform], "_blank", "noopener,noreferrer,width=600,height=540");
		shareOpen = false;
		if (copied) {
			flash("Chart image copied — paste it (⌘/Ctrl+V) into your post", 4500);
		}
	}

	async function copyShareLink() {
		const { link } = shareTarget();
		try {
			await navigator.clipboard.writeText(link);
			flash("Link copied!", 2000);
		} catch {
			flash("Couldn’t copy. Copy the link from the address bar.", 3200);
		}
		shareOpen = false;
	}

	// Copy the chart image itself to the clipboard (paste it straight into any
	// post/doc). Falls back to downloading if the browser can't copy images.
	async function copyImage() {
		shareOpen = false;
		try {
			if (!(navigator.clipboard && window.ClipboardItem)) throw new Error("no clipboard");
			await navigator.clipboard.write([new ClipboardItem({ "image/png": renderChartBlob() })]);
			flash("Chart image copied to clipboard", 2600);
		} catch {
			const blob = await renderChartBlob();
			if (blob) saveBlob(blob, "seattle-reading-genres.png");
			flash("Image saved (clipboard unavailable)", 2600);
		}
	}

	// Rasterize the chart SVG to a titled PNG (Blob), reused by download + share.
	async function renderChartBlob() {
		const src = chartWrap?.querySelector("svg");
		if (!src) return null;
		// Inline computed styles onto a clone: the SVG is painted by scoped
		// component CSS that would be lost once it's serialized on its own.
		const clone = src.cloneNode(true);
		const from = src.querySelectorAll("*");
		const to = clone.querySelectorAll("*");
		// No "display" here on purpose: the event labels drawn only for images
		// (.ev-export, hidden on screen) must show up in the export.
		const PROPS = ["fill", "stroke", "stroke-width", "stroke-dasharray", "stroke-linecap", "stroke-linejoin", "opacity", "font-family", "font-size", "font-weight", "text-anchor", "color", "paint-order", "fill-opacity", "stroke-opacity"];
		to.forEach((node, i) => {
			const cs = getComputedStyle(from[i]);
			node.setAttribute("style", PROPS.map((p) => `${p}:${cs.getPropertyValue(p)}`).join(";"));
		});
		const w = Math.round(src.clientWidth || src.viewBox.baseVal.width || 800);
		const h = Math.round(src.clientHeight || src.viewBox.baseVal.height || 400);
		clone.setAttribute("width", w);
		clone.setAttribute("height", h);
		clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
		const svgUrl = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(new XMLSerializer().serializeToString(clone));
		const img = new Image();
		await new Promise((res, rej) => { img.onload = res; img.onerror = rej; img.src = svgUrl; });
		const scale = 2, padX = 28, footH = 40;
		const canvas = document.createElement("canvas");
		const ctx = canvas.getContext("2d");
		// The logo sits top-right, beside the title, when there's room; on a
		// narrow (phone) chart it gets its own row above the title instead.
		const imgTitle = "What genres is Seattle checking out?";
		ctx.font = '600 22px Georgia, "Times New Roman", serif';
		const logoRow = ctx.measureText(imgTitle).width + 16 > w - chartLogoWidth(ctx) ? 30 : 0;
		const titleH = 68 + logoRow;
		// Lay out the legend (wrapped) first so we know how tall to make the canvas.
		const LEG_FONT = '600 13px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
		// When lines are isolated, the exported chart draws only those — so the
		// legend should list only those too (not every plotted genre).
		const legItems = isolatedKeys.length ? legendItems.filter((it) => isolatedKeys.includes(it.key)) : legendItems;
		const showLegend = legItems.length >= 1;
		const legLH = 22, legSw = 12, legGapSw = 6, legGapItem = 20;
		const legLines = [];
		if (showLegend) {
			ctx.font = LEG_FONT;
			let line = [], lineW = 0;
			for (const it of legItems) {
				const iw = legSw + legGapSw + ctx.measureText(it.label).width;
				if (lineW + iw > w && line.length) { legLines.push(line); line = []; lineW = 0; }
				line.push(it); lineW += iw + legGapItem;
			}
			if (line.length) legLines.push(line);
		}
		const legendH = showLegend ? legLines.length * legLH + 12 : 0;

		canvas.width = (w + padX * 2) * scale;
		canvas.height = (h + titleH + legendH + footH) * scale;
		ctx.scale(scale, scale);
		ctx.fillStyle = "#ffffff";
		ctx.fillRect(0, 0, canvas.width, canvas.height);
		ctx.textBaseline = "alphabetic";
		ctx.fillStyle = "#1a1a1a";
		ctx.font = '600 22px Georgia, "Times New Roman", serif';
		ctx.fillText(imgTitle, padX, 34 + logoRow);
		ctx.fillStyle = "#666666";
		ctx.font = '13px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
		ctx.fillText(plotTitle, padX, 54 + logoRow);
		await drawChartLogo(ctx, logoRow ? padX + chartLogoWidth(ctx) : padX + w, logoRow ? 18 : 26);
		ctx.drawImage(img, padX, titleH, w, h);
		if (showLegend) {
			ctx.font = LEG_FONT;
			ctx.textBaseline = "middle";
			let ly = titleH + h + 18;
			for (const line of legLines) {
				let lx = padX;
				for (const it of line) {
					ctx.fillStyle = it.color;
					ctx.fillRect(lx, ly - legSw / 2, legSw, legSw);
					ctx.fillStyle = "#333333";
					ctx.fillText(it.label, lx + legSw + legGapSw, ly + 0.5);
					lx += legSw + legGapSw + ctx.measureText(it.label).width + legGapItem;
				}
				ly += legLH;
			}
			ctx.textBaseline = "alphabetic";
		}
		ctx.fillStyle = "#999999";
		ctx.font = '11px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
		ctx.fillText("What’s Seattle Reading?  ·  Seattle Public Library checkouts", padX, titleH + h + legendH + 24);
		return await new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
	}

	function saveBlob(blob, name) {
		const a = document.createElement("a");
		a.href = URL.createObjectURL(blob);
		a.download = name;
		a.click();
		setTimeout(() => URL.revokeObjectURL(a.href), 1000);
	}

	async function downloadChart() {
		const blob = await renderChartBlob();
		if (blob) saveBlob(blob, "seattle-reading-genres.png");
	}

	// Share the current view AS AN IMAGE via the native share sheet (mobile and
	// some desktop browsers). The platform-link buttons can't attach a picture --
	// they only show the page's preview image -- so this is the way to actually
	// post the chart itself. Falls back to saving the PNG to attach by hand.
	async function shareImage() {
		shareOpen = false;
		const blob = await renderChartBlob();
		if (!blob) return;
		const name = "seattle-reading-genres.png";
		const file = new File([blob], name, { type: "image/png" });
		const { link, text } = shareTarget();
		if (navigator.canShare && navigator.canShare({ files: [file] })) {
			try { await navigator.share({ files: [file], title: text, text: `${text}\n${link}` }); } catch {}
			return;
		}
		saveBlob(blob, name);
		flash("Image saved — attach it to your post", 3200);
	}
</script>

<div class="genres">
	{#if loadError}
		<p class="load-error">{loadError}</p>
	{:else if !data}
		<p class="loading"><span class="spinner" aria-hidden="true"></span>Loading genre trends…</p>
	{:else}
		<div class="modebar">
			<h2 class="genre-title">Seattle's Genre Trends</h2>
			<p class="mode-note">Each genre's share of book checkouts at the Seattle Public Library, from the subject headings in its catalog.</p>
		</div>

		<!-- Header, as on an author page: the genre, its share, its headings -->
		<div class="g-head">
			{#if headGenre}
				<h3 class="g-name">{headTitle}</h3>
				<p class="g-meta">{fmtShare(windowShare(seriesArr(headGenre)))} of {fmtNoun} checkouts, {yearRange} · {compactNumber(sum(seriesArr(headGenre).slice(lo, hi + 1)))} checkouts</p>
				{#if headTerms.length}
					<p class="g-terms"><span class="g-lead">Subject headings with</span> {#each headTerms as t, k}{#if k}<span class="g-sep" aria-hidden="true">{" · "}</span>{/if}<a href={splSubjectUrl(t)} target="_blank" rel="noopener noreferrer" title="Find books on “{t}” at the Seattle Public Library">{t}</a>{/each}</p>
				{/if}
			{:else if plotGenres.length}
				<!-- Several genres: a plain line, not a second big title under the page's -->
				<p class="g-meta g-compare">{plotGenres.length <= 3 ? listGenres(plotGenres) : `${plotGenres.length} genres`}: share of {fmtNoun} checkouts, {yearRange}. Click a genre's name to show it alone.</p>
			{:else}
				<p class="g-meta">Tick genres in the table below to plot them.</p>
			{/if}
		</div>

		<div class="plot-toolbar">
			<div class="tb-left">
				{#if raw.byFormat}
					<button type="button" class="fmt-btn" class:on={showByFmt} aria-pressed={showByFmt} disabled={!canByFmt}
						title={canByFmt ? "Split this genre into print, ebook and audiobook" : "Show one genre to split it by format"}
						onclick={() => (byFmt = !showByFmt)}>By format</button>
				{/if}
				<label class="smooth-toggle"><input type="checkbox" bind:checked={smoothOn} /> 3-month average</label>
				{#if showByFmt}<span class="iso-note">Each line is a share of all book checkouts; together they make {headName}'s total.</span>{/if}
				{#if !showByFmt && isolatedKeys.length && series.length >= 2}
					<span class="iso-note">Showing {chartSeries.length} of {series.length}<span aria-hidden="true">{" · "}</span><button type="button" class="iso-showall" onclick={() => (isolatedKeys = [])}>Show all</button></span>
				{/if}
			</div>
		</div>

		<!-- The chart, its slider and source line share one white panel -->
		<div class="chart-panel" style="--hang: {Math.max(0, plotInset - 16)}px">
		<div class="chartwrap" bind:this={chartWrap}>
			<LineChart bind:plotInset months={viewMonths} series={chartSeries} mode="line" percent unit="of {fmtNoun} checkouts"
				smooth={smoothOn} annotations={EVENT_ANNOTATIONS} {legendHoverKey} onSeriesClick={showByFmt ? null : (k) => toggleIsolate(k)} />
		</div>

		<!-- A swatch legend under the chart (phones have no end-of-line names).
		     Click one to show it alone; the others gray out, click to add them. -->
		<!-- By format, the legend picks which genre is split. -->
		{#if series.length >= 2}
			<div class="phone-legend" class:off-phone={!isolatedKeys.length && !showByFmt}>
				{#each series as s (s.key)}
					<button type="button" class="pl-item" class:dim={showByFmt ? s.name !== headName : isolatedKeys.length && !isIsolated(s.key)} onclick={() => (showByFmt ? (isolatedKeys = [s.key]) : toggleIsolate(s.key))}><span class="pl-sw" style="background:{s.color}"></span>{s.name}</button>
				{/each}
			</div>
		{/if}

		<YearBrush months={data.months} inset={phone.current ? 0 : plotInset} bind:lo bind:hi />
		<!-- Source on the left; Download and Share as small links on the right -->
		<div class="chart-foot" style="padding-right: {phone.current ? 0 : plotInset}px">
			<p class="chart-source">Source: <a href="https://data.seattle.gov/Community-and-Culture/Checkouts-by-Title/tmmm-ytt6" target="_blank" rel="noopener noreferrer">Seattle Public Library open data</a>. Genres come from Library of Congress and BISAC subject headings; a book can count toward several genres, so the shares overlap. <DataInfo first={data.months[0]} last={data.months[data.months.length - 1]} genres />.</p>
			<div class="tb-right foot-actions">
				<div class="dl-wrap">
					<button class="tb-btn" onclick={() => (dlOpen = !dlOpen)} aria-haspopup="true" aria-expanded={dlOpen} title="Download the data or the chart">
						<DownloadIcon size={15} strokeWidth={2} aria-hidden="true" /><span class="tb-txt"> Download</span><span class="tb-txt"><ChevronDownIcon size={14} strokeWidth={2} aria-hidden="true" /></span>
					</button>
					{#if dlOpen}
						<button class="share-backdrop" aria-label="Close" onclick={() => (dlOpen = false)}></button>
						<div class="share-menu" role="menu">
							<button role="menuitem" class="share-item" onclick={downloadCSV}><span class="share-ic" aria-hidden="true"><TableIcon size={15} strokeWidth={2} /></span> Data (CSV)</button>
							<button role="menuitem" class="share-item" onclick={() => { dlOpen = false; downloadChart(); }}><span class="share-ic" aria-hidden="true"><ImageIcon size={15} strokeWidth={2} /></span> Image (PNG)</button>
						</div>
					{/if}
				</div>
				<div class="share-wrap">
					<button class="tb-btn" onclick={() => (shareOpen = !shareOpen)} title="Share this chart" aria-haspopup="true" aria-expanded={shareOpen}>
						<ShareIcon size={15} strokeWidth={2} aria-hidden="true" /><span class="tb-txt"> Share</span>
					</button>
					{#if shareOpen}
						<button class="share-backdrop" aria-label="Close share menu" onclick={() => (shareOpen = false)}></button>
						<div class="share-menu" role="menu">
							<button role="menuitem" class="share-item" onclick={copyImage}><span class="share-ic" aria-hidden="true"><ImageIcon size={15} strokeWidth={2} /></span> Copy image</button>
							<button role="menuitem" class="share-item" onclick={copyShareLink}><span class="share-ic" aria-hidden="true"><LinkIcon size={15} strokeWidth={2} /></span> Copy link</button>
							<button role="menuitem" class="share-item" onclick={shareImage}><span class="share-ic" aria-hidden="true"><ShareIcon size={15} strokeWidth={2} /></span> Share via…</button>
						</div>
					{/if}
				</div>
				{#if shareMsg}<span class="share-msg" role="status">{shareMsg}</span>{/if}
			</div>
		</div>
		</div><!-- /.chart-panel -->

		<!-- Genres table, styled like the author page's Books table -->
		<section class="books">
			<div class="bk-head">
				<h2 class="bk-title">Genres <span class="bk-count">({genreOrder.length})</span></h2>
				<div class="bk-tools">
					<input class="bk-filter" type="search" bind:value={genreFilter} placeholder="Filter genres or subjects" aria-label="Filter genres or subject terms" />
					{#if shown.size || showOther}<button class="bk-btn" onclick={() => { hideAll(); showOther = false; }}>Clear chart</button>{/if}
				</div>
			</div>
			<ul class="bk-list">
				<li class="bk-row bk-colhead" aria-hidden="true"><span></span><span>Genre</span><span class="bk-sp">{yearRange}</span><span class="bk-num">Share</span></li>
				{#each GROUPS as [groupName, names] (groupName)}
					{@const inGroup = names.filter((n) => genreByName[n] && !HIDDEN_GENRES.has(n) && genreMatches(n)).sort((a, b) => windowShare(seriesArr(genreByName[b])) - windowShare(seriesArr(genreByName[a])))}
					{#if inGroup.length}
						{@const isCollapsed = collapsedGroups.has(groupName) && !genreFilter && inGroup.length > PREVIEW}
						<li class="g-group">
							<button type="button" aria-expanded={!isCollapsed} onclick={() => toggleGroup(groupName)}>
								{groupName} <span class="bk-count">{inGroup.length}</span>{#if COLLAPSIBLE.has(groupName) && inGroup.length > PREVIEW && !genreFilter}<span class="bk-caret" class:up={!isCollapsed} aria-hidden="true"></span>{/if}
							</button>
						</li>
							{#each isCollapsed ? inGroup.slice(0, PREVIEW) : inGroup as name (name)}
								{@const g = genreByName[name]}
								{@const on = shown.has(name)}
								<li class="bk-row" class:plotted={on}>
									<input type="checkbox" class="bk-check" checked={on} onchange={() => toggleShown(name)} aria-label="Plot {name} on the chart" />
									<span class="bk-name-cell">
										{#if on}<span class="bk-swatch" style="background:{colorOf(name)}"></span>{/if}
										<button type="button" class="bk-name g-pick" title="Show {name} alone on the chart" onclick={() => pickGenre(name)}>{name}</button>
										<button type="button" class="bk-eds" aria-expanded={expanded.has(name)} onclick={() => toggleExpand(name)}>subjects &amp; titles<span class="bk-caret" class:up={expanded.has(name)} aria-hidden="true"></span></button>
									</span>
									<svg class="bk-sp bk-spark" width="84" height="20" viewBox="0 0 84 20" aria-hidden="true"><path d={sparkPath(seriesArr(g))} stroke={on ? colorOf(name) : "#b4b2a9"} /></svg>
									<span class="bk-num">{fmtShare(windowShare(seriesArr(g)))}</span>
								</li>
								{#if expanded.has(name)}
									<li class="g-detail">
										{#if g.terms?.length || g.ficTerms?.length}
											<p class="g-detail-terms"><span class="g-lbl">Subject headings containing</span>
												{#each (g.terms || []).map(termText) as t, i}{#if i}{" · "}{/if}<a href={splSubjectUrl(t)} target="_blank" rel="noopener noreferrer">{t}</a>{/each}
												{#if g.ficTerms?.length}<span class="g-fic">{g.terms?.length ? " · " : ""}with a Fiction tag: </span>{#each g.ficTerms.map(termText) as t, i}{#if i}{" · "}{/if}<a href={splSubjectUrl(t)} target="_blank" rel="noopener noreferrer">{t}</a>{/each}{/if}
											</p>
										{/if}
										{#if cleanExamples(g.examples).length}
											<span class="g-lbl">Most-checked-out titles</span>
											<ol class="g-ex">{#each cleanExamples(g.examples) as title}<li>{title}</li>{/each}</ol>
										{/if}
									</li>
								{/if}
							{/each}
							{#if COLLAPSIBLE.has(groupName) && inGroup.length > PREVIEW && !genreFilter}
								<li class="g-more"><button type="button" aria-expanded={!isCollapsed} onclick={() => toggleGroup(groupName)}>{isCollapsed ? `Show all ${inGroup.length} ${groupName.toLowerCase()} genres` : "Show fewer"}<span class="bk-caret" class:up={!isCollapsed} aria-hidden="true"></span></button></li>
							{/if}
					{/if}
				{/each}
				<li class="bk-row g-other" class:plotted={showOther}>
					<input type="checkbox" class="bk-check" checked={showOther} onchange={() => (showOther = !showOther)} aria-label="Plot Other / Unclassified" />
					<span class="bk-name-cell">
						{#if showOther}<span class="bk-swatch" style="background:#b0b0b0"></span>{/if}
						<span class="bk-name">Other / Unclassified</span>
						<button type="button" class="bk-eds" aria-expanded={expanded.has("__other")} onclick={() => toggleExpand("__other")}>what's here<span class="bk-caret" class:up={expanded.has("__other")} aria-hidden="true"></span></button>
					</span>
					<svg class="bk-sp bk-spark" width="84" height="20" viewBox="0 0 84 20" aria-hidden="true"><path d={sparkPath(data.other.map((v) => Math.max(0, v)))} stroke={showOther ? "#b0b0b0" : "#b4b2a9"} /></svg>
					<span class="bk-num">{fmtShare(Math.max(0, windowShare(data.other)))}</span>
				</li>
				{#if expanded.has("__other")}
					<li class="g-detail">
						<p class="g-detail-terms">Books matching <em>none</em> of the {genreOrder.length} genres, mostly general nonfiction without a genre heading.</p>
						{#if data.otherTags?.length}
							<p class="g-detail-terms"><span class="g-lbl">Top subject headings here</span> {#each data.otherTags as t, i}{#if i}{" · "}{/if}{t[0]} <span class="g-pct">{t[1]}%</span>{/each}</p>
						{/if}
						{#if cleanExamples(data.otherExamples).length}
							<span class="g-lbl">Most-checked-out titles</span>
							<ol class="g-ex">{#each cleanExamples(data.otherExamples) as title}<li>{title}</li>{/each}</ol>
						{/if}
					</li>
				{/if}
			</ul>
		</section>

		<details class="sh-note">
			<summary>A note on how genres are defined</summary>
			<p>
				Genres are aggregated from <strong>Library of Congress and BISAC subject headings</strong> in the
				library's catalog records. Click a genre to see which headings are used.
				<a href="https://docs.google.com/forms/d/e/1FAIpQLSfHWbWEj1H4NltjSp3ixjelJKSu2VMQgEkTF3CpjWtWhwARfA/viewform?usp=dialog" target="_blank" rel="noopener noreferrer">Let us know</a>
				if you have suggestions or feedback about how these genres are defined.
			</p>
			<p>
				<strong>Note:</strong> Many scholars and activists have criticized LOC and BISAC classification systems,
				especially for the problematic ways that they represent race, ethnicity, gender, sexuality, and other
				aspects of identity, and also for their U.S. focus. This is something that should be kept in mind when
				using or exploring this data. For more, see:
			</p>
			<ul class="sh-refs">
				<li>Sandra Littletree and Cheryl A. Metoyer, “<a href="https://doi.org/10.1080/01639374.2015.1010113" target="_blank" rel="noopener noreferrer">Knowledge Organization from an Indigenous Perspective: The Mashantucket Pequot Thesaurus of American Indian Terminology Project</a>,” <em>Cataloging &amp; Classification Quarterly</em> (2015).</li>
				<li>D St Amour, Keahi Adolpho, Marika Cifor, Michael Radmacher, B. M. Watson, Crystal Yragui, and Travis Wagner, “<a href="https://journals.cilip.org.uk/catalogue-and-index/article/view/879" target="_blank" rel="noopener noreferrer">Building and Sustaining the Homosaurus, an Inclusive LGBTQ+ Linked Data Vocabulary</a>,” <em>Catalogue and Index</em> 214 (2026). See also the <a href="https://homosaurus.org/about" target="_blank" rel="noopener noreferrer">Homosaurus website</a>.</li>
			</ul>
		</details>
	{/if}
</div>

<style>
	.genres { margin-top: var(--space-6); font-family: var(--font-sans); }
	.sh-refs { margin: 0 0 var(--space-3); padding-left: 1.2em; }
	.sh-refs li { margin: 0 0 6px; line-height: 1.55; color: var(--color-fg-light); }
	.loading, .load-error { font-family: var(--font-sans); color: var(--color-fg-light); }

	/* Section masthead — matches the other tabs (serif title + subtitle + rule). */
	.modebar { border-bottom: 3px solid var(--color-fg); padding-bottom: var(--space-3); margin: var(--space-6) 0 var(--space-5); }
	.genre-title { font-family: var(--font-display, var(--font-serif)); font-weight: 700; font-size: clamp(1.7rem, 3.4vw, 2.5rem); color: var(--color-fg); margin: 0; line-height: 1.05; }
	.mode-note { font-size: var(--text-base); color: var(--color-fg-light); margin: 6px 0 0; line-height: 1.4; }

	/* Header over the chart (same type scale as an author page). */
	.g-head { margin: 0 0 4px; }
	.g-name { font-family: var(--font-serif); font-weight: 400; font-size: clamp(1.4rem, 2.6vw, 1.75rem); line-height: 1.15; color: var(--color-fg); margin: 0; }
	.g-compare { color: var(--color-fg); }
	.g-meta { font-size: 1.02rem; line-height: 1.4; color: var(--color-fg-light); margin: 6px 0 0; }
	.g-terms { font-size: var(--text-sm); line-height: 1.6; color: var(--color-fg-light); margin: 2px 0 0; }
	.g-terms a, .g-detail-terms a { color: var(--color-fg-light); text-decoration: underline; text-decoration-color: var(--color-border); text-underline-offset: 3px; }
	.g-terms a:hover, .g-detail-terms a:hover { color: var(--color-fg); text-decoration-color: currentColor; }
	.g-sep { color: #aaa; }
	.g-lead { margin-right: 2px; }

	/* Toolbar: 3-month average on the left; Download and Share on the right. */
	.plot-toolbar { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); flex-wrap: wrap; margin: var(--space-5) 0 var(--space-4); }
	.tb-left, .tb-right { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
	.iso-note { font-size: var(--text-sm); color: var(--color-fg-light); }
	.iso-showall { background: none; border: 0; padding: 0; font: inherit; color: var(--color-fg); cursor: pointer; text-decoration: underline; text-underline-offset: 3px; }
	.tb-btn { display: inline-flex; align-items: center; gap: 6px; font-family: var(--font-sans); font-size: var(--text-sm); font-weight: 500; line-height: 1; padding: 7px 11px; border: 1px solid var(--color-border); border-radius: 8px; background: var(--color-white); color: var(--color-fg); cursor: pointer; white-space: nowrap; }
	.tb-btn:hover { border-color: var(--color-fg-light); }
	.tb-btn :global(svg) { flex: none; width: 15px; height: 15px; color: var(--color-fg-light); }
	.tb-btn :global(svg.lucide-chevron-down) { width: 14px; height: 14px; }
	.dl-wrap, .share-wrap { position: relative; display: inline-flex; }
	.share-backdrop { position: fixed; inset: 0; z-index: 40; background: none; border: none; cursor: default; }
	.share-menu { position: absolute; top: calc(100% + 6px); right: 0; z-index: 41; display: flex; flex-direction: column; min-width: 196px; padding: 4px; background: var(--color-white); border: 1px solid var(--color-border); border-radius: 8px; box-shadow: 0 6px 20px rgba(0, 0, 0, 0.1); }
	.share-item { display: flex; align-items: center; gap: 10px; padding: 8px 10px; border: none; border-radius: 6px; background: none; font-family: var(--font-sans); font-size: var(--text-sm); font-weight: 500; color: var(--color-fg); cursor: pointer; text-align: left; }
	.share-item:hover { background: var(--color-gray-100); }
	.share-ic { display: inline-flex; width: 16px; height: 16px; color: var(--color-fg-light); }
	.share-ic :global(svg) { display: block; width: 15px; height: 15px; }
	.share-msg { font-size: var(--text-sm); font-weight: 600; color: #2e7d32; }

	.chartwrap { width: 100%; }
	.chart-source { font-size: 12px; color: #8a8a8a; margin: 0; flex: 1 1 260px; }
	.chart-source a { color: inherit; text-decoration: underline; text-decoration-color: #c9c9c9; text-underline-offset: 2px; }
	.chart-source a:hover { color: var(--color-fg); text-decoration-color: currentColor; }
	.chart-foot { display: flex; justify-content: space-between; align-items: center; gap: 8px 16px; flex-wrap: wrap; margin: 16px 0 0; }
	.chart-foot .foot-actions { gap: 8px; flex: none; }
	/* Under the chart, Download and Share open upward. */
	.chart-foot .share-menu { top: auto; bottom: calc(100% + 6px); }
	/* Download / Share: quiet gray buttons (as on Our World in Data), so they
	   read as clickable without competing with the chart. */
	.chart-foot .tb-btn { padding: 5px 10px; border: 0; border-radius: 6px; background: #f1f2f3; font-size: 12.5px; font-weight: 500; color: #555; gap: 5px; }
	.chart-foot .tb-btn:hover { background: #e4e6e8; color: var(--color-fg); }
	.chart-foot .tb-btn :global(svg) { width: 13px; height: 13px; color: currentColor; }

	/* Wide screens: the line labels hang out into the empty right margin, so the
	   plot itself runs the full width of the column (--hang is the label room;
	   always at least 24px from the window edge). */
	@media (min-width: 1080px) {
		.chart-panel { margin-right: calc(-1 * max(0px, min(var(--hang, 0px), (100vw - 960px) / 2 - 24px))); }
	}
	/* Genres table — same look as the author page's Books table. */
	.phone-legend { display: flex; flex-wrap: wrap; justify-content: center; gap: 4px 16px; margin: 10px 0 2px; font-family: var(--font-sans); font-size: var(--text-sm); font-weight: 600; }
	.pl-item { display: inline-flex; align-items: center; gap: 6px; padding: 2px 4px; border: 0; border-radius: 6px; background: none; font: inherit; color: var(--color-fg); cursor: pointer; }
	.pl-item:hover { background: var(--color-gray-100); }
	.pl-item.dim { color: var(--color-fg-light); font-weight: 500; }
	.pl-item.dim .pl-sw { background: #d5d8dc !important; }
	.pl-sw { width: 10px; height: 10px; border-radius: 2px; flex: none; }
	@media (max-width: 600px) { .phone-legend { justify-content: flex-start; gap: 4px 12px; font-size: 13px; } }
	/* Phones: lines are named at their ends, so the legend only appears once some
	   are picked out (to tap the others back in). */
	@media (max-width: 600px) { .phone-legend.off-phone { display: none; } }
	/* Phones: Download / Share as small square icon buttons, at the right. */
	@media (max-width: 600px) {
		.chart-foot .tb-txt { display: none; }
		.chart-foot .tb-btn { width: 36px; height: 36px; padding: 0; justify-content: center; }
		.chart-foot .tb-btn :global(svg) { width: 17px; height: 17px; }
		.chart-foot .foot-actions { margin-left: auto !important; }
	}
	.books { margin: var(--space-6) 0 var(--space-4); padding-top: var(--space-4); border-top: 1px solid var(--color-border); }
	.bk-head { display: flex; justify-content: space-between; align-items: center; gap: 10px 16px; flex-wrap: wrap; margin: 0 0 10px; }
	.bk-title { font-family: var(--font-sans); font-size: 1.1rem; font-weight: 600; margin: 0; color: var(--color-fg); }
	.bk-count { font-weight: 400; color: var(--color-fg-light); }
	.bk-tools { display: flex; gap: 8px; align-items: center; }
	.bk-filter { width: 200px; padding: 7px 10px; font: inherit; font-size: var(--text-sm); border: 1px solid var(--color-border); border-radius: 8px; background: var(--color-white); color: var(--color-fg); }
	.bk-btn { font-family: var(--font-sans); font-size: var(--text-sm); font-weight: 500; padding: 7px 12px; border: 1px solid var(--color-border); border-radius: 8px; background: var(--color-white); color: var(--color-fg); cursor: pointer; white-space: nowrap; }
	.bk-btn:hover { border-color: var(--color-fg-light); }
	.bk-list { list-style: none; margin: 0; padding: 0; }
	.bk-row { display: grid; grid-template-columns: 22px minmax(0, 1fr) 84px 64px; gap: 12px; align-items: center; padding: 9px 8px; border-top: 1px solid var(--color-gray-100, #eee); }
	.bk-row:not(.bk-colhead):hover { background: #f6f6f4; }
	.bk-colhead { padding: 0 0 6px; border-top: 0; border-bottom: 1px solid var(--color-border); font-size: 12px; color: var(--color-fg-light); }
	.bk-check { margin: 0; width: 16px; height: 16px; accent-color: var(--color-fg); appearance: auto; -webkit-appearance: auto; cursor: pointer; }
	.bk-name-cell { min-width: 0; display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
	.bk-swatch { display: inline-block; width: 12px; height: 3px; border-radius: 2px; align-self: center; flex: none; }
	.bk-name { font-family: var(--font-serif); font-size: 1rem; color: var(--color-fg); }
	.g-pick { background: none; border: 0; padding: 0; cursor: pointer; text-align: left; text-decoration: underline; text-decoration-color: transparent; text-underline-offset: 3px; }
	.g-pick:hover, .g-pick:focus-visible { text-decoration-color: currentColor; }
	.bk-eds { font: inherit; font-size: 12px; color: var(--color-fg-light); background: none; border: 0; padding: 0; cursor: pointer; display: inline-flex; align-items: center; gap: 4px; }
	.bk-eds:hover { color: var(--color-fg); text-decoration: underline; text-underline-offset: 3px; }
	.bk-caret { width: 0; height: 0; border-left: 4px solid transparent; border-right: 4px solid transparent; border-top: 5px solid currentColor; margin-left: 4px; }
	.bk-caret.up { border-top: 0; border-bottom: 5px solid currentColor; }
	.bk-spark { display: block; }
	.bk-spark path { fill: none; stroke-width: 1.5; stroke-linejoin: round; }
	.bk-num { text-align: right; font-size: var(--text-sm); font-variant-numeric: tabular-nums; color: var(--color-fg); white-space: nowrap; }
	.bk-colhead .bk-num, .bk-colhead .bk-sp { color: var(--color-fg-light); }
	.g-other .bk-name { font-style: italic; color: var(--color-fg-light); }

	/* Section rows: Fiction / Kids & Young Adult / Nonfiction */
	.g-group { border-top: 1px solid var(--color-border); }
	.g-group button { display: flex; align-items: center; gap: 6px; width: 100%; padding: 14px 8px 6px; background: none; border: 0; font: inherit; font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: var(--color-fg); text-align: left; cursor: pointer; }
	.g-group .bk-count { letter-spacing: 0; }
	.g-group .bk-caret { color: var(--color-fg-light); }
	.g-more button { display: inline-flex; align-items: center; gap: 6px; margin: 4px 0 6px 42px; padding: 4px 0; background: none; border: 0; font: inherit; font-size: var(--text-sm); color: var(--color-fg-light); cursor: pointer; }
	.g-more button:hover { color: var(--color-fg); text-decoration: underline; }

	.g-detail { padding: 10px 8px 12px 42px; background: #f8f7f3; }
	.g-detail-terms { font-size: var(--text-sm); line-height: 1.6; color: var(--color-fg-light); margin: 0 0 8px; }
	.g-lbl { display: block; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; color: var(--color-fg-light); margin: 0 0 4px; }
	.g-fic { color: var(--color-fg-light); }
	.g-pct { font-size: 0.9em; color: #9a9a9a; }
	.g-ex { margin: 0; padding-left: 1.4em; columns: 2; column-gap: 28px; }
	.g-ex li { font-size: var(--text-sm); line-height: 1.5; break-inside: avoid; color: var(--color-fg); }

	.sh-note { font-size: var(--text-sm); margin: 0 0 var(--space-5); }
	.sh-note summary { cursor: pointer; color: var(--color-fg-light); list-style-position: inside; width: fit-content; }
	.sh-note summary:hover { color: var(--color-fg); }
	.sh-note p { font-size: var(--text-sm); line-height: 1.55; color: var(--color-fg-light); margin: 8px 0 0; }
	.sh-note strong { color: var(--color-fg); }

	@media (max-width: 640px) {
		.bk-row { grid-template-columns: 22px minmax(0, 1fr) 56px; }
		.bk-row .bk-sp { display: none; }
		.bk-filter { width: 150px; }
		.g-ex { columns: 1; }
		.g-detail { padding-left: 30px; }
		.g-more button { margin-left: 30px; }
	}
	.smooth-toggle { display: inline-flex; align-items: center; gap: 6px; font-size: var(--text-sm); color: var(--color-fg-light); cursor: pointer; user-select: none; }
	.smooth-toggle input { margin: 0; width: 16px; height: 16px; accent-color: var(--color-fg); appearance: auto; -webkit-appearance: auto; }
	.fmt-btn { padding: 6px 12px; border: 1px solid var(--color-border); border-radius: 8px; background: #fff; font-family: var(--font-sans); font-size: var(--text-sm); font-weight: 600; color: var(--color-fg); cursor: pointer; }
	.fmt-btn.on { background: var(--color-fg); border-color: var(--color-fg); color: #fff; }
	.fmt-btn:disabled { color: var(--color-fg-light); cursor: default; opacity: 0.6; }
</style>
