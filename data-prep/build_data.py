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
import sqlite3
from pathlib import Path
from time import perf_counter
from concurrent.futures import ThreadPoolExecutor
import csv

try:
    import boto3
except ImportError:  # pragma: no cover - boto3 is only needed for the R2 sync step
    boto3 = None

import duckdb

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

# SQLite page size in bytes. Small pages mean a single indexed lookup (an
# author's series, or their titles) touches fewer bytes per HTTP range
# request when the site queries this file directly over the network with
# sql.js-httpvfs. Must be set right after opening a brand-new (empty) db --
# SQLite only lets you change it before the first CREATE TABLE.
DB_PAGE_SIZE = 1024

# How many rows to batch per executemany()/commit while loading the db.
# Keeps one transaction from growing to hold 350k+ rows of undo/redo log in
# memory at once, without paying a commit's fsync cost per row.
DB_INSERT_BATCH = 5_000

# Where DuckDB spills intermediate data (hash tables, sort runs, etc.) to
# disk once MEMORY_LIMIT is hit, instead of raising an out-of-memory error.
# Needs on the order of the CSV size free (a few tens of GB at full scale).
DUCKDB_SPILL_DIR = PROJECT_DIR / "data-prep" / ".duckdb_spill"

# Cap on how much RAM DuckDB will use before spilling to DUCKDB_SPILL_DIR.
DUCKDB_MEMORY_LIMIT = "6GB"

# How many title rows DuckDB packs into each Arrow RecordBatch when
# streaming the title aggregation into titles_by_author. Bounds Python-side
# memory to a couple hundred thousand rows at a time.
TITLE_FETCH_CHUNK = 200_000

# Only keep a title in an author's drill-down list if it was checked out at
# least this many times (ever). Trims the long tail; the author's total and
# trend line still count every checkout. Set to 0 to keep everything.
MIN_TITLE_CHECKOUTS = 10

# Pattern that strips a trailing ", 1966-" / ", 1945 July 28-" from a name.
NAME_DATE_RE = r",\s*[0-9]{4}.*$"

# Map the messy MaterialType column into a few buckets for the badge.
MATERIAL_CASE = """
CASE upper(MaterialType)
    WHEN 'EBOOK' THEN 'ebook'
    WHEN 'AUDIOBOOK' THEN 'audiobook'
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
            trim(regexp_replace(Creator, {_sql_literal(NAME_DATE_RE)}, '')) AS author,
            Title AS title,
            CheckoutYear * 12 + (CheckoutMonth - 1) - {lo} AS mi,
            {MATERIAL_CASE} AS fmt,
            Checkouts AS checkouts
        FROM raw
        WHERE Creator IS NOT NULL
        AND MaterialType != 'SOUNDDISC'
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

   
   # returning to table usage since its saved on the disk now
    if author_map:
        print(f"  applying author_map.json ({len(author_map):,} merges)")
        con.execute("DROP TABLE IF EXISTS amap") # Clean up amap too
        con.execute("CREATE TABLE amap(raw VARCHAR, canonical VARCHAR)")
        con.executemany("INSERT INTO amap VALUES (?, ?)", list(author_map.items()))
        
        # Explicitly clear any existing view or table named 'clean' to prevent conflicts
        con.execute("DROP TABLE IF EXISTS clean")
        
        con.execute(
            f"""
            CREATE TABLE clean AS
            WITH base AS ({BASE_SELECT})
            SELECT COALESCE(m.canonical, b.author) AS author,
                   b.title, b.mi, b.fmt, b.checkouts
            FROM base b
            LEFT JOIN amap m ON b.author = m.raw
            """
        )
    else:
        # Explicitly clear any existing view or table named 'clean' here as well
        con.execute("DROP TABLE IF EXISTS clean")
        
        con.execute(f"CREATE TABLE clean AS {BASE_SELECT}")
    # ------------------------------------------------------------------------

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
    print(f"Building {DB_PATH.name} ...")
    t0 = perf_counter()
    counters = {"n_titles": 0}
    record_stream = stream_author_records(
        record_batch_reader, author_rows, slug_by_author, meta_by_author, counters
    )
    n_authors = build_sqlite(DB_PATH, months, record_stream, counters)
    print(f"  {n_authors:,} authors, {counters['n_titles']:,} qualifying titles")
    print(f"  ({perf_counter() - t0:.2f}s)")

    # Only mark this run's R2 files as processed once library.sqlite3 has
    # actually been rebuilt successfully. 
    if new_files:
        _mark_processed([key for key, _local_csv in new_files])
        print(f"  recorded {len(new_files)} newly-processed file(s) in {PROCESSED_FILES_CSV.name}")

    print("Done.")
    print(f"  {n_authors:,} authors")
    print(f"  {DB_PATH.stat().st_size / 1e6:,.1f} MB -> {DB_PATH}")
    elapsed_time = perf_counter() - start_time
    print(f"Elapsed time: {elapsed_time:.4f} seconds")


if __name__ == "__main__":
    main()