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
-   [Grouping editions into works](#works-clustering)
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
2.  **Rebuild the site data (monthly)** — `.github/workflows/build-data-to-r2.yml` runs `data-prep/build_data.py` (per-author files, with author merges + subject terms) and then `data-prep/build_title_index.py` (the "By title" search index), and uploads them to the **public** R2 bucket. (Scheduled a few hours after the pull so it always has the newest data. You can also trigger it by hand from the **Actions** tab → **Run workflow**.) *The "By genre" data (`static/genres.json`) is built separately by `build_partition.py` and committed to the repo — it is not part of this workflow.*
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

The pipeline turns tens of millions of raw checkout rows into a handful of small static files the browser loads piecemeal. The website never touches the raw data. Everything is precomputed by scripts in `data-prep/`.

### The main build — `build_data.py`

Reads all the raw monthly checkouts and writes the per-author files. In order:

1.  **Load + filter (DuckDB).** Pull the monthly checkout files, keep only books/ebooks/audiobooks, and drop placeholder "authors" the catalog uses for missing names (`NA`, `Unknown`, `Various`, …) — `NA` alone is ~48M checkouts across 132k titles and would swamp everything. Trailing life-dates on the creator field (`, 1979-`) are stripped here. DuckDB does all the crunching as SQL and spills to disk instead of blowing up memory, so it runs on a normal GitHub Actions runner.
2.  **Author clustering, pass 1 — `author_map.json`.** Fold the many raw name spellings into one canonical name per author, using the map produced by `cluster_authors.py` (see the `CLUSTERING HOOK` comment).
3.  **Author clustering, pass 2 — the token-set merge.** A second pass that catches what pass 1 misses. The map reliably clusters most spellings but systematically *misses the plain inverted form* — it makes `dav pilkey, 1966` yet leaves `Pilkey, Dav` a separate author, splitting ~20k authors (including many of the biggest: Pilkey, Stephen King, Agatha Christie, Emily St. John Mandel) into two records with their checkouts divided between them. This pass collapses canonical authors that share the **same set of name tokens** (ignoring case, word order, and life dates) into the most-borrowed form — but refuses to merge a group whose members carry **conflicting birth years**, since that signals two different people (`george michael, 1963` vs `michael george, 1947`). Only ~15 such ambiguous groups exist; they're left alone. The *rule* lives with the rest of the clustering logic in `cluster_authors.py` (`name_variant_remap()`); `build_data.py` imports and applies it at build time, so it runs on every rebuild without needing `author_map.json` regenerated.
4.  **Aggregate (DuckDB).** Sum each author's monthly checkouts, and each title's, as **sparse** `[[monthIndex, count], ...]` series — only the months something was actually borrowed, not a mostly-zero array. Titles below `MIN_TITLE_CHECKOUTS` (50) are dropped from an author's title list — the author's total and trend line still count everything; this just trims the long tail so files stay small.
5.  **Write the output files** (below).
6.  **Subject terms — `annotate_subjects()`.** A post-pass that folds each author's — and each title's — most-common **subject-heading terms** into the JSON. Terms come from the raw `subjects` field, split and weighted by checkouts; umbrella terms (`Fiction`, `Nonfiction`, `Literature`, …) are dropped so specific headings surface. They're stored **with weights** so the browser can pool a work's editions and re-rank — a book's ebook record is often just "Fiction, Literature" while its print record carries the real headings (`Young men`, `Loss`, `Artists`), and pooling surfaces the latter. Wrapped in try/except, so a failure here can't sink an otherwise-complete build.

**The output files:**

-   `meta.json` — the shared month axis (written **once**; the browser fills the zeros back in when it draws a chart).
-   `search-index.json` — `[[slug, name, total], ...]` for every author, most-borrowed first. Loaded once (gzipped), searched in memory.
-   `authors/<shard>/<slug>.json` — one file per author: their total series, every qualifying title's series (with a format badge + subject terms), and the author's own top subject terms. `<shard>` is the first two slug characters, so ~350k files land in ~1k tidy folders instead of one giant one.

### The other build scripts

-   **`build_title_index.py`** → `title-index.json`, powering the **"By title"** reverse-lookup tab. Walks the per-author files and emits `[[title, slug, author, total], ...]` for every distinct work above `TITLE_MIN_CHECKOUTS` (**500** all-time checkouts, set in the workflow), deduped so each title appears once and resolves to its author. Kept small so the browser can load + substring-search it in memory. Runs right after `build_data.py` in the cloud build.
-   **`build_partition.py`** → `genres.json`, powering the **"By genre"** tab. Classifies checkouts into a 50-genre taxonomy **two ways**: *overlap* (each genre = checkouts matching any of its subject terms — genres overlap, and because tagging densified over time everything drifts upward) and *partition* (each checkout assigned to the **first** genre it matches in priority order, rest → "Other", so shares sum to 100% and real declines become visible). Queries Seattle's open-data API directly, year by year. **Run by hand**; the result (`static/genres.json`) is committed — it is *not* part of the monthly cloud build.
-   **`build_overview.py`** → `overview.json`, the precomputed "All Seattle Public Library checkouts" landing chart, so the default view loads instantly instead of waiting on a live API aggregation.
-   **`cluster_authors.py`** → `author_map.json`, the pass-1 author name map consumed by `build_data.py` above.
-   **`build_genres.py`** — shared helpers (`load_months`, the book-universe filter) reused by the genre scripts.

**Tuning knobs:**

-   `MIN_TITLE_CHECKOUTS` in `build_data.py` (default **50**) — the smallest title that appears in an author's title breakdown.
-   `TITLE_MIN_CHECKOUTS` in the build workflow (default **500**) — the smallest title that's searchable in the "By title" tab. Lower = more titles findable but a bigger in-browser index. The UI note reads this threshold back from the data, so it stays accurate automatically.
-   The genre taxonomy — the `TAXONOMY` list at the top of `build_partition.py` (name, include terms, exclude terms, and optional fiction-gated terms per genre).

------------------------------------------------------------------------

## Project structure {#project-structure}

```
whats-seattle-reading-viewer/
├── data-prep/
│   ├── build_data.py         DuckDB: raw checkouts -> per-author JSON files
│   │                           (author merges + subject terms baked in)
│   ├── cluster_authors.py    builds author_map.json (pass-1 name clustering)
│   ├── build_title_index.py  title-index.json for the "By title" tab
│   ├── build_partition.py    genres.json for the "By genre" tab (run by hand)
│   ├── build_genres.py       shared helpers for the genre scripts
│   ├── build_overview.py     overview.json — the fast landing-chart file
│   └── author_map.json       committed pass-1 name map (used by build_data.py)
├── data/raw/                 raw SPL checkout files (not committed)
├── static/
│   ├── genres.json           the "By genre" data (committed; from build_partition.py)
│   ├── overview.json         the landing "all checkouts" chart (committed)
│   └── data/                 generated per-author JSON (NOT committed; built + hosted on R2)
│       ├── meta.json             the shared month axis
│       ├── search-index.json     [[slug, name, total], ...] the author search index
│       ├── title-index.json      [[title, slug, author, total], ...] the title search index
│       └── authors/<shard>/<slug>.json   one file per author (+ titles, subjects)
├── src/
│   ├── routes/+page.svelte   the page
│   └── components/
│       ├── Index.svelte           headline + the three tabs (By author / By title / By genre)
│       ├── StackedViewer.svelte   By author + By title: search, charts, works, subjects  ← start here
│       ├── StackedAreaChart.svelte  the d3 chart (line + stacked-area modes)
│       ├── GenreTrends.svelte     the By-genre tab (partition/overlap, genre search)
│       ├── GenreChart.svelte      the genre line chart
│       ├── YearBrush.svelte       the time-window slider under the charts
│       └── db.js                  the data layer (fetches the JSON files above)
├── .github/workflows/
│   ├── update.yml              pulls new monthly checkouts into R2 (R script)
│   ├── build-data-to-r2.yml    builds per-author files + title index -> R2
│   └── deploy.yml              builds + deploys the site to GitHub Pages
└── svelte.config.js
```

*(A few older components — `Viewer.svelte`, `LineChart.svelte` — are leftovers from the first version and aren't used; the live viewer is `Index → StackedViewer / GenreTrends → StackedAreaChart / GenreChart`.)*

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

**Two passes handle this now.** Besides the map, `cluster_authors.py` exposes `name_variant_remap()` — a token-set merge that collapses author records sharing the exact same name tokens regardless of case, word order, and life dates. `build_data.py` calls it at build time (see [the pipeline section](#how-the-data-pipeline-works)), so the plain `"Lastname, First"` ↔ `"First Lastname"` flip (the old `TODO`) is now covered automatically, and split records like `Pilkey, Dav` + `dav pilkey, 1966` merge on their own — every rebuild, no map regeneration needed.

**What's left for `cluster_authors.py`** is the *fuzzier* matching the exact-token pass can't do: middle-initial differences (`Octavia Butler` vs `Octavia E. Butler`), typos, nicknames, and name changes. That's where `data-prep/author_map.json` (a map from each raw name to one canonical name) earns its keep — the pipeline consumes it in pass 1 (see the **`CLUSTERING HOOK`** comment in `build_data.py`).

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
-   **Top subjects.** Under the chart, the author's (or the selected title's) most-common subject-heading terms, pooled across a work's editions so the specific print headings show through the generic ebook ones.

Three tabs across the top:

-   **By author** (above) — the main view.
-   **By title** — search a title, and it resolves to its author and plots that book (gathering its editions into one line). Only the most-borrowed titles are searchable (see `TITLE_MIN_CHECKOUTS`); the note in the tab always reflects the current threshold.
-   **By genre** — 50 genres over 20 years, as a share of all checkouts. Toggle **partition** (each checkout counted once, in its first-matching genre — so declines are real) vs **overlap** (every genre a book is tagged with). Search genres by name or subject term, expand any genre to see its terms + top titles.

------------------------------------------------------------------------

## Grouping editions into works {#works-clustering}

The same book appears in the catalog many times — print, ebook, audiobook,
reprints, translations — each as a separate title. The viewer can **cluster
those editions into a single "work"** so you chart one line for "Sorcerer's
Stone" instead of four.

It works by stripping the predictable catalog boilerplate (the `/ by Author …`
credit, `: … Book 1` series subtitles, `(unabridged)` tags, accents, articles,
punctuation) down to a normalized **work key**, then grouping titles that share
it. It runs **in your browser, per author**, so it's instant and — importantly —
**you can correct it**: hit **"✨ Show top work groups"** to auto-plot the 5
most-borrowed works, use the **"add whole work"** button in the title table, and
drag titles between groups to fix any mistake.

This is **separate** from the author-name merging done in the data pipeline
(`cluster_authors.py`). For the full algorithm and every design decision, see
[**docs/title-clustering.md**](docs/title-clustering.md).

------------------------------------------------------------------------

## Learning resources {#learning-resources}

New to Svelte or DuckDB? [**LEARNING.md**](LEARNING.md) has a curated, ordered list of tutorials and docs for both — flagged where they match this project's stack (Svelte 5 runes, DuckDB's Python API), plus SQL basics and a table mapping each technology to the files that use it.

------------------------------------------------------------------------

Visual style adapted from The Pudding's svelte-starter.
