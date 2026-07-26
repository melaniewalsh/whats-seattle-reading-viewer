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
from rapidfuzz import fuzz, process
try:
    import boto3
except ImportError:  # pragma: no cover - boto3 is only needed to LIST keys now
    boto3 = None
import unicodedata



PROJECT_DIR = Path(__file__).resolve().parent.parent
RAW_CSV = PROJECT_DIR / "data" / "raw" / "spl-monthly-checkouts_2005-2025.csv"
OUT_MAP = PROJECT_DIR / "data-prep" / "author_map.json"
PROCESSED_FILES_CSV = PROJECT_DIR / "data-prep" / "processed_files.csv"

# The persisted (name, title) -> checkouts aggregate. 
AGG_CACHE = PROJECT_DIR / "data-prep" / "author_title_agg.json"

# Similarity floor (0-100, rapidfuzz.fuzz.ratio scale) 
FUZZY_TITLE_THRESHOLD = 95

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


# MARC relator codes show up as parentheticals like "(ilt)", "(crt)", "(cor)".
# They mark a person's ROLE on a book (illustrator, creator, corrector...), not
# WHICH person it is, so the same human appears under several of them -> safe to
# strip. By contrast, occupational/biographical qualifiers like "(pastor)",
# "(musician)", "(novelist)" are the catalog's way of telling two DIFFERENT
# same-named people apart, so we must KEEP them or we over-merge (e.g. Garfield's
# "Davis, Jim, 1945-" got fused with "Davis, Jim (Pastor)").
RELATOR_CODES = {
    "aut", "ill", "ilt", "edt", "cor", "con", "crt", "cre", "trl", "nrt",
    "prf", "com", "drt", "ctb", "art", "aui", "aft", "ann", "cmp", "lyr",
    "prt", "pbl", "voc", "dub", "hnr", "spk", "act", "dir", "pro", "adp",
    "arr", "cng", "cnd", "aqt", "cll", "clr", "cwt", "ed", "trc", "cov",
}


# Honorific prefies the cataloguer sometimes sticks in front of a name like
# "Dr. Martin Luther King, Jr.", "Rev. Martin Luther King, Jr.", "Sir Arthur
# Conan Doyle", "St. Augustine", "Prof. Richard Feynman". These are catalog
# metadata, not part of the person's actual name, two records for the same
# person, one with the prefix, one without will normalize to different strings
# ("dr martin luther king jr" vs "martin luther king jr") and end up split
# across two author clusters.
#
# Match only when the honorific is at the very start (anchored ^) AND followed
# by whitespace, so we never accidentally strip "Dr" out of a surname like
# "Drew" or a hyphenated name like "Saint-Saens" (those have no following
# space). Multi-creator strings get split by the '/' handler in normalize()
# and each segment is re-normalized, so a leading honorific on a LATER
# segment ("Smith, John / Dr. Jane Doe") is stripped by the recursive call.
HONORIFIC_PREFIX_RE = re.compile(
    r"^\s*(?:dr|doctor|mr|mister|mrs|ms|miss|prof|professor|"
    r"sir|lord|lady|rev|reverend|saint|st|hon|honourable|honorable|"
    r"capt|captain|lt|lieutenant|col|colonel|gen|general|"
    r"herr|frau|madame|mme|mademoiselle|mlle)\b\.?\s+",
    re.IGNORECASE,
)


# SUFFIX tokens (Jr, Sr, II, III, IV, VI ...) 
# "v" alone is intentionally EXCLUDED since a standalone token it is far
# more likely to be a middle initial ("John V. Smith") 
SUFFIX_TOKEN_RE = re.compile(r"^(?:jr\.?|sr\.?|ii|iii|iv|vi)$", re.IGNORECASE)


# Parentheticals that describe an ENTITY TYPE or PLACE rather than telling two
# same-named PEOPLE apart. These attach to bands, corporate names, and places
# (e.g. "Red Hot Chili Peppers (Musical group)", "Washington (State)") and are
# applied inconsistently across records, so KEEPING them would split one entity
# in two. Strip them like relator codes.
NON_PERSON_QUALIFIER_RE = re.compile(
    r"\b(musical\s+gr[ou]up|group|band|orchestra|ensemble|choir|chorus|"
    r"quartet|quintet|sextet|trio|duo|collective|project|"
    r"company|corporation|corp|inc|firm|organization|association|"
    r"state|province|county|region|kingdom|empire|republic)\b"
)


