# What Is Seattle Reading? — a checkout-trends viewer

Search any author and explore their Seattle Public Library checkout trends over time, then drill into individual titles and bundle editions together. Built with [SvelteKit](https://kit.svelte.dev/) on [The Pudding's svelte-starter](https://github.com/the-pudding/svelte-starter), with a Python + [DuckDB](https://duckdb.org/) data pipeline.

**Live site:** https://melaniewalsh.github.io/whats-seattle-reading-viewer/ *(updates automatically on every push to `main`)*

------------------------------------------------------------------------

## Contents

-   [Quick start](#quick-start)
-   [How it's deployed](#how-its-deployed)
-   [Project structure](#project-structure)
-   [How the data pipeline works](#how-the-data-pipeline-works)
-   [HDSSI projects](#hdssi) ← **HDSSI**
-   [What the viewer can do](#what-the-viewer-can-do)
-   [Learning resources](#learning-resources)

------------------------------------------------------------------------

## Quick start {#quick-start}

You need **Node 22+**, **Python 3**, and a couple of packages.

``` bash
# 1. clone
git clone https://github.com/melaniewalsh/whats-seattle-reading-viewer.git
cd whats-seattle-reading-viewer

# 2. install front-end deps (the Pudding starter requires Node 22)
nvm install 22 && nvm use 22      # if you use nvm
npm install

# 3. install the data-prep dependency
pip install duckdb

# 4. get the sample data (the raw CSV is NOT in the repo — it's big)
curl -L -o data/raw/Checkouts_by_Title_2018-2022_15-checkouts.csv \
  https://raw.githubusercontent.com/melaniewalsh/Neat-Datasets/main/Checkouts_by_Title_2018-2022_15-checkouts.csv

# 5. build the data files the site reads
python3 data-prep/build_data.py

# 6. run the dev server
npm run dev        # then open the URL it prints
```

> The generated data (`static/data/`) is already committed, so steps 4–5 are only needed if you want to **change** the data. Steps 1–3 + 6 are enough just to run it.

------------------------------------------------------------------------

## How it's deployed {#how-its-deployed}

The website is hosted for free on **GitHub Pages**. But the data is one big (~730 MB) SQLite database — way too big to put on GitHub — so the database itself lives on **Cloudflare R2**, and the website reads just the little pieces it needs from it as you click around. (A library called sql.js-httpvfs makes this work: it grabs only the few kilobytes a query actually touches instead of downloading the whole file.)

Two things happen automatically:

1.  **Once a month**, `.github/workflows/build-data-to-r2.yml` grabs the newest checkout data, rebuilds the whole database with `data-prep/build_data.py`, and uploads it to R2. (It runs a few hours after the monthly data pull so it always has fresh data.) You can also run it by hand anytime from the **Actions** tab → **Run workflow**.
2.  **Every time you push code**, `.github/workflows/deploy.yml` rebuilds and redeploys the website to GitHub Pages. This is fast — a minute or two — because it never touches the big database; it just points at the copy already sitting on R2.

So: push code and the site updates fast, and the data refreshes on its own once a month.

### Setting up R2 (you only do this once)

The database lives in a **public** R2 bucket so the browser is allowed to read it. In the Cloudflare dashboard → **R2**:

1.  **Make a bucket** named `spl-checkouts-public` (keep it separate from the raw-data bucket so the giant CSVs stay private).
2.  **Turn on public access:** the bucket → **Settings** → **Public Access** → allow the **r2.dev** subdomain. Cloudflare gives you a public URL like `https://pub-xxxx.r2.dev`.
3.  **Add this CORS rule** (same Settings page) so the browser can read the file from our site:

```json
[
  {
    "AllowedOrigins": ["https://melaniewalsh.github.io"],
    "AllowedMethods": ["GET", "HEAD"],
    "AllowedHeaders": ["range"],
    "ExposeHeaders": ["content-range", "content-length", "accept-ranges", "etag"]
  }
]
```

4.  **Paste your public URL** into `src/components/db.js` (look for `REPLACE-WITH-YOUR-PUBLIC-R2-URL`). It should end in `/library.sqlite3`.

Two more one-time things:

-   The build workflow needs to *write* to that bucket, so make sure the R2 keys in the repo's GitHub secrets (`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`) have access to it.
-   In the repo's **Settings → Pages**, set **Source = GitHub Actions**.

------------------------------------------------------------------------

## Project structure {#project-structure}

```         
whats-seattle-reading-viewer/
├── data-prep/
│   ├── build_data.py        DuckDB: turns the raw CSV into small JSON files
│   └── cluster_authors.py   STARTER TASK: merge duplicate author spellings
├── data/raw/                the raw SPL CSV (not committed — see Quick start)
├── static/data/             generated JSON the site reads (committed)
│   ├── meta.json              the shared month axis
│   ├── authors.json           the search index: [{slug, name, total}]
│   └── authors/<slug>.json    one file per author (sparse series + titles)
├── src/
│   ├── routes/+page.svelte  the page
│   └── components/
│       ├── Index.svelte     headline + the interactive
│       ├── Viewer.svelte    search, author panel, titles, bundling  ← start here
│       ├── LineChart.svelte the hand-rolled d3 line chart
│       └── Header.svelte    the wordmark
├── .github/workflows/deploy.yml   builds + deploys to GitHub Pages
└── svelte.config.js
```

------------------------------------------------------------------------

## How the data pipeline works {#how-the-data-pipeline-works}

The raw checkout data has tens of millions of rows. The website never loads all of that. Instead `data-prep/build_data.py` crunches it down ahead of time:

1.  **DuckDB does the heavy number-crunching as SQL** — fast even at tens of millions of rows.
2.  Everything gets packed into one **SQLite database** (`library.sqlite3`): a table of authors and a table of titles, each with a **sparse** monthly series — `[[monthIndex, count], ...]`, storing only the months a title was actually borrowed. The website fills the zeros back in as it draws each chart.
3.  Because it's a real database with indexes, the browser can pull up one author (or search names) by reading just a few kilobytes over the network — no matter how big the file gets. That's what lets a ~730 MB database work on a plain static site.

Two places to plug in for `build_data.py`:

-   `RAW_CSV` — which CSV to read.
-   `MIN_TITLE_CHECKOUTS` — drop titles below N total checkouts from an author's list (default 10). The author's total and trend line still count everything.

------------------------------------------------------------------------

## HDSSI {#hdssi}

Here are some things we can work on for HDSSI.

### 1. Add the full dataset of SPL checkouts / figure out way to auto update every month

Right now the repo uses a **sample** (2018–2022, popular titles only). We should try to add the full data, or a slightly condensed version of full data (like only titles with 5 checkouts, etc.).

**What to do:**

1.  Download the full CSV and drop it in `data/raw/`.
2.  In `data-prep/build_data.py`, change `RAW_CSV` to point at your file.
3.  Consider raising `MIN_TITLE_CHECKOUTS` — the full data has a huge long tail of titles borrowed only once or twice.
4.  Run `python3 data-prep/build_data.py` and see how big `static/data/` gets.

**Heads-up on size:** the full dataset's JSON may be hundreds of MB — too big to commit and serve from GitHub Pages. The fix is to host the generated JSON elsewhere with no egress fees (e.g. **Cloudflare R2**) and point the data fetches in `Viewer.svelte` at that URL instead of the local `static/data/`.

-   This is something maybe Neel can try to figure out, and we can discuss. We could also host in an s3 bucket.

### 2. Merge duplicate authors (entity resolution)

The raw data spells names inconsistently, so the same person appears multiple times. Search "Octavia Butler" on the live site and you'll see **three** of her:

| name               | checkouts |
|--------------------|-----------|
| Octavia E. Butler  | 10,630    |
| Butler, Octavia E. | 1,637     |
| Octavia Butler     | 303       |

**What to do:** open `data-prep/cluster_authors.py`. We want to produce `data-prep/author_map.json`, a mapping from each raw name to one canonical name. The data-prep script already knows how to use this — see the **`CLUSTERING HOOK`** comment in `build_data.py`. The file has a working baseline and `TODO`s pointing at the key missing piece (flipping `"Lastname, First"` → `"First Lastname"`).

``` bash
python3 data-prep/cluster_authors.py   # writes data-prep/author_map.json
python3 data-prep/build_data.py        # rebuilds the site data, now merged
```

Verified example: with a map merging the three Butlers, her total becomes **12,570** (10,630 + 1,637 + 303).

------------------------------------------------------------------------

## What the viewer can do {#what-the-viewer-can-do}

-   **Search** an author and chart their total checkouts per month.
-   **Tick titles** (with a filter box) to chart each as its own line; each title shows a format **badge** (ebook / audio / print).
-   **Bundle** ticked titles into one line — treat every edition/format/reprint as a single "work." The bundle is auto-named after its top title, and you can **rename it**.
-   **Show author total** on/off — to compare just the titles or the bundle alone.
-   Hover the chart for a **tooltip** with the month and per-line checkout counts.

------------------------------------------------------------------------

## Learning resources {#learning-resources}

New to Svelte or DuckDB? [**LEARNING.md**](LEARNING.md) has a curated, ordered list of tutorials and docs for both — flagged where they match this project's stack (Svelte 5 runes, DuckDB's Python API), plus SQL basics and a table mapping each technology to the files that use it.

------------------------------------------------------------------------

Visual style adapted from The Pudding's svelte-starter.