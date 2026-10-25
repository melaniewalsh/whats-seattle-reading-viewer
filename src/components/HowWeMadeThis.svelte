<script>
	// "How We Made This": the data pipeline and the tools behind the site.
	let { onMethod = () => {} } = $props();

	const ext = { target: "_blank", rel: "noopener noreferrer" };
</script>

<section class="hw-page">
	<h2 class="hw-title">How We Made This</h2>
	<p class="hw-intro">What’s Seattle Reading? is built entirely from open data and open-source tools. Here is how the library’s monthly checkout counts become the charts and lists on this site. For what the data can and can’t tell you, see <a href="#data-methodology" onclick={(e) => { e.preventDefault(); onMethod(); }}>Data &amp; Methodology</a>.</p>

	<h3 class="hw-h">1. The data</h3>
	<p>The Seattle Public Library publishes how many times each item in its collection was checked out each month, from April 2005 to the present (this site starts with January 2006, the first full year), as the <a href="https://data.seattle.gov/Community-and-Culture/Checkouts-by-Title/tmmm-ytt6" {...ext}>Checkouts by Title</a> dataset on the City of Seattle’s Open Data Portal. Each row is one title in one format in one month: its title, creator, publisher, publication year, subject headings and number of checkouts. The data is aggregated and contains nothing about individual patrons.</p>
	<p>On the 7th of every month, a scheduled job (an R script run by GitHub Actions) downloads the newest month from the portal’s API and saves it to a <a href="https://www.cloudflare.com/developer-platform/products/r2/" {...ext}>Cloudflare R2</a> storage bucket.</p>

	<h3 class="hw-h">2. Cleaning and counting</h3>
	<p>A Python build then reads every month, more than 50 million rows, with <a href="https://duckdb.org/" {...ext}>DuckDB</a>, an analytics database fast enough to recompute the whole history from scratch each month. The build:</p>
	<ul>
		<li>keeps print books, ebooks and audiobooks, and drops music, films and other materials;</li>
		<li>merges the many spellings of each author’s name (“Butler, Octavia E.”, “Octavia E. Butler”) into one person, keeping apart people who share a name;</li>
		<li>groups the separate catalog records for a book’s editions, formats and reissues into one work, by normalizing and matching titles (automatic and approximate: see Data &amp; Methodology);</li>
		<li>sorts books into dozens of genres using the Library of Congress and BISAC subject headings in the catalog records;</li>
		<li>applies the site’s privacy rules: books with fewer than 5 checkouts in their busiest month are shown by year, and books with fewer than 25 checkouts aren’t listed one by one;</li>
		<li>writes one small JSON file per author, plus the rankings, genre trends and Backlist Boomerangs lists, and uploads them to R2.</li>
	</ul>

	<h3 class="hw-h">3. Covers, dates and descriptions</h3>
	<p>Book covers come from <a href="https://openlibrary.org/developers/api" {...ext}>Open Library</a>, with Apple Books filling gaps, and are copied to R2 so the pages load quickly. Original publication years and the short author and book descriptions come from <a href="https://www.wikipedia.org/" {...ext}>Wikipedia</a> and <a href="https://www.wikidata.org/" {...ext}>Wikidata</a>. All of these are matched automatically by title and author, so a few will be wrong.</p>

	<h3 class="hw-h">4. The website</h3>
	<p>The site is built with <a href="https://svelte.dev/" {...ext}>Svelte</a> and <a href="https://svelte.dev/docs/kit" {...ext}>SvelteKit</a>, starting from <a href="https://github.com/the-pudding/svelte-starter" {...ext}>The Pudding’s Svelte starter</a>. The charts are drawn with <a href="https://d3js.org/" {...ext}>D3</a>, and the icons are from <a href="https://lucide.dev/" {...ext}>Lucide</a>. It is a static site hosted on GitHub Pages: there is no server, and your browser fetches each author’s file straight from R2. The essays and case studies are written in <a href="https://quarto.org/" {...ext}>Quarto</a>.</p>

	<h3 class="hw-h">5. Open source</h3>
	<p>All of the code, from the monthly download to the charts, is on <a href="https://github.com/melaniewalsh/whats-seattle-reading-viewer" {...ext}>GitHub</a>. The approach is described in more detail in our JCDL 2026 paper (see Publications).</p>
</section>

<style>
	.hw-page { max-width: 760px; margin: 0 auto; padding: var(--space-6, 32px) 0 var(--space-8, 48px); font-family: var(--font-sans); color: var(--color-fg); }
	.hw-title { font-family: var(--font-display, var(--font-serif)); font-size: clamp(1.8rem, 3.6vw, 2.6rem); font-weight: 700; line-height: 1.05; margin: 0 0 var(--space-3, 16px); }
	.hw-intro { font-size: var(--text-base); line-height: 1.6; margin: 0 0 var(--space-4, 20px); }
	.hw-h { font-family: var(--font-display, var(--font-serif)); font-size: 1.35rem; margin: var(--space-6, 32px) 0 var(--space-2, 8px); padding-top: var(--space-3, 16px); border-top: 1px solid var(--color-border); }
	.hw-page p, .hw-page li { font-size: 1rem; line-height: 1.65; }
	.hw-page p { margin: 0 0 var(--space-3, 14px); }
	.hw-page ul { margin: 0 0 var(--space-3, 14px); padding-left: 1.2em; }
	.hw-page li { margin-bottom: 6px; }
	.hw-page a { color: #3f88cc; }
</style>
