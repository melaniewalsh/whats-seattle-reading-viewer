<script>
	// Compare.svelte — the Checkout Trends page's compare view: any authors and
	// books on one chart, one line each (like the Google Books Ngram Viewer).
	// The page's search field adds to it (Index.svelte calls addFromSearch).
	// Picks live in the URL (?c=a~<author-slug>&c=w~<author-slug>~<title>) so a
	// comparison can be shared.
	import { onMount } from "svelte";
	import { MediaQuery } from "svelte/reactivity";
	import LinkIcon from "@lucide/svelte/icons/link";
	import DownloadIcon from "@lucide/svelte/icons/download";
	import ChevronDownIcon from "@lucide/svelte/icons/chevron-down";
	import TableIcon from "@lucide/svelte/icons/table";
	import ImageIcon from "@lucide/svelte/icons/image";
	import ShareIcon from "@lucide/svelte/icons/share-2";
	import { renderChartPng, saveBlob } from "$utils/chartImage.js";
	import LineChart from "$components/StackedAreaChart.svelte";
	import YearBrush from "$components/YearBrush.svelte";
	import DataInfo from "$components/DataInfo.svelte";
	import { EVENT_ANNOTATIONS } from "$data/eventAnnotations.js";
	import { getMonths, getAuthor, densify } from "$components/db.js";
	import { normalizeWorkKey, cleanTitleForDisplay, bareTitleAliases } from "$utils/workTitle.js";
	import { displayName } from "$utils/displayName.js";
	import { compactNumber } from "$utils/format.js";
	import workOverrides from "$data/work-overrides.json";

	// onSingle(pick): removing picks left just one -> show its own page.
	// onEmpty(): every pick removed.
	let { openAuthor = () => {}, openTitle = () => {}, onSingle = () => {}, onEmpty = () => {}, onPicks = () => {} } = $props();
	// Phones: the year slider and the Download/Share row run the full width
	// (the plot itself is narrower, beside the line names).
	const phone = new MediaQuery("max-width: 600px");

	// Same order as the trends viewer's book colors; a pick keeps its color
	// while others come and go.
	const COLORS = ["#3f88cc", "#e58a00", "#6a4c93", "#1f7a4d", "#c2255c", "#0b7285", "#b0813b", "#5f6b7a"];
	const MAX = COLORS.length;
	const MONTH_FULL = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

	// Starting points, and what an empty Compare page opens on.
	const MATCHUPS = [
		{ label: "Wuthering Heights vs. Pride and Prejudice", picks: ["w~emily-bronte-1818~Wuthering Heights", "w~jane-austen-1775~Pride and Prejudice"] },
		{ label: "Sally Rooney vs. Colleen Hoover", picks: ["a~sally-rooney", "a~colleen-hoover"] },
		{ label: "Stephen King vs. Agatha Christie", picks: ["a~stephen-king-1947", "a~agatha-christie-1890"] },
		{ label: "Octavia E. Butler vs. Toni Morrison", picks: ["a~octavia-e-butler", "a~toni-morrison-1931"] },
	];

	// Under the field: comparisons AND single authors / books, to show that
	// both work.
	const TRY = [
		{ label: "Sally Rooney", kind: "author", slug: "sally-rooney" },
		MATCHUPS[0],
		{ label: "Pachinko", kind: "work", slug: "min-jin-lee", title: "Pachinko" },
		MATCHUPS[2],
	];

	let months = $state([]);
	let picks = $state.raw([]); // [{ id, kind, slug, title?, label, color, values }]
	let loading = $state(0);
	let smooth = $state(true);
	let yearLo = $state(0);
	let yearHi = $state(0);
	let plotInset = $state(0);
	let dlOpen = $state(false);
	let shareOpen = $state(false);
	let shareMsg = $state("");
	let flashTimer;
	function flash(msg, ms = 2200) {
		clearTimeout(flashTimer);
		shareMsg = msg;
		flashTimer = setTimeout(() => (shareMsg = ""), ms);
	}
	let chartWrap = $state(null);
	let notFound = $state("");

	// One fetch per author, shared by every pick from that author.
	const authorCache = new Map();
	function loadAuthor(slug) {
		if (!authorCache.has(slug)) authorCache.set(slug, getAuthor(slug).catch(() => null));
		return authorCache.get(slug);
	}

	// Resolve a pick id ("a~slug" or "w~slug~title") to its monthly series.
	async function resolve(id) {
		const [kind, slug, ...rest] = id.split("~");
		const a = await loadAuthor(slug);
		if (!a) return null;
		if (kind === "a") {
			return { id, kind: "author", slug, label: displayName(a.name), values: densify(a.series, months.length) };
		}
		const title = rest.join("~");
		const want = normalizeWorkKey(title);
		// Group editions the way the trends page does: the curated groupings in
		// work-overrides.json first (translations, retitled editions), then the
		// automatic work key. So a book's total matches its own page.
		const ovr = new Map();
		(workOverrides[slug] || []).forEach((titles, i) => (titles || []).forEach((t) => ovr.set(t, `ovr-${i}`)));
		const aliases = bareTitleAliases(a.titles.map((t) => t.title));
		const keyOf = (t) => ovr.get(t.title) ?? (aliases.get(normalizeWorkKey(t.title)) ?? normalizeWorkKey(t.title));
		let seed = a.titles.find((t) => normalizeWorkKey(t.title) === want);
		// Loose fallback, as on the trends page: substring match on the work key.
		if (!seed) seed = a.titles.find((t) => { const k = normalizeWorkKey(t.title); return want && k && (k.includes(want) || want.includes(k)); });
		if (!seed) return null;
		const eds = a.titles.filter((t) => keyOf(t) === keyOf(seed));
		const values = new Array(months.length).fill(0);
		for (const t of eds) for (const [i, v] of t.series) values[i] += v;
		return { id, kind: "work", slug, title, label: cleanTitleForDisplay(seed.title) || title, author: displayName(a.name), values };
	}

	function nextColor() {
		const used = new Set(picks.map((p) => p.color));
		return COLORS.find((c) => !used.has(c)) || COLORS[picks.length % COLORS.length];
	}

	async function addPick(id) {
		if (picks.some((p) => p.id === id) || picks.length >= MAX) return;
		notFound = "";
		loading++;
		try {
			const p = await resolve(id);
			if (p && !picks.some((x) => x.id === id)) picks = [...picks, { ...p, color: nextColor() }];
			else if (!p) notFound = id.split("~").slice(-1)[0];
		} finally {
			loading--;
		}
		syncUrl();
	}
	function removePick(id) {
		const was = picks.length;
		picks = picks.filter((p) => p.id !== id);
		// Down from a comparison to one: back to that author's or book's page.
		if (was >= 2 && picks.length === 1) return onSingle(picks[0]);
		if (!picks.length) return onEmpty();
		syncUrl();
	}
	async function setPicks(ids) {
		picks = [];
		yearLo = 0;
		yearHi = Math.max(months.length - 1, 0);
		for (const id of ids) await addPick(id);
	}
	export const setPicksFromIds = (ids) => setPicks(ids);
	export function addFromSearch(res) {
		addPick(res.kind === "work" ? `w~${res.slug}~${res.title}` : `a~${res.slug}`);
	}
	export const count = () => picks.length;
	export const full = () => picks.length >= MAX;

	function syncUrl() {
		try {
			const url = new URL(window.location);
			["c", "tab", "author", "title"].forEach((k) => url.searchParams.delete(k));
			for (const p of picks) url.searchParams.append("c", p.id);
			window.history.replaceState({}, "", url);
		} catch {}
		// The page's search field shows the list ("Sally Rooney, Colleen Hoover").
		onPicks(picks.map((p) => ({ id: p.id, label: p.label })));
	}

	onMount(async () => {
		months = await getMonths();
		yearHi = Math.max(months.length - 1, 0);
		let ids = [];
		try { ids = new URLSearchParams(window.location.search).getAll("c"); } catch {}
		await setPicks(ids.length ? ids : MATCHUPS[0].picks);
	});

	// The chart, cut to the slider's years.
	const isYearFiltered = $derived(months.length > 0 && (yearLo > 0 || yearHi < months.length - 1));
	const viewMonths = $derived(isYearFiltered ? months.slice(yearLo, yearHi + 1) : months);
	const series = $derived(
		picks.map((p) => ({
			key: p.id,
			legendKey: p.id,
			label: p.label,
			color: p.color,
			values: isYearFiltered ? p.values.slice(yearLo, yearHi + 1) : p.values
		}))
	);
	// The slider's backdrop: everything picked, added up.
	const brushValues = $derived.by(() => {
		const out = new Array(months.length).fill(0);
		for (const p of picks) p.values.forEach((v, i) => (out[i] += v));
		return out;
	});
	// Start the slider at the first year anything picked was checked out.
	const brushStart = $derived.by(() => {
		const i = brushValues.findIndex((v) => v > 0);
		if (i <= 0) return 0;
		const yr = months[i]?.slice(0, 4);
		return Math.max(0, months.findIndex((m) => m.slice(0, 4) === yr));
	});
	$effect(() => {
		if (yearLo < brushStart) yearLo = brushStart;
	});

	// Under the chart: each pick's total and its best month.
	const rows = $derived(
		picks.map((p) => {
			let best = 0;
			p.values.forEach((v, i) => { if (v > p.values[best]) best = i; });
			const m = months[best] || "";
			return {
				...p,
				total: p.values.reduce((s, v) => s + v, 0),
				peak: p.values[best] || 0,
				peakLabel: m ? `${MONTH_FULL[Number(m.slice(5, 7)) - 1]} ${m.slice(0, 4)}` : ""
			};
		})
	);

	// Downloads: the chart as an image, or every month's checkouts as a CSV.
	const fileStub = () =>
		picks.map((p) => p.label).join("-vs-").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 80) || "compare";
	function chartImage() {
		const labels = picks.map((p) => p.label);
		const title = labels.length <= 3 ? labels.join(" vs. ") : `Comparing ${labels.length} authors and books`;
		const yrs = viewMonths.length ? `, ${viewMonths[0].slice(0, 4)}–${viewMonths[viewMonths.length - 1].slice(0, 4)}` : "";
		return renderChartPng(chartWrap?.querySelector("svg"), {
			title,
			subtitle: `Checkouts a month at the Seattle Public Library${yrs}${smooth ? " (3-month average)" : ""}`,
			legend: picks.map((p) => ({ label: p.kind === "work" ? `${p.label} (${p.author})` : p.label, color: p.color }))
		});
	}
	async function downloadImage() {
		dlOpen = false;
		const blob = await chartImage();
		if (blob) saveBlob(blob, `${fileStub()}-spl-checkouts.png`);
	}
	// Copy the chart image to paste into a post or doc; where the browser can't
	// copy images, it downloads instead.
	async function copyImage() {
		shareOpen = false;
		try {
			if (!(navigator.clipboard && window.ClipboardItem)) throw new Error("no clipboard");
			// Hand the clipboard the promise itself (Safari needs the write to
			// start right away, inside the click).
			await navigator.clipboard.write([new ClipboardItem({ "image/png": chartImage() })]);
			flash("Image copied");
		} catch {
			const blob = await chartImage();
			if (blob) saveBlob(blob, `${fileStub()}-spl-checkouts.png`);
			flash("Image saved");
		}
	}
	// The phone's share sheet with the chart image; elsewhere, save the image.
	async function shareImage() {
		shareOpen = false;
		const blob = await chartImage();
		if (!blob) return;
		const name = `${fileStub()}-spl-checkouts.png`;
		const file = new File([blob], name, { type: "image/png" });
		const text = picks.map((p) => p.label).join(" vs. ") + " at the Seattle Public Library";
		if (navigator.canShare && navigator.canShare({ files: [file] })) {
			try { await navigator.share({ files: [file], title: text, text: `${text}\n${window.location.href}` }); } catch {}
			return;
		}
		saveBlob(blob, name);
		flash("Image saved — attach it to your post");
	}
	function downloadData() {
		dlOpen = false;
		const cell = (v) => {
			const t = String(v ?? "");
			return /[",\n\r]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t;
		};
		const head = ["date", ...picks.map((p) => (p.kind === "work" ? `${p.label} (${p.author})` : p.label))];
		const rows = months.map((m, i) => [`${m}-01`, ...picks.map((p) => p.values[i] || 0)]);
		const csv = [head, ...rows].map((r) => r.map(cell).join(",")).join("\r\n");
		saveBlob(new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8" }), `${fileStub()}-spl-checkouts.csv`);
	}

	// A line's name (at its end, or in the legend) opens that book's or
	// author's own page.
	function openPick(id) {
		const p = picks.find((x) => x.id === id);
		if (!p) return;
		if (p.kind === "work") openTitle(p.title, p.slug);
		else openAuthor(p.slug);
	}

	async function copyLink() {
		shareOpen = false;
		try {
			await navigator.clipboard.writeText(window.location.href);
			flash("Link copied");
		} catch {
			flash("Couldn’t copy. Copy the link from the address bar.", 3200);
		}
	}
</script>

<div class="compare">
	{#if picks.length === 1}<p class="cmp-note">Add a comma and another author or book above to compare.</p>{/if}
	<p class="try-row">
		<span class="try-lead">Try</span>
		{#each TRY as m, k}{#if k}<span class="try-sep" aria-hidden="true">·</span>{/if}<button class="try-link" class:is-title={m.kind === "work"} onclick={() => (m.picks ? setPicks(m.picks) : m.kind === "work" ? openTitle(m.title, m.slug) : openAuthor(m.slug))}>{m.label}</button>{/each}
	</p>
	{#if notFound}<p class="cmp-note">Couldn't find “{notFound}”.</p>{/if}

	<div class="cmp-chart">
		<div class="cmp-toolbar">
			<label class="smooth-toggle"><input type="checkbox" bind:checked={smooth} /> 3-month average</label>
		</div>
		{#if picks.length && months.length}
			<div class="chart-panel" style="--hang: {Math.max(0, plotInset - 16)}px">
			<div bind:this={chartWrap}><LineChart bind:plotInset months={viewMonths} {series} mode="line" {smooth} annotations={EVENT_ANNOTATIONS} onSeriesClick={openPick} /></div>
			{#if series.length >= 2}
				<div class="cmp-legend">
					{#each picks as p (p.id)}<button type="button" class="cl-item" title="See this {p.kind === 'work' ? 'book' : 'author'}'s own trends page" onclick={() => openPick(p.id)}><span class="cl-sw" style="background:{p.color}"></span>{p.label}</button>{/each}
				</div>
			{/if}
			{#if months.length - brushStart >= 24}
				<YearBrush {months} values={brushValues} start={brushStart} inset={phone.current ? 0 : plotInset} bind:lo={yearLo} bind:hi={yearHi} />
			{/if}
			<div class="chart-foot" style="padding-right: {phone.current ? 0 : plotInset}px">
				<p class="chart-source">Source: <a href="https://data.seattle.gov/Community-and-Culture/Checkouts-by-Title/tmmm-ytt6" target="_blank" rel="noopener noreferrer">Seattle Public Library open data</a>, every edition (print, ebook and audiobook).{" "}<DataInfo first={months[0]} last={months[months.length - 1]} />.</p>
				<div class="foot-actions">
					<span class="dl-wrap">
						<button class="tb-btn" onclick={() => (dlOpen = !dlOpen)} aria-haspopup="true" aria-expanded={dlOpen}><DownloadIcon size={13} strokeWidth={2} aria-hidden="true" /> Download <ChevronDownIcon size={12} strokeWidth={2} aria-hidden="true" /></button>
						{#if dlOpen}
							<button class="dl-backdrop" aria-label="Close download menu" onclick={() => (dlOpen = false)}></button>
							<div class="dl-menu" role="menu">
								<button role="menuitem" onclick={downloadData}><TableIcon size={15} strokeWidth={2} aria-hidden="true" /> Data <span class="dl-fmt">CSV</span></button>
								<button role="menuitem" onclick={downloadImage}><ImageIcon size={15} strokeWidth={2} aria-hidden="true" /> Image <span class="dl-fmt">PNG</span></button>
							</div>
						{/if}
					</span>
					<span class="dl-wrap">
						<button class="tb-btn" onclick={() => (shareOpen = !shareOpen)} title="Share this chart" aria-haspopup="true" aria-expanded={shareOpen}><ShareIcon size={13} strokeWidth={2} aria-hidden="true" /> Share</button>
						{#if shareOpen}
							<button class="dl-backdrop" aria-label="Close share menu" onclick={() => (shareOpen = false)}></button>
							<div class="dl-menu" role="menu">
								<button role="menuitem" onclick={copyImage}><ImageIcon size={15} strokeWidth={2} aria-hidden="true" /> Copy image</button>
								<button role="menuitem" onclick={copyLink}><LinkIcon size={15} strokeWidth={2} aria-hidden="true" /> Copy link</button>
								<button role="menuitem" onclick={shareImage}><ShareIcon size={15} strokeWidth={2} aria-hidden="true" /> Share via…</button>
							</div>
						{/if}
					</span>
					{#if shareMsg}<span class="share-msg" role="status">{shareMsg}</span>{/if}
				</div>
			</div>
			</div>
		{:else if loading}
			<p class="cmp-empty" role="status">Loading…</p>
		{:else}
			<p class="cmp-empty">Search above to add authors or books, or try one of the matchups.</p>
		{/if}
	</div>

	{#if rows.length}
		<table class="cmp-table">
			<thead><tr><th>On the chart</th><th class="num">Total checkouts</th><th class="num">Best month</th></tr></thead>
			<tbody>
				{#each rows as r (r.id)}
					<tr>
						<td>
							<span class="chip-sw" style="background:{r.color}"></span>
							<button class="row-link" class:is-work={r.kind === "work"} title="See this {r.kind === 'work' ? 'book' : 'author'}'s own trends page" onclick={() => (r.kind === "work" ? openTitle(r.title, r.slug) : openAuthor(r.slug))}>{r.label}</button>
							{#if r.kind === "work"}<span class="chip-by">by {r.author}</span>{/if}
						</td>
						<td class="num">{compactNumber(r.total)}</td>
						<td class="num">{r.peak.toLocaleString()} <span class="muted">in {r.peakLabel}</span></td>
					</tr>
				{/each}
			</tbody>
		</table>
	{/if}
</div>

<style>
	.compare { font-family: var(--font-sans); }

	/* What's on the chart: removable chips, each in its line's color. */
	.chips { display: flex; flex-wrap: wrap; gap: 8px; list-style: none; margin: 12px 0 0; padding: 0; }
	.chip { display: inline-flex; align-items: center; gap: 7px; padding: 5px 6px 5px 10px; border: 1px solid var(--color-border); border-radius: 999px; background: #fff; font-size: 14.5px; }
	.chip-sw { display: inline-block; width: 10px; height: 10px; border-radius: 2px; flex: none; vertical-align: 1px; }
	.chip-name { font-weight: 600; color: var(--color-fg); }
	.is-work { font-family: var(--font-serif); font-style: italic; font-weight: 500; }
	.chip-by { color: var(--color-fg-light); font-size: 13px; }
	.chip-x { display: inline-flex; align-items: center; justify-content: center; width: 22px; height: 22px; padding: 0; border: 0; border-radius: 50%; background: none; color: var(--color-fg-light); font-size: 17px; line-height: 1; cursor: pointer; }
	.chip-x:hover { background: var(--color-gray-100); color: var(--color-fg); }

	.try-row { display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 7px; margin: 12px 0 0; font-size: 14.5px; color: var(--color-fg-light); }
	.try-lead::after { content: ":"; }
	.try-sep { color: var(--color-gray-300, #c8c8c8); }
	.try-link { padding: 0; border: 0; background: none; font: inherit; color: var(--color-fg); cursor: pointer; text-decoration: underline; text-decoration-color: var(--color-border); text-underline-offset: 3px; }
	.try-link:hover { text-decoration-color: currentColor; }
	.try-link.is-title { font-style: italic; }
	.cmp-note { margin: 8px 0 0; font-size: 14px; color: var(--color-fg-light); }

	.cmp-chart { margin: 22px 0 0; padding-top: 16px; border-top: 3px solid var(--color-fg); }
	.cmp-toolbar { display: flex; align-items: center; gap: 16px; margin: 0 0 6px; }
	.smooth-toggle { display: inline-flex; align-items: center; gap: 6px; font-size: 14px; color: var(--color-fg-light); cursor: pointer; user-select: none; }
	.smooth-toggle input { appearance: auto; -webkit-appearance: auto; width: 17px; height: 17px; margin: 0; accent-color: var(--color-fg); background: none; flex: none; cursor: pointer; }
	.cmp-empty { margin: 40px 0; text-align: center; color: var(--color-fg-light); }

	/* As on the trends page: on wide screens the line labels hang out into the
	   empty right margin, so the plot runs the full width of the column. */
	@media (min-width: 1080px) {
		.chart-panel { margin-right: calc(-1 * max(0px, min(var(--hang, 0px), (100vw - 960px) / 2 - 24px))); }
	}
	.cmp-legend { display: flex; flex-wrap: wrap; justify-content: center; gap: 4px 18px; margin: 10px 0 2px; font-size: var(--text-sm); font-weight: 600; color: var(--color-fg); }
	.cl-item { display: inline-flex; align-items: center; gap: 6px; padding: 2px 4px; border: 0; border-radius: 6px; background: none; font: inherit; color: inherit; cursor: pointer; }
	.cl-item:hover { background: var(--color-gray-100); }
	.cl-sw { width: 10px; height: 10px; border-radius: 2px; flex: none; }

	.chart-foot { display: flex; justify-content: space-between; align-items: center; gap: 8px 16px; flex-wrap: wrap; margin: 16px 0 0; }
	.chart-source { margin: 0; flex: 1 1 260px; font-size: 12.5px; color: var(--color-fg-light); }
	.chart-source a { color: inherit; }
	.tb-btn { display: inline-flex; align-items: center; gap: 5px; padding: 5px 10px; border: 0; border-radius: 6px; background: #f1f2f3; font: inherit; font-size: 12.5px; font-weight: 500; color: #555; cursor: pointer; }
	.tb-btn:hover { background: #e4e6e8; color: var(--color-fg); }
	.tb-btn :global(svg) { width: 13px; height: 13px; flex: none; }
	/* margin-left: auto keeps the buttons at the right even when they wrap under
	   the source, so their right-anchored menus stay on screen. */
	.foot-actions { display: flex; gap: 8px; align-items: center; flex: none; margin-left: auto; }
	.dl-wrap { position: relative; }
	.dl-backdrop { position: fixed; inset: 0; z-index: 20; background: none; border: 0; cursor: default; }
	.dl-menu { position: absolute; right: 0; top: calc(100% + 6px); z-index: 21; min-width: 196px; padding: 4px; background: #fff; border: 1px solid var(--color-border); border-radius: 8px; box-shadow: 0 6px 20px rgba(0, 0, 0, 0.1); }
	.dl-menu button { display: flex; align-items: center; gap: 10px; width: 100%; padding: 8px 10px; border: 0; border-radius: 6px; background: none; font: inherit; font-size: var(--text-sm); font-weight: 500; color: var(--color-fg); text-align: left; cursor: pointer; }
	.dl-menu button:hover { background: var(--color-gray-100); }
	.dl-menu :global(svg) { flex: none; width: 15px; height: 15px; color: var(--color-fg-light); }
	.share-msg { font-size: var(--text-sm); font-weight: 600; color: #2e7d32; }
	.dl-fmt { margin-left: auto; font-size: 12px; color: var(--color-fg-light); }

	.cmp-table { width: 100%; margin: 28px 0 8px; border-collapse: collapse; font-size: 15px; }
	.cmp-table th { padding: 0 8px 6px; font-size: 12.5px; font-weight: 500; color: var(--color-fg-light); text-align: left; border-bottom: 1px solid var(--color-border); }
	.cmp-table td { padding: 9px 8px; border-bottom: 1px solid var(--color-border); vertical-align: baseline; }
	.cmp-table td:first-child .chip-sw { margin-right: 8px; }
	.cmp-table .num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
	.muted { color: var(--color-fg-light); font-size: 13px; }
	.row-link { padding: 0; border: 0; background: none; font: inherit; font-weight: 600; color: var(--color-fg); cursor: pointer; text-decoration: underline; text-decoration-color: var(--color-border); text-underline-offset: 3px; }
	.row-link.is-work { font-weight: 500; }
	.row-link:hover { text-decoration-color: currentColor; }
	.cmp-table .chip-by { margin-left: 6px; white-space: nowrap; }
	@media (max-width: 600px) {
		.cmp-table .muted { display: block; }
		.cmp-legend { display: none; } /* the chips up top and the line-end names do it */
	}
</style>
