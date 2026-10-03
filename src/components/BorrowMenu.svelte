<script>
	import { base } from "$app/paths";
	import { lookupUrls } from "$utils/lookup.js";
	import BookOpen from "@lucide/svelte/icons/book-open";
	import ChevronDown from "@lucide/svelte/icons/chevron-down";
	import Globe from "@lucide/svelte/icons/globe";
	import ShoppingBag from "@lucide/svelte/icons/shopping-bag";

	// A small blue "Borrow" button that opens a dropdown of places to get the book:
	// the Seattle Public Library catalog, WorldCat (find it at your OWN local library),
	// and Bookshop.org (buy, supporting local bookstores). `q` is the search string
	// (e.g. "The Odyssey Homer"); `compact` shrinks it for dense table rows.
	// variant "outline": the quieter header button ("Borrow at SPL", book icon)
	// variant "link": a plain text link with the SPL logo, for page headers
	// used on the author / book pages; the default blue pill stays elsewhere.
	let { q = "", compact = false, variant = "pill" } = $props();
	let open = $state(false);
	let btnEl;
	// The menu is position:fixed and placed under the button. On its own that
	// escapes an overflow clip in most browsers, but iOS Safari still clips
	// position:fixed descendants of a `-webkit-overflow-scrolling: touch` scroller
	// (the mobile gallery swipe strip). So we also portal the popup out to <body>,
	// removing it from that scroll container entirely — then nothing can clip it.
	let menuPos = $state({ top: 0, left: 0 });
	function portal(node) {
		document.body.appendChild(node);
		return { destroy() { node.remove(); } };
	}
	const links = $derived(lookupUrls(q));
	function toggle() {
		if (open) { open = false; return; }
		if (btnEl) {
			const r = btnEl.getBoundingClientRect();
			const W = 236;
			menuPos = {
				top: Math.round(r.bottom + 6),
				left: Math.round(Math.max(8, Math.min(r.left, window.innerWidth - W - 8)))
			};
		}
		open = true;
	}
	function close() { open = false; }
</script>

<span class="borrow-wrap">
	<button
			bind:this={btnEl}
			class="borrow-btn"
			class:compact
			class:outline={variant === "outline"}
			class:link={variant === "link"}
			onclick={toggle}
			aria-haspopup="true"
			aria-expanded={open}
			title="Where to borrow or buy this book"
	>
		{#if variant === "link"}
			<img class="bl-logo" src="{base}/spl-logo.png" alt="" width="18" height="18" /> <span class="bl-text">Borrow at SPL</span> <ChevronDown size={13} strokeWidth={2} aria-hidden="true" />
		{:else if variant === "outline"}
			<BookOpen size={15} strokeWidth={2} aria-hidden="true" /> Borrow at SPL <ChevronDown size={14} strokeWidth={2} aria-hidden="true" />
		{:else}
			Borrow <span class="borrow-caret" aria-hidden="true">▾</span>
		{/if}
	</button>
	{#if open}
		<div class="borrow-portal" use:portal>
			<button class="borrow-backdrop" aria-label="Close" onclick={close}></button>
			<div class="borrow-menu" role="menu" style="top:{menuPos.top}px; left:{menuPos.left}px;">
				<a role="menuitem" href={links.spl} target="_blank" rel="noopener noreferrer" onclick={close}>
					<img class="bm-ic" src="{base}/spl-logo.png" alt="" width="18" height="18" />
					<span class="bm-text"><span class="bm-name">Seattle Public Library</span><span class="bm-sub">Borrow · the SPL catalog</span></span>
				</a>
				<a role="menuitem" href={links.worldcat} target="_blank" rel="noopener noreferrer" onclick={close}>
					<span class="bm-ic bm-lucide" aria-hidden="true"><Globe size={17} strokeWidth={1.8} /></span>
					<span class="bm-text"><span class="bm-name">Your local library</span><span class="bm-sub">Borrow · find it on WorldCat</span></span>
				</a>
				<a role="menuitem" href={links.bookshop} target="_blank" rel="noopener noreferrer" onclick={close}>
					<span class="bm-ic bm-lucide" aria-hidden="true"><ShoppingBag size={17} strokeWidth={1.8} /></span>
					<span class="bm-text"><span class="bm-name">Bookshop.org</span><span class="bm-sub">Buy · supports local bookstores</span></span>
				</a>
			</div>
		</div>
	{/if}
</span>

<style>
	.borrow-wrap {
		position: relative;
		display: inline-flex;
	}
	/* The single accent control — shares the shared-control box (0.82rem/600,
	   6px 14px padding, 1.5px border, 999px radius) but fills blue. The border is
	   transparent so its height matches the outlined controls beside it. */
	.borrow-btn {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		font-family: var(--font-sans);
		font-size: var(--text-sm);
		font-weight: 600;
		line-height: 1;
		padding: 6px 14px;
		border: 1.5px solid transparent;
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
	.borrow-btn.outline {
		gap: 6px;
		font-weight: 500;
		padding: 7px 11px;
		border: 1px solid var(--color-border);
		border-radius: 8px;
		background: var(--color-white);
		color: var(--color-fg);
	}
	.borrow-btn.outline:hover {
		background: var(--color-white);
		border-color: var(--color-fg-light);
	}
	/* A plain link: logo + words, a light underline that darkens on hover. */
	.borrow-btn.link { gap: 6px; padding: 2px 0; border: 0; border-radius: 0; background: none; font-weight: 500; color: var(--color-fg); }
	.borrow-btn.link .bl-text { text-decoration: underline; text-decoration-color: var(--color-border); text-underline-offset: 3px; }
	.borrow-btn.link:hover { background: none; }
	.borrow-btn.link:hover .bl-text { text-decoration-color: currentColor; }
	.borrow-btn.link .bl-logo { width: 18px; height: 18px; border-radius: 2px; flex: none; }
	.borrow-btn.link :global(svg) { width: 13px; height: 13px; color: var(--color-fg-light); }
	.borrow-btn.compact {
		font-size: var(--text-sm);
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
		z-index: var(--z-modal);
		background: none;
		border: none;
		cursor: default;
	}
	/* position:fixed (coordinates set inline from the button's rect) so the menu
	   escapes any clipping/scrolling ancestor — e.g. the horizontal swipe strip in
	   the mobile gallery, whose overflow would otherwise cut the dropdown off. */
	.borrow-menu {
		position: fixed;
		z-index: calc(var(--z-modal) + 1);
		/* Pin the UI sans — portaled to <body>, the menu would otherwise inherit the
		   page's serif body font. */
		font-family: var(--font-sans);
		display: flex;
		flex-direction: column;
		min-width: 232px;
		/* Never wider than the viewport (with a small gutter) so it can't run off
		   the edge on a phone. */
		max-width: calc(100vw - 24px);
		padding: 4px;
		background: var(--color-white);
		border: 1px solid var(--color-border);
		border-radius: 8px;
		box-shadow: 0 6px 20px rgba(0, 0, 0, 0.1);
	}
	.borrow-menu a {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 8px 10px;
		border-radius: 6px;
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
		font-size: var(--text-lg);
		line-height: 1;
	}
	.bm-text {
		display: flex;
		flex-direction: column;
		line-height: 1.25;
	}
	.bm-name {
		font-family: var(--font-sans);
		font-size: var(--text-sm);
		font-weight: 500;
	}
	.bm-lucide { color: var(--color-fg-light); }
	.bm-lucide :global(svg) { display: block; width: 17px; height: 17px; }
	.bm-sub {
		font-size: var(--text-xs);
		color: var(--color-fg-light);
	}
</style>
