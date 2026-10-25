<script>
	// "How to read this data": a short scrolling story. Each step's text scrolls
	// past a sticky graphic (a chart or a picture) that changes with the step.
	// The words live in src/data/guide.js.
	import { onMount } from "svelte";
	import { base } from "$app/paths";
	import LineChart from "$components/StackedAreaChart.svelte";
	import { EVENT_ANNOTATIONS } from "$data/eventAnnotations.js";
	import { GUIDE_TITLE, GUIDE_DEK, GUIDE_STEPS } from "$data/guide.js";
	import { getMonths, getAllCheckouts, getAuthor, densify } from "$components/db.js";

	let { onNavigate = () => {} } = $props();

	let months = $state.raw([]);
	let charts = $state.raw({}); // chart name -> { series, percent?, unit? }
	let active = $state(0);
	let stepEls = [];

	onMount(() => {
		(async () => {
			const m = await getMonths();
			months = m;
			const out = {};
			try {
				const all = await getAllCheckouts();
				out.total = { series: [{ key: "total", label: "All checkouts", color: "#3f88cc", values: all.total, isAggregate: true }] };
				out.formats = { series: [
					{ key: "print", label: "Print", color: "#3f88cc", values: all.print },
					{ key: "ebook", label: "Ebook", color: "#e58a00", values: all.ebook },
					{ key: "audiobook", label: "Audiobook", color: "#1f7a4d", values: all.audiobook }
				] };
			} catch {}
			try {
				const [butler, leguin] = await Promise.all([getAuthor("octavia-e-butler"), getAuthor("ursula-k-le-guin-1929")]);
				if (butler) out.author = { series: [{ key: "butler", label: "Octavia E. Butler", color: "#3f88cc", values: densify(butler.series, m.length), isAggregate: true }] };
				if (butler && leguin) out.compare = { series: [
					{ key: "butler", label: "Octavia E. Butler", color: "#3f88cc", values: densify(butler.series, m.length) },
					{ key: "leguin", label: "Ursula K. Le Guin", color: "#e58a00", values: densify(leguin.series, m.length) }
				] };
			} catch {}
			try {
				const g = await fetch(`${base}/genres.json`).then((r) => r.json());
				const romance = g.genres.find((x) => x.name === "Romance");
				const idx = new Map(g.months.map((mm, i) => [mm, i]));
				const share = m.map((mm) => { const i = idx.get(mm); return i == null || !g.total[i] ? 0 : (100 * romance.overlap[i]) / g.total[i]; });
				out.romance = { percent: true, unit: "of book checkouts", series: [{ key: "romance", label: "Romance", color: "#e3120b", values: share, isAggregate: true }] };
			} catch {}
			charts = out;
		})();

		// The step nearest the middle of the screen is the active one.
		const io = new IntersectionObserver(
			(entries) => {
				for (const e of entries) if (e.isIntersecting) active = Number(e.target.dataset.i);
			},
			{ rootMargin: "-45% 0px -45% 0px" }
		);
		stepEls.forEach((el) => el && io.observe(el));
		return () => io.disconnect();
	});

	const step = $derived(GUIDE_STEPS[active]);
	const chart = $derived(step?.chart ? charts[step.chart] : null);
</script>