# Professional/academic credentials that the catalog appends after a name
# ("Emma Lauer, LCSW", "Jennifer Freed, PhD"). They're not part of the name, so a
# trailing credential segment is dropped -- otherwise the reorder treats it as
# the surname and produces "lcsw emma lauer". Deliberately EXCLUDES ambiguous
# 2-letter forms (ma, ms, ba, bs, pa) that collide with real names, and only
# strips them when they trail the name (never the first segment), so surnames
# like "Do" / "Ma" in "Do, Anh" survive.
CREDENTIALS = {
    "phd", "md", "do", "dds", "dmd", "dvm", "dnp", "psyd", "edd", "dpt",
    "pharmd", "scd", "dsc", "jd", "esq", "lcsw", "lcsw", "msw", "lmsw",
    "lcpc", "lpc", "lmft", "lmhc", "lpcc", "mft", "rn", "aprn", "np", "crna",
    "cnm", "cnp", "fnp", "pmhnp", "bsn", "msn", "mph", "mba", "mfa", "mpa",
    "cpa", "cfa", "cfp", "rd", "rdn", "ldn", "otr", "slp", "ccc",
    "faap", "facp", "facs", "faan", "faafp",
}


def _is_credential_part(part: str) -> bool:
    """True when a comma segment is purely a credential like 'LCSW' / 'Ph.D.'."""
    return re.sub(r"[.\s]", "", part.lower()) in CREDENTIALS


def _prefold(s: str) -> str:
    """Unify apostrophes and fold diacritics so accent/punctuation-only spelling
    differences don't split one author. "O'Malley"=="O'Malley";
    "Knausgård"=="Knausgaard"; "Boström"=="Bostrom". Scandinavian a-ring / o-slash
    / ae have standard two-letter transliterations, so expand those BEFORE the
    generic combining-mark strip (which would otherwise turn a-ring into "a")."""
    s = s.replace("’", "'").replace("ʼ", "'").replace("`", "'")
    s = s.replace("å", "aa").replace("ø", "o").replace("æ", "ae").replace("ß", "ss")
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def _is_name_expansion(inside: str, base: str) -> bool:
    """True when a parenthetical just spells out initials/given-names already in
    the base name -- the library's "Lewis, C. S. (Clive Staples)" convention.
    Every word must be an existing base word or expand one of its initials, so
    real occupation tags like "(pastor)" or "(physician)" are NOT expansions."""
    base_tokens = re.findall(r"[a-z]+", base.lower())
    base_initials = {t for t in base_tokens if len(t) == 1}
    base_words = {t for t in base_tokens if len(t) > 1}
    words = re.findall(r"[a-z]+", inside)
    if not words:
        return False
    return all(w in base_words or w[0] in base_initials for w in words)


def _split_parens(text: str):
    """Return (text_with_parens_removed, kept_qualifiers).

    Drops MARC relator role-codes, entity/place tags, and name-expansions; keeps
    occupational or biographical qualifiers (as lowercase strings) so callers can
    re-attach them as person-disambiguators."""
    base = re.sub(r"\([^)]*\)", " ", text)  # name with every parenthetical gone
    kept = []

    def repl(m):
        inside = m.group(1).strip().lower().rstrip(".")
        if (
            inside
            and inside not in RELATOR_CODES
            and not NON_PERSON_QUALIFIER_RE.search(inside)
            and not _is_name_expansion(inside, base)
        ):
            kept.append(inside)
        return " "

    stripped = re.sub(r"\(([^)]*)\)", repl, text)
    return stripped, kept


