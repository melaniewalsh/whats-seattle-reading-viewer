# What's Seattle Reading?

**An interactive viewer and open data pipeline for two decades of Seattle Public Library circulation.**

🔗 **Website:** <https://www.whats-seattle-reading.com>

The Seattle Public Library openly publishes anonymized checkout counts for each of the titles in its collection. Our project, *What's Seattle Reading?*, makes  this data, **over 120 million checkouts** for **~600K books**, explorable across print, e-book, and audiobook formats, from 2005 to the present.  

This website is built with [SvelteKit](https://kit.svelte.dev/) and [D3](https://d3js.org/), a Python + [DuckDB](https://duckdb.org/) data pipeline, and static data hosted on [Cloudflare R2](https://developers.cloudflare.com/r2/). All code is MIT-licensed.

---

## In This Repo

This repository provides three things:

1. **Interactive viewer** — a static web app for searching any author, work, and some genres and exploring checkout trends over time. 
2. **Clustered circulation data** — the full SPL checkout dataset, clustered by author and work and reduced to compact JSON time series.
3. **Data & clustering pipeline** — a reproducible pipeline with rule-based author- and work-clustering algorithms that transform tens of millions of raw rows into the files above.

---

## Data

You can access the SPL checkout data clustered by author and work. 

**Bulk download:** Download the full corpus from the [**Releases**](https://github.com/melaniewalsh/whats-seattle-reading-viewer/releases) page. A dated snapshot (`data-YYYY-MM`) is published automatically each month.

This data is also publicly hosted on Cloudflare R2. 

```
https://pub-7559692ae8974bd6a6e7cc54db47a348.r2.dev/<file>
```

You can grab data for a specific author by looking up the author's slug in the directory.

1. Download `search-index.json` — an array of `[slug, name, total]` for every author.
2. Look up the author's `slug` there.
3. Fetch `authors/<first-two-characters-of-slug>/<slug>.json`.


Files:

| File | Contents |
|------|----------|
| `search-index.json` | `[[slug, name, total], …]` for every author, most-borrowed first. |
| `authors/<shard>/<slug>.json` | One file per author. It includes total monthly series + per-title breakdown, sparsely encoded as `[monthIndex, count]` pairs, with format and subject tags. `<shard>` is the first two characters of the slug. |


We also made a script to help you search by author in [`examples/fetch_author.py`](examples/fetch_author.py).


The **raw data** comes from the Seattle Public Library's "Checkouts by Title" open dataset, updated monthly: <https://data.seattle.gov/Community-and-Culture/Checkouts-by-Title/tmmm-ytt6>.

---

## Run Locally

Requires **Node 22+** and **Python 3**.

```bash
git clone https://github.com/melaniewalsh/whats-seattle-reading-viewer.git
cd whats-seattle-reading-viewer
npm install
npm run dev        
```

---

## Process


- **Precompute (Python + DuckDB).** `data-prep/build_data.py` aggregates the raw checkouts into one small JSON file per author, plus a search index. **Authors are resolved first**. **Works are clustered second, *within* each resolved author**, by normalizing catalog titles (stripping statements of responsibility, edition/format boilerplate, accents, punctuation) to a deterministic "work key" and grouping matching keys.
- **Explore (SvelteKit).** The viewer loads the search index once, then fetches a single per-author file whenever the user requests it. Every automatic cluster serves as a suggestion the user can edit in the browser.

---

## Citation & License

We release this code under the **MIT License** (see [LICENSE](LICENSE)). The underlying checkout data is published as open data by the Seattle Public Library.

If you use this resource, please cite our paper:

Melanie Walsh, Neel Gupta, E. Tiago Ramos, Alexis Martin, Karalee Harris, and Lurier Bao. “What’s Seattle Reading? An Interactive Viewer and Open Data Pipeline for Two Decades of Public Library Circulation.” ACM/IEEE Joint Conference on Digital Libraries (JCDL 2026), 2026. https://doi.org/10.1145/3805696.3848491

```
@inproceedings{walshWhatsSeattleReading2026,
  title = {What's {{Seattle Reading}}? {{An Interactive Viewer}} and {{Open Data Pipeline}} for {{Two Decades}} of {{Public Library Circulation}}},
  author = {Walsh, Melanie and Gupta, Neel and Ramos, E. Tiago and Martin, Alexis and Harris, Karalee and Bao, Lurier},
  booktitle = {ACM/IEEE Joint Conference on Digital Libraries (JCDL 2026)},
  year = {2026},
  doi = {10.1145/3805696.3848491},
  url = {https://www.whats-seattle-reading.com/}
}
```

---

## Acknowledgments

Thanks to the Seattle Public Library and David Christensen for stewarding the open checkout data.

This template was originally adapted from [The Pudding's svelte-starter](https://github.com/the-pudding/svelte-starter).
