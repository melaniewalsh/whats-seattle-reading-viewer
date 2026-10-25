<script>
	// "How We Made This": the data pipeline and the tools behind the site.
	let { onMethod = () => {} } = $props();

	const ext = { target: "_blank", rel: "noopener noreferrer" };
</script>

<section class="hw-page">
	<h2 class="hw-title">How We Made This</h2>
	<p>The data comes from the <a href="https://data.seattle.gov/Community-and-Culture/Checkouts-by-Title/tmmm-ytt6" {...ext}>Seattle Public Library</a>. We pull new data and cluster it by author and work with Python and <a href="https://duckdb.org/" {...ext}>DuckDB</a>.</p>
	<p>The site is built with <a href="https://svelte.dev/" {...ext}>Svelte</a> and <a href="https://svelte.dev/docs/kit" {...ext}>SvelteKit</a>, starting from <a href="https://github.com/the-pudding/svelte-starter" {...ext}>The Pudding’s Svelte starter</a>. The charts are drawn with <a href="https://d3js.org/" {...ext}>D3</a>, and the icons are from <a href="https://lucide.dev/" {...ext}>Lucide</a>. It is a static site hosted on GitHub Pages: there is no server, and your browser fetches each author’s file straight from <a href="https://www.cloudflare.com/developer-platform/products/r2/" {...ext}>Cloudflare R2</a>. The essays and case studies are written in <a href="https://quarto.org/" {...ext}>Quarto</a>.</p>
	<p>The code is on <a href="https://github.com/melaniewalsh/whats-seattle-reading-viewer" {...ext}>GitHub</a>. For what the data can and can’t tell you, see <a href="#data-methodology" onclick={(e) => { e.preventDefault(); onMethod(); }}>Data &amp; Methodology</a>.</p>
</section>

<style>
	.hw-page { max-width: 760px; margin: 0 auto; padding: var(--space-6, 32px) 0 var(--space-8, 48px); font-family: var(--font-sans); color: var(--color-fg); }
	.hw-title { font-family: var(--font-display, var(--font-serif)); font-size: clamp(1.8rem, 3.6vw, 2.6rem); font-weight: 700; line-height: 1.05; margin: 0 0 var(--space-3, 16px); }
	.hw-page p { font-size: 1.05rem; line-height: 1.65; margin: 0 0 var(--space-3, 14px); }
	.hw-page a { color: #3f88cc; }
</style>
