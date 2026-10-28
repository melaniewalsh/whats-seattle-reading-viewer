<script>
	// When the data was last updated, and the days until the next monthly
	// update. The monthly pull (.github/workflows/update.yml) and rebuild
	// (build-data-to-r2.yml) run on the 7th at 06:00 and 12:00 UTC; new data is
	// usually live by about 14:00 UTC that day.
	import { onMount } from "svelte";
	import { getMonths } from "$components/db.js";

	let { compact = false, inline = false } = $props();

	const UPDATE_DAY = 7, UPDATE_HOUR_UTC = 14;
	const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

	let through = $state("");    // "August 2026"
	let now = $state(Date.now());

	onMount(() => {
		getMonths().then((m) => {
			const last = m?.[m.length - 1];
			if (last) through = `${MONTHS[Number(last.slice(5, 7)) - 1]} ${last.slice(0, 4)}`;
		}).catch(() => {});
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
	// How far through the month between updates we are (for the dial).
	const progress = $derived.by(() => {
		const d = new Date(next);
		const prev = Date.UTC(d.getUTCFullYear(), d.getUTCMonth() - 1, UPDATE_DAY, UPDATE_HOUR_UTC);
		return Math.min(1, Math.max(0, (now - prev) / (next - prev)));
	});
	// Whole days to go (rounded up, so the day before shows "1 day").
	const daysLeft = $derived(Math.max(0, Math.ceil((next - now) / 86400000)));
	const nextLabel = $derived(new Date(next).toLocaleDateString(undefined, { month: "long", day: "numeric" }));
</script>

{#if compact}
	<span class="ds-compact">
		{#if through}Data through {through}{/if}<br />
		Updated monthly · next scheduled update {nextLabel}
	</span>
{:else if inline}
	<!-- A small chip for the home page's dek: a tiny dial and the days to go. -->
	<span class="ds-inline" title="Next scheduled update: {nextLabel}. New data is added monthly, after the library publishes the previous month's checkouts (sometimes later than planned).">
		<svg class="ds-mini" viewBox="0 0 44 44" width="14" height="14" aria-hidden="true">
			<circle cx="22" cy="22" r="17" class="ds-track" />
			<circle cx="22" cy="22" r="17" class="ds-fill" stroke-dasharray="{(progress * 106.8).toFixed(1)} 106.8" transform="rotate(-90 22 22)" />
		</svg>
		Next update in {daysLeft} {daysLeft === 1 ? "day" : "days"}
	</span>
{:else}
	<!-- A small dial: the ring fills as the month runs out; days left in the middle. -->
	<div class="ds" title="New data is added monthly, after the library publishes the previous month's checkouts (sometimes later than planned).">
		<svg class="ds-dial" viewBox="0 0 44 44" width="56" height="56" aria-hidden="true">
			<circle cx="22" cy="22" r="19" class="ds-track" />
			<circle cx="22" cy="22" r="19" class="ds-fill" stroke-dasharray="{(progress * 119.4).toFixed(1)} 119.4" transform="rotate(-90 22 22)" />
			<text x="22" y="22" class="ds-num">{daysLeft}</text>
			<text x="22" y="31" class="ds-unit">{daysLeft === 1 ? "day" : "days"}</text>
		</svg>
		<div class="ds-text">
			<span class="ds-k">Next scheduled update</span>
			<span class="ds-v">{nextLabel}</span>
			{#if through}<span class="ds-sub">Data through {through}</span>{/if}
		</div>
	</div>
{/if}

<style>
	.ds { display: inline-flex; align-items: center; gap: 10px; padding: 8px 14px 8px 8px; border: 1px solid var(--color-border); border-radius: 999px; background: var(--color-white, #fff); font-family: var(--font-sans); box-shadow: 0 2px 10px rgba(0, 0, 0, 0.05); }
	.ds-dial { flex: none; display: block; width: 56px; height: 56px; }
	.ds-track { fill: none; stroke: var(--color-gray-100, #eee); stroke-width: 4; }
	.ds-fill { fill: none; stroke: #3f88cc; stroke-width: 4; stroke-linecap: round; }
	.ds-num { text-anchor: middle; font-family: var(--font-display, var(--font-serif)); font-size: 15px; font-weight: 700; fill: var(--color-fg); }
	.ds-unit { text-anchor: middle; font-size: 6.5px; fill: var(--color-fg-light); }
	.ds-text { display: flex; flex-direction: column; line-height: 1.3; }
	.ds-k { font-size: 10px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: var(--color-fg-light); }
	.ds-v { font-size: var(--text-sm); font-weight: 600; color: var(--color-fg); }
	.ds-sub { font-size: 12px; color: var(--color-fg-light); }
	.ds-inline { display: inline-flex; align-items: center; gap: 5px; margin-left: 4px; padding: 2px 9px 2px 6px; border: 1px solid var(--color-border); border-radius: 999px; background: var(--color-white, #fff); font-family: var(--font-sans); font-size: 12px; font-weight: 600; line-height: 1.5; color: var(--color-fg-light); white-space: nowrap; vertical-align: 0.15em; cursor: help; }
	.ds-mini { flex: none; display: block; width: 14px; height: 14px; }
	.ds-mini .ds-track, .ds-mini .ds-fill { stroke-width: 8; }
	.ds-compact { font-size: var(--text-sm); line-height: 1.55; }
</style>
