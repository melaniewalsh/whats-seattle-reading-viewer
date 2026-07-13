"""
cluster_authors.py  —  STARTER TASK (unfinished on purpose)
===========================================================
Goal: merge the many spellings of the same author into one.

The raw data spells names inconsistently, so right now the site shows three
separate "Octavia Butler"s:

    Octavia E. Butler        (10,630 checkouts)
    Butler, Octavia E.       ( 1,637 checkouts)
    Octavia Butler           (   303 checkouts)

Your job: decide which raw author strings are the same person, and write out a
mapping from each raw name to a single canonical name. build_data.py already
knows how to use that mapping (see "HOW THIS PLUGS IN" below) — you just have to
produce a good `author_map.json`.

WHAT TO PRODUCE
---------------
Write a JSON file at data-prep/author_map.json shaped like:

    {
      "Butler, Octavia E.": "Octavia E. Butler",
      "Octavia Butler":     "Octavia E. Butler"
    }

Keys are raw names; values are the canonical name to use. Names not in the map
are left as-is. Pick the canonical form however you like (e.g. the spelling with
the most total checkouts).

HOW THIS PLUGS IN
-----------------
In build_data.py, the cleaned `author` column is what everything groups by.
After you create data-prep/author_map.json, add a step there that replaces each
author with author_map.get(author, author) before the aggregation. There is a
clearly-marked "CLUSTERING HOOK" comment in build_data.py showing exactly where.

APPROACHES (start simple, then improve)
---------------------------------------
1. Normalize + exact match: lowercase, strip punctuation, and flip
   "Lastname, First" -> "First Lastname". Group strings that become identical.
   This alone fixes a lot.
2. Fuzzy match: use rapidfuzz (`pip install rapidfuzz`) to group names whose
   similarity is above some threshold. Watch out for false merges
   (e.g. "James Baldwin" vs "James Baldwin Jr.").
3. Embeddings / authority files: match against OpenLibrary or VIAF to get a
   canonical name and even birth/death years. Most robust, most work.

Beware: don't over-merge. Two real different people can share a last name.
When unsure, keep them separate.

Run it with:
    python3 data-prep/cluster_authors.py
then re-run the main build:
    python3 data-prep/build_data.py
"""

import csv
import json
import re
from pathlib import Path
from urllib.parse import urlparse
import duckdb
from time import perf_counter
import os
from dotenv import load_dotenv
try:
    import boto3
except ImportError:  # pragma: no cover - boto3 is only needed to LIST keys now
    boto3 = None
import unicodedata



PROJECT_DIR = Path(__file__).resolve().parent.parent
RAW_CSV = PROJECT_DIR / "data" / "raw" / "spl-monthly-checkouts_2005-2025.csv"
OUT_MAP = PROJECT_DIR / "data-prep" / "author_map.json"
PROCESSED_FILES_CSV = PROJECT_DIR / "data-prep" / "processed_files.csv"

# The persisted (name, title) -> checkouts aggregate. This is what makes runs
# iterative: instead of re-scanning every CSV (local + R2) on every run, we
# only ever scan *new* files and fold their aggregated rows into this cache.
# Passes 1-3 below (date-signature merge, middle-name merge) then run over
# the cache, which already contains every title ever seen for every raw
# name, so cross-file merging still works exactly as before.
AGG_CACHE = PROJECT_DIR / "data-prep" / "author_title_agg.json"

load_dotenv(dotenv_path="data-prep/access.env")

"""
def clean_display(name: str) -> str:
    The display name, matching how build_data.py cleans authors (drop the
    trailing life dates, keep case + punctuation). Map keys must be in THIS form
    so the build script's CLUSTERING HOOK can match them.
    #return re.sub(r",\s*[0-9]{4}.*$", "", str(name)).strip()
"""

R2_ENDPOINT_URL = os.environ.get(
    "R2_ENDPOINT_URL",
    "https://dd55a988a4598a3425259692fe6f7ba1.r2.cloudflarestorage.com/",
)

R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY", "")
R2_BUCKET = os.environ.get("R2_BUCKET", "spl-checkouts")
R2_PREFIX = "monthly/"


def _r2_host():
    """duckdb's s3_endpoint wants a bare host, not the full https:// URL."""
    return urlparse(R2_ENDPOINT_URL).netloc


