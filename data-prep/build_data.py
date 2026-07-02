"""
build_data.py  (DuckDB + sparse series version)
===============================================
Turn the raw Seattle Public Library "Checkouts by Title" CSV into small JSON
files that the website can load quickly.

Why DuckDB? It runs SQL directly on the CSV and chews through tens of millions
of rows in seconds, in memory, with no database server to set up. The sample
here is ~280k rows, but this same script is meant to scale to the full ~50M-row
dataset without changes.

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
  authors/<slug>.json        -> one author: sparse total series + titles

HOW TO RUN
----------
    cd ~/whats-seattle-reading-viewer
    python3 data-prep/build_data.py

STUDENTS: good places to extend this are marked with "TODO".
"""

import json
import re
from collections import defaultdict
from pathlib import Path
from time import perf_counter
import duckdb

# ---------------------------------------------------------------------------
# Paths (relative to this file, so it runs from anywhere).
# ---------------------------------------------------------------------------
PROJECT_DIR = Path(__file__).resolve().parent.parent
RAW_CSV = PROJECT_DIR / "data" / "raw" / "Checkouts_by_Title_2018-2022_15-checkouts.csv"
OUT_DIR = PROJECT_DIR / "static" / "data"
AUTHORS_DIR = OUT_DIR / "authors"

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

def normalize(name: str) -> str:
    
    """A rough key for deciding two names are the same."""
    if not name:
        return ""

    # lowercasing, dash stripping, parenthesis creator
    creator = name.lower().strip("-").strip()
    
    # matches parenthesis and whats inside
    creator = re.sub(r"\(.*?\)", "", creator)
    
    # splitting by commas
    parts = [p.strip() for p in creator.split(",") if p.strip()]

    # extract suffix first so it doesn't break in cases like L. E. Modesitt, Jr.
    suffix = None
    cleaned_parts = []
    
    # suffix pattern to match the suffix standing alone or near punctuation
    suffix_pattern = r"(?:^|\s|,|\.)(jr\.?|sr\.?|ii|iii|iv|v|vi)\b"
    for part in parts:
        if re.match(suffix_pattern, part):
            suffix = part.replace(".", "").strip() # Strip dots from suffix
        else:
            cleaned_parts.append(part)

    # Parsing out middle initials/names using \b[A-Za-z]\.?\b or words
    middle_name = None
    if len(cleaned_parts) > 2:
        # Check if a middle name/initial exists between first and last name
        possible_middle = cleaned_parts[1]
        if re.search(r"\b[A-Za-z]\.?\b", possible_middle) or len(possible_middle.split()) > 0:
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
    creator = re.sub(r"\b\d{4}-?\b", "", creator)
    
    # 2 upper case letters followed by period
    creator = re.sub(r"([a-zA-Z]{2})\.", r"\1", creator)
    
    # consecutive whitespaces
    creator = re.sub(r"\s+", " ", creator).strip()

    # re-attach suffix
    if suffix:
        creator = f"{creator} {suffix}"

    #t_duration = time.perf_counter() - t_start   
    #print(f"Time for normalize function: {t_duration:.6f} seconds")
    return creator


