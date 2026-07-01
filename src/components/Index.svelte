<script>
	import { getContext } from "svelte";
	import { base } from "$app/paths";
	import Viewer from "$components/Viewer.svelte";

	const copy = getContext("copy");
</script>

<svelte:boundary onerror={(e) => console.error(e)}>
	<article>
		<header class="headline">
			<img class="logo" src="{base}/favicon.png" alt="" width="88" height="88" />
			<h1>{copy.title}</h1>
			<p class="dek">{copy.dek}</p>
		</header>

		<Viewer />

		<p class="note">{copy.note}</p>
	</article>
</svelte:boundary>

<style>
	article {
		max-width: 760px;
		margin: 0 auto;
		padding: 0 20px 80px;
	}
	.headline {
		max-width: 720px;
		margin: 8px auto 32px;
		text-align: center;
	}
	.logo {
		display: block;
		width: 88px;
		height: 88px;
		margin: 0 auto 12px;
	}
	.headline h1 {
		font-family: "Baloo Bhai", var(--font-serif);
		font-weight: 700;
		font-size: clamp(2.6rem, 7vw, 4rem);
		line-height: 1.05;
		letter-spacing: 0.005em;
		margin: 0 0 16px;
		color: #6aa9dd;
		/* soft drop shadow gives the rounded letters a puffy, sticker-like feel */
		text-shadow: 2px 3px 0 rgba(53, 122, 189, 0.18);
	}
	.dek {
		font-family: var(--font-sans);
		font-size: 1.1rem;
		line-height: 1.5;
		color: var(--color-fg-light);
		margin: 0;
	}
	.note {
		max-width: 720px;
		margin: 40px auto 0;
		font-family: var(--font-sans);
		font-size: 0.85rem;
		color: var(--color-fg-light);
		text-align: center;
	}
</style>