def configure_duckdb_for_r2(con):
    """Point this duckdb connection at R2 so read_csv_auto('s3://...') works
    directly -- no download, no local copy."""
    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute(f"SET s3_endpoint='{_r2_host()}';")
    con.execute("SET s3_region='auto';")
    con.execute("SET s3_url_style='path';")
    con.execute(f"SET s3_access_key_id='{R2_ACCESS_KEY_ID}';")
    con.execute(f"SET s3_secret_access_key='{R2_SECRET_ACCESS_KEY}';")
    con.execute("SET s3_use_ssl=true;")


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

    Only ever called after a full successful rebuild. If the
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


def list_new_keys_from_r2(all_keys_too=False):
    """
    List every object under R2_PREFIX in the R2 bucket and diff it against
    PROCESSED_FILES_CSV. Duckdb reads these keys
    straight off R2 later via s3:// paths.

    Returns new_keys, or (new_keys, all_keys) if all_keys_too=True (used on
    a cold start with no aggregate cache, where every key needs scanning).

    Nothing is marked processed here intentionally
    """
    if boto3 is None:
        print("  boto3 not installed. Cannot list R2 bucket.")
        return ([], []) if all_keys_too else []
    if not (R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY):
        print("  R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY not set. Skipping R2 sync")
        return ([], []) if all_keys_too else []

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
    return (new_keys, all_keys) if all_keys_too else new_keys


def query_rows_from_r2(con, keys):
    """Aggregate (Creator, Title) -> sum(Checkouts) for exactly these R2
    keys, read directly as s3:// paths. Nothing touches local disk."""
    if not keys:
        return []
    s3_paths = [f"s3://{R2_BUCKET}/{k}" for k in keys]
    return con.execute(
        """
        SELECT Creator AS name, Title AS title, sum(Checkouts) AS total
        FROM read_csv_auto(?, ignore_errors=true)
        WHERE Creator IS NOT NULL
        GROUP BY Creator, Title
        """,
        [s3_paths],
    ).fetchall()


def load_agg_cache():
    """Load the persisted {name: {total, titles}} aggregate from the last
    successful run, if any. Empty dict means "cold start" (or first ever
    run) -- main() falls back to a one-time full historical scan in that
    case."""
    if not AGG_CACHE.exists():
        return {}, {}
    raw = json.loads(AGG_CACHE.read_text(encoding="utf-8"))
    display_totals = {name: v["total"] for name, v in raw.items()}
    display_titles = {name: set(v["titles"]) for name, v in raw.items()}
    return display_totals, display_titles


def save_agg_cache(display_totals, display_titles):
    payload = {
        name: {
            "total": display_totals[name],
            "titles": sorted(display_titles.get(name, ())),
        }
        for name in display_totals
    }
    AGG_CACHE.parent.mkdir(parents=True, exist_ok=True)
    AGG_CACHE.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def normalize(name: str) -> str:
    
    """A rough key for deciding two names are the same."""
    if not name:
        return ""

    # lowercasing, dash stripping, parenthesis creator
    creator = name.lower().strip("-").strip()

    # matches parenthesis and whats inside
    creator = re.sub(r"\(.*?\)", "", creator)

    # Handle "w/" multi-creator strings without commas like "Stan and Jan Berenstain w/ Mike Berenstain"
    creator = re.sub(r'\s+w/\s+', ' / ', creator)

    # Check for slash-space cases like "Crichton, Michael / Patterson, James" but not cases like Kaye/Kantrowitz, Melanie
    if "/ " in creator:
        segments = [s.strip() for s in creator.split("/") if s.strip()]
        if len(segments) > 1:
            # If segments contain commas, process each segment independently
            if all("," in seg for seg in segments):
                return " / ".join(normalize(seg) for seg in segments)
            # If segments dont contain commas (such as after the w/ removal) process without comma validation
            else:
                return " / ".join(normalize(seg) for seg in segments)


    # splitting by commas
    parts = [p.strip() for p in creator.split(",") if p.strip()]

    # drop pure life-date segments (e.g. "1850-1910", "1975-") so a trailing
    # date isn't mistaken for a middle name below
    date_part_pattern = r"^\d{4}-?\d{0,4}\.?$"
    parts = [p for p in parts if not re.match(date_part_pattern, p)]

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

    # single-letter initials ("T." in "T. S. Eliot" / "T.S. Eliot" /
    # "T.S Eliot") never match the 2-letter rule.
    #drop the period but keep a space to get "t s"
    creator = re.sub(r"\b([a-zA-Z])\.", r"\1 ", creator)

    # consecutive whitespaces
    creator = re.sub(r"\s+", " ", creator).strip()

    creator = re.sub(r"\bemperor of\s+\S+", "", creator)

    # re-attach suffix
    if suffix:
        creator = f"{creator} {suffix}"

    #t_duration = time.perf_counter() - t_start   
    #print(f"Time for normalize function: {t_duration:.6f} seconds")
    return creator

