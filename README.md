# What Is Seattle Reading? — a checkout-trends viewer

Search any author and explore their Seattle Public Library checkout trends over time — see their total borrows as a line, break it down title-by-title as a stacked area, group related editions together, and isolate one line at a time. Built with [SvelteKit](https://kit.svelte.dev/) on [The Pudding's svelte-starter](https://github.com/the-pudding/svelte-starter), with a Python + [DuckDB](https://duckdb.org/) data pipeline and static data hosted on [Cloudflare R2](https://developers.cloudflare.com/r2/).

**Live site:** https://melaniewalsh.github.io/whats-seattle-reading-viewer/ *(updates automatically on every push to `main`)*

------------------------------------------------------------------------

## Contents

-   [The short version](#short-version)
-   [Quick start](#quick-start)
-   [How it's deployed](#how-its-deployed)
-   [Updating the data after a change](#updating-data)
-   [How the data pipeline works](#how-the-data-pipeline-works)
-   [Project structure](#project-structure)
-   [HDSSI projects](#hdssi) ← **HDSSI**
-   [What the viewer can do](#what-the-viewer-can-do)
-   [Learning resources](#learning-resources)

------------------------------------------------------------------------

## The short version {#short-version}

The Seattle Public Library publishes ~50 million checkout rows. We can't ship all of that to a browser, so the work is split in two:

1.  **Ahead of time (Python + DuckDB):** `data-prep/build_data.py` crunches the raw checkouts down into a pile of tiny static files — **one small JSON file per author** — plus a compact search index.
2.  **In the browser (SvelteKit):** the site loads the search index once, then fetches **just one little file** for whichever author you click. Those files live on Cloudflare R2 (cheap, no egress fees) and the site itself is free static hosting on GitHub Pages.

That's the whole trick: precompute small per-author files, host them on a CDN, fetch one at a time.

> **A bit of history:** an earlier version packed everything into one ~500 MB SQLite database and had the browser read slices of it over the network (via `sql.js-httpvfs`). It worked, but a single author took dozens of scattered range requests and was slow enough to hang the tab. One-file-per-author is simpler and much faster — each author is a single cached fetch. The old approach is preserved on the `sqlite-httpvfs-version` branch if you're curious.

------------------------------------------------------------------------

## Quick start {#quick-start}

You need **Node 22+** and **Python 3**.

``` bash
# 1. clone
git clone https://github.com/melaniewalsh/whats-seattle-reading-viewer.git
cd whats-seattle-reading-viewer

# 2. install front-end deps (the Pudding starter requires Node 22)
nvm install 22 && nvm use 22      # if you use nvm
npm install

# 3. run the dev server
npm run dev        # then open the URL it prints
```

**About the data in dev.** The generated data (`static/data/`) is **not** committed — it's built by the pipeline and uploaded to R2 (see below). In dev the site reads from your local `static/data/`, so a fresh clone has nothing to show until you put data there. Two options:

-   **Easiest — borrow the live data:** in `src/components/db.js`, temporarily point `DATA_BASE` at the live R2 URL (`R2_BASE`) instead of `${base}/data`. Now `npm run dev` shows the real, full data. (Don't commit that change.)
-   **Build it yourself:** `pip install duckdb boto3 orjson pyarrow`, then `python3 data-prep/build_data.py`. With Cloudflare R2 credentials set (`R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY`) it pulls the monthly checkout files and builds the full dataset into `static/data/`; without them it just builds from whatever monthly files you already have in `data/raw/`.

------------------------------------------------------------------------

## How it's deployed {#how-its-deployed}

The website is free static hosting on **GitHub Pages**. The data (a few hundred MB of small JSON files) is too much to keep in the repo, so it lives on **Cloudflare R2** and the site fetches from there. Three GitHub Actions run the whole thing on autopilot:

1.  **Pull fresh checkouts (monthly)** — `.github/workflows/update.yml` runs an R script that grabs the newest month of SPL data and drops it in the **raw** R2 bucket.
2.  **Rebuild the site data (monthly)** — `.github/workflows/build-data-to-r2.yml` runs `data-prep/build_data.py`, which reads all the raw checkouts, writes the per-author JSON files, and uploads them to the **public** R2 bucket. (Scheduled a few hours after the pull so it always has the newest data. You can also trigger it by hand from the **Actions** tab → **Run workflow**.)
3.  **Redeploy the website (every push)** — `.github/workflows/deploy.yml` rebuilds and redeploys the SvelteKit site to GitHub Pages. This is fast — a minute or two — because it never rebuilds the data; it just points at the copy already on R2.

So: push code and the site updates in a minute; the data refreshes on its own once a month.

### Setting up R2 (you only do this once)

The data lives in a **public** R2 bucket so the browser is allowed to read it. In the Cloudflare dashboard → **R2**:

1.  **Two buckets.** `spl-checkouts` holds the raw monthly CSVs (keep it **private**). `spl-checkouts-public` holds the generated per-author files (this one is public).
2.  **Turn on public access** for `spl-checkouts-public`: bucket → **Settings** → **Public Access** → allow the **r2.dev** subdomain. Cloudflare gives you a URL like `https://pub-xxxx.r2.dev`.
3.  **Add this CORS rule** (same Settings page) so the browser can fetch the files from our site:

```json
[
  {
    "AllowedOrigins": ["https://melaniewalsh.github.io"],
    "AllowedMethods": ["GET", "HEAD"],
    "AllowedHeaders": ["*"],
    "ExposeHeaders": ["content-length", "etag"]
  }
]
```

4.  **Point the site at your bucket:** put the public URL in `R2_BASE` at the top of `src/components/db.js`.

Two more one-time things:

-   The build workflow needs to *write* to the buckets, so make sure the R2 keys in the repo's GitHub secrets (`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`) have access.
-   In the repo's **Settings → Pages**, set **Source = GitHub Actions**.

------------------------------------------------------------------------

## Updating the data after a change {#updating-data}

Say you refined the author clustering (`author_map.json`), changed `MIN_TITLE_CHECKOUTS`, or edited anything else in `data-prep/`. The data only refreshes on its own once a month — here's how to push your change to the live site now.

The rebuild happens in the cloud (it reads ~50M rows, which is too much for a laptop), so you **don't** rebuild the whole thing locally. You commit your change, then click one button to run the build on GitHub's servers.

**The steps:**

1.  **Make your change and check it in.** For clustering, that means running `python3 data-prep/cluster_authors.py` to (re)generate `data-prep/author_map.json`, then committing it:

    ``` bash
    python3 data-prep/cluster_authors.py     # writes data-prep/author_map.json
    git add data-prep/author_map.json         # (plus any code you changed)
    git commit -m "Refine author clustering"
    git push
    ```

    > ⚠️ **`author_map.json` must be committed and pushed.** The cloud build reads it straight from the repo — if it's only on your laptop, the rebuild won't see your merges.

2.  **Run the build.** Go to the repo's **Actions** tab → **"Build full database and upload to R2"** → **Run workflow** (leave the branch on `main`) → **Run workflow**. This reruns `data-prep/build_data.py` with your changes and uploads the fresh per-author files to R2.

3.  **Wait ~30–40 minutes.** The full dataset is big. When the run goes green, it's done — the new files (with `NA` gone, your merges applied, etc.) are on R2, and the **old ones are automatically cleaned up** (the upload mirrors the build, so author files whose spellings got merged away are removed).

4.  **Refresh the live site.** That's it — **no site redeploy needed.** The data lives on R2 separately from the website, so a data change shows up as soon as the build finishes (a hard-refresh, ⌘⇧R, clears any cached files).

**Preview locally before you push (recommended).** Before triggering the 40-minute cloud build, it's worth confirming your change looks right on a smaller scale:

``` bash
python3 data-prep/build_data.py   # builds into static/data/ (see Quick start for data sources)
npm run dev                        # check that the merge / change looks correct
```

Then do steps 1–2 above to push it live.

------------------------------------------------------------------------

## How the data pipeline works {#how-the-data-pipeline-works}

`data-prep/build_data.py` turns tens of millions of raw checkout rows into small static files. The website never loads the raw data.

1.  **DuckDB does the number-crunching as SQL** — fast even at ~50M rows, and it spills to disk instead of blowing up memory, so it runs on a normal GitHub Actions runner.
2.  **Sparse monthly series.** Each author (and each title) is stored as `[[monthIndex, count], ...]` — only the months something was actually borrowed, not a mostly-zero array. The month labels are written **once** to `meta.json`; the browser fills the zeros back in when it draws a chart.
3.  **One file per author.** The output is:
    -   `meta.json` — the shared month axis.
    -   `search-index.json` — `[[slug, name, total], ...]` for every author, sorted most-borrowed first. The browser loads this once (it's gzipped) and searches it in memory.
    -   `authors/<shard>/<slug>.json` — one file per author with their total series plus every qualifying title's series. `<shard>` is the first two characters of the slug, so ~350k files land in ~1k tidy folders instead of one giant one.

The build also **drops placeholder "authors"** the catalog uses for missing names (`NA`, `Unknown`, etc.) — left in, `NA` alone is ~48M checkouts across 132k titles and would swamp everything.

Two knobs in `build_data.py`:

-   `MIN_TITLE_CHECKOUTS` (default **50**) — drop titles below N total checkouts from an author's title list. The author's total and trend line still count everything; this just trims the long tail of once-or-twice-borrowed titles so the files stay small.
-   `DB_PAGE_SIZE` / batching constants — tuning for the build itself.

------------------------------------------------------------------------

## Project structure {#project-structure}

```
whats-seattle-reading-viewer/
├── data-prep/
│   ├── build_data.py        DuckDB: raw checkouts -> per-author JSON files
│   └── cluster_authors.py   STARTER TASK: merge duplicate author spellings
├── data/raw/                raw SPL checkout files (not committed)
├── static/data/             generated JSON (NOT committed; built + hosted on R2)
│   ├── meta.json              the shared month axis
│   ├── search-index.json      [[slug, name, total], ...] the search index
│   └── authors/<shard>/<slug>.json   one file per author
├── src/
│   ├── routes/+page.svelte  the page
│   └── components/
│       ├── Index.svelte           headline + mounts the viewer
│       ├── StackedViewer.svelte   search, chart controls, groups, title list  ← start here
│       ├── StackedAreaChart.svelte  the d3 chart (line + stacked-area modes)
│       └── db.js                  the data layer (fetches the JSON files above)
├── .github/workflows/
│   ├── update.yml              pulls new monthly checkouts into R2 (R script)
│   ├── build-data-to-r2.yml    builds the per-author files + uploads to R2
│   └── deploy.yml              builds + deploys the site to GitHub Pages
└── svelte.config.js
```

*(A few older components — `Viewer.svelte`, `LineChart.svelte` — are leftovers from the first version and aren't used; the live viewer is `Index → StackedViewer → StackedAreaChart`.)*

------------------------------------------------------------------------

## HDSSI {#hdssi}

Things we can work on for HDSSI.

### 1. ✅ Done: full dataset + monthly auto-update

The site now runs on the **full** SPL checkout dataset, rebuilt automatically once a month (see [How it's deployed](#how-its-deployed)). Possible follow-ons: tune `MIN_TITLE_CHECKOUTS`, add more of the raw fields (subjects, publication year), or add a custom domain on R2 for edge caching.

### 2. Merge duplicate authors (entity resolution)

The raw data spells names inconsistently, so the same person appears multiple times. Search "Octavia Butler" and you'll see **three** of her:

| name               | checkouts |
|--------------------|-----------|
| Octavia E. Butler  | 10,630    |
| Butler, Octavia E. | 1,637     |
| Octavia Butler     | 303       |

**What to do:** open `data-prep/cluster_authors.py`. We want to produce `data-prep/author_map.json`, a mapping from each raw name to one canonical name. The pipeline already knows how to use it — see the **`CLUSTERING HOOK`** comment in `build_data.py`. There's a working baseline and `TODO`s pointing at the key missing piece (flipping `"Lastname, First"` → `"First Lastname"`).

``` bash
python3 data-prep/cluster_authors.py   # writes data-prep/author_map.json
python3 data-prep/build_data.py        # rebuilds the site data, now merged
```

Verified example: with a map merging the three Butlers, her total becomes **12,570** (10,630 + 1,637 + 303).

------------------------------------------------------------------------

## What the viewer can do {#what-the-viewer-can-do}

-   **Search** any author, or click one of the **most-borrowed** quick-picks.
-   **Line view (default):** the author's total checkouts per month as one line.
-   **Stacked-area view (toggle):** the total broken down title-by-title. For prolific authors it shows the top titles and rolls the rest into an "Other titles" band so it stays fast.
-   **Tick titles** (with a filter box, sortable by *most borrowed* or *A–Z*) to add each as its own line; each shows a format **badge** (ebook / audio / print).
-   **Groups:** bundle related titles (editions, a series) into a **single aggregated line**. Make a group from the titles you've ticked, **name** it, and **drag** more titles onto it. In the stacked view a group's titles cluster together.
-   **Only / isolate:** hit **Only** on any group or title to show just that one line; its name becomes the chart title.
-   Hover the chart for a **tooltip** with the month and per-line counts.

------------------------------------------------------------------------

## Learning resources {#learning-resources}

New to Svelte or DuckDB? [**LEARNING.md**](LEARNING.md) has a curated, ordered list of tutorials and docs for both — flagged where they match this project's stack (Svelte 5 runes, DuckDB's Python API), plus SQL basics and a table mapping each technology to the files that use it.

------------------------------------------------------------------------

Visual style adapted from The Pudding's svelte-starter.
