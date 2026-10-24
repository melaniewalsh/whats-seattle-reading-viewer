<script>
	// When the data was last updated, and the days until the next monthly
	// update. The monthly pull (.github/workflows/update.yml) and rebuild
	// (build-data-to-r2.yml) run on the 7th at 06:00 and 12:00 UTC; new data is
	// usually live by about 14:00 UTC that day.
	import { onMount } from "svelte";
	import { getMonths, getDataRefreshed } from "$components/db.js";

	let { compact = false } = $props();

	const UPDATE_DAY = 7, UPDATE_HOUR_UTC = 14;
	const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

	let through = $state("");    // "August 2026"
	let refreshed = $state(null); // Date
	let now = $state(Date.now());

	onMount(() => {
		getMonths().then((m) => {
			const last = m?.[m.length - 1];
			if (last) through = `${MONTHS[Number(last.slice(5, 7)) - 1]} ${last.slice(0, 4)}`;
		}).catch(() => {});
		getDataRefreshed().then((d) => (refreshed = d));
		const id = setInterval(() => (now = Date.now()), 60000);
		return () => clearInterval(id);
	});

	// The next scheduled update: the 7th of this month or next, 14:00 UTC.
	const next = $derived.by(() => {
		const d = new Date(now);
		let t = Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), UPDATE_DAY, UPDATE_HOUR_UTC);
		if (t <= now) t = Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, UPDATE_DAY, UPDATE_HOUR_UTC);
		return t;
	});
	// Whole days to go (rounded up, so the day before shows "1 day").
	const daysLeft = $derived(Math.max(0, Math.ceil((next - now) / 86400000)));
	const fmtDate = (d) => d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
	const nextLabel = $derived(new Date(next).toLocaleDateString(undefined, { month: "long", day: "numeric" }));
</script>

{#if compact}
	<span class="ds-compact">
		{#if through}Data through {through}{/if}{#if refreshed}{" · "}refreshed {fmtDate(refreshed)}{/if}<br />
		Updated monthly · next scheduled update {nextLabel}
	</span>
{:else}
	<section class="ds" aria-label="Data updates">
		<div class="ds-now">
			<span class="ds-k">Data through</span>
			<span class="ds-v">{through || "…"}</span>
			{#if refreshed}<span class="ds-sub">Refreshed {fmtDate(refreshed)}</span>{/if}
		</div>
		<div class="ds-next">
			<span class="ds-k">Next scheduled update</span>
			<span class="ds-clock">{#if daysLeft >= 1}<span><b>{daysLeft}</b> {daysLeft === 1 ? "day" : "days"}</span>{:else}<span><b>Today</b></span>{/if}</span>
			<span class="ds-sub">{nextLabel}. The site updates monthly, after the library publishes the previous month's checkouts (sometimes later than planned).</span>
		</div>
	</section>
{/if}

<style>
	.ds { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.6fr); gap: 16px 28px; max-width: 880px; margin: 22px auto 0; padding: 16px 22px; border: 1px solid var(--color-border); border-radius: 10px; font-family: var(--font-sans); }
	.ds-now, .ds-next { display: flex; flex-direction: column; gap: 2px; }
	.ds-k { font-size: 11px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: var(--color-fg-light); }
	.ds-v { font-family: var(--font-display, var(--font-serif)); font-size: 1.5rem; font-weight: 700; color: var(--color-fg); }
	.ds-sub { font-size: var(--text-sm); line-height: 1.45; color: var(--color-fg-light); }
	.ds-clock { display: flex; gap: 14px; flex-wrap: wrap; font-size: var(--text-sm); color: var(--color-fg-light); }
	.ds-clock b { font-family: var(--font-display, var(--font-serif)); font-size: 1.5rem; font-weight: 700; color: var(--color-fg); font-variant-numeric: tabular-nums; margin-right: 3px; }
	.ds-compact { font-size: var(--text-sm); line-height: 1.55; }
	@media (max-width: 640px) {
		.ds { grid-template-columns: 1fr; }
	}
</style>