def name_tokens(name: str):
    #t_start = time.perf_counter()

    """
    #Rough first/last-name tokenization, uses the same comma-flip and
    suffix/date stripping logic as normalize(), returning token list
    instead of a joined string
    """
    if not name:
        return []

    s = name.lower().strip("-").strip()
    # drop elements in parenthesis
    s = re.sub(r"\(.*?\)", "", s) 

    parts = [p.strip() for p in s.split(",") if p.strip()]

    # drop pure life-date segments so they don't block the reversal below
    date_part_pattern = r"^\d{4}-?\d{0,4}\.?$"
    parts = [p for p in parts if not re.match(date_part_pattern, p)]

    suffix_pattern = r"(?:^|\s|,|\.)(jr\.?|sr\.?|ii|iii|iv|v|vi)\b"
    cleaned_parts = []
    for part in parts:
        if not re.match(suffix_pattern, part):
            cleaned_parts.append(part)

    if len(cleaned_parts) == 2:
        # converts last, first middle format to first middle last
        cleaned_parts.reverse()  
    s = " ".join(cleaned_parts)

    # drop life dates (matches 4 numbers)
    s = re.sub(r"\b\d{4}-?\b", "", s)
    # de-abbreviate trailing periods (matches last two letters replaces without)         
    s = re.sub(r"([a-zA-Z]{2})\.", r"\1", s)  
    #  remove periods or commas
    s = re.sub(r"[.,]", " ", s)
    #replace consecutive whitespaces with singular 
    s = re.sub(r"\s+", " ", s).strip()

    #t_duration = time.perf_counter() - t_start   
    #print(f"Time for name_tokens function: {t_duration:.6f} seconds")
    return [t for t in s.split(" ") if t]


def first_last_key(name: str):
    """(first_token, last_token) used to find same-person candidates that
    normalize() didn't already merge (e.g. missing/extra middle name)."""
    # Multi-creator norms look like "first1 last1 / first2 last2" two people, not one, so
    # never allow into middle name matching. Shouldnt break in cases
    # #where Kaye/Kantrowitz, Melanie as no middle name anyway but to watch out for
    if " / " in name:
        return None
    tokens = name_tokens(name)
    if len(tokens) < 2:
        return None
    return (tokens[0], tokens[-1])


def has_middle_name(name: str) -> bool:
    return len(name_tokens(name)) > 2


def extract_date_signature(name: str):
    """Pull out the raw 4-digit year token(s) attached to a name, e.g.
    "1947-2006" or "2000-" (still living)."""
    if not name:
        return None
    matches = re.findall(r"\b\d{4}-?\b", name)
    if not matches:
        return None
    return "".join(matches)


