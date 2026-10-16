<script>
	// BacklistBoomerangs.svelte
	// ========================
	// Books that had a quiet, settled readership at SPL and then, years later,
	// suddenly took off -- an adaptation, a BookTok wave, an author's death, a
	// news event. The list is precomputed by data-prep/build_backlist.py (see
	// its docstring for the rule) and served as backlist.json; this view is a
	// year picker over it.
	import { onMount, untrack } from "svelte";
	import { getBacklist } from "$components/db.js";
	import { displayName } from "$utils/displayName.js";
	import { titleCase } from "$utils/titleCase.js";
	import { compactNumber } from "$utils/format.js";
	import { coverUrl, coverOverride } from "$utils/covers.js";

	let { openAuthor = () => {}, openTitle = () => {} } = $props();

	let data = $state.raw(null);
	let year = $state(null);
	let loading = $state(true);

	onMount(async () => {
		data = await getBacklist();
		if (data?.years?.length) {
			let want = null;
			try { want = Number(new URLSearchParams(window.location.search).get("year")); } catch {}
			year = data.years.includes(want) ? want : data.years[data.years.length - 1];
		}
		loading = false;
	});

	// The top 30 boomerangs for the year (biggest jump first).
	const PER_YEAR = 30;
	const allRows = $derived(data && year ? data.data[String(year)] || [] : []);
	const rows = $derived(allRows.slice(0, PER_YEAR));

	// Covers: a hand-picked override if there is one, else the cover baked into
	// backlist.json at build time (r.c). Only works the build couldn't match fall
	// back to a live Open Library lookup, two at a time -- firing them all at once
	// got most of them throttled, which left the lower rows without covers.
	let covers = $state({});
	const coverKey = (r) => `${r.t}|${r.s}`;
	let queue = [];
	let active = 0;
	function pump() {
		while (active < 2 && queue.length) {
			const r = queue.shift();
			const k = coverKey(r);
			active++;
			coverUrl(r.t, displayName(r.a))
				.then((u) => { covers[k] = u || null; })
				.catch(() => {})
				.finally(() => { active--; pump(); });
		}
	}
	// Re-run only when the rows change (a new year), not on every cover that
	// arrives -- that used to reset the queue and drop the pending lookups.
	$effect(() => {
		const list = rows;
		untrack(() => {
			queue = [];
			for (const r of list) {
				const k = coverKey(r);
				if (k in covers) continue;
				const ov = coverOverride(r.t) || r.c;
				covers[k] = ov || null;
				if (!ov) queue.push(r);
			}
			pump();
		});
	});
	const yearIdx = $derived(data ? data.years.indexOf(year) : -1);
	const rules = $derived(data?.rules || {});

	function setYear(y) {
		year = Number(y);
		try {
			const url = new URL(window.location.href);
			url.searchParams.set("year", String(year));
			window.history.replaceState({}, "", url);
		} catch {}
	}
	function stepYear(d) {
		const i = yearIdx + d;
		if (data && i >= 0 && i < data.years.length) setYear(data.years[i]);
	}

	// Titles below the title index's threshold aren't findable by ?title, so
	// send those clicks to the author page instead.
	function open(r) {
		if (r.total >= 500) openTitle(r.t, r.s);
		else openAuthor(r.s);
	}

	const fmtRate = (n) => (n < 10 ? Number(n).toFixed(1) : Math.round(n).toLocaleString());
	const fmtRatio = (x) => (x >= 100 ? `${Math.round(x)}×` : `${Number(x).toFixed(x >= 10 ? 0 : 1)}×`);

	// Small bar chart of the work's yearly totals, boom year highlighted.
	const SPARK_W = 180, SPARK_H = 46;
	function spark(r) {
		const yrs = r.yr || [];
		const max = Math.max(1, ...yrs.map((d) => d[1]));
		const bw = SPARK_W / Math.max(yrs.length, 1);
		return yrs.map((d, i) => ({
			x: i * bw + 0.5,
			w: Math.max(1, bw - 1),
			h: Math.max(d[1] > 0 ? 1.5 : 0, (d[1] / max) * SPARK_H),
			boom: d[0] === r.year,
			year: d[0],
			v: d[1]
		}));
	}
</script>

<header class="rank-masthead">
	<h2 class="rank-title">Backlist Boomerangs</h2>
	<p class="rank-sub">Books that became popular again or for the first time, typically years after their debut.</p>
</header>

