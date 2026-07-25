"""
build_data.py  (DuckDB + sparse series version, parallelized)
===============================================================
Turn the raw Seattle Public Library "Checkouts by Title" CSV into small JSON
files that the website can load quickly.

Why DuckDB? It runs SQL directly on the CSV and chews through tens of millions
of rows in seconds, with no database server to set up. The sample here is
~280k rows, but this same script is meant to scale to the full ~50M-row
dataset without changes.

At full scale, the CSV is cached as Parquet once (data/raw/*.parquet) and all
subsequent SQL reads from that -- smaller on disk, faster to re-scan, and
paired with a capped MEMORY_LIMIT + temp_directory so DuckDB spills to disk
under memory pressure instead of trying to hold everything in RAM at once.
See `raw`/`clean` below: both are VIEWs, not materialized TABLEs, so neither
one copies the full ~50M rows into memory before aggregation.

Two ideas keep the output small enough to host as plain files:

  1. SPARSE series. A title checked out in only 5 months is stored as 5
     [monthIndex, count] pairs — not a 240-slot array that's mostly zeros.
     The browser fills the zeros back in. This is the single biggest win at
     full scale, where most titles are borrowed only a handful of times.

  2. A shared month axis. The list of all months is written ONCE to meta.json,
     not repeated in every author file.

Output (into web/static/data, served at /data on the site):
  library.sqlite3            -> one file: months, authors, and titles, with
                                 sparse series stored as JSON text columns
                                 and indices for the queries the site needs.

INCREMENTAL INPUT: new monthly files land in a Cloudflare R2 bucket over
time. sync_new_files_from_r2() lists everything under R2_PREFIX, diffs it
against data-prep/processed_files.csv (the running list of filenames
already folded into the database), and downloads only what's new. Each new
file is cached to its own Parquet shard immediately (same reasoning as the
one-time bulk cache below), and the `raw` view reads the bulk cache plus
every shard together. A filename is only appended to processed_files.csv
*after* the full rebuild (aggregation + library.sqlite3) finishes without
error -- so a crash mid-run leaves that file looking unprocessed and it's
retried next time, instead of silently getting skipped forever.

This used to write one JSON file per author (~350k files at full scale) --
authors.json as a search index, plus authors/<INITIALS>/<slug>.json for each
author's own drilldown. That works, but 350k small files is unpleasant to
generate, commit, and serve (inode overhead, slow git status, slow rsync/
git-lfs, etc). Instead we write a single SQLite database file and let the
browser query *into* it directly over HTTP range requests, using
sql.js-httpvfs (see https://phiresky.github.io/blog/2021/hosting-sqlite-databases-on-github-pages/).
SQLite organizes its file in fixed-size pages, so a well-indexed lookup only
has to fetch the handful of pages the B-tree walk actually touches -- a
single author's series + titles is a few KB fetched via a couple of range
requests, not a 668MB download, and there's no 350k-file build step or repo.

Schema (see build_sqlite() below):
  meta(key, value)              -- meta['months'] = JSON list of "YYYY-MM"
  authors(id, slug, name, initials, total, series)  -- series is JSON
  authors_fts(name)              -- FTS5 search index over authors.name,
                                     falls back to a plain btree + LIKE if
                                     the local sqlite3 build lacks FTS5
  titles(id, author_id, title, total, fmt, series)  -- series is JSON

PERFORMANCE NOTES (read this if you're extending the script)
--------------------------------------------------------------
Two changes make this version scale much better than a naive port to Python:

  1. The sparse [monthIndex, count] series for both authors AND titles are
     built *inside DuckDB* with `list(list_value(mi, c) ORDER BY mi)`,
     instead of fetching one Python row per (author, month) or
     (author, title, month) and hand-rolling the nesting with
     `defaultdict(list).append(...)`. At 50M raw rows, that intermediate
     table can be tens of millions of rows — reshaping it in a Python loop
     is single-threaded and slow. Doing the aggregation in SQL means DuckDB
     (multi-threaded, compiled) does that work, and Python only ever sees
     one row per author or per (author, title) — orders of magnitude fewer
     rows to iterate over.

     The title rows are also never collected into one titles_by_author dict
     holding every author's titles at once. title_cursor is ORDER BY author,
     so stream_author_records() pairs each author's title group with that
     author's (slug, total, series) the moment it finishes arriving, and
     hands it straight to a write chunk. Peak memory is bounded by one
     Arrow batch plus one chunk's worth of authors, not the whole
     dataset's title-level data at once.

  2. Writing to SQLite instead of one-file-per-author removes the old
     parallel-write step almost entirely. A single writer connection with
     executemany() batches (INSERT_BATCH rows at a time, inside one
     transaction) comfortably outruns 350k individual write() syscalls --
     SQLite's B-tree insert is cheap and there's no per-file open/close/
     fsync overhead or directory-creation races to worry about. So this
     stays single-threaded and simple; there's no ProcessPoolExecutor for
     the write phase anymore. Slug assignment (which needs to dedupe
     collisions like "j-smith" vs "j-smith-1") also stays single-threaded,
     since it must see every author in a fixed order -- but it's cheap.

HOW TO RUN
----------
    cd ~/whats-seattle-reading-viewer
    python3 data-prep/build_data.py

    Optional: pip install orjson
    orjson is a drop-in, Rust-based JSON encoder that's noticeably faster
    than the stdlib json module, especially at this file count. The script
    uses it automatically if it's installed and falls back to stdlib json
    otherwise -- no code changes needed either way.

STUDENTS: good places to extend this are marked with "TODO".
"""

import json
import os
import re
import shutil
import sqlite3
from pathlib import Path
from time import perf_counter
from concurrent.futures import ThreadPoolExecutor
import csv

from dotenv import load_dotenv

try:
    import boto3
except ImportError:  # pragma: no cover - boto3 is only needed for the R2 sync step
    boto3 = None

import duckdb

load_dotenv("data-prep/access.env")

# ---------------------------------------------------------------------------
# Cloudflare R2 sync -- see sync_new_files_from_r2() in main() for how this
# is used. Credentials come from the environment, never hardcode them here:
#   export R2_ACCESS_KEY_ID=...
#   export R2_SECRET_ACCESS_KEY=...
# ---------------------------------------------------------------------------
R2_ENDPOINT_URL = os.environ.get(
    "R2_ENDPOINT_URL",
    "https://dd55a988a4598a3425259692fe6f7ba1.r2.cloudflarestorage.com/",
)
R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY")
R2_BUCKET = os.environ.get("R2_BUCKET", "spl-checkouts")
R2_PREFIX = "monthly/"



# Pre-compiled once at import time
PAREN_RE = re.compile(r"\(.*?\)")
SUFFIX_RE = re.compile(r"(?:^|\s|,|\.)(jr\.?|sr\.?|ii|iii|iv|v|vi)\b")
MIDDLE_RE = re.compile(r"\b[A-Za-z]\.?\b")
YEAR_RE = re.compile(r"\b\d{4}-?\b")
UPPER_DOT_RE = re.compile(r"([a-zA-Z]{2})\.")
WHITESPACE_RE = re.compile(r"\s+")
SLUG_RE = re.compile(r"[^a-z0-9]+")
SLUG_CLEAN_RE = re.compile(r"[^a-zA-Z0-9_-]")

try:
    import orjson

    def _dumps(obj) -> bytes:
        return orjson.dumps(obj)

    _JSON_BACKEND = "orjson"
except ImportError:  # pragma: no cover - environment dependent
    def _dumps(obj) -> bytes:
        return json.dumps(obj).encode("utf-8")

    _JSON_BACKEND = "stdlib json"

# ---------------------------------------------------------------------------
# Paths (relative to this file, so it runs from anywhere).
# ---------------------------------------------------------------------------
PROJECT_DIR = Path(__file__).resolve().parent.parent
RAW_CSV = PROJECT_DIR / "data" / "raw" / "spl-monthly-checkouts_2005-2025.csv"
# Parquet cache of RAW_CSV. Built once (see main()), then reused
RAW_PARQUET = RAW_CSV.with_suffix(".parquet")
OUT_DIR = PROJECT_DIR / "static" / "data"
DB_PATH = OUT_DIR / "library.sqlite3"

# Where new monthly files downloaded from R2 land, and where each gets its
# own Parquet shard cached immediately after download (mirrors RAW_PARQUET's
# reasoning: smaller on disk, faster to re-scan on every subsequent run).
MONTHLY_RAW_DIR = PROJECT_DIR / "data" / "raw" / "monthly"
MONTHLY_PARQUET_DIR = PROJECT_DIR / "data" / "raw" / "monthly_parquet"

