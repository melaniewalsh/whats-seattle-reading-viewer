<script>
	// A subject heading's page: its most-borrowed books, all time (built by
	// data-prep/build_data.py write_subject_pages).
	import { getSubject } from "$components/db.js";
	import { displayName } from "$utils/displayName.js";
	import { titleCase } from "$utils/titleCase.js";
	import { cleanWorkTitle, searchTitle } from "$utils/cleanTitle.js";
	import { compactNumber } from "$utils/format.js";
	import { coverUrl } from "$utils/covers.js";
	import { imgTimeout } from "$utils/imgTimeout.js";
	import ExtArrow from "$components/ExtArrow.svelte";

	let { slug, openTitle, openAuthor, onLoaded = () => {} } = $props();

	let data = $state.raw(null);
	let failed = $state(false);
	let covers = $state.raw({}); // row index -> cover URL | null

	$effect(() => {
		const s = slug;
		let alive = true;
		data = null;
		failed = false;
		covers = {};
		getSubject(s)
			.then((d) => {
				if (!alive) return;
				data = d;
				onLoaded(d.subject);
				// Covers baked in by the build; the rest are looked up a few at a time.
				const baked = {};
				d.rows.forEach((r, i) => { if (r[4]) baked[i] = r[4]; });
				covers = baked;
				const todo = d.rows.map((r, i) => i).filter((i) => !d.rows[i][4]);
				const next = () => {
					const i = todo.shift();
					if (i === undefined || !alive) return;
					const r = d.rows[i];
					coverUrl(searchTitle(r[0]), displayName(r[1])).then((u) => {
						if (alive) covers = { ...covers, [i]: u || null };
						next();
					});
				};
				for (let k = 0; k < 4; k++) next();
			})
			.catch(() => { if (alive) failed = true; });
		return () => { alive = false; };
	});

	const splUrl = (t) => `https://seattle.bibliocommons.com/v2/search?query=${encodeURIComponent(t.replace(/[()]/g, ""))}&searchType=subject`;
</script>

