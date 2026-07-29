<script>
	import { base } from "$app/paths";
	import { lookupUrls } from "$utils/lookup.js";

	// A small blue "Borrow" button that opens a dropdown of places to get the book:
	// the Seattle Public Library catalog, WorldCat (find it at your OWN local library),
	// and Bookshop.org (buy, supporting local bookstores). `q` is the search string
	// (e.g. "The Odyssey Homer"); `compact` shrinks it for dense table rows.
	let { q = "", compact = false } = $props();
	let open = $state(false);
	const links = $derived(lookupUrls(q));
	function close() { open = false; }
</script>

<span class="borrow-wrap">
	<button
			class="borrow-btn"
			class:compact
			onclick={() => (open = !open)}
			aria-haspopup="true"
			aria-expanded={open}
			title="Where to borrow or buy this book"
	>
		Borrow <span class="borrow-caret" aria-hidden="true">▾</span>
	</button>
	{#if open}
		<button class="borrow-backdrop" aria-label="Close" onclick={close}></button>
		<div class="borrow-menu" role="menu">
			<a role="menuitem" href={links.spl} target="_blank" rel="noopener noreferrer" onclick={close}>
				<img class="bm-ic" src="{base}/spl-logo.png" alt="" width="18" height="18" />
				<span class="bm-text"><span class="bm-name">Seattle Public Library</span><span class="bm-sub">Borrow · the SPL catalog</span></span>
			</a>
			<a role="menuitem" href={links.worldcat} target="_blank" rel="noopener noreferrer" onclick={close}>
				<span class="bm-ic bm-emoji" aria-hidden="true">🌍</span>
				<span class="bm-text"><span class="bm-name">Your local library</span><span class="bm-sub">Borrow · find it on WorldCat</span></span>
			</a>
			<a role="menuitem" href={links.bookshop} target="_blank" rel="noopener noreferrer" onclick={close}>
				<span class="bm-ic bm-emoji" aria-hidden="true">🛍️</span>
				<span class="bm-text"><span class="bm-name">Bookshop.org</span><span class="bm-sub">Buy · supports local bookstores</span></span>
			</a>
		</div>
	{/if}
</span>

<style>
	.borrow-wrap {
		position: relative;
		display: inline-flex;
	}
	.borrow-btn {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		font-family: var(--font-sans);
		font-size: 0.82rem;
		font-weight: 600;
		padding: 5px 11px;
		border: none;
		border-radius: 999px;
		background: #3f88cc;
		color: #fff;
		cursor: pointer;
		white-space: nowrap;
		transition: background 0.12s;
	}
	.borrow-btn:hover {
		background: #2f6ea8;
	}
	.borrow-btn.compact {
		font-size: 0.78rem;
		padding: 3px 9px;
	}
	.borrow-caret {
		font-size: 0.7em;
		opacity: 0.85;
		margin-left: -1px;
	}
	.borrow-backdrop {
		position: fixed;
		inset: 0;
		z-index: 40;
		background: none;
		border: none;
		cursor: default;
	}
	.borrow-menu {
		position: absolute;
		top: calc(100% + 6px);
		left: 0;
		z-index: 41;
		display: flex;
		flex-direction: column;
		min-width: 232px;
		/* Never wider than the viewport (with a small gutter) so it can't run off
		   the edge on a phone. */
		max-width: calc(100vw - 24px);
		padding: 5px;
		background: var(--color-white);
		border: 1px solid var(--color-border);
		border-radius: 10px;
		box-shadow: 0 8px 24px rgba(0, 0, 0, 0.16);
	}
	.borrow-menu a {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 8px 10px;
		border-radius: 7px;
		text-decoration: none;
		color: var(--color-fg);
	}
	.borrow-menu a:hover {
		background: var(--color-gray-100);
	}
	.bm-ic {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 22px;
		height: 22px;
		flex: none;
		object-fit: contain;
	}
	.bm-emoji {
		font-size: 1.05rem;
		line-height: 1;
	}
	.bm-text {
		display: flex;
		flex-direction: column;
		line-height: 1.25;
	}
	.bm-name {
		font-family: var(--font-sans);
		font-size: 0.86rem;
		font-weight: 600;
	}
	.bm-sub {
		font-size: 0.72rem;
		color: var(--color-fg-light);
	}
</style>
