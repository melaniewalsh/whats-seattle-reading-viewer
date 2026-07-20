import csv
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path
from time import perf_counter
from urllib.parse import urlparse
import unicodedata

try:
    import duckdb
except ImportError:
    duckdb = None
try:
    import boto3
except ImportError:  # pragma: no cover - boto3 is only needed to LIST keys
    boto3 = None
from dotenv import load_dotenv


PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_PREP_DIR = Path(__file__).resolve().parent

# Authority files 
AUTHORITY_SEARCH_DIRS = [
    DATA_PREP_DIR,
    Path(""),
    PROJECT_DIR / "upload",
]

def _find_authority_file(filename: str) -> Path:
    """Find an authority file in any of the search dirs. Returns the first
    match, or the default path (DATA_PREP_DIR / filename) if not found."""
    for d in AUTHORITY_SEARCH_DIRS:
        candidate = d / filename
        if candidate.exists():
            return candidate
    return DATA_PREP_DIR / filename

LCSH_CSV = _find_authority_file("subjects.madsrdf_headings.csv")
LCSHAC_CSV = _find_authority_file("LCSHAC.madsrdf_headings.csv")
GENREFORM_CSV = _find_authority_file("genreForms.madsrdf_headings.csv")
# LC/NACO Name Authority File extract. Same 3-column shape as the LCSH/
# LCSHAC/GenreForm CSVs above: uri, heading, type (e.g. PersonalName,
# CorporateName). This is what lets pieces like "Poirot Hercule Fictitious
# character Fiction" resolve -- fictitious characters, real people, and
# corporate bodies are cataloged as NAME authority records (not subject
# headings), so they never lived in subjects.madsrdf_headings.csv. Adjust
# the filename below if your extract is named differently.
NAMES_CSV = _find_authority_file("names.madsrdf_headings.csv")
FAST_CSV = _find_authority_file("fast_extracted.csv")
BISAC_TXT = _find_authority_file("bisacodesnames.txt")
GSAFD_JSON = _find_authority_file("gsafd.json")
OVERDRIVE_CSV = _find_authority_file("Known_Overdrive_Subjects.csv")
# Directory of single-record LC MADS/RDF JSON-LD dumps for headings that
# have since been deprecated (e.g. id.loc.gov's ".json" export for a
# DeprecatedAuthority record). These terms no longer appear in the base
# LCSH/GenreForm/etc. extracts above, but old SPL checkout rows can still
# carry the old wording, so they need to be matched separately. Drop as
# many *.json files here as needed -- every file in the directory is read.
DEPRECATED_GENREFORM_DIR = _find_authority_file("video_recordings_for_the_hearing_impaired-deprecated.json")

# Local fallback for development without R2 access
LOCAL_CSV_FALLBACK = PROJECT_DIR / "data" / "raw" / "spl-monthly-checkouts_2005-2025.csv"

# Author name-variant map produced by cluster_authors.py. If present, we fold
# raw Creator names through it the same way build_data.py does, so the
# (author, title) pairs stored in subject_map.json match clean.author in
# build_data.py and the downstream JOIN is rigorous. Without this file the
# raw Creator string is used as-is.
AUTHOR_MAP_PATH = DATA_PREP_DIR / "author_map.json"

# Outputs
OUT_MAP = DATA_PREP_DIR / "subject_map.json"
OUT_SUMMARY = DATA_PREP_DIR / "subject_match_summary.json"
PROCESSED_FILES_CSV = DATA_PREP_DIR / "processed_files_subjects.csv"

# The persisted (Author, Title, Subjects, MaterialTypes) aggregate. Same role
# as author_title_agg.json in cluster_authors.py: lets a delta run skip
# re-scanning old monthly files.
SUBJECT_AGG_CACHE = DATA_PREP_DIR / "subject_title_agg.json"


# Only include rows whose MaterialType matches one of these (case-insensitive).
# A row's MaterialType may be a comma-separated list like "ER, SOUNDDISC"s
# the row is INCLUDED if any piece is in INCLUDE and NO piece is in EXCLUDE.
MATERIALTYPE_INCLUDE = {
    "book",       # standard book
    "regprint",   # regular print book
    "largeprint", # large print book
    "er",         # Electronic Resource (ebook)
    "audiobook",  
}
MATERIALTYPE_EXCLUDE = {
    "videodisc",  # DVDs
    "visual",     # visual materials
    "atlas",      # atlases
    "map",        # maps
    "mixed",      # mixed materials
    "music",      # music (explicitly tagged)
    "unspecified",# unknown
    "sounddisc",
    "soundrec",
}


load_dotenv(dotenv_path=str(DATA_PREP_DIR / "access.env"))

R2_ENDPOINT_URL = os.environ.get(
    "R2_ENDPOINT_URL",
    "https://dd55a988a4598a3425259692fe6f7ba1.r2.cloudflarestorage.com/",
)
R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY", "")
R2_BUCKET = os.environ.get("R2_BUCKET", "spl-checkouts")
R2_PREFIX = os.environ.get("R2_PREFIX", "monthly/")



APOSTROPHE = re.compile(r"['\u2019\u2018`]")
NON_ALNUM = re.compile(r"[^\w\s]")
MULTI_WS = re.compile(r"\s+")

#{"na", "NA", "N/A", "n/a", "none", "unknown", ""}

SUBJECT_PLACEHOLDER_VALUES = re.compile(
    r"\b(na|NA|N\/A|n\/a|none|unknown)\b"
)


def strip_diacritics(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", s)
        if not unicodedata.combining(c)
    )

def normalize(text: str) -> str:
    """Aggressive normalization matching the offline pipeline:
       lowercase -> strip apostrophes -> replace non-alphanumeric with space
       -> collapse whitespace.

    Stripping apostrophes (rather than replacing with space) is required so
    that SPL's apostrophe-stripped forms ('Childrens audiobooks') match LCSH's
    original forms ("Children's audiobooks").
    """

    if not text:
        return ""
    s = text.lower()
    s = strip_diacritics(s)          # NEW: fold ō -> o, é -> e, etc.
    s = APOSTROPHE.sub("", s)
    s = NON_ALNUM.sub(" ", s)
    s = MULTI_WS.sub(" ", s)
    s = SUBJECT_PLACEHOLDER_VALUES.sub("", s) 
    return s.strip()



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
    """The set of R2 keys already folded into a previous subject_map.json."""
    if not PROCESSED_FILES_CSV.exists():
        return set()
    with PROCESSED_FILES_CSV.open(newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    if not rows:
        return set()
    body = rows[1:] if rows[0] == ["filename"] else rows
    return {row[0] for row in body if row}


def _mark_processed(keys):
    """Append newly-ingested R2 keys to PROCESSED_FILES_CSV.

    Only ever called after a full successful rebuild. If the matching or
    map write raises partway through, these keys are never written here,
    so the next run treats them as new again and retries them instead of
    silently leaving them out of the map forever.
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
    """List every object under R2_PREFIX in the R2 bucket and diff it against
    PROCESSED_FILES_CSV. Duckdb reads these keys straight off R2 later via
    s3:// paths.

    Returns new_keys, or (new_keys, all_keys) if all_keys_too=True (used on
    a cold start with no aggregate cache, where every key needs scanning).
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

    all_keys = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=R2_BUCKET, Prefix=R2_PREFIX):
        for obj in page.get("Contents", []):
            all_keys.append(obj["Key"])

    new_keys = [k for k in all_keys if k not in already_processed]
    print(f"  {len(all_keys):,} files in bucket, {len(new_keys):,} not yet processed")
    return (new_keys, all_keys) if all_keys_too else new_keys