def normalize(name: str) -> str:

    """A rough key for deciding two names are the same."""
    if not name:
        return ""

    # lowercasing, dash stripping, parenthesis creator
    creator = name.lower().strip("-").strip()

    # Unify apostrophes + fold diacritics so "O'Malley"=="O'Malley" and
    # "Knausgård"=="Knausgaard" cluster instead of splitting.
    creator = _prefold(creator)

    # Strip relator role-codes but keep real disambiguators to re-attach below.
    creator, kept_quals = _split_parens(creator)

    # Drop a leading honorific prefix ("Dr.", "Mr.", "Sir", "Rev.", "St.",
    # "Prof.", ...) BEFORE any comma-split / reorder logic runs. Otherwise
    # "Dr. Martin Luther King, Jr." normalizes to "dr martin luther king jr"
    #Done after _split_parens so a parenthetical
    # role-code on a LATER creator in a multi-segment string isn't disturbed,
    # and before the '/' split so a LATER segment's leading honorific gets
    # stripped by the recursive normalize() call below.
    creator = HONORIFIC_PREFIX_RE.sub("", creator, count=1)

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

    # Drop life-date segments so months/days/years don't leak into the name and
    # get scrambled by the reorder below.
    #
    # BUG THIS FIXES: the old pattern (r"^\d{4}-?\d{0,4}\.?$") only matched
    # PURELY-numeric dates like "1850-1910" / "1975-". But the catalog also uses
    # a "year month day" form, e.g. "Davis, Jim, 1945 July 28-". There the "1945
    # July 28-" segment wasn't recognized as a date, so "July 28" was treated as a
    # name part and the reorder produced the canonical "july 28 davis jim" (Jim
    # Davis showed up on the site as "July 28 Davis Jim", and likewise for Mark
    # Stewart, Jane Hamilton, etc.). Matching any segment that STARTS with a
    # 4-digit year catches every form: "1945 July 28-", "1850-1910", "1975-".
    date_part_pattern = r"^\d{4}\b"
    parts = [p for p in parts if not re.match(date_part_pattern, p)]

    # extract suffix first so it doesn't break in cases like L. E. Modesitt, Jr.
    suffix = None
    cleaned_parts = []

    # suffix pattern to match the suffix standing alone or near punctuation
    suffix_pattern = r"(?:^|\s|,|\.)(jr\.?|sr\.?|ii|iii|iv|v|vi)\b"
    for i, part in enumerate(parts):
        # A TRAILING segment that is purely a credential ("Emma Lauer, LCSW",
        # "Jennifer Freed, PhD") isn't part of the name -- drop it so it doesn't
        # get reordered to the front as a fake surname. Never the first segment,
        # so a real surname like "Do"/"Ma" survives.
        if i > 0 and _is_credential_part(part):
            continue
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

    # re-attach kept qualifiers so different same-named people stay distinct
    # (e.g. "jim davis pastor" != "jim davis").
    if kept_quals:
        creator = f"{creator} " + " ".join(kept_quals)
        creator = re.sub(r"\s+", " ", creator).strip()

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
    # same apostrophe/diacritic folding as normalize() so blocking keys align
    s = _prefold(s)
    # strip relator role-codes but keep real disambiguators (re-attached below)
    s, kept_quals = _split_parens(s)

    # Mirroring normalize(): drop a leading honorific prefix so tokenization of
    # the raw name lines up with tokenization of the normalized name. Without this, the "dr"
    # token survives in name_tokens("Dr. Martin Luther King, Jr.") and
    # first_last_key() returns ('dr', 'king') instead of ('martin', 'king').
    s = HONORIFIC_PREFIX_RE.sub("", s, count=1)

    parts = [p.strip() for p in s.split(",") if p.strip()]

    # drop pure life-date segments so they don't block the reversal below
    date_part_pattern = r"^\d{4}-?\d{0,4}\.?$"
    parts = [p for p in parts if not re.match(date_part_pattern, p)]

    suffix_pattern = r"(?:^|\s|,|\.)(jr\.?|sr\.?|ii|iii|iv|v|vi)\b"
    cleaned_parts = []
    for i, part in enumerate(parts):
        if i > 0 and _is_credential_part(part):
            continue
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
    # re-attach kept qualifiers so blocking keeps distinct people apart
    if kept_quals:
        s = s + " " + " ".join(kept_quals)
    #replace consecutive whitespaces with singular
    s = re.sub(r"\s+", " ", s).strip()

  
    return [t for t in s.split(" ") if t and not SUFFIX_TOKEN_RE.match(t)]


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


def token_set_key(name: str):
    """Order-independent token signature, used alongside first_last_key() to
    catch spellings whose words are the same but in a different ORDER --
    e.g. a raw catalog string like "K. Le Guin Ursula" instead of "Ursula K.
    Le Guin". normalize() only reorders "Last, First" forms that contain a
    comma; a comma-less string is assumed to already be in First..Last order,
    so a genuinely scrambled comma-less name (an initial dragged to the
    front, first/last swapped, etc.) normalizes to a different word order
    and first_last_key's positional (tokens[0], tokens[-1]) check won't match
    it to the correctly-ordered spelling of the same person. Sorting the
    tokens ignores position entirely and catches these. Requires
    fuzzy_title_matches() before union, same as first_last_key, so two
    different people who happen to share every name token 
    aren't merged on this alone."""
    if " / " in name:
        return None
    tokens = name_tokens(name)
    if len(tokens) < 2:
        return None
    return tuple(sorted(tokens))


