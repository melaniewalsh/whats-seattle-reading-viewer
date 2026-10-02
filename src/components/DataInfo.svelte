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

	const inline = $derived(`Seattle Public Library, Checkouts by Title (${y0}–${y1}) – processed by What Is Seattle Reading?`);
	const full = $derived(
		`Seattle Public Library. “Checkouts by Title” [dataset], ${y0}–${y1}. City of Seattle Open Data Portal, ${DATASET}. ` +
		`Processed by Melanie Walsh and Neel Gupta, What Is Seattle Reading? University of Washington, ${y1}. ${siteUrl}`,
	);

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

<button type="button" class="di-link" onclick={open}>Learn more about this data</button>

<dialog class="di" bind:this={dialog} onclick={onBackdrop} aria-labelledby="di-title">
	<div class="di-body">
		<button type="button" class="di-close" onclick={close} aria-label="Close"><XIcon size={18} strokeWidth={2} /></button>

		<h2 id="di-title" class="di-title">Library checkouts <span class="di-tag">Seattle Public Library</span></h2>
		<p class="di-lede">
			{#if genres}
				Each genre's share of all book checkouts at the Seattle Public Library, by month, with genres drawn from catalog subject headings.
			{:else}
				How many times an author's or book's titles were checked out each month at the Seattle Public Library: print books, ebooks and audiobooks.
			{/if}
		</p>

		<dl class="di-facts">
			<div class="di-wide"><dt>Source</dt><dd>Seattle Public Library, <a href={DATASET} target="_blank" rel="noopener noreferrer">Checkouts by Title</a>, processed by What Is Seattle Reading?</dd></div>
			<div><dt>Data through</dt><dd>{monthYear(last)}</dd></div>
			<div><dt>Updated</dt><dd>Monthly, as the library publishes each month's data</dd></div>
			<div><dt>Date range</dt><dd>{monthYear(first)} – {monthYear(last)}</dd></div>
			<div><dt>Unit</dt><dd>{genres ? "share of book checkouts (%)" : "checkouts per month"}</dd></div>
		</dl>

		<h3 class="di-h">About the source</h3>
		<p>
			The Seattle Public Library publishes how many times each title in its collection was checked out
			in each month, for physical items and for digital ebooks and audiobooks, on the City of Seattle's
			open data portal. Each record names the title, its creator, its format and its catalog subject
			headings.
		</p>

		<div class="di-notes">
			<h3 class="di-kicker">Notes on how we process it</h3>
			<ul>
				<li>We keep print books (including large print and comics), ebooks and audiobooks. Music, movies and other formats are left out, as are audiobooks on CD, which the catalog files with music CDs. Records with no named author are left out too.</li>
				<li>These are checkouts, not unique readers, holds or renewals. A popular book can be borrowed thousands of times.</li>
				<li>Authors' many catalog spellings are clustered into one author, and a book's editions (print, ebook, audiobook, reissues) are grouped automatically by title. Both are approximate; you can regroup editions yourself.</li>
				{#if genres}
					<li>Genres come from Library of Congress and BISAC subject headings. A book can count toward several genres, so the shares overlap, and the headings themselves are applied unevenly.</li>
				{/if}
				<li>The shaded bands mark the Covid closures and the 2024 ransomware outage, when checkouts weren't recorded normally.</li>
			</ul>
		</div>

		<h3 class="di-h">How to cite this data</h3>
		<p class="di-sub">In-line citation, for charts and other tight spaces:</p>
		<div class="di-cite">
			<code>{inline}</code>
			<button type="button" class="di-copy" onclick={() => copy("inline", inline)} aria-label="Copy the in-line citation">{#if copied === "inline"}<CheckIcon size={16} strokeWidth={2} />{:else}<CopyIcon size={16} strokeWidth={2} />{/if}</button>
		</div>
		<p class="di-sub">Full citation:</p>
		<div class="di-cite">
			<code>{full}</code>
			<button type="button" class="di-copy" onclick={() => copy("full", full)} aria-label="Copy the full citation">{#if copied === "full"}<CheckIcon size={16} strokeWidth={2} />{:else}<CopyIcon size={16} strokeWidth={2} />{/if}</button>
		</div>
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
	.di-facts a, .di-more a { color: inherit; text-decoration: underline; text-underline-offset: 2px; }
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
