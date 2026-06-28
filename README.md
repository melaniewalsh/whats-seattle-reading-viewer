# What Is Seattle Reading? — a checkout-trends viewer

Search any author and explore their Seattle Public Library checkout trends over
time, then drill into individual titles and bundle editions together. Built with
[SvelteKit](https://kit.svelte.dev/) on
[The Pudding's svelte-starter](https://github.com/the-pudding/svelte-starter),
with a Python + [DuckDB](https://duckdb.org/) data pipeline.

**Live site:** https://melaniewalsh.github.io/whats-seattle-reading-viewer/
*(updates automatically on every push to `main`)*

---

## Contents
- [Quick start](#quick-start)
- [How it's deployed](#how-its-deployed)
- [Project structure](#project-structure)
- [How the data pipeline works](#how-the-data-pipeline-works)
- [Student projects](#student-projects) ← **start here if you've been invited to help**
- [What the viewer can do](#what-the-viewer-can-do)

---

## Quick start

You need **Node 22+**, **Python 3**, and a couple of packages.

```bash
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

> The generated data (`static/data/`) is already committed, so steps 4–5 are only
> needed if you want to **change** the data. Steps 1–3 + 6 are enough just to run it.

---

## How it's deployed

Pushing to `main` triggers `.github/workflows/deploy.yml`, which builds the
SvelteKit site and publishes it to **GitHub Pages**. There's no server and no
database — it's a fully static site, which is why it's free to host.

The site lives at a sub-path (`/whats-seattle-reading-viewer/`), so the build
passes a `BASE_PATH`; this is wired up in `svelte.config.js` and the data fetches
in `Viewer.svelte` use it.

**First-time setup (once per repo):** in the repo's **Settings → Pages**, set
**Source = GitHub Actions**. After that every push deploys automatically.

---

## Project structure

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

---

## How the data pipeline works

The raw CSV has hundreds of thousands of rows (millions, for the full dataset).
The website never loads it. Instead `data-prep/build_data.py` pre-computes everything:

1. **DuckDB runs the aggregation as SQL directly on the CSV** — fast even at tens
   of millions of rows.
2. Each author becomes one small JSON file with a **sparse** monthly series:
   `[[monthIndex, count], ...]` for only the months a title was actually
   borrowed (the browser fills in the zeros via `densify()` in `Viewer.svelte`).
3. The shared month axis is written **once** to `meta.json`, not repeated per file.

Two knobs in `build_data.py`:
- `RAW_CSV` — which CSV to read.
- `MIN_TITLE_CHECKOUTS` — drop titles below N total checkouts from an author's
  list (default 10). The author's total and trend line still count everything.

---

## Student projects

If you've been invited to help, here are the two main jobs. Each is self-contained.

### 1. Point it at the full dataset

Right now the repo uses a **sample** (2018–2022, popular titles only). The full
Seattle Public Library *"Checkouts by Title"* dataset (~50M rows, 2005–present)
lives on the city's open-data portal: <https://data.seattle.gov> (search
"Checkouts by Title"). It has the same columns as the sample.

**What to do:**
1. Download the full CSV and drop it in `data/raw/`.
2. In `data-prep/build_data.py`, change `RAW_CSV` to point at your file.
3. Consider raising `MIN_TITLE_CHECKOUTS` — the full data has a huge long tail of
   titles borrowed only once or twice.
4. Run `python3 data-prep/build_data.py` and see how big `static/data/` gets.

**Heads-up on size:** the full dataset's JSON may be hundreds of MB — too big to
commit and serve from GitHub Pages. The fix is to host the generated JSON
elsewhere with no egress fees (e.g. **Cloudflare R2**) and point the data fetches
in `Viewer.svelte` at that URL instead of the local `static/data/`. Talk to Mel
before doing this part.

### 2. Merge duplicate authors (entity resolution)

The raw data spells names inconsistently, so the same person appears multiple
times. Search "Octavia Butler" on the live site and you'll see **three** of her:

| name | checkouts |
|---|---|
| Octavia E. Butler | 10,630 |
| Butler, Octavia E. | 1,637 |
| Octavia Butler | 303 |

**What to do:** open `data-prep/cluster_authors.py`. Your job is to produce
`data-prep/author_map.json`, a mapping from each raw name to one canonical name. The
data-prep script already knows how to use it — see the **`CLUSTERING HOOK`** comment in
`build_data.py`. The file has a working baseline and `TODO`s pointing at the key
missing piece (flipping `"Lastname, First"` → `"First Lastname"`).

```bash
python3 data-prep/cluster_authors.py   # writes data-prep/author_map.json
python3 data-prep/build_data.py        # rebuilds the site data, now merged
```

Verified example: with a map merging the three Butlers, her total becomes
**12,570** (10,630 + 1,637 + 303). Be careful **not to over-merge** — two
different people can share a last name.

---

## What the viewer can do

- **Search** an author and chart their total checkouts per month.
- **Tick titles** (with a filter box) to chart each as its own line; each title
  shows a format **badge** (ebook / audio / print).
- **Bundle** ticked titles into one line — treat every edition/format/reprint as
  a single "work." The bundle is auto-named after its top title, and you can
  **rename it**.
- **Show author total** on/off — to compare just the titles or the bundle alone.
- Hover the chart for a **tooltip** with the month and per-line checkout counts.

---

Built by Melanie Walsh and students at the University of Washington Information
School. Data: Seattle Public Library open data. Visual style adapted from
The Pudding's svelte-starter.