def normalize_title(title: str) -> str:
    # Initialize string, convert to lowercase, and strip whitespace
    t = str(title or "").lower().strip()
    
    # Fold accents to plain ASCII (normalize NFD and strip combining marks)
    t = unicodedata.normalize('NFD', t)
    t = "".join(char for char in t if not unicodedata.combining(char))
    
    # Drop "/ by Author" segments
    t = t.split('/')[0]
    
    # keep the English parallel title in bilingual catalog records (" = ")
    if " = " in t:
        t = t.split(" = ")[-1]
        
    # expand ampersands
    t = t.replace("&", "and")
    
    # drop content inside parentheses and brackets
    t = re.sub(r"\([^)]*\)", "", t)
    t = re.sub(r"\[[^\]]*\]", "", t)
    
    # repeatedly strip trailing noise segments separated by colons or semicolons
    noise_pattern = re.compile(
        r"(book|bk|series|volume|vol|part|edition|unabridged|abridged|screenplay|"
        r"read by|narrated|illustrated|deluxe|anniversary|collector|special|movie|"
        r"film|adapted|reissue|boxe?d? ?set|complete|novel|novella|memoir|thriller|"
        r"mystery|story|stories|tale|tales|romance|biography|autobiography|poems|"
        r"essays|playscript|\bscript\b|\bproduction|\bserie|\blivre|\btome|\blibro|"
        r"\btomo|\bedicion)", 
        re.IGNORECASE
    )
    or_pattern = re.compile(r"[:;]\s*or[\s,]", re.IGNORECASE)
    
    while True:
        prev = t
        # find the last segment starting with : or ;
        match = re.search(r"[:;]\s*[^:;]*$", t)
        if match:
            seg = match.group(0)
            if noise_pattern.search(seg) or or_pattern.search(seg):
                # Replace the trailing segment with empty string
                t = t[:match.start()]
        if t == prev:
            break

    # drop standalone format/edition keywords
    t = re.sub(r"\b(unabridged|abridged|audiobook|e-?book|large print|compact disc|sound recording)\b", "", t)
    
    # drop articles
    t = re.sub(r"\b(the|a|an)\b", "", t)
    
    # remove apostrophes to merge contractions
    t = t.replace("'", "")
    
    # strip all remaining non-alphanumeric characters (including spaces/hyphens)
    t = re.sub(r"[^a-z0-9]+", "", t)
    
    return t



