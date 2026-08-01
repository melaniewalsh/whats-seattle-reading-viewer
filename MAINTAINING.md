# Maintaining *What's Seattle Reading?*

Internal notes for maintainers: deployment, the monthly data rebuild, the full pipeline internals, and project to-dos. For the public overview, see [README.md](README.md).

> **A bit of history.** An earlier version packed everything into one ~500 MB SQLite database and had the browser read slices of it over the network (via `sql.js-httpvfs`). It worked, but a single author took dozens of scattered range requests and could hang the tab. One-file-per-author is simpler and much faster — each author is a single cached fetch. The old approach is preserved on the `sqlite-httpvfs-version` branch.

---

## How it's deployed

The website is free static hosting on **GitHub Pages**. The data (a few hundred MB of small JSON files) is too much to keep in the repo, so it lives on **Cloudflare R2** and the site fetches from there. Three GitHub Actions run the whole thing on autopilot:

1. **Pull fresh checkouts (monthly)** — `.github/workflows/update.yml` runs an R script that grabs the newest month of SPL data and drops it in the **raw** R2 bucket.
2. **Rebuild the site data (monthly)** — `.github/workflows/build-data-to-r2.yml` runs `data-prep/build_data.py` (per-author files, with author merges + subject terms) then `data-prep/build_title_index.py` (the "By title" index), and uploads them to the **public** R2 bucket. Scheduled a few hours after the pull; also triggerable by hand from **Actions → Run workflow**. *The genre data (`static/genres.json`) is built separately by `build_partition.py` and committed — it is not part of this workflow.*
3. **Redeploy the website (every push)** — `.github/workflows/deploy.yml` rebuilds and redeploys the SvelteKit site to GitHub Pages. Fast (a minute or two) because it never rebuilds the data — it just points at the copy already on R2.

So: push code and the site updates in a minute; the data refreshes on its own once a month.

### Setting up R2 (one time)

In the Cloudflare dashboard → **R2**:

1. **Two buckets.** `spl-checkouts` holds the raw monthly CSVs (keep **private**). `spl-checkouts-public` holds the generated per-author files (**public**).
2. **Turn on public access** for `spl-checkouts-public`: bucket → **Settings → Public Access** → allow the **r2.dev** subdomain. Cloudflare gives you a URL like `https://pub-xxxx.r2.dev`.
3. **Add this CORS rule** (same Settings page) so the browser can fetch from our site:

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

4. **Point the site at your bucket:** put the public URL in `R2_BASE` at the top of `src/components/db.js`.

Two more one-time things:

- The build workflow needs to *write* to the buckets, so the R2 keys in the repo's GitHub secrets (`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`) must have access.
- In **Settings → Pages**, set **Source = GitHub Actions**.

> Note: `r2.dev` public URLs are rate-limited by Cloudflare and intended for light traffic. For heavier or production use, attach a **custom domain** to the public bucket (R2 → Settings → Custom Domains).

---

## Updating the data after a change

Say you refined the author clustering (`author_map.json`), changed `MIN_TITLE_CHECKOUTS`, or edited anything in `data-prep/`. The data auto-refreshes only once a month — here's how to push a change live now.

The rebuild happens in the cloud (it reads ~50M rows, too much for a laptop), so you don't rebuild the whole thing locally. You commit your change, then run the build on GitHub's servers.

1. **Make your change and commit it.** For clustering, regenerate the map and commit it:

   ```bash
   python3 data-prep/cluster_authors.py     # writes data-prep/author_map.json
   git add data-prep/author_map.json         # (plus any code you changed)
   git commit -m "Refine author clustering"
   git push
   ```

   > ⚠️ **`author_map.json` must be committed and pushed** — the cloud build reads it straight from the repo. If it's only on your laptop, the rebuild won't see your merges.

2. **Run the build.** Repo **Actions** tab → **"Build full database and upload to R2"** → **Run workflow** (branch `main`).
3. **Wait ~30–40 minutes.** When the run goes green, the fresh per-author files are on R2, and **old ones are automatically cleaned up** (the upload mirrors the build).
4. **Refresh the live site.** No site redeploy needed — the data lives on R2 separately from the website (hard-refresh, ⌘⇧R, clears cached files).

**Preview locally first (recommended):**

```bash
python3 data-prep/build_data.py   # builds into static/data/ (see README for data sources)
npm run dev                        # check the change looks right
```

---

## Pipeline internals

Everything is precomputed by scripts in `data-prep/`; the website never touches the raw data.

### The main build — `build_data.py`

Reads all the raw monthly checkouts and writes the per-author files. In order:

1. **Load + filter (DuckDB).** Pull the monthly checkout files, keep only book formats (print, large print, ebook, audiobook — music CDs, video/DVD, maps, etc. dropped), and drop placeholder "authors" (`NA`, `Unknown`, `Various`, …) — `NA` alone is ~48M checkouts across 132k titles and would swamp everything. Trailing life-dates on the creator field (`, 1979-`) are stripped here. DuckDB does the crunching as SQL and spills to disk, so it runs on a normal GitHub Actions runner.
2. **Author clustering, pass 1 — `author_map.json`.** Fold the many raw name spellings into one canonical name per author, using the map produced by `cluster_authors.py` (see the `CLUSTERING HOOK` comment).
3. **Author clustering, pass 2 — the token-set merge (`name_variant_remap`).** A cheap, exact backstop on *every* build. It reduces each canonical name to a **bag of words** (lowercased, birth/death years stripped — birth year set aside for a safety check) and buckets names with the **same set of words**, regardless of order or case; each bucket merges into its most-borrowed form. **Safety check:** a bucket with *conflicting* birth years is left alone (two different people who share a name; only ~15 buckets hit this). This re-derives the exact-token merges from scratch each build, so ~20k split authors (Pilkey, King, Christie, Mandel…) stay merged even when the committed map is stale. Pass 1 remains essential for the genuinely fuzzy cases.
4. **Aggregate (DuckDB).** Sum each author's and each title's monthly checkouts as **sparse** `[[monthIndex, count], …]` series (only months something was borrowed). Titles below `MIN_TITLE_CHECKOUTS` (25) are dropped from an author's title list — the author's total still counts everything; this just trims the long tail.
5. **Write the output files** (below).
6. **Subject terms — `annotate_subjects()`.** Folds each author's and each title's most-common **subject-heading terms** into the JSON, weighted by checkouts; umbrella terms (`Fiction`, `Literature`, …) dropped so specific headings surface. Stored with weights so the browser can pool a work's editions and re-rank. Wrapped in try/except so a failure here can't sink an otherwise-complete build.

**Output files:**

- `meta.json` — the shared month axis (written once; the browser fills zeros back in when drawing).
- `search-index.json` — `[[slug, name, total], …]` for every author, most-borrowed first; loaded once (gzipped) and searched in memory.
- `authors/<shard>/<slug>.json` — one file per author: total series, every qualifying title's series (format badge + subject terms), and top subject terms. `<shard>` is the first two slug chars, so ~350k files land in ~1k folders.

### Other build scripts

- **`build_title_index.py`** → `title-index.json` — the "By title" reverse-lookup. Emits `[[title, slug, author, total], …]` for every distinct work above `TITLE_MIN_CHECKOUTS` (**500** all-time, set in the workflow), deduped. Runs right after `build_data.py` in the cloud build.
- **`build_partition.py`** → `genres.json` — the genre tab. Classifies checkouts into a 50-genre taxonomy two ways: *overlap* (each genre = checkouts matching any of its terms) and *partition* (each checkout assigned to its first-matching genre, so shares sum to 100%). Queries Seattle's open-data API year by year. **Run by hand**; the result is committed, not part of the monthly build.
- **`build_overview.py`** → `overview.json` — the precomputed "all SPL checkouts" landing chart, so the default view loads instantly.
- **`cluster_authors.py`** → `author_map.json` — the pass-1 author name map consumed by `build_data.py`.
- **`build_genres.py`** — shared helpers (`load_months`, the book-universe filter) reused by the genre scripts.

### Tuning knobs

- `MIN_TITLE_CHECKOUTS` in `build_data.py` (default **25**) — smallest title in an author's breakdown.
- `TITLE_MIN_CHECKOUTS` in the build workflow (default **500**) — smallest title searchable in the "By title" tab. The UI note reads this back from the data.
- The genre taxonomy — the `TAXONOMY` list at the top of `build_partition.py`.

---

## Author merging (entity resolution) — reference

The raw data spells names inconsistently, so one person appears multiple times. Search "Octavia Butler" and you'll see three:

| name               | checkouts |
|--------------------|-----------|
| Octavia E. Butler  | 10,630    |
| Butler, Octavia E. | 1,637     |
| Octavia Butler     | 303       |

Two passes handle this:

- **Pass 1 — `cluster_authors.py` → `author_map.json` (fuzzy).** `normalize()` builds a match key (lowercase, flip `Lastname, First` → `First Lastname`, strip dates and `(qualifiers)`) and clusters names that share it, plus fuzzier matching (middle-initial differences, typos, nicknames, name changes). Committed as a map the build reads in.
- **Pass 2 — `name_variant_remap()` (exact, at build time).** Re-merges by exact bag-of-words as a backstop.

Why both? Of the map's ~450k merges, **~92% are exact-token merges** Pass 2 would catch on its own; **~8% are genuinely fuzzy** and only `cluster_authors.py` can do them. So Pass 2 guarantees the mechanical 92% on every build (even with a stale map), and Pass 1 remains essential for the fuzzy 8%.

With the three Butlers merged, her total becomes **12,570** (10,630 + 1,637 + 303).

---

## Project to-dos

- Tune `MIN_TITLE_CHECKOUTS` / `TITLE_MIN_CHECKOUTS` as the index grows.
- Add more raw fields to the per-author files (publication year, more subjects).
- Attach a custom domain on R2 for edge caching and to escape the `r2.dev` rate limit.
- Archive a versioned snapshot of the clustered data (e.g. Zenodo) for a citable DOI.

---

## Learning resources

New to Svelte or DuckDB? [**LEARNING.md**](LEARNING.md) has an ordered list of tutorials and docs for both, flagged where they match this project's stack (Svelte 5 runes, DuckDB's Python API).

*A few older components — `Viewer.svelte`, `LineChart.svelte` — are leftovers from the first version and aren't used; the live viewer is `Index → StackedViewer / GenreTrends → StackedAreaChart / GenreChart`.*