# Running list of R2 filenames already folded into library.sqlite3. A name
# only gets appended here after a full successful rebuild -- see
# sync_new_files_from_r2() and the end of main().
PROCESSED_FILES_CSV = PROJECT_DIR / "data-prep" / "processed_files.csv"

# SQLite page size in bytes. Over a high-latency network, the cost is the
# NUMBER of range requests, not bytes-per-request -- so bigger pages are better:
# they make the B-tree shallower and pack more per page, so a lookup touches
# fewer pages (and the browser fetches them in large chunks anyway; see
# requestChunkSize in db.js). Must be set on a brand-new (empty) db, before the
# first CREATE TABLE.
DB_PAGE_SIZE = 8192

# How many rows to batch per executemany()/commit while loading the db.
# Keeps one transaction from growing to hold 350k+ rows of undo/redo log in
# memory at once, without paying a commit's fsync cost per row.
DB_INSERT_BATCH = 5_000

# Where DuckDB spills intermediate data (hash tables, sort runs, etc.) to
# disk once MEMORY_LIMIT is hit, instead of raising an out-of-memory error.
# Needs on the order of the CSV size free (a few tens of GB at full scale).
DUCKDB_SPILL_DIR = PROJECT_DIR / "data-prep" / ".duckdb_spill"

# Cap on how much RAM DuckDB will use before spilling to DUCKDB_SPILL_DIR.
DUCKDB_MEMORY_LIMIT = os.environ.get("DUCKDB_MEMORY_LIMIT", "6GB")

# How many title rows DuckDB packs into each Arrow RecordBatch when
# streaming the title aggregation into titles_by_author. Bounds Python-side
# memory to a couple hundred thousand rows at a time.
TITLE_FETCH_CHUNK = 200_000

# Only keep a title in an author's drill-down list if it was checked out at
# least this many times (ever). Trims the long tail; the author's total and
# trend line still count every checkout. Set to 0 to keep everything.
# 0 = show every title (accepts the long-tail noise of one-off catalog spellings).
MIN_TITLE_CHECKOUTS = 0

# Pattern that strips a trailing ", 1966-" / ", 1945 July 28-" from a name.
NAME_DATE_RE = r",\s*[0-9]{4}.*$"

# Map the messy MaterialType column into a few buckets for the badge.
MATERIAL_CASE = """
CASE upper(MaterialType)
    WHEN 'EBOOK' THEN 'ebook'
    WHEN 'AUDIOBOOK' THEN 'audiobook'
    WHEN 'LARGEPRINT' THEN 'largeprint'
    WHEN 'BOOK' THEN 'print'
    WHEN 'REGPRINT' THEN 'print'
    WHEN 'COMIC' THEN 'print'
    ELSE 'other'
END
"""

# How many author-writing chunks to hand out to worker processes.
N_WORKERS = max(1, os.cpu_count() - 10 or 1) # Be aware his actually seems to be counting logical processors, not cores


def normalize(name: str) -> str:

    """A rough key for deciding two names are the same."""
    if not name:
        return ""

    # lowercasing, dash stripping, parenthesis creator
    creator = name.lower().strip("-").strip()

    # matches parenthesis and whats inside
    creator = PAREN_RE.sub("", creator)

    # splitting by commas
    parts = [p.strip() for p in creator.split(",") if p.strip()]

    # extract suffix first so it doesn't break in cases like L. E. Modesitt, Jr.
    suffix = None
    cleaned_parts = []

    # suffix pattern to match the suffix standing alone or near punctuation
    for part in parts:
        if SUFFIX_RE.match(part):
            suffix = part.replace(".", "").strip()  # Strip dots from suffix
        else:
            cleaned_parts.append(part)

    # Parsing out middle initials/names using \b[A-Za-z]\.?\b or words
    middle_name = None
    if len(cleaned_parts) > 2:
        # Check if a middle name/initial exists between first and last name
        possible_middle = cleaned_parts[1]
        if MIDDLE_RE.search(possible_middle) or len(possible_middle.split()) > 0:
            middle_name = possible_middle
            # Keep only the first name in cleaned_parts for re-ordering
            cleaned_parts = [cleaned_parts[0], cleaned_parts[-1]]

    # do Last, First format reversal if 2 main parts remain
    if len(cleaned_parts) == 2:
        cleaned_parts.reverse()
        creator = " ".join(cleaned_parts)
    else:
        creator = " ".join(cleaned_parts)

    # re-attach middle name in the same relative position
    if middle_name:
        creator = f"{creator} {middle_name}"

    # remaining years, extra spaces, and fix abbreviations
    # 4 digit sequence, optional hyphen
    creator = YEAR_RE.sub("", creator)

    # 2 upper case letters followed by period
    creator = UPPER_DOT_RE.sub(r"\1", creator)

    # consecutive whitespaces
    creator = WHITESPACE_RE.sub(" ", creator).strip()

    # re-attach suffix
    if suffix:
        creator = f"{creator} {suffix}"

    return creator


def _sql_literal(path) -> str:
    """
    Turn a filesystem path into a single-quoted SQL string literal.

    Needed because DuckDB's COPY ... TO <dest> doesn't accept a bound (?)
    parameter for <dest> -- only a literal works there (see main()). Only
    single quotes need escaping (by doubling) in a standard SQL string
    literal; backslashes -- relevant on Windows paths -- are NOT special
    inside single-quoted strings, so they're passed through as-is.
    """
    return "'" + str(path).replace("'", "''") + "'"


def slugify(name: str) -> str:
    """Make a filename- and URL-safe id, e.g. 'J. K. Rowling' -> 'j-k-rowling'."""
    slug = SLUG_RE.sub("-", name.lower()).strip("-")
    return slug or "unknown"


def _author_initials(author: str) -> str:
    # Remove illegal Windows filename characters
    win_clean = re.sub(r'[\/:*?"<>|]', '', author)
    name_parts = normalize(win_clean).split()
    
    if len(name_parts) >= 2:
        initials = (name_parts[0][0] + name_parts[-1][0]).upper()
    elif len(name_parts) == 1:
        initials = name_parts[0][0].upper()
    else:
        initials = "Missing"
    return initials.strip()



def assign_slugs(author_rows):
    """Walk every author once (in the exact order author_rows was fetched --
    total DESC) and hand back two small, author-keyed dicts: slug_by_author
    and meta_by_author (total + series, no titles).

    Slug collision handling ("j-smith" -> "j-smith-1") must see every author
    in this fixed order to be deterministic, so it stays single-threaded --
    but it only ever touches strings/ints/the small per-author series, never
    the (potentially huge) per-title data. That's what keeps this pass cheap
    even at 50M rows: it's O(authors), not O(titles).
    """
    used_slugs = {}
    slug_by_author = {}
    meta_by_author = {}
    for author, total, series in author_rows:
        slug = slugify(author)
        slug = SLUG_CLEAN_RE.sub("", slug)[:100]
        if slug in used_slugs:
            used_slugs[slug] += 1
            slug = f"{slug}-{used_slugs[slug]}"
        else:
            used_slugs[slug] = 0

        slug_by_author[author] = slug
        meta_by_author[author] = (total, series)
    return slug_by_author, meta_by_author


def stream_author_records(record_batch_reader, author_rows, slug_by_author, meta_by_author, counters):
    seen = set()
    current_author = object()
    current_title = object()
    current_titles = None
    title_series = []
    title_metadata = {}

    for batch in record_batch_reader:
        for row in batch.to_pylist():
            author = row["author"]
            title = row["title"]
            
            # If we hit a new author, flush the last one
            if author != current_author:
                if current_titles is not None:
                    if title_series:
                        current_titles.append({
                            "title": str(current_title),
                            "total": title_metadata["total"],
                            "fmt": title_metadata["fmt"],
                            "series": title_series
                        })
                    current_titles.sort(key=lambda t: t["total"], reverse=True)
                    total, series = meta_by_author[current_author]
                    seen.add(current_author)
                    yield (slug_by_author[current_author], current_author, total, series, current_titles)
          
                current_author = author
                current_titles = []
                current_title = title
                title_series = []
                title_metadata = {"total": row["total"], "fmt": row["fmt"]}
        
            # If we change titles within the same author, flush the title list
            elif title != current_title:
                if title_series:
                    current_titles.append({
                        "title": str(current_title),
                        "total": title_metadata["total"],
                        "fmt": title_metadata["fmt"],
                        "series": title_series
                    })
                current_title = title
                title_series = []
                title_metadata = {"total": row["total"], "fmt": row["fmt"]}
                counters["n_titles"] += 1

            title_series.append([row["mi"], row["c"]])

    # Flush final remaining elements
    if title_series and current_titles is not None:
        current_titles.append({
            "title": str(current_title),
            "total": title_metadata["total"],
            "fmt": title_metadata["fmt"],
            "series": title_series
        })
    if current_titles is not None:
        current_titles.sort(key=lambda t: t["total"], reverse=True)
        total, series = meta_by_author[current_author]
        seen.add(current_author)
        yield (slug_by_author[current_author], current_author, total, series, current_titles)

    for author, total, series in author_rows:
        if author not in seen:
            yield (slug_by_author[author], author, total, series, [])