{#if loading}
	<p class="bb-loading">Loading…</p>
{:else if !data}
	<p class="bb-loading">The backlist data isn't available right now.</p>
{:else}
	<div class="ta-controls">
		<label class="ta-field">
			<span>Year</span>
			<select value={String(year)} onchange={(e) => setYear(e.currentTarget.value)}>
				{#each [...data.years].reverse() as y}
					<option value={String(y)}>{y}</option>
				{/each}
			</select>
		</label>
	</div>

	<div class="gal-yearnav">
		<button class="gal-arrow" onclick={() => stepYear(-1)} disabled={yearIdx <= 0} aria-label="Earlier year">‹</button>
		<span class="gal-yearlabel">{year}</span>
		<button class="gal-arrow" onclick={() => stepYear(1)} disabled={!data || yearIdx >= data.years.length - 1} aria-label="Later year">›</button>
	</div>

	<p class="ta-caption">
		{#if allRows.length > rows.length}The top <strong>{rows.length}</strong> books{:else}<strong>{rows.length}</strong> {rows.length === 1 ? "book" : "books"}{/if} whose checkouts in {year} jumped to at least
		<strong>{rules.minRatio}×</strong> their average over the previous two years. Ranked by the size of the jump.
		{#if String(year) === String(data.through).slice(0, 4)}<span class="ta-hint">({year} so far, through {data.through}.)</span>{/if}
	</p>

	<ol class="bb-list">
		{#each rows as r, i (r.s + r.t)}
			<li class="bb-row">
				<span class="bb-rank">{i + 1}</span>
				<button class="bb-cover" class:has-img={!!covers[coverKey(r)]} onclick={() => open(r)} aria-label="See the trend for {titleCase(r.t)}">
					{#if covers[coverKey(r)]}
						<img src={covers[coverKey(r)]} alt="" loading="lazy" decoding="async" width="54" height="81" />
					{/if}
				</button>
				<div class="bb-main">
					<button class="bb-title" onclick={() => open(r)}>{titleCase(r.t)}</button>
					<span class="bb-by">by <button class="bb-author" onclick={() => openAuthor(r.s)}>{displayName(r.a)}</button></span>
					<p class="bb-stats">
						Average checkouts per month in {r.year} were <strong>{fmtRate(r.peak)}</strong>—<span class="bb-ratio">{fmtRatio(r.ratio)}</span> more than the two years before.
						First borrowed in {r.first} · {compactNumber(r.total)} all-time
					</p>
				</div>
				<svg class="bb-spark" viewBox="0 0 {SPARK_W} {SPARK_H}" width={SPARK_W} height={SPARK_H} role="img" aria-label="Checkouts per year, {r.yr[0]?.[0]}–{r.yr[r.yr.length - 1]?.[0]}">
					{#each spark(r) as b}
						<rect x={b.x} y={SPARK_H - b.h} width={b.w} height={b.h} class:boom={b.boom}>
							<title>{b.year}: {b.v.toLocaleString()} checkouts</title>
						</rect>
					{/each}
				</svg>
			</li>
		{/each}
	</ol>

	<details class="bb-method">
		<summary>How this list is made</summary>
		<p>For every book (all editions and formats combined), we compare each calendar year — starting at least {rules.minAgeYears} years after its first checkout — with the average of the {rules.baselineMonths} months before it. The months of the 2020 branch closures and the 2024 ransomware outage are skipped when computing that baseline. A book is listed under the year of its biggest jump if that year's monthly average is at least {rules.minRatio}× the baseline, at least {rules.minDelta} checkouts a month higher, and the year had at least {rules.minPeakTotal} checkouts in total.</p>
	</details>
{/if}

<style>
	/* Masthead, controls and year stepper mirror the Most Borrowed page. */
	.rank-masthead {
		border-bottom: 3px solid var(--color-fg);
		padding-bottom: var(--space-3);
		margin: var(--space-6) 0 var(--space-5);
	}
	.rank-title {
		font-family: var(--font-display, var(--font-serif));
		font-size: clamp(1.7rem, 3.4vw, 2.5rem);
		font-weight: 700;
		line-height: 1.05;
		color: var(--color-fg);
		margin: 0;
	}
	.rank-sub {
		font-size: var(--text-base);
		line-height: 1.4;
		color: var(--color-fg-light);
		margin: var(--space-2) 0 0;
	}
	.ta-controls {
		display: flex;
		align-items: flex-end;
		gap: var(--space-3);
		flex-wrap: wrap;
		margin: var(--space-2) 0 var(--space-4);
	}
	.ta-field {
		flex: 0 1 200px;
		min-width: 120px;
		display: flex;
		flex-direction: column;
		gap: 4px;
		font-family: var(--font-sans);
		font-size: 0.78rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--color-fg-light);
	}
	.ta-field select {
		width: 100%;
		font-family: var(--font-sans);
		font-size: var(--text-base);
		font-weight: 600;
		text-transform: none;
		letter-spacing: 0;
		color: var(--color-fg);
		padding: 8px 10px;
		border: 1.5px solid var(--color-border);
		border-radius: 8px;
		background: var(--color-white);
	}
	.gal-yearnav {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 16px;
		margin: 2px 0 22px;
	}
	.gal-arrow {
		width: 34px;
		height: 34px;
		border-radius: 50%;
		border: 1.5px solid var(--color-border);
		background: var(--color-white);
		color: var(--color-fg);
		font-size: 1.1rem;
		line-height: 1;
		cursor: pointer;
		display: flex;
		align-items: center;
		justify-content: center;
	}
	.gal-arrow:hover:not(:disabled) { border-color: var(--color-fg-light); }
	.gal-arrow:disabled { opacity: 0.35; cursor: default; }
	.gal-yearlabel {
		font-family: var(--font-serif);
		font-size: 1.15rem;
		font-weight: 700;
		color: var(--color-fg);
		min-width: 5.5rem;
		text-align: center;
	}
	.ta-caption {
		font-family: var(--font-sans);
		font-size: var(--text-base);
		line-height: 1.5;
		color: var(--color-fg-light);
		margin: 0 0 var(--space-4);
	}
	.ta-caption strong { color: var(--color-fg); }
	.ta-hint { color: var(--color-fg-light); }
	.bb-loading { font-family: var(--font-sans); color: var(--color-fg-light); margin: var(--space-4) 0; }

	.bb-list {
		list-style: none;
		margin: 0;
		padding: 0;
		border-top: 1px solid var(--color-border);
	}
	.bb-row {
		display: grid;
		grid-template-columns: 2rem 54px 1fr 180px;
		gap: 16px;
		align-items: center;
		padding: 12px 0;
		border-bottom: 1px solid var(--color-border);
		font-family: var(--font-sans);
	}
	.bb-rank {
		font-family: var(--font-serif);
		font-size: 1.05rem;
		font-weight: 700;
		color: var(--color-fg-light);
		text-align: right;
	}
	.bb-cover {
		width: 54px;
		aspect-ratio: 2 / 3;
		padding: 0;
		border: none;
		border-radius: 3px;
		overflow: hidden;
		background: var(--color-gray-100, #eef0f3);
		box-shadow: 0 1px 4px rgba(0, 0, 0, 0.18);
		cursor: pointer;
	}
	.bb-cover:hover { box-shadow: 0 3px 10px rgba(0, 0, 0, 0.26); }
	.bb-cover img { display: block; width: 100%; height: 100%; object-fit: cover; }
	.bb-spark { display: block; justify-self: end; }
	.bb-spark rect { fill: #c9d6e6; }
	.bb-spark rect.boom { fill: #e3120b; }
	.bb-main { min-width: 0; }
	.bb-title {
		font-family: var(--font-serif);
		font-size: 1.12rem;
		font-weight: 700;
		color: var(--color-fg);
		background: none;
		border: 0;
		padding: 0;
		cursor: pointer;
		text-align: left;
		line-height: 1.25;
	}
	.bb-title:hover { color: #3f88cc; text-decoration: underline; }
	.bb-by { font-size: var(--text-sm); color: var(--color-fg-light); margin-left: 6px; }
	.bb-author {
		font: inherit;
		color: var(--color-fg);
		background: none;
		border: 0;
		padding: 0;
		cursor: pointer;
	}
	.bb-author:hover { color: #3f88cc; text-decoration: underline; }
	.bb-stats {
		margin: 4px 0 0;
		font-size: var(--text-sm);
		line-height: 1.45;
		color: var(--color-fg-light);
	}
	.bb-stats strong { color: var(--color-fg); }
	.bb-ratio {
		font-weight: 700;
		color: #e3120b;
	}
	.bb-method {
		margin: var(--space-5) 0 var(--space-4);
		font-family: var(--font-sans);
		font-size: var(--text-sm);
		color: var(--color-fg-light);
		line-height: 1.5;
	}
	.bb-method summary { cursor: pointer; font-weight: 700; color: var(--color-fg); }
	.bb-method p { margin: 8px 0 0; }
	@media (max-width: 640px) {
		.bb-row { grid-template-columns: 1.4rem 46px 1fr; gap: 12px; align-items: start; }
		.bb-cover { width: 46px; }
		.bb-spark { grid-column: 2 / -1; justify-self: stretch; width: 100%; height: 34px; }
	}
</style>