def query_rows_from_r2(con, keys):
    """Aggregate (Author, Title, Subjects, MaterialType) for exactly these R2
    keys, read directly as s3:// paths. Nothing touches local disk.

    We need the MaterialType so we can filter to book/ebook/audiobook at match
    time, and the Author (Creator) so subject_map.json can store (author,
    title) pairs that join rigorously against build_data.py's clean table.
    A single (Author, Title, Subjects) triple may appear with multiple
    MaterialTypes across different monthly files, so we GROUP BY all four.
    """
    if not keys:
        return []
    s3_paths = [f"s3://{R2_BUCKET}/{k}" for k in keys]
    return con.execute(
        """
        SELECT Creator AS author, Title AS title, Subjects AS subjects, MaterialType AS materialtype
        FROM read_csv_auto(?, ignore_errors=true)
        WHERE Title IS NOT NULL AND Creator IS NOT NULL
        GROUP BY Creator, Title, Subjects, MaterialType
        """,
        [s3_paths],
    ).fetchall()


def query_rows_from_local(con, path):
    """Fallback: read from a local CSV when R2 is not configured."""
    if not path.exists():
        return []
    print(f"  Reading local CSV: {path}")
    return con.execute(
        """
        SELECT Creator AS author, Title AS title, Subjects AS subjects, MaterialType AS materialtype
        FROM read_csv_auto(?, ignore_errors=true)
        WHERE Title IS NOT NULL AND Creator IS NOT NULL
        GROUP BY Creator, Title, Subjects, MaterialType
        """,
        [str(path)],
    ).fetchall()




# Cache version, bump when the cache shape changes to invalidate old caches.
# v1: {title: subjects_string}
# v2: {title: {subjects, materialtypes}}
# v3: {"author\ttitle": {subjects, materialtypes}}  -- keyed by (author, title)
#      so subject_map.json can store rigorous (author, title) pairs that join
#      against build_data.py's clean table (which applies the same author_map
#      canonicalization we do).
AGG_CACHE_VERSION = 3


