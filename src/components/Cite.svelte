<script>
	// "Cite the Project": how to cite the website, the paper about it, and the
	// library's data, in a few styles, each with a Copy button.
	import { onMount } from "svelte";
	import { publications } from "$data/publications.js";
	import { getMonths } from "$components/db.js";

	const SITE = "https://www.whats-seattle-reading.com";
	const YEAR = 2026;
	const paper = publications.find((p) => /Interactive Viewer and Open Data Pipeline/.test(p.title));

	// Today's date, for "Accessed …" lines.
	const now = new Date();
	const accessedMla = now.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }).replace(/(\w{3})\w*/, "$1.").replace("May.", "May");
	const accessedLong = now.toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" });
	let dataThrough = $state("");
	onMount(() => {
		getMonths().then((m) => {
			const last = m?.[m.length - 1];
			if (last) dataThrough = new Date(Date.UTC(+last.slice(0, 4), +last.slice(5, 7) - 1, 15)).toLocaleDateString("en-US", { month: "long", year: "numeric", timeZone: "UTC" });
		}).catch(() => {});
	});

	// Each entry: [label, html (for display), plain text (for copying)].
	const site = [
		["APA", `Walsh, M., Gupta, N., Ramos, E. T., Martin, A., Harris, K., &amp; Bao, L. (${YEAR}). <em>What’s Seattle Reading?</em> [Interactive website]. University of Washington Information School. ${SITE}`],
		["MLA", `Walsh, Melanie, et al. <em>What’s Seattle Reading?</em> University of Washington Information School, ${YEAR}, www.whats-seattle-reading.com. Accessed ${accessedMla}.`],
		["Chicago", `Walsh, Melanie, Neel Gupta, E. Tiago Ramos, Alexis Martin, Karalee Harris, and Lurier Bao. <em>What’s Seattle Reading?</em> University of Washington Information School, ${YEAR}. ${SITE}.`],
		["BibTeX", `@misc{walshWhatsSeattleReading,
  title = {What's {{Seattle Reading}}?},
  author = {Walsh, Melanie and Gupta, Neel and Ramos, E. Tiago and Martin, Alexis and Harris, Karalee and Bao, Lurier},
  year = {${YEAR}},
  howpublished = {University of Washington Information School},
  url = {${SITE}},
  note = {Accessed ${accessedLong}}
}`]
	];
	const data = [
		["APA", `Seattle Public Library. (${YEAR}). <em>Checkouts by Title</em> [Data set]. City of Seattle Open Data Portal. https://data.seattle.gov/d/tmmm-ytt6`],
		["MLA", `Seattle Public Library. <em>Checkouts by Title</em>. City of Seattle Open Data Portal, data.seattle.gov/d/tmmm-ytt6. Accessed ${accessedMla}.`],
		["Chicago", `Seattle Public Library. “Checkouts by Title.” City of Seattle Open Data Portal. Accessed ${accessedLong}. https://data.seattle.gov/d/tmmm-ytt6.`]
	];
	const plain = (html) => html.replace(/<[^>]+>/g, "").replace(/&amp;/g, "&");

	let copied = $state("");
	let copiedTimer;
	async function copy(key, html) {
		try {
			await navigator.clipboard.writeText(plain(html));
			copied = key;
			clearTimeout(copiedTimer);
			copiedTimer = setTimeout(() => (copied = ""), 2000);
		} catch {}
	}
</script>