def slugify(name: str) -> str:
    """Make a filename- and URL-safe id, e.g. 'J. K. Rowling' -> 'j-k-rowling'."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "unknown"


def main():
    start_time = perf_counter()
    AUTHORS_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()

    print(f"Reading {RAW_CSV} with DuckDB ...")
    con.execute(
        "CREATE TABLE raw AS SELECT * FROM read_csv_auto(?, ignore_errors=true)",
        [str(RAW_CSV)],
    )
    n_rows = con.execute("SELECT count(*) FROM raw").fetchone()[0]
    print(f"  {n_rows:,} rows")

    # -- Build the shared month axis -----------------------------------------
    # Encode each (year, month) as a single integer y*12 + (m-1) so we can find
    # the range and turn months into 0-based indices.
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
    con.execute(
        f"""
        CREATE TABLE clean_raw AS
        SELECT
            trim(regexp_replace(Creator, ?, '')) AS author,
            Title AS title,
            CheckoutYear * 12 + (CheckoutMonth - 1) - {lo} AS mi,
            {MATERIAL_CASE} AS fmt,
            Checkouts AS checkouts
        FROM raw
        WHERE Creator IS NOT NULL
        AND MaterialType != 'SoundDisk' ;
        """,
        [NAME_DATE_RE],
    )

    # ---- CLUSTERING HOOK ---------------------------------------------------
    # If a student has produced data-prep/author_map.json (see data-prep/cluster_authors.py),
    # fold each mapped name into its canonical name here, so all the spellings of
    # one author are counted together. Without that file, names are used as-is.
    author_map = {}
    map_path = PROJECT_DIR / "data-prep" / "author_map.json"
    if map_path.exists():
        author_map = json.loads(map_path.read_text(encoding="utf-8"))

    if author_map:
        print(f"  applying author_map.json ({len(author_map):,} merges)")
        con.execute("CREATE TABLE amap(raw VARCHAR, canonical VARCHAR)")
        con.executemany("INSERT INTO amap VALUES (?, ?)", list(author_map.items()))
        con.execute(
            """
            CREATE TABLE clean AS
            SELECT COALESCE(m.canonical, c.author) AS author,
                   c.title, c.mi, c.fmt, c.checkouts
            FROM clean_raw c
            LEFT JOIN amap m ON c.author = m.raw
            """
        )
    else:
        con.execute("CREATE TABLE clean AS SELECT * FROM clean_raw")
    # ------------------------------------------------------------------------

    # -- Aggregate everything in SQL (this is the heavy lifting) -------------
    # 1) author totals, most-borrowed first
    author_totals = con.execute(
        "SELECT author, sum(checkouts) AS total FROM clean GROUP BY author ORDER BY total DESC"
    ).fetchall()

    # 2) author monthly series (sparse: only months with checkouts)
    author_monthly = con.execute(
        "SELECT author, mi, sum(checkouts) AS c FROM clean GROUP BY author, mi ORDER BY author, mi"
    ).fetchall()

    # 3) title totals + primary format (the format with the most checkouts)
    title_meta = con.execute(
        """
        SELECT author, title, sum(fc) AS total, arg_max(fmt, fc) AS fmt
        FROM (
            SELECT author, title, fmt, sum(checkouts) AS fc
            FROM clean GROUP BY author, title, fmt
        )
        GROUP BY author, title
        """
    ).fetchall()

    # 4) title monthly series (sparse)
    title_monthly = con.execute(
        "SELECT author, title, mi, sum(checkouts) AS c "
        "FROM clean GROUP BY author, title, mi ORDER BY author, title, mi"
    ).fetchall()

    # -- Reshape the flat SQL rows into per-author structures ----------------
    author_series = defaultdict(list)            # author -> [[mi, c], ...]
    for author, mi, c in author_monthly:
        author_series[author].append([mi, int(c)])

    title_series = defaultdict(list)             # (author, title) -> [[mi, c], ...]
    for author, title, mi, c in title_monthly:
        title_series[(author, title)].append([mi, int(c)])

    titles_by_author = defaultdict(list)         # author -> [{title, total, fmt}, ...]
    for author, title, total, fmt in title_meta:
        if total >= MIN_TITLE_CHECKOUTS:
            titles_by_author[author].append({"title": str(title), "total": int(total), "fmt": fmt})

    # -- Write one file per author -------------------------------------------
    print(f"Writing {len(author_totals):,} author files ...")
    authors_index = []
    used_slugs = {}

    for author, total in author_totals:
        slug = slugify(author)
        slug = re.sub(r"[^a-zA-Z0-9_-]", "", slug)[:100]
        if slug in used_slugs:
            used_slugs[slug] += 1
            slug = f"{slug}-{used_slugs[slug]}"
        else:
            used_slugs[slug] = 0

        # titles, biggest first, each with its sparse series
        titles = sorted(titles_by_author[author], key=lambda t: -t["total"])
        for t in titles:
            t["series"] = title_series[(author, t["title"])]

        payload = {
            "name": author,
            "total": int(total),
            "series": author_series[author],   # sparse [[mi, c], ...]
            "titles": titles,
        }

        #(AUTHORS_DIR / f"{slug}.json").write_text(json.dumps(payload))
        #authors_index.append({"slug": slug, "name": author, "total": int(total)})

        name_parts = normalize(author).split()

        if len(name_parts) >= 2:
            author_initials = (name_parts[0][0] + name_parts[-1][0]).upper()
        elif len(name_parts) == 1:
            # Single names
            author_initials = name_parts[0][0].upper()
        else:
            # Fallback for empty author strings
            author_initials = "Missing"
        
        author_initials_dir = AUTHORS_DIR / author_initials
        file_path = author_initials_dir / f"{slug}.json"

        author_initials_dir.mkdir(parents=True, exist_ok=True)
        file_path.write_text(json.dumps(payload))
        authors_index.append({
            "slug": slug,
            "name": author,
            "total": int(total)
        })

    # -- Write the shared axis + the search index ----------------------------
    (OUT_DIR / "meta.json").write_text(json.dumps({"months": months}))
    (OUT_DIR / "authors.json").write_text(json.dumps(authors_index))

    print("Done.")
    print(f"  {len(authors_index):,} authors")
    print(f"  shared axis -> {OUT_DIR/'meta.json'}")
    print(f"  search index -> {OUT_DIR/'authors.json'}")
    end_time = perf_counter()
    elapsed_time = end_time - start_time
    print(f"Elapsed time: {elapsed_time:.4f} seconds")


if __name__ == "__main__":
    main()