def extract_date_signature(name: str):
    """Return the BIRTH year (first 4-digit year token) attached to a name,
    or None if no year appears.

    The catalog records the same person's lifespan in several inconsistent
    forms  "Merwin, W. S. (William Stanley), 1927-" (still-living at
    cataloguing time), "..., 1927-2019" (after death), "..., 1927-2019,"
    (with a stray trailing comma). The previous implementation concatenated
    EVERY \\b\\d{4}-?\\b match, so these three raw spellings of one person
    produced THREE different date signatures ("1927", "1927-2019",
    "1927-2019") and landed in three separate Pass-1 (norm, date_sig)
    buckets. Pass 2 only re-merges the undated form with ONE best-matching
    dated form on title evidence, so the other dated form was left split
    off  "Merwin, W. S. (William Stanley), 1927-" never re-merged with
    "Merwin, W. S. (William Stanley), 1927-2019".

    Using only the birth year (first 4-digit year) collapses every
    lifespan-format variant of one person into a single date signature.
    This is consistent with name_variant_remap.birth_year() further down
    in this file, which already treats the first 4-digit year as the
    person-disambiguator and refuses to merge across conflicting birth
    years. Different DEATH years for the same birth year are catalog
    metadata noise (the cataloguer hadn't recorded the death yet, or
    recorded it wrong), not a marker of two different people.
    """
    if not name:
        return None
    m = re.search(r"\b\d{4}\b", name)
    return m.group(0) if m else None


def _period_marked_initials(name: str) -> set:
    """Single letters in the RAW name that are unambiguously initials --
    i.e. immediately followed by a period, like the "B." in "James B.
    Patterson". A bare single letter with no period (rare, but could be a
    real one-letter name) is left alone rather than assumed to be an
    initial, since name_tokens() has already stripped periods by the time
    we'd otherwise have to guess from token length alone."""
    if not name:
        return set()
    return {m.lower() for m in re.findall(r"\b([A-Za-z])\.", name)}