def write_author_files(out_dir, months, record_stream, counters, variants_by_author=None):
    """Write the site's data as plain static JSON files -- one tiny file per
    author -- instead of a single SQLite database queried over HTTP range
    requests.

    Why the change: the SQLite-over-HTTP approach (sql.js-httpvfs) works, but a
    single author drilldown makes the browser walk a B-tree scattered across a
    ~500 MB file, which is dozens of small range requests over the network.
    Served from R2's un-cached, rate-limited public URL that was slow and would
    trip the rate limiter. One file per author turns each drilldown into a
    SINGLE fetch of a few hundred bytes -- fast, and exactly the small-static-
    file pattern a CDN is built to cache. See src/components/db.js.

    Output (into out_dir, served at /data on the site and mirrored to R2):

      meta.json                      -> {"months": [...]}  the shared month axis
      search-index.json              -> [[slug, name, total], ...] sorted by
                                        total DESC. Loaded once by the search
                                        box, then searched in-memory. Uploaded
                                        gzipped (see the deploy workflow) so the
                                        one-time download stays small.
      authors/<shard>/<slug>.json    -> {"name","total","series","titles"} --
                                        one author's own sparse series plus every
                                        qualifying title's sparse series, the
                                        same shape getAuthor() used to return.

    <shard> is the first two characters of the slug, so ~350k author files land
    in ~1k tidy subdirectories instead of one unwieldy directory.
    """
    authors_dir = out_dir / "authors"
    # Start clean: a rebuild with a higher threshold produces fewer authors, and
    # we don't want last run's now-dropped author files lingering on R2.
    if authors_dir.exists():
        shutil.rmtree(authors_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "meta.json").write_bytes(_dumps({"months": months}))

    search_index = []
    made_dirs = set()
    n_authors = 0
    for slug, name, total, series, titles in record_stream:
        n_authors += 1
        shard = slug[:2] or "__"
        if shard not in made_dirs:
            (authors_dir / shard).mkdir(parents=True, exist_ok=True)
            made_dirs.add(shard)
        # `titles` is already a list of {title,total,fmt,series} dicts, sorted
        # total-DESC by stream_author_records(); write it straight through.
        payload = {"name": name, "total": total, "series": series, "titles": titles}
        # Attach the raw catalog spellings merged into this author (only when 2+,
        # i.e. an actual cluster worth showing) for the UI "name variants" list.
        if variants_by_author:
            variants = variants_by_author.get(name)
            if variants and len(variants) > 1:
                payload["variants"] = sorted(variants)
        (authors_dir / shard / f"{slug}.json").write_bytes(_dumps(payload))
        search_index.append([slug, name, total])

    # record_stream doesn't arrive strictly total-DESC (authors WITH titles come
    # out alphabetical), so rank the search index here. The site shows the top
    # slice before anyone types and ranks live matches by total.
    search_index.sort(key=lambda row: row[2], reverse=True)
    (out_dir / "search-index.json").write_bytes(_dumps(search_index))

    print(f"  wrote {n_authors:,} author files into {authors_dir} ({len(made_dirs)} shards)")
    return n_authors


def annotate_subjects(con, out_dir, slug_by_author):
    """Post-pass: fold each author's (and each of their titles') most-common
    subject-heading TERMS into the already-written author JSON files.

    Runs AFTER write_author_files so it never perturbs the memory-tuned author/
    title streaming above; the caller wraps it in try/except, so if it fails the
    core build has still produced complete (subject-less) files. Terms come from
    the raw `subjects` field -- a comma-separated list per checkout row -- split
    into individual terms, weighted by checkouts, with case variants folded
    together (keeping the most-borrowed casing for display). Umbrella terms
    (Fiction/Nonfiction/Literature/...) are dropped so specific headings surface.
    Writes weighted pairs so the frontend can pool a work's editions + re-rank:
      author file  ->  "subjects": [[term, checkouts], ...]   (top 8, pooled)
      each title   ->  "subjects": [[term, checkouts], ...]   (top 10 per edition)
    """
    authors_dir = out_dir / "authors"

    # This runs LAST -- the memory-tuned author/title streaming (which needs the
    # low global limit to spill instead of OOM) is already done and its big Python
    # structures freed. The subject UNNEST is heavy, so give it much more room here
    # (the merge pass raised the baseline enough to tip the old 3 GB limit into an
    # OOM). Safe on the 16 GB CI runner since nothing else is running now.
    # 6GB (not more): the runner has ~16GB and Python still holds some, so a
    # higher DuckDB limit risks an OS OOM-kill of the whole build (10GB did).
    # 6GB is ~2x the point the pass failed at, and if it's still not enough
    # DuckDB errors *inside* the try/except -> subjects skip, build survives.
    try:
        con.execute(f"SET memory_limit='{os.environ.get('SUBJECTS_MEMORY_LIMIT', '6GB')}'")
    except Exception:  # noqa: BLE001
        pass

    # Umbrella terms carry almost no information and (because ebook records tag
    # little else) drown out the specific print headings -- e.g. The Goldfinch's
    # ebook is just "Fiction, Literature" (37k checkouts) while its print record
    # has "Young men, Loss, Artists, ...". Drop them so the specifics surface.
    STOP = ("'fiction','nonfiction','non-fiction','literature','general',"
            "'fiction general','general fiction','adult','adult fiction'")

    # Per-author top terms -- one small row per author, so a dict is fine to hold.
    # Stored WITH weights ([term, checkouts]) so the frontend can pool a work's
    # editions and re-rank; author terms are already pooled across everything.
    print("  [subjects] aggregating author terms ...")
    author_terms = {}
    for author, terms in con.execute(
        f"""
        WITH exploded AS (
            SELECT author, trim(u.term) AS term, checkouts
            FROM clean, UNNEST(string_split(coalesce(subjects, ''), ',')) AS u(term)
            WHERE length(trim(u.term)) > 1
              AND lower(trim(u.term)) NOT IN ({STOP})
        ),
        per AS (
            SELECT author, arg_max(term, checkouts) AS term, sum(checkouts) AS c
            FROM exploded
            GROUP BY author, lower(trim(term))
        )
        SELECT author, list_slice(list({{'t': term, 'n': c}} ORDER BY c DESC), 1, 8) AS terms
        FROM per
        GROUP BY author
        """
    ).fetchall():
        if terms:
            author_terms[author] = [[e["t"], int(e["n"])] for e in terms]

    # Per-(author, title) top terms, streamed ORDER BY author so we hold only one
    # author's titles in memory at a time and patch that author's file in one go.
    print("  [subjects] aggregating per-title terms + patching files ...")
    cur = con.execute(
        f"""
        WITH exploded AS (
            SELECT author, title, trim(u.term) AS term, checkouts
            FROM clean, UNNEST(string_split(coalesce(subjects, ''), ',')) AS u(term)
            WHERE length(trim(u.term)) > 1
              AND lower(trim(u.term)) NOT IN ({STOP})
        ),
        per AS (
            SELECT author, title, arg_max(term, checkouts) AS term, sum(checkouts) AS c
            FROM exploded
            GROUP BY author, title, lower(trim(term))
        )
        SELECT author, title, list_slice(list({{'t': term, 'n': c}} ORDER BY c DESC), 1, 10) AS terms
        FROM per
        GROUP BY author, title
        ORDER BY author
        """
    )
    reader = cur.fetch_record_batch(rows_per_batch=TITLE_FETCH_CHUNK)

    sentinel = object()
    state = {"author": sentinel, "titles": {}}
    n_patched = [0]

    def flush():
        author = state["author"]
        state_titles = state["titles"]
        state["titles"] = {}
        if author is sentinel:
            return
        slug = slug_by_author.get(author)
        if not slug:
            return
        path = authors_dir / (slug[:2] or "__") / f"{slug}.json"
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return
        aterms = author_terms.get(author)
        if aterms:
            data["subjects"] = aterms
        for t in data.get("titles", []):
            tt = state_titles.get(t["title"])
            if tt:
                t["subjects"] = [[e["t"], int(e["n"])] for e in tt]
        path.write_bytes(_dumps(data))
        n_patched[0] += 1

    for batch in reader:
        for row in batch.to_pylist():
            if row["author"] != state["author"]:
                flush()
                state["author"] = row["author"]
            state["titles"][row["title"]] = row["terms"]
    flush()
    print(f"  [subjects] patched {n_patched[0]:,} author files")


