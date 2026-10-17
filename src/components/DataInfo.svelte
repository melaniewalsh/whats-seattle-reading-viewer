<script>
	// DataInfo.svelte
	// "Learn more about this data": a link (placed after a chart's source line)
	// that opens a panel describing the data, how we process it, and how to cite
	// it -- modeled on Our World in Data's source panels.
	//
	// Props:
	//   first, last : "YYYY-MM" months the data covers
	//   genres      : true on the Genres page (adds the subject-heading note)
	import { base } from "$app/paths";
	import CopyIcon from "@lucide/svelte/icons/copy";
	import CheckIcon from "@lucide/svelte/icons/check";
	import XIcon from "@lucide/svelte/icons/x";
	import { publications } from "$data/publications.js";

	let { first = "", last = "", genres = false } = $props();

	const DATASET = "https://data.seattle.gov/Community-and-Culture/Checkouts-by-Title/tmmm-ytt6";
	const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
	const monthYear = (m) => (m ? `${MONTHS[Number(m.slice(5, 7)) - 1]} ${m.slice(0, 4)}` : "");
	const y0 = $derived(first.slice(0, 4));
	const y1 = $derived(last.slice(0, 4));

	let dialog = $state(null);
	let copied = $state("");
	let siteUrl = $state("");
	$effect(() => {
		try { siteUrl = `${window.location.origin}${base}/`; } catch {}
	});

	// The project (this site) and the library's dataset are cited separately.
	// The project's citation is its JCDL 2026 paper.
	const PROJECT_TITLE = "What’s Seattle Reading? An Interactive Viewer and Open Data Pipeline for Two Decades of Public Library Circulation";
	const project = $derived(`Melanie Walsh, Neel Gupta, E. Tiago Ramos, Alexis Martin, Karalee Harris, and Lurier Bao. “${PROJECT_TITLE}.” ACM/IEEE Joint Conference on Digital Libraries (JCDL 2026), 2026. https://doi.org/10.1145/3805696.3848491`);
	const projectBib = $derived(
		`@inproceedings{walshWhatsSeattleReading2026,\n  title = {What's {{Seattle Reading}}? {{An Interactive Viewer}} and {{Open Data Pipeline}} for {{Two Decades}} of {{Public Library Circulation}}},\n  author = {Walsh, Melanie and Gupta, Neel and Ramos, E. Tiago and Martin, Alexis and Harris, Karalee and Bao, Lurier},\n  booktitle = {ACM/IEEE Joint Conference on Digital Libraries (JCDL 2026)},\n  year = {2026},\n  doi = {10.1145/3805696.3848491},\n  url = {${siteUrl}}\n}`,
	);
	// The data paper (Journal of Open Humanities Data), from the Publications list.
	const paper = publications.find((p) => /johd/i.test(p.doi || ""));
	// Its citation is "Authors. Journal 11, no. 1 (2025)." -> split, so the title
	// can go in its usual place: Authors. "Title." Journal ... DOI
	const [paperAuthors, paperVenue] = paper ? [paper.citation.split(/\.\s+/)[0], paper.citation.split(/\.\s+/).slice(1).join(". ").replace(/\.\s*$/, "")] : ["", ""];
	const paperTitle = paper ? paper.title.replace(/[.?]?$/, (m) => m || "") : "";
	const paperCite = paper ? `${paperAuthors}. “${paperTitle.replace(/\.$/, "")}${/[?!]$/.test(paperTitle) ? "" : "."}” ${paperVenue}. ${paper.doi}` : "";
	const full = $derived(`Seattle Public Library. “Checkouts by Title” [dataset], ${y0}–${y1}. City of Seattle Open Data Portal. ${DATASET}`);

	function open() { dialog?.showModal(); }
	function close() { dialog?.close(); }
	async function copy(which, text) {
		try { await navigator.clipboard.writeText(text); } catch {}
		copied = which;
		setTimeout(() => (copied === which && (copied = "")), 1800);
	}
	// A click on the dimmed backdrop (outside the panel) closes it.
	function onBackdrop(e) { if (e.target === dialog) close(); }
</script>