def normalize_title(title: str, author: str = None) -> str:
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
    
    # strip remaining non-alphanumeric characters but KEEP single spaces as
    # word separators for token sort ratio
    t = re.sub(r"[^a-z0-9]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()

    # drop any tokens that are just the author's own name (e.g. a series
    # title like "James Patterson's Alex Cross" or a catalog record that
    # repeats "by James B. Patterson" inside the title field itself).
    # left in, these give two DIFFERENT "James _ Patterson"s a fake shared
    # title token ("james", "patterson").
    
    #for a middle initial like the "B."
    # we can tell it's an initial (not a real
    # title word coincidentally worth one letter like ('a') because it's followed by
    # a period in the raw name
    if author:
        initials = _period_marked_initials(author)
        author_tokens = {tok for tok in name_tokens(author) if tok not in initials}
        if author_tokens:
            # The apostrophe strip above already turned a possessive like
            # "Patterson's" into "pattersons", so also match a name token
            # with a trailing "s" (word minus its own trailing "s") before
            # dropping it, or "patterson" survives the title as "pattersons".
            def _is_author_word(w):
                return w in author_tokens or (w.endswith("s") and w[:-1] in author_tokens)
            t = " ".join(w for w in t.split() if not _is_author_word(w))

    return t


def fuzzy_title_matches(titles_a, titles_b, threshold=FUZZY_TITLE_THRESHOLD):
    """Count how many titles in `titles_a` have a fuzzy match in `titles_b`
    (both are sets of already-normalize_title()'d strings).

    This replaces exact set intersection 
    Matching is greedy one-to-one (each title in `titles_b` can only be
    claimed once) so a single generic/repetitive title can't inflate the
    count by matching many things at once. 

    Biased toward ties go to "no match" (see `best_score = threshold - 1`
    below, so a candidate must strictly clear the threshold).

    Titles are matched to their single best available partner rather than counted
    as a hit against every title they're similar to.
    """
    if not titles_a or not titles_b:
        return 0

    a_list = list(titles_a)
    b_list = list(titles_b)

    # token sort ratio penalizes out of order tokens
    scores = process.cdist(a_list, b_list, scorer=fuzz.token_sort_ratio)

    used_b = set()
    matches = 0
    for i in range(len(a_list)):
        best_j, best_score = None, threshold - 1
        for j in range(len(b_list)):
            if j in used_b:
                continue
            if scores[i][j] > best_score:
                best_j, best_score = j, scores[i][j]
        if best_j is not None:
            used_b.add(best_j)
            matches += 1
    return matches


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


def name_variant_remap(name_totals):
    """Collapse author records that are the same person under different name
    FORMS -- "Pilkey, Dav" + "dav pilkey, 1966", "Mandel, Emily St. John" +
    "emily st john mandel, 1979" -- which the fuzzy pass can leave split (it
    reliably clusters most spellings but systematically misses the plain
    inverted form, splitting ~20k authors' checkouts across two records).

    Groups names that share the SAME set of word tokens (case-, order-, and
    life-date-insensitive) and maps each to the highest-total form. Refuses to
    merge a group whose members carry conflicting BIRTH years (first 4-digit
    year), since that marks two different people ("george michael, 1963" vs
    "michael george, 1947") -- ~15 such groups exist and are left alone.

    `name_totals` is an iterable of (name, total_checkouts). Returns a dict
    {variant_name: representative_name}, listing only names that should move
    (identity mappings omitted). This is a pure, deterministic rule with no I/O:
    build_data.py imports and applies it at build time, so the logic lives here
    with the rest of the clustering yet runs on every rebuild -- no need to
    regenerate author_map.json to keep it current.
    """
    import collections
    import re as _re

    def toks(name):
        # Drop parenthetical name-expansions ("Salinger, J. D. (Jerome David)")
        # before tokenizing, so a record that spells the initials out doesn't split
        # from the plain-initials form of the same author.
        name = _re.sub(r"\([^)]*\)", " ", name)
        return " ".join(sorted(
            t for t in _re.findall(r"[a-z0-9]+", name.lower())
            if not _re.fullmatch(r"\d{4}", t)))

    def birth_year(name):
        m = _re.findall(r"\d{4}", name)
        return m[0] if m else None

    groups = collections.defaultdict(list)
    for name, total in name_totals:
        key = toks(name)
        if key:
            groups[key].append((name, int(total or 0)))

    remap = {}
    for members in groups.values():
        if len(members) < 2:
            continue
        births = {birth_year(n) for n, _ in members if birth_year(n)}
        if len(births) > 1:
            continue  # conflicting birth years -> likely different people
        rep = max(members, key=lambda m: m[1])[0]
        for name, _ in members:
            if name != rep:
                remap[name] = rep
    return remap


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
            display_titles.setdefault(d, set()).add(normalize_title(title, author=name))

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
        if len(dated) == 1:
            # Exactly one dated person carries this name, so the undated spelling
            # is unambiguously them (the catalog just left the year off some
            # records). Merge without needing title overlap -- otherwise "James
            # Thurber" stays split from "Thurber, James, 1894-1961" whenever their
            # title sets don't happen to fuzzy-match.
            uf.union(u, dated[0])
        else:
            # Several DIFFERENT dated people share this normalized name, so the
            # undated spelling is ambiguous -- only merge it into whichever one it
            # actually shares a title with.
            best, best_overlap = None, 0
            for d in dated:
                overlap = fuzzy_title_matches(entities[u]["titles"], entities[d]["titles"])
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
    # middle name/initial like "Octavia Butler" vs "Octavia E. Butler"
    buckets = {}
    for canonical, info in stage1_info.items():
        key = first_last_key(info["norm"])
        if key is not None:
            buckets.setdefault(("fl", key), []).append(canonical)
        tkey = token_set_key(info["norm"])
        if tkey is not None:
            buckets.setdefault(("ts", tkey), []).append(canonical)

    uf2 = UnionFind(stage1_info.keys())
    for members in buckets.values():
        if len(members) < 2:
            continue
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                a, b = members[i], members[j]
                # Two records that both carry a birth year, and DIFFERENT ones,
                # are different people who happen to share a name ("Bradford,
                # Richard, 1932-" vs "1957-") -- never merge them, even on a
                # shared title (a fuzzy title collision would otherwise fuse them).
                da, db = stage1_info[a]["date"], stage1_info[b]["date"]
                if da and db and da != db:
                    continue
                if fuzzy_title_matches(stage1_info[a]["titles"], stage1_info[b]["titles"]) > 0:
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