def build_sqlite(db_path, months, record_stream, counters):
    """
    Create library.sqlite3 and stream every author's series + titles into it.

    Replaces the old file-per-author writer. Schema:
      meta(key, value)             -- meta['months'] = JSON list of months
      authors(id, slug, name, initials, total, series)
      authors_fts(name)             -- FTS5 search index, content-linked to
                                       authors so it stores no duplicate text
      titles(id, author_id, title, total, fmt, series)

    `series` columns hold the same sparse [[monthIndex, count], ...] JSON
    the old per-author files used -- the browser-side densify() unpacks it
    the same way either side of this change.
    """
    if db_path.exists():
        db_path.unlink()

    db = sqlite3.connect(str(db_path))
    # Page size can only be set before the first table is created on a
    # fresh db, and only takes effect after a VACUUM (done at the end).
    db.execute(f"PRAGMA page_size={DB_PAGE_SIZE}")
    # This file is a disposable build artifact regenerated from the CSV on
    # every run, not a live database someone can lose data from so skipping
    # the journal/fsync overhead SQLite normally uses to survive a crash
    # mid-write, in exchange for a much faster bulk load.
    db.execute("PRAGMA journal_mode=OFF")
    db.execute("PRAGMA synchronous=OFF")

    db.executescript(
        """
        CREATE TABLE meta (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE authors (
            id       INTEGER PRIMARY KEY,
            slug     TEXT UNIQUE NOT NULL,
            name     TEXT NOT NULL,
            initials TEXT NOT NULL,
            total    INTEGER NOT NULL,
            series   TEXT NOT NULL
        );
        -- Powers "top N authors" (the default view before anyone searches).
        CREATE INDEX idx_authors_total ON authors (total DESC);

        CREATE TABLE titles (
            id        INTEGER PRIMARY KEY,
            author_id INTEGER NOT NULL REFERENCES authors (id),
            title     TEXT NOT NULL,
            total     INTEGER NOT NULL,
            fmt       TEXT NOT NULL,
            series    TEXT NOT NULL
        );
        -- Every "load one author's drilldown" query is
        -- `WHERE author_id = ? ORDER BY total DESC`.  This index satisfies
        -- both the filter and the sort in one B-tree range scan instead of
        -- a filter followed by a separate sort step.
        CREATE INDEX idx_titles_author ON titles (author_id, total DESC);
        """
    )

    # Full-text search over author names, for the search-as-you-type box.
    # FTS5 ships in every sql.js / sql.js-httpvfs wasm build the site will
    # query with, but building the db locally also needs FTS5 compiled
    # into whatever system sqlite3 Python is linked against. Degrade
    # to a plain index + LIKE if it isn't available here.
    # The site-side query code below already knows to try FTS5 first and
    # fall back the same way.
    try:
        db.execute(
            """
            CREATE VIRTUAL TABLE authors_fts USING fts5(
                name, content='authors', content_rowid='id'
            )
            """
        )
        has_fts5 = True
    except sqlite3.OperationalError:
        db.execute("CREATE INDEX idx_authors_name ON authors (name COLLATE NOCASE)")
        has_fts5 = False
    print(f"  [author search index: {'FTS5' if has_fts5 else 'LIKE + btree (no FTS5 in local sqlite3)'}]")

    db.execute("INSERT INTO meta VALUES ('months', ?)", [json.dumps(months)])

    author_rows_buf, title_rows_buf, fts_rows_buf = [], [], []

    def flush():
        if author_rows_buf:
            db.executemany(
                "INSERT INTO authors (id, slug, name, initials, total, series) VALUES (?,?,?,?,?,?)",
                author_rows_buf,
            )
        if title_rows_buf:
            db.executemany(
                "INSERT INTO titles (author_id, title, total, fmt, series) VALUES (?,?,?,?,?)",
                title_rows_buf,
            )
        if has_fts5 and fts_rows_buf:
            db.executemany("INSERT INTO authors_fts (rowid, name) VALUES (?,?)", fts_rows_buf)
        author_rows_buf.clear()
        title_rows_buf.clear()
        fts_rows_buf.clear()

    n_authors = 0
    for author_id, (slug, author, total, series, titles) in enumerate(record_stream, start=1):
        n_authors = author_id
        author_rows_buf.append(
            (author_id, slug, author, _author_initials(author), total, _dumps(series).decode())
        )
        fts_rows_buf.append((author_id, author))
        for t in titles:
            title_rows_buf.append((author_id, t["title"], t["total"], t["fmt"], _dumps(t["series"]).decode()))
        if len(author_rows_buf) >= DB_INSERT_BATCH:
            flush()

    flush()
    db.commit()

    print("  building indices + compacting (VACUUM applies the page_size change) ...")
    db.execute("ANALYZE")
    db.execute("VACUUM")
    db.close()

    return n_authors


# Cloudflare R2 sync
def _load_processed_filenames():
    """The set of R2 keys already folded into a previous library.sqlite3."""
    if not PROCESSED_FILES_CSV.exists():
        return set()
    with PROCESSED_FILES_CSV.open(newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    if not rows:
        return set()
    # Skip the header row if present.
    body = rows[1:] if rows[0] == ["filename"] else rows
    return {row[0] for row in body if row}


def _mark_processed(keys):
    """
    Append newly-ingested R2 keys to PROCESSED_FILES_CSV.

    Only ever called after a full successful rebuild (see main()) -- if the
    aggregation or sqlite build raises partway through, these keys are never
    written here, so the next run treats them as new again and retries them
    instead of silently leaving them out of the database forever.
    """
    if not keys:
        return
    PROCESSED_FILES_CSV.parent.mkdir(parents=True, exist_ok=True)
    write_header = not PROCESSED_FILES_CSV.exists()
    with PROCESSED_FILES_CSV.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(["filename"])
        for key in keys:
            writer.writerow([key])


def sync_new_files_from_r2():
    """
    List every object under R2_PREFIX in the R2 bucket, diff it against
    PROCESSED_FILES_CSV, and download whatever isn't in there yet.

    Returns a list of (key, local_csv_path) pairs for the newly-downloaded
    files. Nothing is marked processed here -- that only happens in main(),
    after the rest of the pipeline (aggregation + library.sqlite3) has
    finished without raising.
    """
    if boto3 is None:
        print("  boto3 not installed -- skipping R2 sync, using local files only")
        return []
    if not (R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY):
        print("  R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY not set -- skipping R2 sync")
        return []

    s3 = boto3.client(
        "s3",
        endpoint_url=R2_ENDPOINT_URL,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        region_name="auto",  # Cloudflare's recommended value for R2
    )

    already_processed = _load_processed_filenames()

    # list_objects_v2 only returns up to 1000 keys per call. Paginating so
    # this doesn't stop scanning once the bucket grows past that.
    all_keys = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=R2_BUCKET, Prefix=R2_PREFIX):
        for obj in page.get("Contents", []):
            all_keys.append(obj["Key"])

    new_keys = [k for k in all_keys if k not in already_processed]
    print(f"  {len(all_keys):,} files in bucket, {len(new_keys):,} not yet processed")
    if not new_keys:
        return []

    MONTHLY_RAW_DIR.mkdir(parents=True, exist_ok=True)

    # Download in parallel -- boto3 clients are thread-safe, and these are
    # network-bound, so a handful of threads cuts wall time a lot vs. one-at-a-
    # time. Order of `downloaded` doesn't matter; every shard is read together.
    def _download(key):
        local_path = MONTHLY_RAW_DIR / key.rsplit("/", 1)[-1]
        s3.download_file(R2_BUCKET, key, str(local_path))
        print(f"    downloaded {key}")
        return (key, local_path)

    with ThreadPoolExecutor(max_workers=8) as pool:
        downloaded = list(pool.map(_download, new_keys))
    return downloaded


