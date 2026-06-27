<script>
	import { getContext } from "svelte";
	import Viewer from "$components/Viewer.svelte";

	const copy = getContext("copy");
</script>

<svelte:boundary onerror={(e) => console.error(e)}>
	<article>
		<header class="headline">
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
	.headline h1 {
		font-family: var(--font-serif);
		font-size: clamp(2.2rem, 6vw, 3.4rem);
		line-height: 1.05;
		letter-spacing: -0.01em;
		margin: 0 0 16px;
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
