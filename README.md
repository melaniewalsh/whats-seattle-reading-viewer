# What's Seattle Reading?

**An interactive viewer and open data pipeline for two decades of Seattle Public Library circulation.**

🔗 **Live site:** <https://melaniewalsh.github.io/whats-seattle-reading-viewer/>

The Seattle Public Library openly publishes anonymized checkout counts by title — **over 120 million checkouts** across print, e-book, and audiobook formats, from 2005 to the present. *What's Seattle Reading?* makes this dataset usable: it clusters the raw records by author and work, reduces them to compact per-author time series, and serves them through a free interactive viewer where anyone can search and explore borrowing trends over time.

Built with [SvelteKit](https://kit.svelte.dev/) and [D3](https://d3js.org/), a Python + [DuckDB](https://duckdb.org/) data pipeline, and static data hosted on [Cloudflare R2](https://developers.cloudflare.com/r2/). All code is MIT-licensed, and the system rebuilds itself automatically each month.

---

## The resource

This repository provides three things:

1. **Interactive viewer** — a static web app for searching any author, work, or genre and exploring checkout trends over time. Users can group editions into a single "work," correct clusters by hand, and download the underlying data.
   → <https://melaniewalsh.github.io/whats-seattle-reading-viewer/>
2. **Clustered circulation data** — the full SPL checkout dataset, clustered by author and work and reduced to compact JSON time series (one file per author), publicly hosted and rebuilt monthly.
3. **Data & clustering pipeline** — a reproducible pipeline with rule-based author- and work-clustering algorithms that transform tens of millions of raw rows into the files above.

---

## Data access

The derived, clustered data is publicly hosted on Cloudflare R2:

```
https://pub-7559692ae8974bd6a6e7cc54db47a348.r2.dev/<file>
```

Key files:

| File | Contents |
|------|----------|
| `meta.json` | The shared month axis (2005–present). |
| `search-index.json` | `[[slug, name, total], …]` for every author, most-borrowed first. |
| `authors/<shard>/<slug>.json` | One file per author: total monthly series + per-title breakdown, sparsely encoded as `[monthIndex, count]` pairs, with format and subject tags. `<shard>` is the first two characters of the slug. |
| `title-index.json`, `overview.json` | Supporting search/landing indexes used by the viewer. |

**Fetching an author's data.** The bucket has no directory listing and slugs are normalized (and may carry a disambiguating year), so you can't guess filenames — get them from the index:

1. Download `search-index.json` — an array of `[slug, name, total]` for every author.
2. Look up the author's `slug` there.
3. Fetch `authors/<first-two-characters-of-slug>/<slug>.json`.

For example, James Baldwin's slug is `james-baldwin-1924`, so his file is
`…r2.dev/authors/ja/james-baldwin-1924.json`. To pull the whole dataset, iterate over the slugs in `search-index.json`.

The **raw source** is the Seattle Public Library's "Checkouts by Title" open dataset, updated monthly: <https://data.seattle.gov/Community-and-Culture/Checkouts-by-Title/tmmm-ytt6>.

---

## Run it locally

Requires **Node 22+** and **Python 3**.

```bash
git clone https://github.com/melaniewalsh/whats-seattle-reading-viewer.git
cd whats-seattle-reading-viewer
npm install
npm run dev        # then open the URL it prints
```

The generated data (`static/data/`) is not committed. For local development, either point `DATA_BASE` in `src/components/db.js` at the R2 URL (`R2_BASE`) to load the full live data, or build it yourself — see [MAINTAINING.md](MAINTAINING.md).

---

## How it works

The SPL dataset (~50 million rows) is too large to ship to a browser, so the work is split in two:

- **Precompute (Python + DuckDB).** `data-prep/build_data.py` aggregates the raw checkouts into one small JSON file per author, plus a search index. **Authors are resolved first** — many raw name spellings (e.g. "Octavia E. Butler," "Butler, Octavia E.," "Octavia Butler") are merged into one canonical author using text-normalization rules and title-overlap evidence. **Works are clustered second, *within* each resolved author**, by normalizing catalog titles (stripping statements of responsibility, edition/format boilerplate, accents, punctuation) to a deterministic "work key" and grouping matching keys.
- **Explore (SvelteKit).** The viewer loads the search index once, then fetches a single per-author file on demand. Every machine-proposed cluster is a *suggestion* the reader can revise in the browser — drag titles between works, split editions out, and more.

Resolving authors before works keeps the problem tractable and eliminates spurious cross-author matches. The whole system rebuilds monthly via scheduled GitHub Actions and deploys for free on GitHub Pages + Cloudflare R2.

For the work-clustering algorithm and its design decisions, see **[docs/title-clustering.md](docs/title-clustering.md)**. For deployment, data-rebuild, and maintenance details, see **[MAINTAINING.md](MAINTAINING.md)**.

---

## Repository structure

```
data-prep/     Python + DuckDB pipeline (aggregation, author & work clustering)
src/           SvelteKit viewer
  components/    Index, StackedViewer, StackedAreaChart, GenreTrends, db.js (data layer)
  routes/        the page
static/        committed data (genres, overview) + generated per-author data (hosted on R2)
.github/       scheduled workflows (pull data → rebuild → deploy)
docs/          algorithm documentation
```

---

## Citation & license

Released under the **MIT License** (see [LICENSE](LICENSE)). The underlying checkout data is published as open data by the Seattle Public Library.

If you use this resource, please cite the project (an accompanying paper is under review — a full citation will be added here once it is published):

> *What's Seattle Reading? An Interactive Viewer and Open Data Pipeline for Two Decades of Public Library Circulation.* <https://github.com/melaniewalsh/whats-seattle-reading-viewer>

---

## Acknowledgments

Thanks to the Seattle Public Library and David Christensen for stewarding the open checkout data.

*Visual style adapted from [The Pudding's svelte-starter](https://github.com/the-pudding/svelte-starter).*