def merge_name_variants(con):
    """Apply the second-pass author reconciliation at build time.

    The RULE -- collapse case/order/date name-variants the fuzzy pass left split
    ("Pilkey, Dav" + "dav pilkey, 1966"), guarded by a conflicting-birth-year
    check -- lives in cluster_authors.name_variant_remap(), alongside the rest of
    the author-clustering logic. Here we just feed it the post-map canonical
    names + their checkout totals and fold the variants together in `clean`.
    Running it every build means it never needs author_map.json regenerated to
    stay current.
    """
    from cluster_authors import name_variant_remap
    rows = con.execute(
        "SELECT author, CAST(sum(checkouts) AS BIGINT) AS c FROM clean GROUP BY author"
    ).fetchall()
    remap = name_variant_remap(rows)
    if not remap:
        print("  no author name-variant merges")
        return
    print(f"  merging {len(remap):,} name-variants into {len(set(remap.values())):,} authors "
          f"(e.g. 'Pilkey, Dav' + 'dav pilkey, 1966')")
    con.execute("DROP TABLE IF EXISTS namemerge")
    con.execute("CREATE TABLE namemerge(variant VARCHAR, rep VARCHAR)")
    con.executemany("INSERT INTO namemerge VALUES (?, ?)", list(remap.items()))
    # Rewrite clean with variants folded into their representative. Can't
    # CREATE-OR-REPLACE a table from a SELECT over itself, so stage then swap.
    con.execute(
        """
        CREATE TABLE clean_merged AS
        SELECT COALESCE(nm.rep, c.author) AS author, c.title, c.mi, c.fmt, c.checkouts, c.subjects
        FROM clean c LEFT JOIN namemerge nm ON c.author = nm.variant
        """
    )
    con.execute("DROP TABLE clean")
    con.execute("ALTER TABLE clean_merged RENAME TO clean")
    # Release the memory this rewrite held so it doesn't carry into (and OOM) the
    # later subject-terms pass -- that's what tipped subjects over the old limit.
    con.execute("DROP TABLE IF EXISTS namemerge")
    con.execute("CHECKPOINT")


def build_top_authors(con, out_dir, slug_by_author, months, lo, top_n=20):
    """Top-N clustered authors per genre per year, by checkouts of books tagged
    with that genre (the "overlap" definition, reusing the Genres tab's term
    lists). Powers the "Top authors" tab. Writes out_dir/top-authors.json:
      {years:[...], genres:[...], data:{genre:{"<year>":[[slug,name,co],...],
       "all":[...]}}}
    Runs AFTER the author files so a failure here can't sink the main build."""
    import sys as _sys
    _sys.path.insert(0, str(PROJECT_DIR / "data-prep"))
    from build_partition import overlap_clauses  # (name, sql_clause) per genre

    years = sorted({int(m[:4]) for m in months})

    # Pre-aggregate to (author, year, subjects) once so each genre pass filters a
    # much smaller table instead of re-scanning every raw checkout row.
    con.execute("DROP TABLE IF EXISTS ays")
    con.execute(
        f"""
        CREATE TABLE ays AS
        SELECT author, ((mi + {lo}) // 12) AS year, subjects,
               CAST(sum(checkouts) AS BIGINT) AS c
        FROM clean
        GROUP BY author, year, subjects
        """
    )

    # Broad structural catch-all buckets from the partition taxonomy that aren't
    # meaningful "top authors by genre" categories -- drop them from this tab so
    # the dropdown stays to distinct, reader-facing genres (~40).
    GENRE_EXCLUDE = {
        "Fiction", "Nonfiction", "Art", "Illustrated Works", "Informational Works",
        "Instructional & Educational Works", "Readers Publications",
    }
    # "All genres" (no subject filter) first, then every genre's overlap clause.
    clauses = [("All genres", None)] + [
        (n, c) for n, c in overlap_clauses() if n not in GENRE_EXCLUDE
    ]
    genres_out, data = [], {}
    for name, clause in clauses:
        where = f"WHERE {clause}" if clause else ""
        rows = con.execute(
            f"SELECT author, year, CAST(sum(c) AS BIGINT) AS c FROM ays {where} "
            f"GROUP BY author, year"
        ).fetchall()
        per_year, all_time = {}, {}
        for author, year, c in rows:
            per_year.setdefault(year, []).append((author, c))
            all_time[author] = all_time.get(author, 0) + c

        def topn(pairs):
            top = sorted(pairs, key=lambda p: -p[1])[:top_n]
            return [[slug_by_author.get(a, ""), a, c] for a, c in top]

        gdata = {str(y): topn(per_year.get(y, [])) for y in years}
        gdata["all"] = topn(list(all_time.items()))
        data[name] = gdata
        genres_out.append(name)

    con.execute("DROP TABLE IF EXISTS ays")
    (out_dir / "top-authors.json").write_bytes(
        _dumps({"years": years, "genres": genres_out, "data": data})
    )
    print(f"  wrote top-authors.json ({len(genres_out)} genres x {len(years)} years)")


# --- work clustering (Python port of StackedViewer.svelte normalizeWorkKey) ---
# Keep in sync with the frontend so a "work" here matches what the site groups.
import unicodedata as _ud

_WORK_NOISE = re.compile(
    r"(book|bk|series|volume|vol|part|edition|unabridged|abridged|screenplay|"
    r"read by|narrated|illustrated|deluxe|anniversary|collector|special|movie|"
    r"film|adapted|reissue|boxe?d? ?set|complete|novel|novella|memoir|thriller|"
    r"mystery|story|stories|tale|tales|romance|biography|autobiography|poems|"
    r"essays|playscript|litrpg|gamelit|\bscript\b|\bproduction|\bserie|\blivre|"
    r"\btome|\blibro|\btomo|\bedicion)",
    re.I,
)
_WORK_FMT = re.compile(
    r"\b(unabridged|abridged|audiobook|e-?book|large print|compact disc|sound recording)\b",
    re.I,
)


def normalize_work_key(title):
    t = (title or "").lower()
    t = _ud.normalize("NFD", t)
    t = "".join(c for c in t if not _ud.combining(c))
    t = t.split(" / ")[0]
    if re.search(r"\s=\s", t):
        t = re.split(r"\s=\s", t)[-1]
    t = re.sub(r",\s+or,\s+.*$", "", t, flags=re.I)
    t = t.replace("&", " and ")
    t = re.sub(r"\([^)]*\)", " ", t)
    t = re.sub(r"\s*\([^)]*$", " ", t)
    t = re.sub(r"\[[^\]]*\]", " ", t)

    def _noise_repl(m):
        seg = m.group(0)
        return " " if (_WORK_NOISE.search(seg) or re.search(r"[:;]\s*or[\s,]", seg, re.I)) else seg

    prev = None
    while prev != t:
        prev = t
        t = re.sub(r"[:;]\s*[^:;]*$", _noise_repl, t)
    t = _WORK_FMT.sub(" ", t)
    t = re.sub(r"\b(the|a|an)\b", " ", t)
    t = re.sub(r"['’]", "", t)
    t = re.sub(r"[^a-z0-9]+", "", t)
    return t