<section class="cite-page">
	<h2 class="cite-title">Cite the Project</h2>
	<p class="cite-intro">If you use this website in your research, teaching or reporting, please cite it. If you write about a particular chart or ranking, include its link: every page's address keeps what it shows (the author, the year, the genre), so readers can open the same view. The numbers change a little each month as new data arrives, so say when you looked{#if dataThrough}{" "}(the site currently has data through {dataThrough}){/if}.</p>

	<h3 class="cite-h">The website</h3>
	{#each site as [label, html]}
		<div class="cite-row">
			<span class="cite-label">{label}</span>
			{#if label === "BibTeX"}<pre class="cite-text cite-bib">{html}</pre>{:else}<p class="cite-text">{@html html}</p>{/if}
			<button type="button" class="cite-copy" onclick={() => copy(`site-${label}`, html)}>{copied === `site-${label}` ? "Copied!" : "Copy"}</button>
		</div>
	{/each}

	{#if paper}
		<h3 class="cite-h">The paper about the project</h3>
		<p class="cite-note">For the data pipeline, how editions are grouped into works, and how the site was built, cite our paper.</p>
		<div class="cite-row">
			<span class="cite-label">Paper</span>
			<p class="cite-text">{paper.citation.split(". ")[0]}. “{paper.title.replace(/\.$/, "")}.” {paper.citation.split(". ").slice(1).join(". ")} <a href={paper.doi} target="_blank" rel="noopener noreferrer">{paper.doi}</a></p>
			<button type="button" class="cite-copy" onclick={() => copy("paper", `${paper.citation.split(". ")[0]}. “${paper.title.replace(/\.$/, "")}.” ${paper.citation.split(". ").slice(1).join(". ")} ${paper.doi}`)}>{copied === "paper" ? "Copied!" : "Copy"}</button>
		</div>
		<div class="cite-row">
			<span class="cite-label">BibTeX</span>
			<pre class="cite-text cite-bib">{paper.bibtex}</pre>
			<button type="button" class="cite-copy" onclick={() => copy("paper-bib", paper.bibtex)}>{copied === "paper-bib" ? "Copied!" : "Copy"}</button>
		</div>
	{/if}

	<h3 class="cite-h">The library's data</h3>
	<p class="cite-note">The checkout counts come from the Seattle Public Library's open data. If you analyze the data itself, cite it too.</p>
	{#each data as [label, html]}
		<div class="cite-row">
			<span class="cite-label">{label}</span>
			<p class="cite-text">{@html html}</p>
			<button type="button" class="cite-copy" onclick={() => copy(`data-${label}`, html)}>{copied === `data-${label}` ? "Copied!" : "Copy"}</button>
		</div>
	{/each}

	<p class="cite-note cite-license">The site's text, charts and derived data are shared under a <a href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noopener license">Creative Commons Attribution 4.0</a> license: you can reuse them with credit.</p>
</section>

<style>
	.cite-page { max-width: 760px; margin: 0 auto; padding: var(--space-6, 32px) 0 var(--space-8, 48px); font-family: var(--font-sans); }
	.cite-title { font-family: var(--font-display, var(--font-serif)); font-size: clamp(1.8rem, 3.6vw, 2.6rem); font-weight: 700; line-height: 1.05; margin: 0 0 var(--space-3, 16px); color: var(--color-fg); }
	.cite-intro { font-size: var(--text-base); line-height: 1.6; color: var(--color-fg); margin: 0 0 var(--space-5, 28px); }
	.cite-h { font-family: var(--font-display, var(--font-serif)); font-size: 1.35rem; margin: var(--space-6, 32px) 0 var(--space-2, 8px); padding-top: var(--space-3, 16px); border-top: 1px solid var(--color-border); color: var(--color-fg); }
	.cite-note { font-size: var(--text-sm); line-height: 1.55; color: var(--color-fg-light); margin: 0 0 var(--space-3, 12px); }
	.cite-license { margin-top: var(--space-6, 32px); }
	.cite-row { display: grid; grid-template-columns: 72px minmax(0, 1fr) auto; gap: 12px; align-items: start; padding: 12px 0; border-bottom: 1px solid var(--color-border); }
	.cite-label { font-size: 11px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: var(--color-fg-light); padding-top: 3px; }
	.cite-text { margin: 0; font-size: 0.95rem; line-height: 1.55; color: var(--color-fg); overflow-wrap: anywhere; }
	.cite-text a, .cite-note a { color: #3f88cc; }
	.cite-bib { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; line-height: 1.5; white-space: pre-wrap; background: #fafaf7; border: 1px solid var(--color-border); border-radius: 6px; padding: 10px 12px; }
	.cite-copy { padding: 5px 12px; border: 1px solid var(--color-border); border-radius: 6px; background: #fff; font-family: var(--font-sans); font-size: var(--text-sm); font-weight: 600; color: var(--color-fg); cursor: pointer; white-space: nowrap; }
	.cite-copy:hover { border-color: var(--color-fg-light); }
	@media (max-width: 600px) {
		.cite-row { grid-template-columns: minmax(0, 1fr) auto; }
		.cite-label { grid-column: 1 / -1; }
	}
</style>
