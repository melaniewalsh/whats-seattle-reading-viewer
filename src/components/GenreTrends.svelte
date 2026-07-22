<script>
	// GenreTrends.svelte — the "Genres" tab.
	//
	// 30 genres, each precomputed (build_partition.py) two ways, with a toggle:
	//   • Overlap   — a genre's raw share of checkouts (books are multi-tagged, so
	//                 these overlap and almost everything drifts up over time).
	//   • Partition — each checkout assigned to the FIRST genre it matches, so the
	//                 shares sum to 100% and real declines appear.
	// Showing both side-by-side is the point: you can see why "share of checkouts"
	// looks like everything's rising until you make it a true partition.
	import { onMount } from "svelte";
	import { base } from "$app/paths";
	import GenreChart from "$components/GenreChart.svelte";
	import YearBrush from "$components/YearBrush.svelte";

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

	let data = $state(null);
	let loadError = $state("");
	let mode = $state("partition"); // "partition" | "overlap"
	let shown = $state(new Set());  // genre names currently plotted
	let showOther = $state(false);  // the "Other / Unclassified" partition line
	let expanded = $state(new Set());
	let genreFilter = $state(""); // search box: filter the table by genre name OR subject term
	// Long sections start collapsed so the table isn't a wall of rows.
	let collapsedGroups = $state(new Set(["Kids & Young Adult", "Nonfiction"]));
	function toggleGroup(name) {
		const s = new Set(collapsedGroups);
		s.has(name) ? s.delete(name) : s.add(name);
		collapsedGroups = s;
	}
	let isolatedKeys = $state([]);
	let genreOrder = $state([]);     // stable display order (by size, for colors)
	let genreByName = $state({});
	let lo = $state(0);              // time-slider window (month indices, inclusive)
	let hi = $state(0);
	let chartWrap = $state(null);    // ref to the chart container, for the PNG export
	let shareOpen = $state(false);   // whether the share popover is open
	let shareMsg = $state("");       // transient toast after copy/save

	onMount(async () => {
		try {
			const res = await fetch(`${base}/genres.json`);
			if (!res.ok) throw new Error(String(res.status));
			const d = await res.json();
			const by = {};
			for (const g of d.genres) by[g.name] = g;
			const order = [...d.genres].sort((a, b) => sum(b.partition) - sum(a.partition)).map((g) => g.name);
			genreByName = by;
			genreOrder = order;
			// Plot five genres but isolate Romance: only Romance's line shows, the
			// other four stay in the legend, greyed out (click to bring them back).
			const romance = by["Romance"] ? "Romance" : order[0];
			shown = new Set([romance, ...order.filter((n) => n !== romance)].slice(0, 5));
			isolatedKeys = [`g:${romance}`];
			lo = 0;
			hi = d.months.length - 1;
			data = d;
		} catch (e) {
			loadError = "Couldn't load genre data.";
		}
	});

	function sum(a) { let s = 0; for (const v of a || []) s += v; return s; }
	const share = (arr) => arr.map((v, i) => (data.total[i] ? (100 * v) / data.total[i] : 0));
	const overall = (arr) => (data ? (100 * sum(arr)) / Math.max(1, sum(data.total)) : 0);
	const seriesArr = (g) => (mode === "overlap" ? g.overlap : g.partition);
	const colorIdx = (name) => genreOrder.indexOf(name);
	const colorOf = (name) => PALETTE[colorIdx(name) % PALETTE.length];

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
			out.push({ key: "g:__other", name: "Other / Unclassified", color: "#b0b0b0", values: clip(data.other) });
		}
		return out;
	});

	function toggleShown(name) {
		const n = new Set(shown); n.has(name) ? n.delete(name) : n.add(name); shown = n;
		isolatedKeys = isolatedKeys.filter((k) => k !== `g:${name}`);
	}
	function toggleExpand(name) {
		const n = new Set(expanded); n.has(name) ? n.delete(name) : n.add(name); expanded = n;
	}
	// Clicking a genre row plots it (if not already) and toggles its detail. Use the
	// checkbox to remove it from the chart.
	function clickGenre(name) {
		if (!shown.has(name)) shown = new Set(shown).add(name);
		toggleExpand(name);
	}
	function toggleIsolate(k) {
		isolatedKeys = isolatedKeys.includes(k) ? isolatedKeys.filter((x) => x !== k) : [...isolatedKeys, k];
	}
	const isIsolated = (k) => isolatedKeys.includes(k);
	const showAll = () => (shown = new Set(genreOrder));
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

	// --- Share / download (mirrors the "By author" tab exactly) --------------
	const plotTitle = $derived(mode === "partition"
		? "Share of book checkouts · each counted once, in its first genre"
		: "Raw overlapping share of book checkouts · books are multi-tagged");
	const legendItems = $derived(series.map((s) => ({ label: s.name, color: s.color, key: s.key })));

	// A shareable link (reopens the genre tab) plus a caption.
	function shareTarget() {
		let link = window.location.href;
		try {
			const url = new URL(window.location.href);
			url.searchParams.set("view", "genre");
			link = url.toString();
		} catch {}
		const text = "What Is Seattle Reading? — What genres is Seattle checking out?";
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
			shareMsg = "Chart image copied — paste it (⌘/Ctrl+V) into your post";
			setTimeout(() => (shareMsg = ""), 4500);
		}
	}

	async function copyShareLink() {
		const { link } = shareTarget();
		try { await navigator.clipboard.writeText(link); } catch {}
		shareMsg = "Link copied!";
		setTimeout(() => (shareMsg = ""), 2000);
		shareOpen = false;
	}

	// Copy the chart image itself to the clipboard (paste it straight into any
	// post/doc). Falls back to downloading if the browser can't copy images.
	async function copyImage() {
		shareOpen = false;
		try {
			if (!(navigator.clipboard && window.ClipboardItem)) throw new Error("no clipboard");
			await navigator.clipboard.write([new ClipboardItem({ "image/png": renderChartBlob() })]);
			shareMsg = "Chart image copied to clipboard";
		} catch {
			const blob = await renderChartBlob();
			if (blob) saveBlob(blob, "seattle-reading-genres.png");
			shareMsg = "Image saved (clipboard unavailable)";
		}
		setTimeout(() => (shareMsg = ""), 2600);
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
		const PROPS = ["fill", "stroke", "stroke-width", "stroke-dasharray", "stroke-linecap", "stroke-linejoin", "opacity", "font-family", "font-size", "font-weight", "text-anchor", "color"];
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
		const scale = 2, padX = 28, titleH = 68, footH = 40;
		const canvas = document.createElement("canvas");
		const ctx = canvas.getContext("2d");
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
		ctx.fillText("What genres is Seattle checking out?", padX, 34);
		ctx.fillStyle = "#666666";
		ctx.font = '13px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
		ctx.fillText(plotTitle, padX, 54);
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
		ctx.fillText("What Is Seattle Reading?  ·  Seattle Public Library checkouts", padX, titleH + h + legendH + 24);
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
		shareMsg = "Image saved — attach it to your post";
		setTimeout(() => (shareMsg = ""), 3200);
	}