def clean_title_for_display(title):
    t = (title or "").split(" / ")[0]
    t = re.sub(r"\s*:\s*.*$", "", t)
    t = re.sub(r"\([^)]*\)", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def build_top_works(con, out_dir, slug_by_author, months, lo, top_n=20):
    """Top-N clustered WORKS per genre per year, by checkouts of genre-tagged
    editions. Parallels build_top_authors but ranks works (editions clustered by
    normalize_work_key) instead of authors. Writes out_dir/top-works.json:
      {years, genres, data:{genre:{"<year>":[[title,author,slug,co],...],"all":[...]}}}"""
    import sys as _sys
    _sys.path.insert(0, str(PROJECT_DIR / "data-prep"))
    from build_partition import overlap_clauses

    years = sorted({int(m[:4]) for m in months})

    # title -> work key, computed once over the DISTINCT titles (far fewer than
    # the 50M checkout rows).
    titles = [r[0] for r in con.execute("SELECT DISTINCT title FROM clean WHERE title IS NOT NULL").fetchall()]
    con.execute("DROP TABLE IF EXISTS titlework")
    con.execute("CREATE TABLE titlework(title VARCHAR, wk VARCHAR)")
    con.executemany(
        "INSERT INTO titlework VALUES (?, ?)",
        [(t, normalize_work_key(t)) for t in titles],
    )

    # Best display title + author for each work (the highest-checkout edition).
    con.execute("DROP TABLE IF EXISTS workmeta")
    con.execute(
        """
        CREATE TABLE workmeta AS
        WITH wt AS (
            SELECT tw.wk AS wk, c.title AS title, CAST(sum(c.checkouts) AS BIGINT) AS co
            FROM clean c JOIN titlework tw ON c.title = tw.title
            WHERE tw.wk <> '' GROUP BY 1, 2),
        wa AS (
            SELECT tw.wk AS wk, c.author AS author, CAST(sum(c.checkouts) AS BIGINT) AS co
            FROM clean c JOIN titlework tw ON c.title = tw.title
            WHERE tw.wk <> '' GROUP BY 1, 2),
        t AS (SELECT wk, arg_max(title, co) AS disp_title FROM wt GROUP BY wk),
        a AS (SELECT wk, arg_max(author, co) AS disp_author FROM wa GROUP BY wk)
        SELECT t.wk, t.disp_title, a.disp_author FROM t JOIN a USING (wk)
        """
    )
    meta = {
        wk: (clean_title_for_display(dt), au)
        for wk, dt, au in con.execute("SELECT wk, disp_title, disp_author FROM workmeta").fetchall()
    }

    # Pre-aggregate (work, year, subjects) once; each genre pass filters this.
    con.execute("DROP TABLE IF EXISTS cw")
    con.execute(
        f"""
        CREATE TABLE cw AS
        SELECT tw.wk AS wk, ((c.mi + {lo}) // 12) AS year, c.subjects AS subjects,
               CAST(sum(c.checkouts) AS BIGINT) AS c
        FROM clean c JOIN titlework tw ON c.title = tw.title
        WHERE tw.wk <> ''
        GROUP BY wk, year, subjects
        """
    )

    GENRE_EXCLUDE = {
        "Fiction", "Nonfiction", "Art", "Illustrated Works", "Informational Works",
        "Instructional & Educational Works", "Readers Publications",
    }
    clauses = [("All genres", None)] + [
        (n, c) for n, c in overlap_clauses() if n not in GENRE_EXCLUDE
    ]
    genres_out, data = [], {}
    for name, clause in clauses:
        where = f"WHERE {clause}" if clause else ""
        rows = con.execute(
            f"SELECT wk, year, CAST(sum(c) AS BIGINT) AS c FROM cw {where} GROUP BY wk, year"
        ).fetchall()
        per_year, all_time = {}, {}
        for wk, year, c in rows:
            per_year.setdefault(year, []).append((wk, c))
            all_time[wk] = all_time.get(wk, 0) + c

        def topn(pairs):
            top = sorted(pairs, key=lambda p: -p[1])[:top_n]
            out = []
            for wk, c in top:
                title, author = meta.get(wk, ("", ""))
                out.append([title, author, slug_by_author.get(author, ""), c])
            return out

        gdata = {str(y): topn(per_year.get(y, [])) for y in years}
        gdata["all"] = topn(list(all_time.items()))
        data[name] = gdata
        genres_out.append(name)

    for tbl in ("cw", "workmeta", "titlework"):
        con.execute(f"DROP TABLE IF EXISTS {tbl}")

    # Resolve each unique work's cover URL now (Open Library search), so the site
    # serves covers immediately instead of searching per-visit. Baked on as a 5th
    # column [title, author, slug, checkouts, cover|null]; the site keeps a runtime
    # Wikipedia fallback for the ones Open Library misses (null). Best-effort: any
    # failure just leaves 4-column rows and the site resolves covers as before.
    try:
        _bake_work_covers(data)
    except Exception as e:  # pragma: no cover - network dependent
        print(f"  WARNING: cover baking failed ({e}); site will resolve covers at runtime")

    (out_dir / "top-works.json").write_bytes(
        _dumps({"years": years, "genres": genres_out, "data": data})
    )
    print(f"  wrote top-works.json ({len(genres_out)} genres x {len(years)} years)")


_TITLE_STOP = {"a", "an", "the", "and", "or", "of", "to", "in", "for", "is"}
_JUNK_RE = __import__("re").compile(
    r"\b(summary|summaries|study\s?guide|analysis|sparknotes|cliffs?notes|workbook|"
    r"conversation starters|quicklet|instaread|blinkist|bookrags|trivia[- ]on)\b",
    __import__("re").I,
)


def _title_tokens(s):
    import re as _re
    return [t for t in _re.sub(r"[^a-z0-9 ]+", " ", (s or "").lower()).split() if t and t not in _TITLE_STOP]


def _title_containment(requested, found):
    """Fraction of the requested title's words present in the found title.
    Containment (not symmetric Jaccard) so a subtitle on the result doesn't
    dilute the score, while a different volume in a series still falls short."""
    A = _title_tokens(requested)
    if not A:
        return 0.0
    B = set(_title_tokens(found))
    return sum(1 for t in A if t in B) / len(A)


def _is_junk(d):
    # Study guides / summaries / workbooks masquerade as the real book.
    if _JUNK_RE.search(d.get("title") or ""):
        return True
    return any(_JUNK_RE.search(a) for a in (d.get("author_name") or []))


def _has_english(d):
    lg = d.get("language")
    return (not lg) or ("eng" in lg)


def _author_tokens(s):
    import re as _re
    return {t for t in _re.sub(r"[^a-z ]+", " ", (s or "").lower()).split() if len(t) >= 3}


def _author_matches(requested, names):
    # Any shared name token (>=3 chars); tolerant of ordering/format.
    R = _author_tokens(requested)
    if not R:
        return True
    return any(_author_tokens(n) & R for n in (names or []))


def _english_cover(work_key, default_cover, language):
    """A work's default cover_i can be a foreign-language edition even when
    English ones exist (e.g. Game Changer's cover is the French "Sortie de
    zone"). When the work is multilingual, check its editions: if the default
    cover positively belongs to a non-English edition, swap in an English
    edition's cover. Conservative — only swaps on a confirmed non-English owner,
    so good English defaults (whose owning edition isn't tagged) are left be."""
    import urllib.request as _u, json as _j
    if not work_key or not language or all(l == "eng" for l in language):
        return default_cover
    try:
        req = _u.Request(
            f"https://openlibrary.org{work_key}/editions.json?limit=50",
            headers={"User-Agent": "whats-seattle-reading cover build (melwalsh@uw.edu)"},
        )
        with _u.urlopen(req, timeout=25) as r:
            entries = (_j.loads(r.read()) or {}).get("entries") or []
    except Exception:
        return default_cover
    owner_langs = None
    eng_covers = []
    for e in entries:
        el = [l.get("key", "").split("/")[-1] for l in (e.get("languages") or [])]
        covers = [c for c in (e.get("covers") or []) if c and c > 0]
        if "eng" in el:
            eng_covers += covers
        if default_cover in covers:
            owner_langs = el
    if owner_langs is not None and "eng" not in owner_langs and eng_covers:
        return eng_covers[0]
    return default_cover


def _resolve_ol_cover(title, author):
    """Open Library search -> a -L.jpg cover URL, or None. Matches the site's
    runtime logic (utils/covers.js) so baked and fallback covers agree.

    Uses a general `q=` search (title + author as free text) rather than the
    field-scoped `title=`/`author=` params: field-scoped search only matches
    exact edition records and misses Open Library's merged "work" (e.g. it
    returns an obscure 1-edition "Sorcerer's Stone" record instead of the
    canonical Harry Potter work, filed under "Philosopher's Stone").

    Drop study-guide / summary junk (it masquerades as the real book and can be
    weirdly popular), then require a title-containment match so a fuzzy search
    doesn't collapse a whole series onto its most popular volume (every "Harry
    Potter …" query otherwise returns book 1) — while still accepting genuine
    title variants (Sorcerer's ↔ Philosopher's) and subtitled editions ("Still
    Life (A Three Pines Mystery)"). When it doesn't empty the pool, also require
    the author to match (rejects a same-title book by a different author, while
    keeping a classic whose editions are credited to a translator). There is NO
    popularity fallback: no title match -> None (the site shows a placeholder)
    rather than a random popular book. Among survivors, prefer an English
    edition, then the most popular one."""
    import re as _re
    best = _search_cover(title, author, query_author=True)
    if best is None and author:
        best = _search_cover(title, author, query_author=False)
    # A stray leading article in the catalog title ("A Long Way Down" for Jason
    # Reynolds' "Long Way Down") pins the search to a different, identically-titled
    # book. If all we found is a same-title book by a DIFFERENT author, retry
    # without the leading article and take it only if the author then matches.
    if best is not None and author and not _author_matches(author, best.get("author_name")):
        alt = _re.sub(r"^(a|an|the)\s+", "", title, flags=_re.I)
        if alt != title:
            d2 = _search_cover(alt, author, query_author=True)
            if d2 is not None and _author_matches(author, d2.get("author_name")):
                best = d2
    if best is None:
        return None
    cid = _english_cover(best.get("key"), best.get("cover_i"), best.get("language"))
    return f"https://covers.openlibrary.org/b/id/{cid}-L.jpg" if cid else None


def _search_cover(title, author, query_author=True):
    import urllib.request as _u, urllib.parse as _up, json as _j
    term = f"{title or ''} {author or ''}".strip() if (author and query_author) else (title or "")
    q = _up.urlencode({"q": term, "limit": "20", "fields": "key,cover_i,edition_count,readinglog_count,title,language,author_name"})
    try:
        req = _u.Request(
            f"https://openlibrary.org/search.json?{q}",
            headers={"User-Agent": "whats-seattle-reading cover build (melwalsh@uw.edu)"},
        )
        with _u.urlopen(req, timeout=25) as r:
            docs = (_j.loads(r.read()) or {}).get("docs") or []
    except Exception:
        return None
    docs = [d for d in docs if d.get("cover_i") is not None and not _is_junk(d)]
    title_gated = [d for d in docs if _title_containment(title, d.get("title")) >= 0.6]
    author_gated = [d for d in title_gated if _author_matches(author, d.get("author_name"))] if author else title_gated
    if author_gated:
        pool = author_gated
    else:
        # No author match — keep only exact same-title works (a classic credited
        # to a translator, not a different, more popular book that merely
        # contains the words: "Book" -> "The Book Thief").
        rq = set(_title_tokens(title))
        pool = [d for d in title_gated if rq and set(_title_tokens(d.get("title"))) == rq]
    if not pool:
        return None
    pool.sort(key=lambda d: (_has_english(d), d.get("readinglog_count") or 0, d.get("edition_count") or 0), reverse=True)
    return pool[0]


def _bake_work_covers(data):
    """Resolve one cover per unique (title, author) across every top-works row and
    append it (or None) as a 5th element on each row, in place."""
    from concurrent.futures import ThreadPoolExecutor
    uniq = []
    seen = set()
    for gdata in data.values():
        for lst in gdata.values():
            for row in lst:
                k = (row[0], row[1])
                if k not in seen:
                    seen.add(k)
                    uniq.append(k)
    print(f"  resolving {len(uniq)} unique work covers via Open Library...")
    with ThreadPoolExecutor(max_workers=5) as ex:
        results = list(ex.map(lambda k: _resolve_ol_cover(k[0], k[1]), uniq))
    covers = dict(zip(uniq, results))
    hit = sum(1 for v in results if v)
    print(f"  resolved {hit}/{len(uniq)} covers")
    for gdata in data.values():
        for lst in gdata.values():
            for row in lst:
                row.append(covers.get((row[0], row[1])))


def main():
    start_time = perf_counter()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(PROJECT_DIR / "data-prep" / "workspace.duckdb"))

    con.execute(f"PRAGMA threads={N_WORKERS}")
    con.execute("SET preserve_insertion_order=false")

    # By default an in-memory connection has no MEMORY_LIMIT, so DuckDB just
    # keeps growing until the OS kills the process.
    DUCKDB_SPILL_DIR.mkdir(parents=True, exist_ok=True)
    con.execute(f"SET memory_limit='{DUCKDB_MEMORY_LIMIT}'")
    con.execute(f"SET temp_directory='{DUCKDB_SPILL_DIR}'")
    con.execute("PRAGMA max_temp_directory_size='40GiB'")

    print(f"[json backend: {_JSON_BACKEND}] [workers: {N_WORKERS}]")

    # -- Pull any new monthly files down from R2 before reading anything ----
    print("Checking R2 bucket for new monthly files ...")
    new_files = sync_new_files_from_r2()  # [(key, local_csv_path), ...]

    # Cache each newly-downloaded monthly CSV to its own Parquet shard right
    # away, same reasoning as the one-time bulk cache below: smaller on
    # disk, faster to re-scan on every subsequent run.
    if new_files:
        MONTHLY_PARQUET_DIR.mkdir(parents=True, exist_ok=True)
        print(f"Caching {len(new_files)} new monthly file(s) as Parquet ...")
        t0 = perf_counter()
        for _key, local_csv in new_files:
            shard_path = MONTHLY_PARQUET_DIR / (local_csv.stem + ".parquet")
            con.execute(
                f"""
                COPY (SELECT * FROM read_csv_auto(?, ignore_errors=true))
                TO {_sql_literal(shard_path)} (FORMAT PARQUET)
                """,
                [str(local_csv)],
            )
            # Delete the raw CSV as soon as it's cached to Parquet. The full CSV
            # corpus is ~12 GB; keeping it around alongside the Parquet cache and
            # DuckDB's spill files overruns a CI runner's disk. Parquet is the
            # source of truth from here on, so the CSV is safe to drop.
            local_csv.unlink(missing_ok=True)
        print(f"  cached  ({perf_counter() - t0:.2f}s)")

    # cache the original bulk CSV as Parquet once, then always read from that
    if RAW_PARQUET.exists():
        print(f"Using cached Parquet at {RAW_PARQUET}")
    elif RAW_CSV.exists():
        print(f"Caching {RAW_CSV} as Parquet ({RAW_PARQUET}) ...")
        t0 = perf_counter()
        # `COPY ... TO <dest>` can't be a bound (?)  
        con.execute(
            f"""
            COPY (SELECT * FROM read_csv_auto(?, ignore_errors=true))
            TO {_sql_literal(RAW_PARQUET)} (FORMAT PARQUET)
            """,
            [str(RAW_CSV)],
        )
        print(f"  cached  ({perf_counter() - t0:.2f}s)")
    else:
        print(f"  no bulk CSV at {RAW_CSV}. building from R2-synced monthly files only")

    # `raw` is every Parquet shard we have. The one-time bulk cache plus
    # every monthly file synced from R2 so far (this run's and all past
    # runs')read together as one view. Re-aggregating over the whole
    # growing corpus every run (rather than trying to merge deltas into an
    # existing library.sqlite3) keeps totals correct with no special-casing:
    # DuckDB chews through tens of millions of rows in seconds, so a full
    # recompute is cheap enough to just always do.
    parquet_shards = sorted(MONTHLY_PARQUET_DIR.glob("*.parquet")) if MONTHLY_PARQUET_DIR.exists() else []
    parquet_paths = ([RAW_PARQUET] if RAW_PARQUET.exists() else []) + parquet_shards
    if not parquet_paths:
        raise SystemExit(
            "No data to build from: no cached bulk Parquet and nothing synced from R2."
        )
    parquet_list_literal = "[" + ", ".join(_sql_literal(p) for p in parquet_paths) + "]"
    print(f"Reading {len(parquet_paths)} Parquet file(s) with DuckDB ...")
    t0 = perf_counter()
    con.execute(f"CREATE OR REPLACE VIEW raw AS SELECT * FROM read_parquet({parquet_list_literal})")
    n_rows = con.execute("SELECT count(*) FROM raw").fetchone()[0]
    print(f"  {n_rows:,} rows  ({perf_counter() - t0:.2f}s)")

    # -- Build the shared month axis -----------------------------------------
    lo, hi = con.execute(
        """
        SELECT min(CheckoutYear * 12 + (CheckoutMonth - 1)),
               max(CheckoutYear * 12 + (CheckoutMonth - 1))
        FROM raw WHERE Creator IS NOT NULL
        AND CheckoutYear BETWEEN 2005 AND 2030 
        """
    ).fetchone()
    months = [f"{k // 12}-{k % 12 + 1:02d}" for k in range(lo, hi + 1)]
    print(f"  {len(months)} months: {months[0]} … {months[-1]}")

    # -- Clean: one tidy table with author, title, month-index, format -------
    # Built directly from `raw` in a single materialization 
    BASE_SELECT = f"""
        SELECT
            -- Creator, {_sql_literal(NAME_DATE_RE)}, '')) AS author,
            Creator AS author,
            Title AS title,
            CheckoutYear * 12 + (CheckoutMonth - 1) - {lo} AS mi,
            {MATERIAL_CASE} AS fmt,
            Checkouts AS checkouts,
            Subjects AS subjects
        FROM raw
        WHERE Creator IS NOT NULL
        -- Drop placeholder "authors" the catalog uses for missing/unknown
        -- names. "NA" alone is ~48M checkouts across 132k titles -- lumped into
        -- one fake author it becomes a 75 MB file that crashes the browser when
        -- charted, and it's the #1 entry by total. These aren't real authors.
        AND upper(trim(Creator)) NOT IN ('NA', 'N/A', 'UNKNOWN', 'VARIOUS', 'ANONYMOUS')
        AND trim(regexp_replace(Creator, {_sql_literal(NAME_DATE_RE)}, '')) != ''
        -- Keep only book formats: print, large print, ebook, audiobook. Drops
        -- music CDs (SOUNDDISC), songs, video/DVD, maps, etc. (upper() so the
        -- mixed-case 'Ebook'/'Audiobook' spellings are kept too).
        AND upper(MaterialType) IN ('EBOOK', 'AUDIOBOOK', 'BOOK', 'REGPRINT', 'COMIC', 'LARGEPRINT')
        AND CheckoutYear BETWEEN 2005 AND 2030
    """

    # ---- CLUSTERING HOOK ---------------------------------------------------
    # If a student has produced data-prep/author_map.json (see data-prep/cluster_authors.py),
    # fold each mapped name into its canonical name here, so all the spellings of
    # one author are counted together. Without that file, names are used as-is.
    author_map = {}
    map_path = PROJECT_DIR / "data-prep" / "author_map.json"
    if map_path.exists():
        author_map = json.loads(map_path.read_text(encoding="utf-8"))

    # Invert the map: canonical author -> the raw catalog spellings merged into
    # it. Surfaced in the site's "name variants" dropdown so readers can see
    # exactly which catalog records were clustered together. Keyed by the same
    # canonical string that becomes each author file's "name" (clean.author).
    variants_by_author = {}
    for raw, canonical in author_map.items():
        variants_by_author.setdefault(canonical, []).append(raw)

   
   # returning to table usage since its saved on the disk now
    if author_map:
        print(f"  applying author_map.json ({len(author_map):,} merges)")
        con.execute("DROP TABLE IF EXISTS amap") # Clean up amap too
        con.execute("CREATE TABLE amap(raw VARCHAR, canonical VARCHAR)")
        con.executemany("INSERT INTO amap VALUES (?, ?)", list(author_map.items()))
        
        # Explicitly clear any existing view or table named 'clean' to prevent conflicts
        con.execute("DROP TABLE IF EXISTS clean")
        
        # if a map is always found (base select author and map's raw author match),
        # the author name used from the base select (b.author) wont make it into
        # #the clean table and the canonical name will be used instead if it exists
        con.execute(
            f"""
            CREATE TABLE clean AS
            WITH base AS ({BASE_SELECT})
            SELECT COALESCE(m.canonical, b.author) AS author,
                   b.title, b.mi, b.fmt, b.checkouts, b.subjects
            FROM base b
            LEFT JOIN amap m ON b.author = m.raw
            """
        )
    else:
        # Explicitly clear any existing view or table named 'clean' here as well
        con.execute("DROP TABLE IF EXISTS clean")
        
        con.execute(f"CREATE TABLE clean AS {BASE_SELECT}")
    # ------------------------------------------------------------------------

    # Second-pass reconciliation: fold together author records the map left split
    # (case/order/date name-variants), so an author's checkouts aren't divided.
    #print("Merging split author name-variants ...")
    #merge_name_variants(con)

   # -- Reshaping -----------------------------------------------------------
    print("Aggregating author totals in SQL ...")
    t0 = perf_counter()
    # This standard aggregation safely spills to disk under memory pressure
    author_totals_rows = con.execute(
        """
        SELECT author, CAST(sum(checkouts) AS BIGINT) AS total
        FROM clean
        GROUP BY author
        ORDER BY total DESC
        """
    ).fetchall()
    print(f"  {len(author_totals_rows):,} authors tallied ({perf_counter() - t0:.2f}s)")

    print("Streaming flat author series from SQL ...")
    t0 = perf_counter()
    # Fetch flat rows sorted by author so we can build lists linearly in Python
    author_series_cursor = con.execute(
        """
        SELECT author, mi, CAST(sum(checkouts) AS BIGINT) AS c
        FROM clean
        GROUP BY author, mi
        ORDER BY author, mi
        """
    )
    
    # Reconstructs the sparse series map in Python memory 
    author_series_map = {}
    author_series_reader = author_series_cursor.fetch_record_batch(rows_per_batch=TITLE_FETCH_CHUNK)
    for batch in author_series_reader:
        for row in batch.to_pylist():
            auth = row["author"]
            if auth not in author_series_map:
                author_series_map[auth] = []
            author_series_map[auth].append([row["mi"], row["c"]])
            
    # Rebuild the expected author_rows format: list of (author, total, series)
    author_rows = [
        (author, total, author_series_map.get(author, []))
        for author, total in author_totals_rows
    ]
    del author_series_map  # Free up temporary map memory
    print(f"  Author series mapped ({perf_counter() - t0:.2f}s)")

    print("Aggregating title series in SQL ...")
    t0 = perf_counter()
    # Remove the internal list(...) aggregation here too to prevent a second OOM
    title_cursor = con.execute(
        """
        WITH month_fmt AS (
            SELECT author, title, mi, fmt, CAST(sum(checkouts) AS BIGINT) AS c
            FROM clean
            GROUP BY author, title, mi, fmt
        ),
        month_only AS (
            SELECT author, title, mi, CAST(sum(c) AS BIGINT) AS c
            FROM month_fmt
            GROUP BY author, title, mi
        ),
        series_flat AS (
            SELECT author, title, mi, c
            FROM month_only
            WHERE author IN (
                SELECT author FROM month_only GROUP BY author, title HAVING sum(c) >= ?
            )
        ),
        totals_agg AS (
            SELECT author, title, CAST(sum(c) AS BIGINT) AS total
            FROM month_only
            GROUP BY author, title
            HAVING sum(c) >= ?
        ),
        fmt_agg AS (
            SELECT author, title, arg_max(fmt, fc) AS fmt
            FROM (SELECT author, title, fmt, sum(c) AS fc FROM month_fmt GROUP BY author, title, fmt)
            GROUP BY author, title
        )
        SELECT sf.author, sf.title, t.total, f.fmt, sf.mi, sf.c
        FROM series_flat sf
        JOIN totals_agg t USING (author, title)
        JOIN fmt_agg f USING (author, title)
        ORDER BY sf.author, sf.title, sf.mi
        """,
        [MIN_TITLE_CHECKOUTS, MIN_TITLE_CHECKOUTS],
    )

    # fetch_record_batch() streams the result as Arrow RecordBatches instead
    # of going through the DB-API cursor. fetchmany() unpacks one row at a
    # time through the C API; batch.to_pylist() converts a whole batch to
    # Python dicts in one bulk call, which cuts per-row overhead. Note this
    # doesn't make the final Python objects "free" as to_pylist() still
    # allocates a real dict per row, same as before but the batch-level
    # conversion is cheaper than DuckDB's row-by-row DB-API path, and it's
    # still bounded to one batch (TITLE_FETCH_CHUNK rows) in memory at a time.
    record_batch_reader = title_cursor.fetch_record_batch(rows_per_batch=TITLE_FETCH_CHUNK)

    # Slug assignment only ever looks at author_rows (same total-DESC order
    # as before) without needing any title data to be in memory yet.
    slug_by_author, meta_by_author = assign_slugs(author_rows)

    # record_stream is a generator: instead of first building a
    # titles_by_author dict holding every author's titles at once and only
    # then walking it, it pairs each author's titles with that author's
    # (slug, total, series) the moment DuckDB finishes emitting that
    # author's rows (title_cursor is ORDER BY author, so they arrive
    # consecutively). build_sqlite() below pulls from it and batches rows
    # into the db as they arrive, so at most one insert-batch's worth of
    # nested payloads exists in memory at a time so not every author's
    # title list sitting in memory simultaneously before writing starts.
    print(f"Writing per-author JSON files into {OUT_DIR} ...")
    t0 = perf_counter()
    counters = {"n_titles": 0}
    record_stream = stream_author_records(
        record_batch_reader, author_rows, slug_by_author, meta_by_author, counters
    )
    n_authors = write_author_files(OUT_DIR, months, record_stream, counters, variants_by_author)
    print(f"  {n_authors:,} authors, {counters['n_titles']:,} qualifying titles")
    print(f"  ({perf_counter() - t0:.2f}s)")

    # Fold top subject-heading terms into the author files (isolated post-pass;
    # a failure here must not sink an otherwise-complete build).
    try:
        annotate_subjects(con, OUT_DIR, slug_by_author)
    except Exception as e:  # noqa: BLE001
        print(f"  WARNING: subject annotation failed ({e}); files written without subjects")

    # Top authors per genre per year (isolated post-pass, same as subjects).
    try:
        build_top_authors(con, OUT_DIR, slug_by_author, months, lo)
    except Exception as e:  # noqa: BLE001
        print(f"  WARNING: top-authors build failed ({e}); Top authors tab will be empty")

    # Top works per genre per year (isolated post-pass).
    try:
        build_top_works(con, OUT_DIR, slug_by_author, months, lo)
    except Exception as e:  # noqa: BLE001
        print(f"  WARNING: top-works build failed ({e}); Top works tab will be empty")

    # Only mark this run's R2 files as processed once library.sqlite3 has
    # actually been rebuilt successfully. 
    if new_files:
        _mark_processed([key for key, _local_csv in new_files])
        print(f"  recorded {len(new_files)} newly-processed file(s) in {PROCESSED_FILES_CSV.name}")

    print("Done.")
    print(f"  {n_authors:,} authors")
    total_bytes = sum(f.stat().st_size for f in OUT_DIR.rglob("*") if f.is_file())
    index_bytes = (OUT_DIR / "search-index.json").stat().st_size
    print(f"  {total_bytes / 1e6:,.1f} MB total across {OUT_DIR} "
          f"(search-index.json alone: {index_bytes / 1e6:,.1f} MB) -> uploaded to R2")
    elapsed_time = perf_counter() - start_time
    print(f"Elapsed time: {elapsed_time:.4f} seconds")


if __name__ == "__main__":
    main()