<button type="button" class="di-link" onclick={open}>Learn more about this data</button><dialog class="di" bind:this={dialog} onclick={onBackdrop} aria-labelledby="di-title">
	<div class="di-body">
		<button type="button" class="di-close" onclick={close} aria-label="Close"><XIcon size={18} strokeWidth={2} /></button>

		<h2 id="di-title" class="di-title">Library checkouts <span class="di-tag">Seattle Public Library</span></h2>
		{#if genres}
			<p class="di-lede">
				Each genre's share of all book checkouts at the Seattle Public Library, by month, with genres drawn from catalog subject headings.
			</p>
		{/if}

		<dl class="di-facts">
			<div class="di-wide"><dt>Source</dt><dd>Seattle Public Library, <a href={DATASET} target="_blank" rel="noopener noreferrer">Checkouts by Title</a>, processed by What's Seattle Reading?</dd></div>
			<div><dt>Data through</dt><dd>{monthYear(last)}</dd></div>
			<div><dt>Updated</dt><dd>Monthly, as the library publishes each month's data (sometimes there are delays)</dd></div>
			<div><dt>Date range</dt><dd>{monthYear(first)} – {monthYear(last)}</dd></div>
			<div><dt>Unit</dt><dd>{genres ? "share of book checkouts (%)" : "checkouts per month"}</dd></div>
		</dl>

		<h3 class="di-h">About the source</h3>
		<p>
			The Seattle Public Library publishes how many times each title in its collection was checked out
			in each month, for physical items and for digital ebooks and audiobooks, on the City of Seattle's
			open data portal. Each record names the title, creator, format and subject headings. The data is
			aggregated and not connected to individual patrons.
		</p>
		<p>
			Physical checkouts come from 27 branch locations across the city. Digital checkouts include SPL
			patrons, as well as checkouts from the <a href="https://booksunbanned.com/" target="_blank" rel="noopener noreferrer">Books Unbanned Program</a>, which provides free nationwide ebook
			access for teens and young adults up to age 26. In 2024, Books Unbanned was responsible for 245K
			checkouts, a 5% share of all digital checkouts.
		</p>
		{#if paper}
			<p>
				For a fuller description of the data, see {paperAuthors},
				<a href={paper.doi} target="_blank" rel="noopener noreferrer">“{paperTitle.replace(/\.$/, "")}”</a>,
				<em>{paperVenue}</em>.
			</p>
		{/if}

		<div class="di-notes">
			<h3 class="di-kicker">Notes on Data</h3>
			<ul>
				<li>This website only displays checkouts for print books (including large print and comics), ebooks and audiobooks. We do not consider music, movies and other formats. We also exclude records with no named author.</li>
				<li>The data does not include holds or renewals.</li>
				<li>Authors' various catalog spellings are clustered into one author, and a book's editions are grouped automatically by title.</li>
				{#if genres}
					<li>Genres come from Library of Congress and BISAC subject headings. A book can count toward several genres, so the shares overlap, and the headings themselves are applied unevenly.</li>
				{/if}
				<li>The shaded bands mark the Covid closures and the 2024 ransomware outage, when checkouts weren't recorded normally. See more details below.</li>
			</ul>
		</div>

		<h3 class="di-h">Checkout Disruptions and Other Considerations</h3>
		{#if paper}
			<p class="di-sub">Drawn from {paperAuthors}, <a href={paper.doi} target="_blank" rel="noopener noreferrer">“{paperTitle.replace(/\.$/, "")}”</a>, <em>{paperVenue}</em>.</p>
		{/if}
		<p>
			Checkouts dropped in 2020 during the COVID-19 pandemic. Beginning on March 13, 2020, the SPL halted
			physical checkouts, and progressively reintroduced them over the next year until a full re-opening on
			July 1, 2021 (<a href="https://web.archive.org/web/20241209044138/https://www.spl.org/about-us/library-impact/2020-impact-report/a-look-back" target="_blank" rel="noopener noreferrer">The Seattle Public Library, 2024</a>). Many patrons turned toward ebooks and audiobooks.
		</p>
		<p>
			Recorded checkouts also dropped between May and July of 2024, following a ransomware cyberattack on
			May 25 (<a href="https://www.geekwire.com/2024/seattle-public-library-recovers-from-ransomware-attack-makes-moves-to-strengthen-tech-security/" target="_blank" rel="noopener noreferrer">Schlosser, GeekWire, 2024</a>) that caused a prolonged service outage. As a response, the library shut down
			some of their data tracking systems. While checkouts continued via manual paper process, these
			checkouts do not show up exactly on the date of checkout in the SPL open data. Physical holds were not
			available from May 25 to August 8, and digital book checkouts were also unavailable for most patrons
			for almost three weeks of the ransomware outage.
		</p>
		<p>
			Lastly, the SPL made policy changes around fines, renewals, and digital holds that likely influence
			checkout behavior and trends across this time period. In January 2020, the library stopped fining patrons for
			late returns, leading to a slight lengthening of average checkout time (10 to 12 days for the 25th
			percentile). In July 2022, patrons were allowed to renew checkouts up to three times instead of two.
			Finally, in March 2024, the library reduced the maximum number of digital holds a specific patron can
			have from 25 to 10 (in order to cut costs for high demand volumes) (<a href="https://shelftalkblog.wordpress.com/2024/03/13/the-seattle-public-library-is-reducing-our-maximum-digital-holds-heres-why/" target="_blank" rel="noopener noreferrer">The Seattle Public Library, 2024</a>).
		</p>

		<h3 class="di-h">If you use this project, you can cite the associated paper:</h3>
		<div class="di-cite">
			<code>{project}</code>
			<button type="button" class="di-copy" onclick={() => copy("project", project)} aria-label="Copy the project citation">{#if copied === "project"}<CheckIcon size={16} strokeWidth={2} />{:else}<CopyIcon size={16} strokeWidth={2} />{/if}</button>
		</div>
		<p class="di-sub">BibTeX:</p>
		<div class="di-cite">
			<code>{projectBib}</code>
			<button type="button" class="di-copy" onclick={() => copy("bib", projectBib)} aria-label="Copy the BibTeX">{#if copied === "bib"}<CheckIcon size={16} strokeWidth={2} />{:else}<CopyIcon size={16} strokeWidth={2} />{/if}</button>
		</div>

		<h3 class="di-h">Citation for raw data:</h3>
		<p class="di-sub">Full citation:</p>
		<div class="di-cite">
			<code>{full}</code>
			<button type="button" class="di-copy" onclick={() => copy("full", full)} aria-label="Copy the full citation">{#if copied === "full"}<CheckIcon size={16} strokeWidth={2} />{:else}<CopyIcon size={16} strokeWidth={2} />{/if}</button>
		</div>
		{#if paper}
			<p class="di-sub">Paper describing raw data:</p>
			<div class="di-cite">
				<code>{paperCite}</code>
				<button type="button" class="di-copy" onclick={() => copy("paper", paperCite)} aria-label="Copy the data paper citation">{#if copied === "paper"}<CheckIcon size={16} strokeWidth={2} />{:else}<CopyIcon size={16} strokeWidth={2} />{/if}</button>
			</div>
		{/if}
		<p class="di-more">Our research with this data is listed under <a href="{base}/?tab=publications">Publications</a>.</p>
	</div>
</dialog>

<style>
	.di-link { background: none; border: 0; padding: 0; font: inherit; color: inherit; cursor: pointer; text-decoration: underline; text-decoration-color: #c9c9c9; text-underline-offset: 2px; }
	.di-link:hover { color: var(--color-fg); text-decoration-color: currentColor; }

	/* margin:auto centers the modal (the site's global reset zeroes it). */
	.di { margin: auto; overflow-y: auto; overscroll-behavior: contain; width: min(760px, calc(100vw - 32px)); max-height: calc(100vh - 48px); padding: 0; border: 0; border-radius: 12px; box-shadow: 0 18px 50px rgba(0, 0, 0, 0.25); color: var(--color-fg); background: var(--color-white, #fff); }
	.di::backdrop { background: rgba(20, 20, 20, 0.45); }
	.di-body { position: relative; padding: 34px 40px 30px; font-family: var(--font-sans); font-size: 15px; line-height: 1.55; }
	.di-close { position: absolute; top: 18px; right: 18px; width: 38px; height: 38px; display: inline-flex; align-items: center; justify-content: center; border: 1px solid var(--color-border); border-radius: 50%; background: var(--color-white, #fff); color: var(--color-fg); cursor: pointer; }
	.di-close:hover { border-color: var(--color-fg-light); }
	.di-title { font-family: var(--font-serif); font-weight: 400; font-size: 1.9rem; line-height: 1.15; margin: 0 48px 6px 0; }
	.di-tag { font-size: 1.1rem; color: var(--color-fg-light); margin-left: 6px; }
	.di-lede { margin: 0 0 20px; color: var(--color-fg); }
	.di-facts { display: grid; grid-template-columns: 1fr 1fr; gap: 14px 28px; margin: 0 0 26px; }
	.di-facts .di-wide { grid-column: 1 / -1; }
	.di-facts dt { font-size: 13px; color: var(--color-fg-light); }
	.di-facts dd { margin: 2px 0 0; }
	.di-facts a, .di-more a, .di p a { color: inherit; text-decoration: underline; text-underline-offset: 2px; }
	.di-h { font-family: var(--font-serif); font-weight: 400; font-size: 1.35rem; margin: 26px 0 8px; }
	.di p { margin: 0 0 10px; }
	.di-notes { background: var(--color-gray-100, #f2f2f2); border-radius: 6px; padding: 16px 20px 6px; margin: 20px 0 6px; }
	.di-kicker { font-family: var(--font-sans); font-size: 12px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: var(--color-fg-light); margin: 0 0 8px; }
	.di-notes ul { margin: 0 0 10px; padding-left: 1.1em; }
	.di-notes li { margin: 0 0 6px; }
	.di-sub { font-size: 14px; color: var(--color-fg-light); }
	.di-cite { display: flex; align-items: flex-start; gap: 12px; padding: 12px 14px; margin: 0 0 14px; background: #f7f7f5; border: 1px solid var(--color-border); border-radius: 6px; }
	.di-cite code { flex: 1; font-family: ui-monospace, Menlo, monospace; font-size: 13px; line-height: 1.55; white-space: pre-wrap; word-break: break-word; }
	.di-copy { flex: none; display: inline-flex; padding: 4px; border: 0; background: none; color: var(--color-fg-light); cursor: pointer; border-radius: 4px; }
	.di-copy:hover { color: var(--color-fg); background: var(--color-gray-100); }
	.di-more { font-size: 14px; color: var(--color-fg-light); margin-top: 16px !important; }
	@media (max-width: 560px) {
		.di-body { padding: 26px 20px 22px; }
		.di-facts { grid-template-columns: 1fr; }
		.di-title { font-size: 1.5rem; }
	}
</style>