</script>

<div class="genres">
	{#if loadError}
		<p class="load-error">{loadError}</p>
	{:else if !data}
		<p class="loading"><span class="spinner" aria-hidden="true"></span>Loading genre trends…</p>
	{:else}
		<div class="modebar">
			<div class="seg" role="tablist">
				<button class="seg-btn" class:on={mode === "partition"} onclick={() => (mode = "partition")}>Partition</button>
				<button class="seg-btn" class:on={mode === "overlap"} onclick={() => (mode = "overlap")}>Overlap</button>
			</div>
			<p class="mode-note">
				{#if mode === "partition"}
					Each checkout counted <strong>once</strong>, in the first genre it matches — shares sum to 100%
				{:else}
					Each genre's <strong>raw</strong> share; books are multi-tagged so these overlap
				{/if}
			</p>
		</div>

		<div class="chartwrap" bind:this={chartWrap}>
			<GenreChart months={viewMonths} {series} {isolatedKeys} />
		</div>
		<YearBrush months={data.months} values={data.total} bind:lo bind:hi />

		{#if series.length >= 2}
			<div class="glegend">
				{#each series as s (s.key)}
					<button class="gleg-btn" class:on={isIsolated(s.key)} class:dim={isolatedKeys.length && !isIsolated(s.key)}
							title="Show only this — click again to bring the others back" onclick={() => toggleIsolate(s.key)}
					><span class="gleg-sw" style="background:{s.color}"></span>{s.name}</button>
				{/each}
				{#if isolatedKeys.length}<button class="gleg-showall" onclick={() => (isolatedKeys = [])}>Show all</button>{/if}
			</div>
		{/if}

		<div class="chart-actions">
			<button class="chart-action" onclick={downloadChart} title="Download the chart as a PNG image">
				<span aria-hidden="true">⤓</span> Download image
			</button>
			<div class="share-wrap">
				<button class="chart-action" onclick={() => (shareOpen = !shareOpen)} title="Share this chart" aria-haspopup="true" aria-expanded={shareOpen}>
					<span aria-hidden="true">↗</span> Share
				</button>
				{#if shareOpen}
					<button class="share-backdrop" aria-label="Close share menu" onclick={() => (shareOpen = false)}></button>
					<div class="share-menu" role="menu">
						<button role="menuitem" class="share-item copyimg" onclick={copyImage}><span class="share-ic" aria-hidden="true">⧉</span> Copy image</button>
						<button role="menuitem" class="share-item copy" onclick={copyShareLink}><span class="share-ic" aria-hidden="true">🔗</span> Copy link</button>
						<button role="menuitem" class="share-item img" onclick={shareImage}><span class="share-ic" aria-hidden="true">↗</span> Share via…</button>
					</div>
				{/if}
			</div>
			{#if shareMsg}<span class="share-msg" role="status">{shareMsg}</span>{/if}
		</div>

		<div class="gtable-head-row">
			<h3 class="gtable-title">All {genreOrder.length} genres</h3>
			<div class="bulk">
				<button onclick={showAll}>Show all</button><button onclick={hideAll}>Hide all</button>
			</div>
		</div>
		<div class="gt-search">
			<input type="search" class="gt-search-input" bind:value={genreFilter}
				placeholder="Search genres or subject terms — e.g. vampire, cooking, memoir" aria-label="Search genres" />
			{#if genreFilter}<button class="gt-search-clear" onclick={() => (genreFilter = "")} aria-label="Clear search" title="Clear">×</button>{/if}
		</div>

		<div class="gtable">
			<div class="gt-head" role="row">
				<span class="gt-cell gt-show">Plot</span>
				<span class="gt-cell gt-name">Genre</span>
				<span class="gt-cell gt-share">Share</span>
			</div>
			{#each GROUPS as [groupName, names] (groupName)}
				{@const inGroup = names.filter((n) => genreByName[n] && genreMatches(n)).sort((a, b) => sum(genreByName[b].partition) - sum(genreByName[a].partition))}
				{#if inGroup.length}
				{@const isCollapsed = collapsedGroups.has(groupName) && !genreFilter}
				<button type="button" class="gt-group" class:collapsed={isCollapsed} role="row" aria-expanded={!isCollapsed} onclick={() => toggleGroup(groupName)}>
					<span class="gt-group-tri" aria-hidden="true">{isCollapsed ? "▸" : "▾"}</span>{groupName}<span class="gt-group-count">{inGroup.length}</span>
				</button>
				{#if !isCollapsed}
				{#each inGroup as name (name)}
					{@const g = genreByName[name]}
					<div class="gt-row genre-row" role="row" class:off={!shown.has(name)}>
						<span class="gt-cell gt-show"><input type="checkbox" checked={shown.has(name)} onchange={() => toggleShown(name)} aria-label={`Plot ${name}`} /></span>
						<button class="gt-cell gt-name" onclick={() => clickGenre(name)} aria-expanded={expanded.has(name)}>
							<span class="gt-tri">{expanded.has(name) ? "▾" : "▸"}</span>
							<span class="gt-sw" style="background:{colorOf(name)}"></span>{name}
						</button>
						<span class="gt-cell gt-share">{overall(seriesArr(g)).toFixed(1)}%</span>
					</div>
					{#if expanded.has(name)}
						<div class="gt-detail">
							<div class="gt-terms">Subject terms:{#if g.terms?.length} {#each g.terms as t, i}<code>{t}</code>{i < g.terms.length - 1 ? " " : ""}{/each}{/if}{#if g.ficTerms?.length}<span class="gt-ficlbl">{g.terms?.length ? "· " : ""}only with a <strong>Fiction</strong> tag:</span> {#each g.ficTerms as t, i}<code class="fic">{t}</code>{i < g.ficTerms.length - 1 ? " " : ""}{/each}{/if}</div>
							{#if cleanExamples(g.examples).length}
								<span class="gt-ex-label">Most-checked-out titles</span>
								<ol class="gt-ex-list">{#each cleanExamples(g.examples) as title}<li>{title}</li>{/each}</ol>
							{/if}
						</div>
					{/if}
				{/each}
				{/if}
			{/if}
			{/each}
				<div class="gt-row genre-row other-row" class:off={!showOther}>
					<span class="gt-cell gt-show"><input type="checkbox" checked={showOther} onchange={() => (showOther = !showOther)} aria-label="Plot Other" /></span>
					<button class="gt-cell gt-name" onclick={() => toggleExpand("__other")} aria-expanded={expanded.has("__other")}>
						<span class="gt-tri">{expanded.has("__other") ? "▾" : "▸"}</span>
						<span class="gt-sw" style="background:#b0b0b0"></span>Other / Unclassified
					</button>
					<span class="gt-cell gt-share">{overall(data.other).toFixed(1)}%</span>
				</div>
				{#if expanded.has("__other")}
					<div class="gt-detail">
						<div class="gt-terms">Books matching <em>none</em> of the {genreOrder.length} genres — mostly general, un-genre'd nonfiction.</div>
						{#if data.otherTags?.length}
							<div class="gt-terms">Top subject tags here: {#each data.otherTags as t, i}<code>{t[0]}</code><span class="gt-pct">{t[1]}%</span>{i < data.otherTags.length - 1 ? " " : ""}{/each}</div>
						{/if}
						{#if cleanExamples(data.otherExamples).length}
							<span class="gt-ex-label">Most-checked-out titles</span>
							<ol class="gt-ex-list">{#each cleanExamples(data.otherExamples) as title}<li>{title}</li>{/each}</ol>
						{/if}
					</div>
				{/if}
		</div>

		<details class="sh-note">
			<summary>A note on how genres are defined</summary>
			<p>
				Genres here come from <strong>Library of Congress and BISAC subject headings</strong> in the
				library's catalog records. Those headings are applied inconsistently, are US-centric, and have
				been widely critiqued for how they name racial, ethnic, and other identity groups — from Sanford
				Berman's <em>Prejudices and Antipathies</em> (1971) to more recent work on “othering” in library
				classification and the “Illegal aliens” heading controversy.
			</p>
			<p>
				So categories like <em>African American</em>, <em>Asian</em>, <em>Hispanic &amp; Latino</em>,
				<em>Native American</em>, or <em>Jewish</em> fiction reflect <strong>how books were catalogued</strong> —
				an approximate, contested classification — not the identities of the authors. We also had to
				<em>aggregate</em> many narrower headings (e.g. “Chinese fiction,” “Bengali Americans fiction”)
				into one bucket, which flattens real differences. Read them as a rough lens, not an authoritative count.
			</p>
		</details>

		<p class="gsource">Source: Seattle Public Library — Checkouts by Title (data.seattle.gov). Genre via subject-heading match; all books (print + digital, incl. audiobooks). Example titles reflect the partition (first-match) assignment.</p>
	{/if}
</div>

<style>
	.genres { margin-top: 8px; }
	.genres input[type="checkbox"] {
		appearance: auto; -webkit-appearance: auto; width: 16px; height: 16px;
		accent-color: var(--color-fg); background: none; flex: none; cursor: pointer; margin: 0;
	}
	.genres h2 { font-family: var(--font-serif); font-size: 1.9rem; margin: 0 0 4px; }
	.meta { color: var(--color-fg-light); font-family: var(--font-sans); font-size: 0.95rem; margin: 0 0 10px; }
	.sh-note { font-family: var(--font-sans); font-size: 0.85rem; margin: 0 0 18px; }
	.sh-note summary { cursor: pointer; color: var(--color-fg-light); list-style-position: inside; width: fit-content; }
	.sh-note summary:hover { color: var(--color-fg); }
	.sh-note p { font-size: 0.85rem; line-height: 1.55; color: var(--color-fg-light); margin: 8px 0 0; max-width: 68ch; }
	.sh-note strong { color: var(--color-fg); }
	.loading, .load-error { font-family: var(--font-sans); color: var(--color-fg-light); }

	.modebar { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; margin: 0 0 8px; }
	.seg { display: inline-flex; border: 1px solid var(--color-border); border-radius: 999px; overflow: hidden; flex: none; }
	.seg-btn { font-family: var(--font-sans); font-size: 0.82rem; font-weight: 600; padding: 5px 16px; border: none; background: var(--color-white); color: var(--color-fg-light); cursor: pointer; }
	.seg-btn.on { background: var(--color-fg); color: var(--color-white); }
	.mode-note { font-family: var(--font-sans); font-size: 0.82rem; color: var(--color-fg-light); margin: 0; flex: 1; min-width: 200px; line-height: 1.4; }
	.chartwrap { width: 100%; }

	/* Share / download — identical to the "By author" tab. */
	.chart-actions { display: flex; flex-wrap: wrap; align-items: center; justify-content: flex-end; gap: 8px; margin: 10px 0 4px; }
	.chart-action { display: inline-flex; align-items: center; gap: 6px; font-family: var(--font-sans); font-size: 0.8rem; font-weight: 600; color: var(--color-fg); cursor: pointer; padding: 6px 12px; border: 1.5px solid var(--color-border); border-radius: 999px; background: var(--color-white); transition: background 0.12s, border-color 0.12s; }
	.chart-action:hover { border-color: var(--color-fg-light); background: #f7f7f7; }
	.chart-action span { opacity: 0.7; font-size: 0.95em; }
	.share-msg { font-family: var(--font-sans); font-size: 0.8rem; font-weight: 600; color: #2e7d32; }
	.share-wrap { position: relative; display: inline-flex; }
	.share-backdrop { position: fixed; inset: 0; z-index: 40; background: none; border: none; cursor: default; }
	.share-menu { position: absolute; top: calc(100% + 6px); right: 0; z-index: 41; display: flex; flex-direction: column; min-width: 168px; padding: 5px; background: var(--color-white); border: 1px solid var(--color-border); border-radius: 10px; box-shadow: 0 8px 24px rgba(0, 0, 0, 0.16); }
	.share-item { display: flex; align-items: center; gap: 10px; padding: 8px 10px; border: none; border-radius: 7px; background: none; font-family: var(--font-sans); font-size: 0.85rem; font-weight: 600; color: var(--color-fg); cursor: pointer; text-align: left; }
	.share-item:hover { background: #f2f2f2; }
	.share-ic { display: inline-flex; align-items: center; justify-content: center; width: 22px; height: 22px; flex: none; border-radius: 5px; font-size: 0.75rem; font-weight: 700; color: #fff; font-style: normal; }
	.share-item.fb .share-ic { background: #1877f2; }
	.share-item.tw .share-ic { background: #000; }
	.share-item.bs .share-ic { background: #0a7aff; }
	.share-item.li .share-ic { background: #0a66c2; }
	.share-item.img .share-ic { background: #2e7d32; }
	.share-item.copyimg .share-ic { background: #444; }
	.share-item.copy .share-ic { background: #666; }
	.share-sep { height: 1px; margin: 4px 6px; background: var(--color-border); }

	.glegend { display: flex; flex-wrap: wrap; justify-content: center; gap: 6px 14px; margin: 12px 0 4px; font-family: var(--font-sans); font-size: 0.82rem; font-weight: 600; }
	.gleg-btn { display: inline-flex; align-items: center; gap: 6px; border: none; background: none; padding: 2px 5px; border-radius: 6px; font: inherit; color: var(--color-fg); cursor: pointer; transition: opacity 0.12s, background 0.12s; }
	.gleg-btn:hover { background: var(--color-gray-100); }
	.gleg-btn.dim { opacity: 0.38; }
	.gleg-btn.on { background: var(--color-gray-100); box-shadow: inset 0 0 0 1.5px var(--color-border); }
	.gleg-sw { width: 12px; height: 12px; border-radius: 3px; flex: none; }
	.gleg-showall { border: 1px solid var(--color-border); background: var(--color-white); padding: 3px 12px; border-radius: 999px; font-family: var(--font-sans); font-size: 0.78rem; font-weight: 600; color: var(--color-fg); cursor: pointer; }

	.gtable-head-row { display: flex; align-items: baseline; justify-content: space-between; margin: 26px 0 4px; gap: 12px; }
	.gtable-title { font-family: var(--font-serif); font-size: 1.2rem; margin: 0; }
	.bulk { display: flex; gap: 6px; }
	.bulk button { font-family: var(--font-sans); font-size: 0.72rem; border: 1px solid var(--color-border); background: var(--color-white); color: var(--color-fg-light); border-radius: 999px; padding: 2px 10px; cursor: pointer; }
	.gtable-hint { font-family: var(--font-sans); font-size: 0.85rem; color: var(--color-fg-light); margin: 0 0 12px; line-height: 1.45; }
	.gt-search { position: relative; margin: 0 0 12px; }
	.gt-search-input { width: 100%; box-sizing: border-box; padding: 9px 34px 9px 14px; font-family: var(--font-sans); font-size: 0.9rem; border: 1px solid var(--color-border); border-radius: 999px; background: var(--color-white); color: var(--color-fg); }
	.gt-search-input:focus { outline: none; border-color: #3f88cc; box-shadow: 0 0 0 3px rgba(63,136,204,0.15); }
	.gt-search-clear { position: absolute; right: 6px; top: 50%; transform: translateY(-50%); width: 24px; height: 24px; border: none; background: none; font-size: 1.1rem; line-height: 1; color: var(--color-fg-light); cursor: pointer; border-radius: 50%; }
	.gt-search-clear:hover { background: var(--color-gray-100); color: var(--color-fg); }

	.gtable { border: 1px solid var(--color-border); border-radius: var(--radius-md); overflow: hidden; font-family: var(--font-sans); }
	.gt-head, .gt-row { display: grid; grid-template-columns: 48px 1fr 72px; align-items: center; gap: 10px; padding: 8px 12px; }
	.gt-head { font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.04em; color: var(--color-fg-light); font-weight: 700; border-bottom: 1px solid var(--color-border); }
	.gt-group { display: flex; align-items: center; gap: 6px; width: 100%; padding: 7px 12px; background: var(--color-gray-100, #f2f2f2); border: none; border-top: 1px solid var(--color-border); font-family: var(--font-sans); font-size: 0.72rem; font-weight: 800; text-transform: uppercase; letter-spacing: 0.05em; color: var(--color-fg); text-align: left; cursor: pointer; }
	.gt-group:hover { background: var(--color-gray-200, #e8e8e8); }
	.gt-group:first-of-type { border-top: none; }
	.gt-group-tri { font-size: 0.6rem; color: var(--color-fg-light); width: 0.7em; }
	.gt-group-count { margin-left: 4px; font-weight: 700; color: var(--color-fg-light); letter-spacing: 0; }
	.genre-row { border-top: 1px solid var(--color-gray-100); font-size: 0.9rem; }
	.genre-row:first-of-type { border-top: none; }
	.genre-row.off { opacity: 0.55; }
	.other-row { font-style: italic; color: var(--color-fg-light); }
	.gt-show { text-align: center; }
	.gt-name { display: inline-flex; align-items: center; gap: 7px; border: none; background: none; font: inherit; font-weight: 600; color: var(--color-fg); cursor: pointer; text-align: left; padding: 0; }
	.gt-tri { color: #6a4c93; font-size: 0.8rem; width: 12px; flex: none; }
	.gt-sw { width: 11px; height: 11px; border-radius: 3px; flex: none; }
	.gt-share { text-align: right; font-weight: 600; white-space: nowrap; font-size: 0.85rem; }

	.gt-detail { padding: 8px 12px 12px 48px; background: #fbfbf9; border-top: 1px solid var(--color-gray-100); }
	.gt-terms { font-size: 0.78rem; color: var(--color-fg-light); margin-bottom: 8px; }
	.gt-terms code { background: var(--color-gray-100); padding: 1px 5px; border-radius: 4px; font-size: 0.92em; }
	.gt-terms code.fic { background: #efe9f5; color: #6a4c93; }
	.gt-ficlbl { margin: 0 3px 0 5px; color: var(--color-fg-light); }
	.gt-pct { margin: 0 6px 0 3px; font-size: 0.9em; color: var(--color-fg-light); }
	.gt-ex-label { display: block; font-size: 0.66rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; color: var(--color-fg-light); margin-bottom: 6px; }
	.gt-ex-list { margin: 0; padding-left: 1.4em; columns: 2; column-gap: 28px; }
	.gt-ex-list li { font-size: 0.82rem; line-height: 1.5; break-inside: avoid; color: var(--color-fg); }

	.gsource { font-family: var(--font-sans); font-size: 0.78rem; color: var(--color-fg-light); margin: 14px 0 0; }
</style>