<div class="subject">
	{#if failed}
		<p class="sj-status">This subject doesn't have a page.</p>
	{:else if !data}
		<p class="sj-status">Loading…</p>
	{:else}
		<header class="rank-masthead">
			<h2 class="rank-title">{data.subject}</h2>
			<p class="rank-sub">The most-borrowed books with this subject heading at the Seattle Public Library, all time. <a href={splUrl(data.subject)} target="_blank" rel="noopener noreferrer">Find it in the SPL catalog&nbsp;<ExtArrow /></a></p>
		</header>
		<table class="ta-table">
			<thead>
				<tr><th class="ta-rank">#</th><th class="ta-name">Book</th><th class="ta-count">Checkouts</th></tr>
			</thead>
			<tbody>
				{#each data.rows as r, i (r[0] + "~" + r[2])}
					<tr>
						<td class="ta-rank">{i + 1}</td>
						<td class="ta-name">
							<div class="tw-cell">
								<button class="tw-cover" onclick={() => openTitle(r[0], r[2])} title="See borrowing trend">
									{#if covers[i]}
										<img src={covers[i]} alt="" width="70" height="105" loading="lazy" onerror={() => (covers = { ...covers, [i]: null })} {@attach imgTimeout(() => (covers = { ...covers, [i]: null }))} />
									{:else}
										<span class="tw-cover-ph" aria-hidden="true">📖</span>
									{/if}
								</button>
								<span class="tw-text">
									<button class="tw-title" title="See this book's checkout trend" onclick={() => openTitle(r[0], r[2])}>{titleCase(cleanWorkTitle(r[0]))}</button>
									<span class="tw-by">by {#if r[2]}<button class="tw-authorlink" title="See this author's checkout trend" onclick={() => openAuthor(r[2])}>{displayName(r[1])}</button>{:else}{displayName(r[1])}{/if}</span>
								</span>
							</div>
						</td>
						<td class="ta-count"><span class="ta-num" title={r[3].toLocaleString()}>{compactNumber(r[3])}</span></td>
					</tr>
				{/each}
			</tbody>
		</table>
		{#if data.works > data.rows.length}<p class="sj-note">Showing the top {data.rows.length} of {data.works.toLocaleString()} books with this subject (books with fewer than 25 checkouts aren't counted).</p>{/if}
	{/if}
</div>

<style>
	.subject { width: 100%; font-family: var(--font-sans); }
	.sj-status { margin: 40px 0; color: var(--color-fg-light); }
	.sj-note { margin: 14px 0 0; font-size: var(--text-sm); color: var(--color-fg-light); }
	.rank-masthead { border-bottom: 3px solid var(--color-fg); padding-bottom: var(--space-3); margin: var(--space-6) 0 var(--space-5); }
	.rank-title { font-family: var(--font-display, var(--font-serif)); font-size: clamp(1.7rem, 3.4vw, 2.5rem); font-weight: 700; line-height: 1.05; color: var(--color-fg); margin: 0; }
	.rank-sub { font-size: var(--text-base); line-height: 1.4; color: var(--color-fg-light); margin: var(--space-2) 0 0; }
	.rank-sub a { color: inherit; text-decoration: underline; text-decoration-color: var(--color-border); text-underline-offset: 3px; }
	.ta-table { width: 100%; max-width: 760px; table-layout: fixed; border-collapse: collapse; font-size: 0.95rem; }
	.ta-table th { text-align: left; font-size: 0.72rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: var(--color-fg-light); padding: 6px 10px; border-bottom: 2px solid var(--color-border); }
	.ta-table td { padding: 9px 10px; border-bottom: 1px solid var(--color-border); vertical-align: baseline; }
	.ta-rank { width: 3rem; color: var(--color-fg-light); font-variant-numeric: tabular-nums; white-space: nowrap; }
	td.ta-rank { vertical-align: top; padding-top: 13px; }
	td.ta-count { width: 4.5rem; vertical-align: top; padding-top: 13px; text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
	th.ta-count { text-align: right; width: 7rem; }
	.ta-num { font-size: 0.9rem; font-weight: 700; color: var(--color-fg); }
	.tw-cell { display: flex; align-items: flex-start; gap: 12px; }
	.tw-cover { flex: none; width: 52px; height: 78px; border: none; padding: 0; cursor: pointer; border-radius: 4px; overflow: hidden; display: flex; align-items: center; justify-content: center; background: var(--color-gray-100); box-shadow: 0 1px 3px rgba(0, 0, 0, 0.16); }
	.tw-cover img { width: 100%; height: 100%; object-fit: cover; display: block; }
	.tw-cover-ph { font-size: 24px; opacity: 0.4; }
	@media (min-width: 600px) {
		.tw-cell { gap: 16px; }
		.tw-cover { width: 70px; height: 105px; }
		.tw-cover-ph { font-size: 32px; }
	}
	.tw-text { min-width: 0; flex: 1; display: flex; flex-direction: column; align-items: flex-start; }
	.tw-title { display: block; font: inherit; font-weight: 700; color: var(--color-fg); background: none; border: none; padding: 0; text-align: left; cursor: pointer; text-decoration: underline; text-decoration-color: var(--color-border); text-decoration-thickness: 1.5px; text-underline-offset: 3px; }
	.tw-title:hover { text-decoration-color: var(--color-fg-light); }
	.tw-by { display: inline-block; margin-top: 1px; font-size: 0.82rem; font-weight: 500; color: var(--color-fg-light); }
	.tw-authorlink { font: inherit; color: inherit; background: none; border: 0; padding: 0; cursor: pointer; text-decoration: underline; text-decoration-color: var(--color-border); text-underline-offset: 3px; }
	.tw-authorlink:hover { text-decoration-color: currentColor; }
</style>