class UnionFind:
    def __init__(self, items):
        self.parent = {item: item for item in items}

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def main():
    start_time = perf_counter()

    con = duckdb.connect()
    configure_duckdb_for_r2(con)

    display_totals, display_titles = load_agg_cache()

    if not display_totals:
        # If no cache yet, this one run has to pay the full cost
        # of scanning every monthly file on R2. Every
        # run after this only scans whatever's new.
        print("No cached aggregate found: doing a one-time full historical")
        new_keys, all_keys = list_new_keys_from_r2(all_keys_too=True)
        rows = con.execute(
            """
            SELECT Creator AS name, Title AS title, sum(Checkouts) AS total
            FROM read_csv_auto(?, ignore_errors=true)
            WHERE Creator IS NOT NULL AND
            Creator <> 'NA'
            GROUP BY Creator, Title
            """,
            [[f"s3://{R2_BUCKET}/{k}" for k in all_keys]],
        ).fetchall()
        new_files = all_keys
    else:
        print("Checking R2 bucket for new monthly files ...")
        new_files = list_new_keys_from_r2()
        rows = query_rows_from_r2(con, new_files)

    # Fold the new rows into the (possibly cached) totals/titles. Several
    # raw rows can share one display name. Add up their checkouts and
    # collect their titles per display name.
    for name, title, total in rows:
        d = name
        display_totals[d] = display_totals.get(d, 0) + int(total)
        if title:
            display_titles.setdefault(d, set()).add(normalize_title(title))

    # Persist immediately so the next run's delta is correct even if
    # clustering below throws. This mirrors _mark_processed()'s
    # only-after-success semantics for PROCESSED_FILES_CSV, but the
    # aggregate itself is safe to save early since it's purely additive.
    save_agg_cache(display_totals, display_titles)

    # Pass 1: group raw spellings by (normalized name, year signature)
    # The canonical name is now the normalized name itself, entities that share a normalized
    # name but carry different year signatures are kept apart here; pass
    # 2 below is the only place they can be reunited, and only on title
    # evidence.
    groups = {}  # (norm, date_sig) -> [raw display names]
    for display in display_totals:
        norm = normalize(display)
        date_sig = extract_date_signature(display)
        groups.setdefault((norm, date_sig), []).append(display)

    entities = {}  # (norm, date_sig) -> {checkouts, titles, canonical, norm, date}
    raw_to_key = {}
    for key, raws in groups.items():
        norm, date_sig = key
        checkouts = sum(display_totals[r] for r in raws)
        titles = set()
        for r in raws:
            titles |= display_titles.get(r, set())
            raw_to_key[r] = key
        # Fold the year signature into the canonical text so a dated entity
        # stays visibly distinct from any undated one until/unless pass 2
        # below finds title evidence that they're the same person.
        canonical = f"{norm}, {date_sig}" if date_sig else norm
        entities[key] = {
            "checkouts": checkouts,
            "titles": titles,
            "canonical": canonical,
            "norm": norm,
            "date": date_sig,
        }

    # Pass 2: reunite a dated entity with an undated one of the same
    # normalized name, but only when they share a title 
    uf = UnionFind(entities.keys())

    by_norm = {}
    for key, info in entities.items():
        by_norm.setdefault(info["norm"], []).append(key)

    for norm, keys in by_norm.items():
        if len(keys) < 2:
            continue
        undated = [k for k in keys if k[1] is None]
        dated = [k for k in keys if k[1] is not None]
        if not undated or not dated:
            continue
        u = undated[0]  # only one (norm, None) key can exist per norm
        # If several different dated entities share this normalized name
        # only merge the undated spelling into whichever one it actually shares a title
        # with
        best, best_overlap = None, 0
        for d in dated:
            overlap = len(entities[u]["titles"] & entities[d]["titles"])
            if overlap > best_overlap:
                best, best_overlap = d, overlap
        if best is not None:
            uf.union(u, best)

    components = {}
    for key in entities:
        components.setdefault(uf.find(key), []).append(key)

    key_to_stage1 = {}   # (norm, date) key -> stage-1 canonical text
    stage1_info = {}     # stage-1 canonical text -> {checkouts, titles, norm, date}
    for members in components.values():
        dated_members = [m for m in members if entities[m]["date"]]
        pool = dated_members if dated_members else members
        best = max(pool, key=lambda m: entities[m]["checkouts"])
        canonical = entities[best]["canonical"]
        checkouts = sum(entities[m]["checkouts"] for m in members)
        titles = set()
        for m in members:
            titles |= entities[m]["titles"]
            key_to_stage1[m] = canonical
        stage1_info[canonical] = {
            "checkouts": checkouts,
            "titles": titles,
            "norm": entities[best]["norm"],
            "date": entities[best]["date"],
        }

    #  Pass 3: catch spellings that differ only by a missing/extra 
    # middle name/initial (e.g. "Octavia Butler" vs "Octavia E. Butler").
    buckets = {}
    for canonical, info in stage1_info.items():
        key = first_last_key(info["norm"])
        if key is not None:
            buckets.setdefault(key, []).append(canonical)

    uf2 = UnionFind(stage1_info.keys())
    for members in buckets.values():
        if len(members) < 2:
            continue
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                a, b = members[i], members[j]
                if stage1_info[a]["titles"] & stage1_info[b]["titles"]:
                    uf2.union(a, b)

    # Build the final canonical spelling for each component: prefer a
    # candidate with a middle name (more specific), then among those prefer
    # one that carries a year signature (more specific still), then break
    # any remaining tie by checkouts.
    components2 = {}
    for canonical in stage1_info:
        components2.setdefault(uf2.find(canonical), []).append(canonical)

    stage1_to_final = {}
    for members in components2.values():
        with_middle = [m for m in members if has_middle_name(stage1_info[m]["norm"])]
        candidates = with_middle if with_middle else members
        with_date = [m for m in candidates if stage1_info[m]["date"]]
        if with_date:
            candidates = with_date
        final_canonical = max(candidates, key=lambda m: stage1_info[m]["checkouts"])
        for m in members:
            stage1_to_final[m] = final_canonical

    # Raw -> final canonical map 
    author_map = {}
    for raw, key in raw_to_key.items():
        stage1_canonical = key_to_stage1[key]
        final_canonical = stage1_to_final[stage1_canonical]
        if raw != final_canonical:
            author_map[raw] = final_canonical

    OUT_MAP.write_text(json.dumps(author_map, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f"Wrote {len(author_map):,} name -> canonical mappings to {OUT_MAP}")
    print("Now run:  python3 data-prep/build_data.py")
    end_time = perf_counter()
    elapsed_time = end_time - start_time
    print(f"Elapsed time: {elapsed_time:.4f} seconds")

    if new_files:
        _mark_processed(new_files)
        print(f"  recorded {len(new_files)} newly-processed file(s) in {PROCESSED_FILES_CSV.name}")


if __name__ == "__main__":
    main()