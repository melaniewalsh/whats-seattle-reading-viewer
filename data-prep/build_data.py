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
  meta.json                  -> { months: ["2018-01", ...] }  (shared x-axis)
  authors.json               -> [{slug, name, total}]         (search index)
  authors/<INITIALS>/<slug>.json -> one author: sparse total series + titles

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

  2. Writing the per-author JSON files is embarrassingly parallel (each
     author's file is independent), but it's also CPU-bound (JSON
     serialization holds Python's GIL) as well as I/O-bound (one write()
     syscall per file, and there can be hundreds of thousands of files).
     A ProcessPoolExecutor sidesteps the GIL entirely for both the
     serialization and the write, and scales roughly linearly with cores.
     Slug assignment (which needs to dedupe collisions like "j-smith" vs
     "j-smith-1") is kept single-threaded in the main process since it must
     see every author in a fixed order — but it's cheap, so that's fine.

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
from concurrent.futures import ProcessPoolExecutor
from itertools import islice
from pathlib import Path
from time import perf_counter
#import boto3
#import pandas as pd
#from io import BytesIO
import duckdb

#s3 = boto3.client(
    #"s3",
    #endpoint_url="https://dd55a988a4598a3425259692fe6f7ba1.r2.cloudflarestorage.com/",
    #aws_access_key_id="YOUR_ACCESS_KEY",
    #aws_secret_access_key="YOUR_SECRET_KEY",
    #region_name="auto",  # Cloudflare's recommended value for R2
#)

#bucket = "spl-checkouts"

#resp = s3.list_objects_v2(Bucket=bucket, Prefix="monthly/")
#filenames = [obj["Key"] for obj in resp.get("Contents", [])]

#prev list loaded from csv of previously scanned files

#for f in filenames:
    #if f not in prev_list
        #run the rest of the code
            #if code runs sucessfully without error
            #add f to the csv



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
AUTHORS_DIR = OUT_DIR / "authors"

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



def _chunk(seq, n_chunks):
    """Split seq into n_chunks roughly-equal-size lists (order preserved)."""
    seq = list(seq)
    if not seq:
        return []
    size = -(-len(seq) // n_chunks)  # ceil division
    return [seq[i : i + size] for i in range(0, len(seq), size)]


def _chunked(iterable, size):
    """Yield successive lists of up to `size` items from iterable.

    Unlike _chunk(), this never materializes the whole sequence first -- it
    pulls just enough items to fill one chunk, yields it, and moves on. That
    lets a caller build one chunk's worth of author records, hand it to a
    worker, and let it be garbage-collected before the next chunk is built.
    """
    it = iter(iterable)
    while True:
        batch = list(islice(it, size))
        if not batch:
            return
        yield batch


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


def _write_chunk(args):
    """
    Worker function: serialize + write one chunk of authors to disk.

    Runs in a separate process, so it does its own JSON encoding and its own
    file writes -- no GIL contention with other workers. Returns the slice
    of the search index (slug -> {initials, name, total}) for this chunk so
    the main process can merge it into authors.json.
    """
    chunk, authors_dir_str = args
    authors_dir = Path(authors_dir_str)
    index_entries = {}

    for slug, author, total, series, titles in chunk:
        initials = _author_initials(author)
        author_dir = authors_dir / initials

        payload = {
            "name": author,
            "total": total,
            "series": series,
            "titles": titles,
        }
        (author_dir / f"{slug}.json").write_bytes(_dumps(payload))
        index_entries[slug] = {"initials": initials, "name": author, "total": total}

    return index_entries


def main():
    start_time = perf_counter()
    AUTHORS_DIR.mkdir(parents=True, exist_ok=True)
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

    # cache the CSV as Parquet once, then always read from that
    if not RAW_PARQUET.exists():
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
        print(f"Using cached Parquet at {RAW_PARQUET}")

    print(f"Reading {RAW_PARQUET} with DuckDB ...")
    t0 = perf_counter()
    con.execute(f"CREATE OR REPLACE VIEW raw AS SELECT * FROM read_parquet({_sql_literal(RAW_PARQUET)})")   
    n_rows = con.execute("SELECT count(*) FROM raw").fetchone()[0]
    print(f"  {n_rows:,} rows  ({perf_counter() - t0:.2f}s)")

    # -- Build the shared month axis -----------------------------------------
    lo, hi = con.execute(
        """
        SELECT min(CheckoutYear * 12 + (CheckoutMonth - 1)),
               max(CheckoutYear * 12 + (CheckoutMonth - 1))
        FROM raw WHERE Creator IS NOT NULL
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
        AND MaterialType != 'SoundDisk'
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

    # Slug assignment is split out from the title stream entirely only ever looks at author_rows
    # author (same total-DESC order as before) without needing any
    # title data to be in memory yet.
    slug_by_author, meta_by_author = assign_slugs(author_rows)

    # Pre-create every authors/<INITIALS>/ directory up front so
    # processes below never race each other creating the same directory.
    all_initials = {_author_initials(author) for author, _total, _series in author_rows}
    for initials in all_initials:
        (AUTHORS_DIR / initials).mkdir(parents=True, exist_ok=True)

    # Write one file per author, in parallel across processes.
    
    # generator: instead of first building a
    # titles_by_author dict holding every author's titles at once and only
    # then walking it, it pairs each author's titles with that author's
    # (slug, total, series) the moment DuckDB finishes emitting that
    # author's rows (title_cursor is ORDER BY author, so they arrive
    # consecutively). _chunked() pulls enough finished author records
    # to fill one chunk, so at most one chunk's worth of nested payloads
    # (roughly 1/N_WORKERS of the whole dataset) exists at a time,
    # instead of every author's title list sitting in memory simultaneously
    # before writing starts. Chunks are handed to the pool with `submit` as
    # they're produced (not `map`, which would need the full argument list
    # up front) so the next chunk isn't built until the current one has
    # been queued for its worker.
    print(f"Writing {len(author_rows):,} author files across {N_WORKERS} processes ...")
    t0 = perf_counter()
    chunk_size = max(1, -(-len(author_rows) // N_WORKERS))  # ceil division
    counters = {"n_titles": 0}
    record_stream = stream_author_records(
        record_batch_reader, author_rows, slug_by_author, meta_by_author, counters
    )
    authors_index = {}

    if N_WORKERS <= 1 or len(author_rows) <= chunk_size:
        # If small dataset skip process-pool
        for chunk in _chunked(record_stream, chunk_size):
            authors_index.update(_write_chunk((chunk, str(AUTHORS_DIR))))
    else:
        with ProcessPoolExecutor(max_workers=N_WORKERS) as pool:
            futures = [
                pool.submit(_write_chunk, (chunk, str(AUTHORS_DIR)))
                for chunk in _chunked(record_stream, chunk_size)
            ]
            for future in futures:
                authors_index.update(future.result())
    print(f"  {counters['n_titles']:,} qualifying titles")
    print(f"  wrote {len(authors_index):,} files  ({perf_counter() - t0:.2f}s)")

    # -- Write the shared axis + the search index ----------------------------
    (OUT_DIR / "meta.json").write_bytes(_dumps({"months": months}))
    (OUT_DIR / "authors.json").write_bytes(_dumps(authors_index))

    print("Done.")
    print(f"  {len(authors_index):,} authors")
    print(f"  shared axis -> {OUT_DIR/'meta.json'}")
    print(f"  search index -> {OUT_DIR/'authors.json'}")
    elapsed_time = perf_counter() - start_time
    print(f"Elapsed time: {elapsed_time:.4f} seconds")


if __name__ == "__main__":
    main()