def _load_author_map():
    """Read data-prep/author_map.json if it exists. Returns {raw: canonical}.

    Mirrors build_data.py's author-folding step: when this map is present,
    we fold raw Creator names through it before keying the aggregate cache,
    so the (author, title) pairs in subject_map.json match clean.author in
    build_data.py and the downstream JOIN is exact. Without this file the
    raw Creator string is used as-is.
    """
    if not AUTHOR_MAP_PATH.exists():
        return {}
    try:
        return json.loads(AUTHOR_MAP_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  WARN: could not parse {AUTHOR_MAP_PATH}: {e}; using raw Creator names")
        return {}


def _cache_key(author, title):
    """Build the aggregate-cache key for an (author, title) pair.

    JSON object keys must be strings, so we join with a TAB character (which
    neither author nor title strings in SPL data are expected to contain).
    The key is reversible: split on the first tab to get (author, title) back.
    """
    return f"{author}\t{title}"


def _split_cache_key(key):
    """Inverse of _cache_key: return (author, title)."""
    parts = key.split("\t", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return "", parts[0] if parts else ""


def load_agg_cache():
    """Load the persisted {"author\ttitle": {subjects, materialtypes}}
    aggregate from the last successful run, if any. Empty dict means 'cold
    start' (or first ever run) — main() falls back to a one-time full
    historical scan in that case.

    Cache shape (v3):
        {
          "<author>\t<title>": {
            "subjects": "<subjects string>",
            "materialtypes": ["BOOK", "SOUNDDISC", ...]  # sorted unique
          },
          ...
        }

    v1 was {title: subjects_string}; v2 was {title: {subjects, materialtypes}}.
    Both are discarded if detected so the rebuild picks up (author, title)
    pairs instead.
    """
    if not SUBJECT_AGG_CACHE.exists():
        return {}
    raw = json.loads(SUBJECT_AGG_CACHE.read_text(encoding="utf-8"))
    if not raw:
        return {}
    sample_val = next(iter(raw.values()))
    # v1: values are bare strings
    if isinstance(sample_val, str):
        print(f"  [cache] Detected v1 cache (string values); discarding and rescanning.")
        return {}
    # v2: keys are bare titles (no tab separator)
    sample_key = next(iter(raw.keys()))
    if isinstance(sample_val, dict) and "\t" not in sample_key:
        print(f"  [cache] Detected v2 cache (title-only keys); discarding and rescanning "
              f"for (author, title) pairs.")
        return {}
    return raw


def save_agg_cache(title_to_info):
    """Persist the aggregate so the next run's delta is correct even if
    matching below throws. The aggregate is purely additive (new months
    only ever add titles/materialtypes; existing titles' subjects don't
    change), so it's safe to save early."""
    SUBJECT_AGG_CACHE.parent.mkdir(parents=True, exist_ok=True)
    SUBJECT_AGG_CACHE.write_text(
        json.dumps(title_to_info, ensure_ascii=False),
        encoding="utf-8",
    )


def materialtype_allowed(materialtype_str):
    """Check if a MaterialType string passes the book/ebook/audiobook filter.

    The MaterialType may be a comma-separated list like "ER, SOUNDDISC".
    Split on comma, normalize (lowercase, strip), then:
      - INCLUDE if any piece is in MATERIALTYPE_INCLUDE
      - AND no piece is in MATERIALTYPE_EXCLUDE

    Case-insensitive throughout.
    """
    if not materialtype_str:
        return False
    pieces = [p.strip().lower() for p in str(materialtype_str).split(",") if p.strip()]
    if not pieces:
        return False
    has_include = any(p in MATERIALTYPE_INCLUDE for p in pieces)
    has_exclude = any(p in MATERIALTYPE_EXCLUDE for p in pieces)
    return has_include and not has_exclude


#Auth map construction

AUTHORITIES_LIST = [
    "SHM H 180: Assigning and Constructing Subject Headings (sec. R, S) — https://www.loc.gov/aba/publications/FreeSHM/H0180.pdf",
    "SHM H 1075: Subdivisions (four types, standard orders)",
    "SHM Module 6-1: Subdivision overview (training)",
    "subjects.madsrdf_headings.csv — LCSH machine-readable authority file (ComplexSubject entries as subdivision attestation source)",
    "names.madsrdf_headings.csv — LC/NACO Name Authority File (LCNAF) extract; personal/corporate/family name headings, including fictitious-character name headings (e.g. 'Poirot, Hercule (Fictitious character)'), used as an additional main-heading pool per SHM H 1075 (a subdivided heading may have a name, not just a topic, as its main element).",
]


def _read_csv_source(path, hidx, tidx):
    """Yield (heading, type_val, uri) triples from a LCSH/LCSHAC/GenreForm/
    LCNAF/FAST CSV. Column 0 is the URI (e.g. http://id.loc.gov/authorities/
    subjects/sh85093415), column `hidx` is the heading, column `tidx` is the
    type (PersonalName / CorporateName / Topic / GenreForm / ...).
    """
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        next(reader, None)
        for row in reader:
            if len(row) <= max(hidx, tidx if tidx is not None else 0):
                continue
            heading = row[hidx]
            if not heading or not heading.strip():
                continue
            type_val = row[tidx] if tidx is not None and tidx < len(row) else ""
            uri = row[0].strip() if row[0] else None
            yield heading, type_val, uri


def _read_bisac_source(path):
    """Yield (name, 'BISAC', None) triples -- BISAC codes are alphanumeric
    (e.g. 'FIC027000') but have no canonical URL, so uri is None.
    """
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.rstrip("\n").rstrip("\r")
            if not line.strip():
                continue
            m = re.search(r"\s{2,}", line)
            if not m:
                continue
            name = line[m.end():].strip()
            if not name:
                continue
            yield name, "BISAC", None
            # Top-level BISAC entries are coded "CATEGORY / General" (e.g.
            # "MEDICAL / General"). SPL's own top-level pieces (e.g. "Medical")
            # never carry the "/ General" suffix, so also register the bare
            # category form to catch those direct-lookup matches.
            m2 = re.match(r"^(.*?)\s*/\s*General$", name, re.IGNORECASE)
            if m2:
                bare = m2.group(1).strip()
                if bare:
                    yield bare, "BISAC", None


def _read_gsafd_source(path):
    """Parse the GSAFD (Guidelines on Subject Access to Individual Works of
    Fiction, Drama, Etc.) authority file, a JSON array of MARC-in-JSON
    authority records.

    Each record's 155 field is the authorized genre/form heading (e.g.
    "Erotic fiction"). 455 fields are "see from" cross-references -- lexical
    variants that real-world data (e.g. SPL/OverDrive subject strings) is
    likely to use instead of the authorized term (e.g. "Adult fiction",
    "Erotic novels", "Erotic stories" -> "Erotic fiction"). We yield both the
    canonical heading and every 455 variant, each paired with the *canonical*
    text, so a checkout record tagged with the variant term still resolves
    to the authorized GSAFD heading.

    555 fields are "see also" related-term references (e.g. "Love stories"
    related to "Erotic fiction"). These point to a genuinely different
    heading, not a synonym, so they are intentionally NOT yielded here --
    aliasing them would incorrectly merge distinct genres.

    Yields: (text, type_val, canonical_heading, uri) 4-tuples. `uri` is the
    record's 001 field (control number) formatted as an LC authorities URL
    when present, else None. Variants inherit the canonical record's URI
    so a checkout tagged with the variant still links to the same record.
    """
    records = json.loads(Path(path).read_text(encoding="utf-8"))
    for rec in records:
        canonical = None
        variants = []
        uri = None
        for field in rec.get("fields", []):
            if "155" in field:
                subfields = field["155"].get("subfields", [])
                parts = [sf["a"] for sf in subfields if "a" in sf]
                if parts and canonical is None:
                    canonical = parts[0]
            elif "455" in field:
                subfields = field["455"].get("subfields", [])
                parts = [sf["a"] for sf in subfields if "a" in sf]
                if parts:
                    variants.append(parts[0])
            elif "001" in field:
                # MARC 001 = control number. For GSAFD these are LC control
                # numbers; format as an LC authorities URL so the badge links
                # somewhere useful. If the value already looks like a URL, keep it.
                ctrl = str(field["001"]).strip()
                if ctrl and not ctrl.startswith("http"):
                    uri = f"http://id.loc.gov/authorities/subjects/{ctrl}"
                else:
                    uri = ctrl or None
        if not canonical:
            continue
        yield canonical, "GSAFD", canonical, uri
        for v in variants:
            if v != canonical:
                yield v, "GSAFD", canonical, uri


def _read_deprecated_record(path):
    """Parse a single LC MADS/RDF JSON-LD dump for one deprecated authority
    record -- the shape id.loc.gov returns for a DeprecatedAuthority's
    ".json" endpoint (a flat array containing the deprecated record itself,
    its variantLabel(s), its admin-metadata blank nodes, and the record it
    points to via useInstead).

    We want old SPL checkout rows tagged with the now-retired wording to
    still resolve to whatever term replaced it, so this yields the
    deprecated variant paired with the *current* authoritative label from
    the useInstead target -- same (text, type, canonical) shape as
    _read_gsafd_source, so it's handled identically downstream.

    Yields: (deprecated_text, type_val, canonical_text, uri) 4-tuples. `uri`
    is the useInstead target's @id (the current authority record's URI), so
    the badge links to the replacement record, not the deleted one.
    """
    records = json.loads(Path(path).read_text(encoding="utf-8"))
    by_id = {rec["@id"]: rec for rec in records if "@id" in rec}

    n_deprecated_seen = 0
    n_yielded = 0
    for rec in records:
        rec_id = rec.get("@id", "<no @id>")
        types = rec.get("@type", [])
        if "http://www.loc.gov/mads/rdf/v1#DeprecatedAuthority" not in types:
            continue
        n_deprecated_seen += 1
        use_instead = rec.get("http://www.loc.gov/mads/rdf/v1#useInstead")
        variants = rec.get("http://www.loc.gov/mads/rdf/v1#variantLabel", [])
        if not use_instead:
            print(f"  WARN: deprecated record skipped (missing useInstead): "
                  f"{rec_id} -- file: {path}")
            continue
        if not variants:
            print(f"  WARN: deprecated record skipped (no variantLabel): "
                  f"{rec_id} -- file: {path}")
            continue
        target_id = use_instead[0].get("@id")
        target = by_id.get(target_id)
        if not target:
            print(f"  WARN: deprecated record skipped (useInstead target not in same file): "
                  f"{rec_id} -> {target_id} -- file: {path}")
            continue
        canon_vals = (
            target.get("http://www.loc.gov/mads/rdf/v1#authoritativeLabel")
            or target.get("http://www.w3.org/2004/02/skos/core#prefLabel")
        )
        if not canon_vals:
            print(f"  WARN: deprecated record skipped (useInstead target has no label): "
                  f"{rec_id} -> {target_id} -- file: {path}")
            continue
        canonical = canon_vals[0].get("@value")
        if not canonical:
            print(f"  WARN: deprecated record skipped (useInstead target label has no @value): "
                  f"{rec_id} -> {target_id} -- file: {path}")
            continue
        type_val = "GenreForm" if any("GenreForm" in t for t in types) else "LCSH"
        # URI is the REPLACEMENT record's @id (the current authority), not the
        # deprecated record's @id -- linking to a deleted record is useless.
        uri = target_id
        for v in variants:
            text = v.get("@value")
            if text and text != canonical:
                n_yielded += 1
                yield text, type_val, canonical, uri
    if n_deprecated_seen == 0:
        # No DeprecatedAuthority records at all in this file -- probably
        # someone pointed this at a non-deprecated id.loc.gov .json endpoint.
        # This is the exact shape of bug that produced the original
        # 'Deprecated: 11' garbage: a non-deprecated file silently yielding
        # 0 here meant nobody noticed the dispatcher was misrouting it.
        print(f"  WARN: no DeprecatedAuthority records found in {path} -- "
              f"did you mean to download the deprecated variant?")
    else:
        print(f"  deprecated: {n_deprecated_seen} DeprecatedAuthority record(s) found, "
              f"{n_yielded} variant label(s) yielded -- file: {path}")


def _read_deprecated_dir_source(dir_path):
    """Chain _read_deprecated_record() over every *.json file in dir_path.

    Also accepts a single *.json file path -- the original implementation
    silently returned when passed a file (because `Path.is_dir()` was False),
    which meant anyone who pointed DEPRECATED_GENREFORM_DIR straight at a
    JSON dump (instead of a directory of dumps) got 0 deprecated entries
    with no warning. This makes both shapes work.
    """
    p = Path(dir_path)
    if p.is_file() and p.suffix.lower() == ".json":
        yield from _read_deprecated_record(p)
        return
    if p.is_dir():
        for f in sorted(p.glob("*.json")):
            yield from _read_deprecated_record(f)


def _read_overdrive_source(path):
    """Read the 'Known OverDrive Subjects' CSV: two columns, subject name
    and an OverDrive collection/search URL, no header row. We yield the
    subject name plus the URL (column 1) as the URI when present, so the
    Overdrive badge can link to the collection page.
    Yields: (name, 'Overdrive', uri) triples.
    """
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        for row in reader:
            if not row or not row[0].strip():
                continue
            name = row[0].strip()
            uri = row[1].strip() if len(row) > 1 and row[1].strip() else None
            yield name, "Overdrive", uri


def build_authority_map():
    """Build the initial subject_map.json from the 9 authority sources.

    Collects ALL authorities that attest a given normalized heading -- no
    silent first-match-wins dedup. Each entry ends up with:
        - origin  : the FIRST (highest-priority) source -- kept for backward
                    compatibility with the existing Pass 2/3 overwrite logic
                    and any downstream code that still reads a single origin.
        - origins : list of EVERY source that attests this heading, in the
                    order they were processed (priority order, see SOURCES).
        - uris    : {origin: uri} dict -- the authority URI for each source
                    that provided one (some sources, e.g. BISAC, have no URL
                    and are simply absent from the dict).
        - type    : the type_val from the first source that provided one.
        - heading : the canonical display heading (for GSAFD/Deprecated this
                    is the canonical term; for everything else it's the
                    heading text itself from the first attesting source).

    Priority order (just controls which source is listed first / becomes the
    `origin` field; nothing is dropped):
        LCSH > LCSHAC > GenreForm > LCNAF > GSAFD > Deprecated
        > FAST > BISAC > Overdrive

    GSAFD, Deprecated, FAST, BISAC, and Overdrive entries may still be
    replaced later by Pass 2/3 subdivision-chain reconstructions --
    that's intentional: a fully-reconstructed LCSH ComplexSubject string
    beats a partial match against these auxiliary vocabularies. When that
    happens the new origin is APPENDED to `origins` (not substituted), so
    the user can still see every vocabulary that vouched for the heading.
    """
    SOURCES = [
        ("LCSH",      LCSH_CSV,      1, 2, "csv"),
        ("LCSHAC",    LCSHAC_CSV,    1, 2, "csv"),
        ("GenreForm", GENREFORM_CSV, 1, 2, "csv"),
        ("LCNAF",     NAMES_CSV,     1, 2, "csv"),
        ("GSAFD",     GSAFD_JSON,    None, None, "gsafd"),
        ("Deprecated", DEPRECATED_GENREFORM_DIR, None, None, "deprecated"),
        ("FAST",      FAST_CSV,      1, 2, "csv"),
        ("BISAC",     BISAC_TXT,     1, None, "bisac"),
        ("Overdrive", OVERDRIVE_CSV, None, None, "overdrive"),
    ]
    out = {}
    for origin, path, hidx, tidx, kind in SOURCES:
        if not path.exists():
            print(f"  WARN: missing authority file: {path}")
            continue
        if kind == "csv":
            iterator = _read_csv_source(path, hidx, tidx)
        elif kind == "bisac":
            iterator = _read_bisac_source(path)
        elif kind == "gsafd":
            iterator = _read_gsafd_source(path)
        elif kind == "deprecated":
            iterator = _read_deprecated_dir_source(path)
        else:  # overdrive
            iterator = _read_overdrive_source(path)
        added = 0
        appended = 0  # how many entries had this origin appended (already existed)
        seen = 0
        for item in iterator:
            seen += 1
            if kind in ("gsafd", "deprecated"):
                # gsafd and deprecated readers yield 4-tuples
                heading, type_val, canonical, uri = item
                # Variants alias to the canonical heading text so a checkout
                # record using the variant phrasing still surfaces the
                # authorized term.
                display_heading = canonical
            else:
                # csv / bisac / overdrive readers yield 3-tuples
                heading, type_val, uri = item
                display_heading = heading
            n = normalize(heading)
            if not n:
                continue
            if n not in out:
                out[n] = {
                    "type": type_val,
                    "origin": origin,                # backward-compat: first source
                    "origins": [origin],             # full list, appended to below
                    "uris": {origin: uri} if uri else {},
                    "heading": display_heading,
                    "titles": [],
                }
                added += 1
            else:
                entry = out[n]
                # Heading already exists from a higher-priority source. Append
                # this origin (and its URI) rather than dropping it silently.
                if origin not in entry["origins"]:
                    entry["origins"].append(origin)
                    appended += 1
                if uri and origin not in entry["uris"]:
                    entry["uris"][origin] = uri
                # Don't overwrite the display heading or type -- the first
                # (highest-priority) source's values are kept, matching the
                # pre-existing single-origin behavior.
        print(f"  {origin:11s} | read {seen:>8d} | added {added:>8d} | "
              f"appended-to-existing {appended:>8d} | from {path.name}")
    return out


# ============================================================================
# SUBDIVISION ATTESTATION INDICES (Phase 2)
# ============================================================================

def build_subdivision_indices():
    """Build the attestation indices needed for pass 2 and pass 3 matching.

    Returns:
      main_attest:     Counter[normalized_main] -> count of ComplexSubject entries
      main_orig:       dict[normalized_main] -> original text (first seen)
      sub_attest:      Counter[normalized_sub] -> count of ComplexSubject entries
      sub_orig:        dict[normalized_sub] -> original text (first seen)
      pair_attest:     Counter[(norm_sub1, norm_sub2)] -> count of adjacent pairs
      norm_to_uri:     dict[normalized_heading] -> uri (for ALL LCSH headings,
                       both standalone and ComplexSubject)
      fast_uri:        dict[normalized_term] -> (uri, term, fast_id)
      lcshac_uri:      dict[normalized_heading] -> (uri, heading)
      lcnaf_uri:       dict[normalized_heading] -> (uri, heading) for LC/NACO
                       Name Authority headings (personal/corporate/family
                       names, including fictitious-character name headings
                       like "Poirot, Hercule (Fictitious character)"). These
                       are folded into main_orig/norm_to_uri below just like
                       LCSH standalone headings, so a name can serve as the
                       "main heading" half of a pass 2/3 match (e.g. name +
                       "Fiction", or name + "Comic books, strips, etc.").
                       lcnaf_uri itself is only kept around so citations can
                       correctly say "name heading" instead of "LCSH heading".
    """
    main_attest = Counter()
    main_orig = {}
    sub_attest = Counter()
    sub_orig = {}
    pair_attest = Counter()
    norm_to_uri = {}
    fast_uri = {}
    lcshac_uri = {}
    lcnaf_uri = {}

    # LCSH, LCSHAC, GenreForm, and LCNAF (names) all share the same CSV shape
    # (uri, heading, type). Name headings essentially never contain "--", so
    # they fall through to the "else" branch below and get registered as
    # standalone main headings, exactly like a standalone LCSH heading.
    for path in [LCSH_CSV, LCSHAC_CSV, GENREFORM_CSV, NAMES_CSV]:
        if not path.exists():
            print(f"  WARN: missing authority file: {path} -- "
                  f"subdivision attestation indices will be incomplete for this source, "
                  f"and Pass 2/3 matching may silently produce 0 hits for its headings")
            continue
        is_lcshac = (path == LCSHAC_CSV)
        is_lcnaf = (path == NAMES_CSV)
        with open(path, newline="", encoding="utf-8") as fh:
            r = csv.reader(fh)
            next(r)
            for row in r:
                if len(row) < 3:
                    continue
                h = row[1]
                uri = row[0]
                if "--" in h:
                    pieces = [p.strip() for p in h.split("--") if p.strip()]
                    if pieces:
                        main = pieces[0]
                        mn = normalize(main)
                        if mn:
                            main_attest[mn] += 1
                            if mn not in main_orig:
                                main_orig[mn] = main
                        subs = pieces[1:]
                        for sub in subs:
                            sn = normalize(sub)
                            if sn:
                                sub_attest[sn] += 1
                                if sn not in sub_orig:
                                    sub_orig[sn] = sub
                        for i in range(len(subs) - 1):
                            s1 = normalize(subs[i])
                            s2 = normalize(subs[i+1])
                            if s1 and s2:
                                pair_attest[(s1, s2)] += 1
                else:
                    n = normalize(h)
                    if n:
                        if n not in main_orig:
                            main_orig[n] = h
                        if n not in norm_to_uri:
                            norm_to_uri[n] = uri
                        if is_lcshac and n not in lcshac_uri:
                            lcshac_uri[n] = (uri, h)
                        if is_lcnaf and n not in lcnaf_uri:
                            lcnaf_uri[n] = (uri, h)

    # FAST URI lookup (for main headings only attested in FAST)
    if FAST_CSV.exists():
        with open(FAST_CSV, newline="", encoding="utf-8") as fh:
            r = csv.reader(fh)
            next(r)
            for row in r:
                if len(row) < 3:
                    continue
                fast_id = row[0].strip()
                term = row[1]
                n = normalize(term)
                if n and fast_id:
                    if fast_id.startswith("fst"):
                        numeric = fast_id[3:]
                        uri = f"http://id.worldcat.org/fast/{numeric}"
                    else:
                        uri = fast_id
                    if n not in fast_uri:
                        fast_uri[n] = (uri, term, fast_id)

    return main_attest, main_orig, sub_attest, sub_orig, pair_attest, norm_to_uri, fast_uri, lcshac_uri, lcnaf_uri


# add reference

def make_citation(main_text, main_norm, main_uri, main_attest,
                  subdivisions, pair_attest_counts, n_way):
    """Build a citation block for a pass-2 or pass-3 match."""
    if n_way == 2:
        recon = (
            "main_heading + subdivision per SHM H 180 sec. S "
            "(Complete subject heading strings with subdivisions) and SHM H 1075 "
            "(four subdivision types: Topical/Geographic/Chronological/Form; "
            "standard orders). Subdivision attestation derived empirically from "
            "LCSH ComplexSubject entries in subjects.madsrdf_headings.csv. "
            "Note: per SHM H 180 sec. D & N.4 (2026-01 revision), LC catalogers "
            "no longer assign form subdivisions in new cataloging (use LCGFT "
            "instead); SPL data reflects pre-migration practice."
        )
    else:
        recon = (
            f"main_heading + {' + '.join(['subdivision'] * (n_way - 1))} "
            f"({n_way}-way split) per SHM H 180 sec. R (explicit multi-level "
            f"subdivision example: 'United States--Civilization--African American "
            f"influences') and sec. S. Subdivision chain attested empirically: "
            f"each subdivision appears in N LCSH ComplexSubject entries, and "
            f"each adjacent pair (sub_i, sub_i+1) is attested in at least 1 "
            f"real LCSH ComplexSubject entry. Pair attestation counts: "
            f"{pair_attest_counts}. This is the strongest empirical evidence "
            f"that the subdivision chain is a valid LCSH construction, not a "
            f"fabricated combination. Note: per SHM H 180 sec. D & N.4 "
            f"(2026-01 revision), LC catalogers no longer assign form "
            f"subdivisions in new cataloging (use LCGFT instead); SPL data "
            f"reflects pre-migration practice."
        )

    return {
        "main_heading": {
            "text": main_text,
            "normalized": main_norm,
            "uri": main_uri,
            "attestation_count": main_attest,
            "attestation_note": (
                "Standalone LCSH heading"
                if main_uri and "worldcat.org/fast" not in str(main_uri)
                and "childrensSubjects" not in str(main_uri)
                and "/authorities/names/" not in str(main_uri)
                else (
                    f"Established FAST heading (OCLC faceted LCSH): {main_text!r} (URI: {main_uri})"
                    if main_uri and "worldcat.org/fast" in str(main_uri)
                    else (
                        f"Established LCSHAC (LC Children's Subject) heading: {main_text!r} (URI: {main_uri})"
                        if main_uri and "childrensSubjects" in str(main_uri)
                        else (
                            f"Established LC/NACO Name Authority (LCNAF) heading: {main_text!r} (URI: {main_uri})"
                            if main_uri and "/authorities/names/" in str(main_uri)
                            else f"Appears as prefix in {main_attest} LCSH ComplexSubject entries"
                        )
                    )
                )
            ),
        },
        "subdivisions": [
            {
                "text": t,
                "normalized": nrm,
                "attestation_count": ac,
                "attestation_note": f"Appears as subdivision in {ac} LCSH ComplexSubject entries",
            }
            for (t, nrm, ac) in subdivisions
        ],
        "pair_attestations": [
            {"subdivision_i": i + 1, "subdivision_j": i + 2, "count": pc}
            for i, pc in enumerate(pair_attest_counts)
        ],
        "reconstruction": recon,
        "authorities": AUTHORITIES_LIST,
    }


def resolve_main_uri(main_norm, smap, norm_to_uri, fast_uri, lcshac_uri, lcnaf_uri=None):
    """Resolve a main heading to (uri, proper_text, attestation_note).
    Tries LCSH -> LCSHAC -> LCNAF (names) -> FAST -> smap (ComplexSubject prefix)."""
    if lcnaf_uri is None:
        lcnaf_uri = {}
    # 1. Standalone LCSH (this also covers LCNAF names, since names are
    #    folded into norm_to_uri/main_orig by build_subdivision_indices --
    #    the lcnaf_uri check just below produces the nicer wording for them)?
    if main_norm in norm_to_uri:
        uri = norm_to_uri[main_norm]
        text = smap.get(main_norm, {}).get("heading", main_norm)
        if main_norm in lcnaf_uri:
            _, term = lcnaf_uri[main_norm]
            return uri, term, f"Established LC/NACO Name Authority (LCNAF) heading: {term!r} (URI: {uri})"
        return uri, text, "Standalone LCSH heading"
    # 2. LCSH ComplexSubject (e.g. "African Americans--Civil rights")?
    if main_norm in smap and smap[main_norm].get("origin") in ("LCSH", "LCSHAC", "GenreForm", "LCNAF"):
        entry = smap[main_norm]
        # The heading has -- in it; the URI might still be in norm_to_uri
        # because we also indexed ComplexSubject headings there
        if main_norm in norm_to_uri:
            uri = norm_to_uri[main_norm]
            return uri, entry["heading"], f"Itself an established LCSH ComplexSubject heading: {entry['heading']!r} (URI: {uri})"
        return None, entry["heading"], f"Itself an established LCSH heading: {entry['heading']!r}"
    # 3. LCSHAC?
    if main_norm in lcshac_uri:
        uri, term = lcshac_uri[main_norm]
        return uri, term, f"Established LCSHAC (LC Children's Subject) heading: {term!r} (URI: {uri})"
    # 4. LCNAF (name heading not otherwise caught above)?
    if main_norm in lcnaf_uri:
        uri, term = lcnaf_uri[main_norm]
        return uri, term, f"Established LC/NACO Name Authority (LCNAF) heading: {term!r} (URI: {uri})"
    # 5. FAST?
    if main_norm in fast_uri:
        uri, term, fast_id = fast_uri[main_norm]
        return uri, term, (
            f"Established FAST heading (OCLC faceted LCSH): {term!r} "
            f"(FAST ID: {fast_id}, URI: {uri}). FAST is a faceted version of "
            f"LCSH maintained by OCLC; the heading is derived from LCSH authority."
        )
    # 6. Not found — fall back to normalized form
    return None, main_norm, "Appears as prefix in 0 LCSH ComplexSubject entries"


# THREE-PASS MATCHING
def try_pass2_match(norm_piece, valid_main_headings, main_attest, sub_attest):
    """2-way split: main + subdivision. Returns dict or None."""
    words = norm_piece.split(" ")
    best = None
    for i in range(1, len(words)):
        prefix = " ".join(words[:i])
        suffix = " ".join(words[i:])
        if not prefix or not suffix:
            continue
        if prefix in valid_main_headings and suffix in sub_attest:
            sub_a = sub_attest[suffix]
            main_a = main_attest.get(prefix, 0)
            candidate = {
                "main_norm": prefix,
                "main_attest": main_a,
                "subdivisions": [(suffix, suffix, sub_a)],
                "pair_attest_counts": [],
                "n_way": 2,
                "suffix_len": len(suffix),
                "prefix_len": len(prefix),
            }
            if (best is None
                or candidate["suffix_len"] > best["suffix_len"]
                or (candidate["suffix_len"] == best["suffix_len"]
                    and candidate["prefix_len"] > best["prefix_len"])):
                best = candidate
    return best


def try_pass3_match(norm_piece, valid_main_headings, main_attest, sub_attest, pair_attest):
    """3-way and 4-way splits with pair attestation. Returns dict or None."""
    words = norm_piece.split(" ")
    if len(words) < 3:
        return None
    best = None
    # 3-way
    for i in range(1, len(words) - 1):
        for j in range(i + 1, len(words)):
            main = " ".join(words[:i])
            s1 = " ".join(words[i:j])
            s2 = " ".join(words[j:])
            if not main or not s1 or not s2:
                continue
            if (main in valid_main_headings
                and s1 in sub_attest and s2 in sub_attest
                and pair_attest.get((s1, s2), 0) > 0):
                candidate = {
                    "main_norm": main,
                    "main_attest": main_attest.get(main, 0),
                    "subdivisions": [
                        (s1, s1, sub_attest[s1]),
                        (s2, s2, sub_attest[s2]),
                    ],
                    "pair_attest_counts": [pair_attest[(s1, s2)]],
                    "n_way": 3,
                    "suffix_len": len(s2),
                    "prefix_len": len(main),
                }
                if (best is None
                    or candidate["n_way"] > best["n_way"]
                    or (candidate["n_way"] == best["n_way"]
                        and candidate["suffix_len"] > best["suffix_len"])):
                    best = candidate
    # 4-way
    if len(words) >= 4:
        for i in range(1, len(words) - 2):
            for j in range(i + 1, len(words) - 1):
                for k in range(j + 1, len(words)):
                    main = " ".join(words[:i])
                    s1 = " ".join(words[i:j])
                    s2 = " ".join(words[j:k])
                    s3 = " ".join(words[k:])
                    if not main or not s1 or not s2 or not s3:
                        continue
                    if (main in valid_main_headings
                        and s1 in sub_attest and s2 in sub_attest and s3 in sub_attest
                        and pair_attest.get((s1, s2), 0) > 0
                        and pair_attest.get((s2, s3), 0) > 0):
                        candidate = {
                            "main_norm": main,
                            "main_attest": main_attest.get(main, 0),
                            "subdivisions": [
                                (s1, s1, sub_attest[s1]),
                                (s2, s2, sub_attest[s2]),
                                (s3, s3, sub_attest[s3]),
                            ],
                            "pair_attest_counts": [
                                pair_attest[(s1, s2)],
                                pair_attest[(s2, s3)],
                            ],
                            "n_way": 4,
                            "suffix_len": len(s3),
                            "prefix_len": len(main),
                        }
                        if (best is None
                            or candidate["n_way"] > best["n_way"]
                            or (candidate["n_way"] == best["n_way"]
                                and candidate["suffix_len"] > best["suffix_len"])):
                            best = candidate
    return best


def main():
    start_time = perf_counter()

    # Build authority map
    print("=" * 80)
    print("PHASE 1: Building authority map from local authority files")
    print("=" * 80)
    smap = build_authority_map()
    print(f"\n  Total unique normalized subjects: {len(smap):,}")

    # Build subdivision indices
    print()
    print("=" * 80)
    print("PHASE 2: Building subdivision attestation indices")
    print("=" * 80)
    (main_attest, main_orig, sub_attest, sub_orig, pair_attest,
     norm_to_uri, fast_uri, lcshac_uri, lcnaf_uri) = build_subdivision_indices()
    print(f"  Unique main headings:           {len(main_orig):,}")
    print(f"  Unique subdivisions:             {len(sub_attest):,}")
    print(f"  Unique subdivision pairs:        {len(pair_attest):,}")
    print(f"  Standalone LCSH headings w/URI:  {len(norm_to_uri):,}")
    print(f"  FAST headings w/URI:             {len(fast_uri):,}")
    print(f"  LCSHAC headings w/URI:           {len(lcshac_uri):,}")
    print(f"  LCNAF (name) headings w/URI:     {len(lcnaf_uri):,}")

    valid_main_headings = set(smap.keys()) | set(main_orig.keys())
    print(f"\n  Combined valid main-heading pool: {len(valid_main_headings):,}")

    # Fetch (Title, Subjects) pairs from R2 
    print()
    print("=" * 80)
    print("PHASE 3: Fetching (Title, Subjects) pairs from R2")
    print("=" * 80)

    title_to_subjects = load_agg_cache()

    used_r2 = False
    used_local_fallback = False
    new_files = []

    if duckdb is None:
        print("  duckdb not installed; using local CSV fallback if available")
        used_local_fallback = True
    else:
        con = duckdb.connect()
        try:
            configure_duckdb_for_r2(con)
            used_r2 = True
        except Exception as e:
            print(f"  Could not configure duckdb for R2: {e}")
            print(f"  Falling back to local CSV")
            used_local_fallback = True

    if used_r2:
        if not title_to_subjects:
            # Cold start: scan every monthly file on R2 once
            print("  No cached aggregate found: doing a one-time full historical scan")
            new_keys, all_keys = list_new_keys_from_r2(all_keys_too=True)
            if not all_keys:
                print("  R2 bucket empty or inaccessible; falling back to local CSV")
                used_r2 = False
                used_local_fallback = True
            else:
                rows = con.execute(
                    """
                    SELECT Creator AS author, Title AS title, Subjects AS subjects, MaterialType AS materialtype
                    FROM read_csv_auto(?, ignore_errors=true)
                    WHERE Title IS NOT NULL AND Creator IS NOT NULL
                    GROUP BY Creator, Title, Subjects, MaterialType
                    """,
                    [[f"s3://{R2_BUCKET}/{k}" for k in all_keys]],
                ).fetchall()
                new_files = all_keys
                print(f"  Scanned {len(all_keys):,} R2 keys -> {len(rows):,} unique (Author, Title, Subjects) triples")
        else:
            print("  Checking R2 bucket for new monthly files ...")
            new_files = list_new_keys_from_r2()
            rows = query_rows_from_r2(con, new_files)
            print(f"  Scanned {len(new_files):,} new R2 keys -> {len(rows):,} new (Author, Title, Subjects) triples")

    if used_local_fallback:
        if duckdb is None:
            # Use csv module as a last-resort fallback
            if not LOCAL_CSV_FALLBACK.exists():
                print(f"\n  ERROR: Neither R2 nor local CSV available.")
                print(f"         Set R2 credentials in {DATA_PREP_DIR / 'access.env'}")
                print(f"         OR place a CSV at {LOCAL_CSV_FALLBACK}")
                sys.exit(1)
            print(f"  Reading local CSV (csv module fallback): {LOCAL_CSV_FALLBACK}")
            rows = []
            with open(LOCAL_CSV_FALLBACK, newline="", encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                seen = set()
                for row in reader:
                    author = (row.get("Creator") or "").strip()
                    title = (row.get("Title") or "").strip()
                    if not title or not author:
                        continue
                    subjects = (row.get("Subjects") or "").strip()
                    mt = (row.get("MaterialType") or "").strip()
                    key = (author, title, subjects, mt)
                    if key in seen:
                        continue
                    seen.add(key)
                    rows.append((author, title, subjects, mt))
            print(f"  Read {len(rows):,} unique (Author, Title, Subjects, MaterialType) tuples from local CSV")
        else:
            con = duckdb.connect()
            rows = query_rows_from_local(con, LOCAL_CSV_FALLBACK)
            if not rows:
                # Previous code here tried `Path("")` as a fallback, but
                # `Path("")` is `PosixPath('.')` (the cwd) and `exists()` is
                # always True for it -- so read_csv_auto('.') would be called
                # on a directory and fail with a confusing duckdb error.
                # Treat 'no rows from the configured fallback path' as a
                # hard error instead of silently trying nonsensical paths.
                if not LOCAL_CSV_FALLBACK.exists():
                    print(f"\n  ERROR: local CSV not found at {LOCAL_CSV_FALLBACK}")
                    print(f"         Set R2 credentials in {DATA_PREP_DIR / 'access.env'} "
                          f"OR place a CSV at {LOCAL_CSV_FALLBACK}")
                    sys.exit(1)
                else:
                    print(f"\n  ERROR: local CSV at {LOCAL_CSV_FALLBACK} yielded 0 rows. "
                          f"Check the file is not empty / not just a header.")
                    sys.exit(1)
            print(f"  Read {len(rows):,} unique (Title, Subjects) pairs from local CSV")

    # Fold the new rows into the aggregate.
    # Cache shape (v3): {"author\ttitle": {subjects: str, materialtypes: [str, ...]}}
    # Keyed by (author, title) so subject_map.json can store rigorous pairs
    # that JOIN against build_data.py's clean table. Author names are folded
    # through author_map.json (same as build_data.py) before keying.
    author_map = _load_author_map()
    if author_map:
        print(f"  Applying author_map.json ({len(author_map):,} merges) to Creator names")
    new_titles_added = 0
    new_materialtypes_added = 0
    for row in rows:
        # rows is a list of (author, title, subjects, materialtype) tuples
        author = row[0] if isinstance(row, (tuple, list)) else row.get("author", "")
        title = row[1] if isinstance(row, (tuple, list)) else row.get("title", "")
        subjects = row[2] if isinstance(row, (tuple, list)) else row.get("subjects", "")
        mt = row[3] if isinstance(row, (tuple, list)) else row.get("materialtype", "")
        if not title or not author:
            continue
        # Fold raw Creator -> canonical author, same as build_data.py does
        # when building `clean`. Without this step the downstream JOIN would
        # miss every author whose raw name was folded.
        author = author_map.get(author, author)
        key = _cache_key(author, title)
        if key not in title_to_subjects:
            title_to_subjects[key] = {
                "subjects": subjects or "",
                "materialtypes": [mt] if mt else [],
            }
            new_titles_added += 1
        else:
            entry = title_to_subjects[key]
            if mt and mt not in entry["materialtypes"]:
                entry["materialtypes"].append(mt)
                entry["materialtypes"].sort()
                new_materialtypes_added += 1
            if not entry["subjects"] and subjects:
                entry["subjects"] = subjects
    print(f"  {new_titles_added:,} new unique (author, title) pairs added to aggregate cache")
    print(f"  {new_materialtypes_added:,} new materialtype entries merged into existing pairs")
    print(f"  Total unique (author, title) pairs in aggregate: {len(title_to_subjects):,}")

    # Persist immediately so the next run's delta is correct even if matching below throws.
    save_agg_cache(title_to_subjects)

    # Three-pass matching (filtered by MaterialType)
    print()
    print("=" * 80)
    print("PHASE 4: Three-pass matching  (MaterialType filter: book/ebook/audiobook)")
    print("=" * 80)
    print(f"  Include set: {sorted(MATERIALTYPE_INCLUDE)}")
    print(f"  Exclude set: {sorted(MATERIALTYPE_EXCLUDE)}")

    pieces_total = 0
    pass1_hits = 0
    pass2_hits = 0
    pass3_hits = 0
    misses = 0
    titles_skipped_mt = 0
    pass3_origin_breakdown = Counter()
    unmatched_counter = Counter()
    pass2_cache = {}
    pass3_cache = {}

    # MaterialType distribution stats (for reporting)
    mt_stats = Counter()
    titles_processed = 0
    for cache_key, info in title_to_subjects.items():
        # v3 cache keys are "author\ttitle" strings; split back into the pair
        # so we can store [author, title] in each subject entry's titles list.
        author, title = _split_cache_key(cache_key)
        titles_processed += 1
        if titles_processed % 1000 == 0:
            print(f"  ... processed {titles_processed:,} / {len(title_to_subjects):,} (author, title) pairs")

        # MaterialType filter: include title only if at least one of its
        # materialtypes passes the filter
        mts = info.get("materialtypes", []) if isinstance(info, dict) else []
        allowed_mts = [mt for mt in mts if materialtype_allowed(mt)]
        if not allowed_mts:
            titles_skipped_mt += 1
            continue

        for mt in allowed_mts:
            mt_stats[mt] += 1

        subjects = info.get("subjects", "") if isinstance(info, dict) else (info if isinstance(info, str) else "")
        if not subjects:
            continue
        for piece in subjects.split(","):
            piece = piece.strip()
            if not piece:
                continue
            pieces_total += 1
            n = normalize(piece)
            if not n:
                continue

            # Direct lookup
            entry = smap.get(n)
            if entry is not None:
                pass1_hits += 1
                # Store [author, title] pairs (not bare title strings) so
                # build_data.py can JOIN rigorously on (author, title).
                pair = [author, title]
                if not entry["titles"] or entry["titles"][-1] != pair:
                    entry["titles"].append(pair)
                continue

            # Pass 2 & 3 (with caching)
            if n in pass2_cache:
                m2 = pass2_cache[n]
            else:
                m2 = try_pass2_match(n, valid_main_headings, main_attest, sub_attest)
                pass2_cache[n] = m2

            if n in pass3_cache:
                m3 = pass3_cache[n]
            else:
                m3 = try_pass3_match(n, valid_main_headings, main_attest, sub_attest, pair_attest)
                pass3_cache[n] = m3

            # Choose best: prefer pass 3 (higher n_way) over pass 2
            best = m2
            if m3 is not None:
                if best is None or m3["n_way"] > best["n_way"]:
                    best = m3

            if best is None:
                misses += 1
                unmatched_counter[piece] += 1
                continue

            # Resolve main heading URI/text
            main_uri, main_text, attest_note = resolve_main_uri(
                best["main_norm"], smap, norm_to_uri, fast_uri, lcshac_uri, lcnaf_uri,
            )
            # Override attestation note if main_attest > 0 and no URI
            if not main_uri and best["main_attest"] > 0:
                attest_note = f"Appears as prefix in {best['main_attest']} LCSH ComplexSubject entries"

            # Build subdivisions list with proper text
            subdivisions = []
            for (sn, _, sa) in best["subdivisions"]:
                st = sub_orig.get(sn, sn)
                subdivisions.append((st, sn, sa))

            # Reconstruct canonical heading
            if best["n_way"] == 2:
                reconstructed = f"{main_text}--{subdivisions[0][0]}"
                origin_label = "LCSH Subdivision"
            elif best["n_way"] == 3:
                reconstructed = f"{main_text}--{subdivisions[0][0]}--{subdivisions[1][0]}"
                origin_label = "LCSH Subdivision Chain (3-way)"
            else:  # 4
                reconstructed = (
                    f"{main_text}--{subdivisions[0][0]}--"
                    f"{subdivisions[1][0]}--{subdivisions[2][0]}"
                )
                origin_label = "LCSH Subdivision Chain (4-way)"

            citation = make_citation(
                main_text, best["main_norm"], main_uri, best["main_attest"],
                subdivisions, best["pair_attest_counts"], best["n_way"],
            )
            # Patch the attestation_note into the citation
            citation["main_heading"]["attestation_note"] = attest_note

            if n not in smap:
                smap[n] = {
                    "type": "ComplexSubject",
                    "origin": origin_label,
                    "origins": [origin_label],
                    "uris": {"LCSH Subdivision": main_uri} if main_uri else {},
                    "heading": reconstructed,
                    "titles": [],
                    "citation": citation,
                }
                pass3_origin_breakdown[f"new_{best['n_way']}_way"] += 1
            else:
                existing = smap[n]
                if existing["origin"] not in ("LCSH", "LCSHAC", "GenreForm", "LCNAF",
                                              "LCSH Subdivision",
                                              "LCSH Subdivision Chain (3-way)",
                                              "LCSH Subdivision Chain (4-way)"):
                    # Auxiliary vocabulary (GSAFD/Deprecated/FAST/BISAC/Overdrive)
                    # -- replace the primary origin with the stronger LCSH
                    # reconstruction, but APPEND the new origin to `origins`
                    # so the user can still see every vocabulary that vouched
                    # for this heading. The old origin stays in the list.
                    old_origin = existing.get("origin")
                    existing.update({
                        "type": "ComplexSubject",
                        "origin": origin_label,
                        "heading": reconstructed,
                        "citation": citation,
                    })
                    # Backfill origins/uris on legacy entries that predate the
                    # multi-origin format (they only have a single `origin`).
                    if "origins" not in existing:
                        existing["origins"] = [old_origin] if old_origin else []
                    if origin_label not in existing["origins"]:
                        existing["origins"].append(origin_label)
                    if "uris" not in existing:
                        existing["uris"] = {}
                    if main_uri and origin_label not in existing["uris"]:
                        existing["uris"][origin_label] = main_uri
                    pass3_origin_breakdown[f"overwrote_{best['n_way']}_way"] += 1
                else:
                    # Existing entry is already an LCSH-family heading; the
                    # Pass 2/3 reconstruction is the same vocabulary, so just
                    # make sure its origin + URI are recorded (idempotent).
                    if "origins" not in existing:
                        existing["origins"] = [existing["origin"]]
                    if origin_label not in existing["origins"]:
                        existing["origins"].append(origin_label)
                    if "uris" not in existing:
                        existing["uris"] = {}
                    if main_uri and origin_label not in existing["uris"]:
                        existing["uris"][origin_label] = main_uri

            entry = smap[n]
            pair = [author, title]
            if not entry["titles"] or entry["titles"][-1] != pair:
                entry["titles"].append(pair)

            if best["n_way"] == 2:
                pass2_hits += 1
            else:
                pass3_hits += 1

    # Write outputs
    print()
    print("=" * 80)
    print("PHASE 5: Writing outputs")
    print("=" * 80)
    smap_to_write = {k: v for k, v in smap.items() if v.get("titles")}
    dropped_no_titles = len(smap) - len(smap_to_write)

    OUT_MAP.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_MAP, "w", encoding="utf-8") as fh:
        json.dump(smap_to_write, fh, ensure_ascii=False, sort_keys=True)
    size_mb = OUT_MAP.stat().st_size / (1024 * 1024)
    print(f"  Map: {OUT_MAP}  ({size_mb:.1f} MB)")
    print(f"  Dropped {dropped_no_titles:,} subject(s) with no titles attached "
          f"(kept {len(smap_to_write):,} of {len(smap):,})")

    total_matched = pass1_hits + pass2_hits + pass3_hits
    print()
    print("RESULTS:")
    print(f"  Titles in aggregate:                {len(title_to_subjects):,}")
    print(f"  Titles skipped (MaterialType):      {titles_skipped_mt:,}  ({100*titles_skipped_mt/len(title_to_subjects):.1f}%)")
    print(f"  Titles matched:                     {len(title_to_subjects) - titles_skipped_mt:,}")
    print()
    print(f"  MaterialType breakdown of included titles:")
    for mt, c in mt_stats.most_common():
        print(f"    {mt:25s} {c:>6d}")
    print()
    print(f"  Subject pieces total:               {pieces_total:,}")
    print(f"  Pass 1 (direct lookup):             {pass1_hits:,}  ({100*pass1_hits/pieces_total:.1f}%)")
    print(f"  Pass 2 (main + subdivision):        {pass2_hits:,}  ({100*pass2_hits/pieces_total:.1f}%)")
    print(f"  Pass 3 (main + sub + sub [+ sub]):  {pass3_hits:,}  ({100*pass3_hits/pieces_total:.1f}%)")
    print(f"  Total matched:                      {total_matched:,}  ({100*total_matched/pieces_total:.1f}%)")
    print(f"  Unmatched:                          {misses:,}  ({100*misses/pieces_total:.1f}%)")
    print()
    print("  Pass 2/3 entry breakdown:")
    for k, v in sorted(pass3_origin_breakdown.items()):
        print(f"    {k}: {v:,}")

    # Final composition (of what's actually written to OUT_MAP)
    print()
    print("Final map composition by origin (titled subjects only, as written):")
    composition = Counter()
    for v in smap_to_write.values():
        composition[v.get("origin", "UNKNOWN")] += 1
    for o, c in composition.most_common():
        print(f"  {o:40s} {c:>8d}")
    print(f"  {'TOTAL':40s} {len(smap_to_write):>8d}")

    # Breakdown by subject type (Topic, PersonalName, CorporateName, GenreForm,
    # ComplexSubject, etc.) -- both how many distinct subjects of that type
    # made it into the titled map, and how many title-attachments they carry.
    type_subject_counts = Counter()
    type_title_counts = Counter()
    for v in smap_to_write.values():
        t = v.get("type") or "UNKNOWN"
        type_subject_counts[t] += 1
        type_title_counts[t] += len(v.get("titles", []))

    print()
    print("Titled subjects and title-attachments by subject type:")
    print(f"  {'type':25s} {'subjects':>10s} {'titles':>10s}")
    for t, _ in type_title_counts.most_common():
        print(f"  {t:25s} {type_subject_counts[t]:>10,d} {type_title_counts[t]:>10,d}")

    # Summary file
    subjects_with_titles = len(smap_to_write)
    total_title_attachments = sum(len(v.get("titles", [])) for v in smap_to_write.values())
    subject_type_breakdown = {
        t: {
            "subjects": type_subject_counts[t],
            "title_attachments": type_title_counts[t],
        }
        for t in sorted(type_title_counts, key=lambda k: type_title_counts[k], reverse=True)
    }
    summary = {
        "stats": {
            "pieces_total": pieces_total,
            "pass1_direct_lookup": pass1_hits,
            "pass2_main_plus_subdivision_2way": pass2_hits,
            "pass3_main_plus_subdivision_chain_3way_4way": pass3_hits,
            "total_matched": total_matched,
            "match_rate_pct": round(100 * total_matched / pieces_total, 2) if pieces_total else 0,
            "unmatched": misses,
            "pass2_new_entries": pass3_origin_breakdown.get("new_2_way", 0),
            "pass3_new_3way_entries": pass3_origin_breakdown.get("new_3_way", 0),
            "pass3_new_4way_entries": pass3_origin_breakdown.get("new_4_way", 0),
            "subjects_with_at_least_one_title": subjects_with_titles,
            "total_title_attachments": total_title_attachments,
            "title_attachments_by_subject_type": subject_type_breakdown,
            "final_map_total_entries": len(smap_to_write),
            "final_map_entries_before_title_filter": len(smap),
            "subjects_dropped_no_titles": dropped_no_titles,
            "materialtype_filter": {
                "include_set": sorted(MATERIALTYPE_INCLUDE),
                "exclude_set": sorted(MATERIALTYPE_EXCLUDE),
                "titles_in_aggregate": len(title_to_subjects),
                "titles_skipped_by_filter": titles_skipped_mt,
                "titles_included": len(title_to_subjects) - titles_skipped_mt,
                "included_materialtype_breakdown": dict(mt_stats.most_common()),
            },
            "authority_source": "subjects.madsrdf_headings.csv (LCSH machine-readable authority file)",
            "subdivision_authority_basis": "All text-after-'--' pieces in LCSH ComplexSubject entries",
            "main_heading_authority_basis": "All text-before-'--' pieces in LCSH ComplexSubject entries, plus all standalone LCSH headings, plus all LC/NACO Name Authority (LCNAF) headings (personal/corporate/family names, including fictitious-character name headings)",
            "pair_attestation_basis": f"Adjacent subdivision pairs in LCSH ComplexSubject entries ({len(pair_attest):,} unique pairs)",
            "citation_standard": (
                "Verified against SHM H 180 (Assigning and Constructing Subject Headings, 2026-01 revision): "
                "sec. R (explicit multi-level subdivision example 'United States--Civilization--African American "
                "influences'), sec. S (complete subject heading strings with subdivisions — heading strings "
                "need not exist as authority records; catalogers supply subdivision elements per SHM instructions), "
                "sec. M (multi-element topics get multiple headings — explains SPL comma-separated Subjects column), "
                "sec. F (typically max 6 headings per work), sec. G (subdividing a heading is a legitimate "
                "specificity mechanism), sec. D & N.4 (LC no longer assigns form subdivisions in new cataloging "
                "per 2026-01 revision — use LCGFT; SPL data reflects pre-migration practice). Cross-references: "
                "SHM H 1075 (four subdivision types: Topical/Geographic/Chronological/Form; standard orders), "
                "SHM Module 6-1 (Subdivision overview training)."
            ),
            "h180_url": "https://www.loc.gov/aba/publications/FreeSHM/H0180.pdf",
            "h180_verified_date": "2026-07-14",
            "final_map_composition": dict(composition),
            "input_source": "R2 bucket" if used_r2 else "local CSV fallback",
            "input_files_processed": len(new_files) if used_r2 else "n/a",
        },
        "top_unmatched_pieces": [
            {"piece": p, "count": c} for p, c in unmatched_counter.most_common(50)
        ],
    }
    with open(OUT_SUMMARY, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    print(f"\n  Summary: {OUT_SUMMARY}  ({OUT_SUMMARY.stat().st_size / 1024:.1f} KB)")

    # Mark processed files (only on success and only for R2 mode)
    if used_r2 and new_files:
        _mark_processed(new_files)
        print(f"  recorded {len(new_files)} newly-processed file(s) in {PROCESSED_FILES_CSV.name}")

    end_time = perf_counter()
    print(f"\nElapsed time: {end_time - start_time:.2f} seconds")
    print(f"\nNow run:  python3 {PROJECT_DIR / 'data-prep' / 'build_data.py'}")


if __name__ == "__main__":
    main()