<div class="guide">
	<header class="g-head">
		<h2 class="g-title">{GUIDE_TITLE}</h2>
		<p class="g-dek">{GUIDE_DEK}</p>
	</header>

	<div class="g-scrolly">
		<div class="g-graphic" aria-hidden="true">
			<div class="g-graphic-inner">
				{#if step?.chart}
					{#if chart && months.length}
						{#key step.chart}
							<div class="g-chart">
								<LineChart {months} series={chart.series} mode="line" smooth percent={!!chart.percent} unit={chart.unit} annotations={EVENT_ANNOTATIONS} />
							</div>
						{/key}
					{:else}
						<p class="g-loading">Loading…</p>
					{/if}
				{:else if step?.image}
					{#key step.image}<img class="g-img" src="{base}/{step.image}" alt="" width="800" height="500" />{/key}
				{:else}
					<div class="g-notecard">
						<p>Checkouts ≠ reading</p>
						<p>Editions are grouped automatically</p>
						<p>Subject headings have a history</p>
						<p>Small counts are protected</p>
					</div>
				{/if}
			</div>
		</div>

		<div class="g-steps">
			{#each GUIDE_STEPS as s, i}
				<section class="g-step" class:on={i === active} data-i={i} bind:this={stepEls[i]}>
					<div class="g-card">
						<span class="g-num">{i + 1}</span>
						<h3>{s.title}</h3>
						<p>{s.text}</p>
						{#if s.link}<button type="button" class="g-link" onclick={() => onNavigate(s.link)}>{s.link.label} →</button>{/if}
					</div>
				</section>
			{/each}
			<section class="g-step g-end">
				<div class="g-card">
					<h3>Now explore</h3>
					<p>Look up any author or book, or browse the lists.</p>
					<button type="button" class="g-link" onclick={() => onNavigate({ tab: "search" })}>Search authors and books →</button>
				</div>
			</section>
		</div>
	</div>
</div>

<style>
	.guide { font-family: var(--font-sans); }
	.g-head { border-bottom: 3px solid var(--color-fg); padding-bottom: var(--space-3); margin: var(--space-6) 0 var(--space-5); }
	.g-title { font-family: var(--font-display, var(--font-serif)); font-size: clamp(1.8rem, 3.6vw, 2.6rem); font-weight: 700; line-height: 1.05; margin: 0; color: var(--color-fg); }
	.g-dek { margin: var(--space-2) 0 0; font-size: var(--text-base); color: var(--color-fg-light); }

	/* Desktop: steps on the left, the graphic stays put on the right. */
	.g-scrolly { display: grid; grid-template-columns: minmax(0, 5fr) minmax(0, 7fr); gap: 40px; }
	.g-steps { grid-column: 1; grid-row: 1; padding-bottom: 30vh; }
	.g-graphic { grid-column: 2; grid-row: 1; }
	.g-graphic-inner { position: sticky; top: 90px; min-height: 420px; display: flex; align-items: center; }
	.g-chart { width: 100%; }
	.g-img { width: 100%; height: auto; border: 1px solid var(--color-border); border-radius: 8px; box-shadow: 0 6px 24px rgba(0, 0, 0, 0.08); }
	.g-loading { color: var(--color-fg-light); }
	.g-notecard { width: 100%; padding: 28px 30px; border: 1px solid var(--color-border); border-radius: 10px; background: #fafaf7; }
	.g-notecard p { margin: 0; padding: 12px 0; border-bottom: 1px solid var(--color-border); font-family: var(--font-display, var(--font-serif)); font-size: 1.35rem; font-weight: 600; color: var(--color-fg); }
	.g-notecard p:last-child { border-bottom: 0; }

	.g-step { min-height: 70vh; display: flex; flex-direction: column; justify-content: center; opacity: 0.35; transition: opacity 0.25s; }
	.g-card { display: flex; flex-direction: column; align-items: flex-start; }
	.g-step.on, .g-end { opacity: 1; }
	.g-step:first-child { min-height: 50vh; justify-content: flex-start; padding-top: 10px; }
	.g-num { display: inline-flex; align-items: center; justify-content: center; width: 28px; height: 28px; border-radius: 50%; background: var(--color-fg); color: #fff; font-size: 13px; font-weight: 700; margin-bottom: 10px; }
	.g-step h3 { font-family: var(--font-display, var(--font-serif)); font-size: 1.5rem; line-height: 1.15; margin: 0 0 10px; color: var(--color-fg); }
	.g-step p { font-size: 1.02rem; line-height: 1.6; margin: 0 0 14px; color: var(--color-fg); }
	.g-link { align-self: flex-start; padding: 8px 14px; border: 1px solid var(--color-border); border-radius: 8px; background: #fff; font: inherit; font-size: var(--text-sm); font-weight: 600; color: var(--color-fg); cursor: pointer; }
	.g-link:hover { border-color: var(--color-fg-light); }
	.g-end { min-height: 40vh; }

	/* Phones: the graphic sticks to the top, the steps scroll up over it as cards. */
	@media (max-width: 760px) {
		.g-scrolly { display: block; }
		.g-graphic { position: sticky; top: 56px; z-index: 1; background: var(--color-bg, #fff); padding: 8px 0; }
		.g-graphic-inner { position: static; min-height: 0; }
		.g-steps { position: relative; z-index: 2; }
		.g-step { min-height: 85vh; justify-content: flex-end; padding-bottom: 20vh; opacity: 1; }
		.g-card { padding: 16px 16px 14px; border: 1px solid var(--color-border); border-radius: 10px; background: #fff; box-shadow: 0 4px 16px rgba(0, 0, 0, 0.08); }
		.g-step:first-child { min-height: 85vh; justify-content: flex-end; }
		.g-notecard p { font-size: 1.05rem; padding: 8px 0; }
	}
</style>
