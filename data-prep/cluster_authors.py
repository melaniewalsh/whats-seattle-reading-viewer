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

import json
import re
from pathlib import Path
import duckdb
from time import perf_counter


PROJECT_DIR = Path(__file__).resolve().parent.parent
RAW_CSV = PROJECT_DIR / "data" / "raw" / "spl-monthly-checkouts_2005-2025.csv"
OUT_MAP = PROJECT_DIR / "data-prep" / "author_map.json"

"""
def clean_display(name: str) -> str:
    The display name, matching how build_data.py cleans authors (drop the
    trailing life dates, keep case + punctuation). Map keys must be in THIS form
    so the build script's CLUSTERING HOOK can match them.
    #return re.sub(r",\s*[0-9]{4}.*$", "", str(name)).strip()
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
    tokens = name_tokens(name)
    if len(tokens) < 2:
        return None
    return (tokens[0], tokens[-1])


def has_middle_name(name: str) -> bool:
    return len(name_tokens(name)) > 2


def normalize_title(title: str) -> str:
    t = str(title or "").lower().strip()
    t = re.sub(r"[^a-z0-9\s]", "", t)
    t = re.sub(r"\s+", " ", t).strip()
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
    # Get each distinct raw author/title pair and total checkouts.
    rows = con.execute(
        """
        SELECT Creator AS name, Title AS title, sum(Checkouts) AS total
        FROM read_csv_auto(?, ignore_errors=true)
        WHERE Creator IS NOT NULL
        GROUP BY Creator, Title
        """,
        [str(RAW_CSV)],
    ).fetchall()

    # Several raw rows can share one display name add up their checkouts and collect their titles per display name first
    display_totals = {}
    display_titles = {}
    for name, title, total in rows:
        #d = clean_display(name)
        d = name
        display_totals[d] = display_totals.get(d, 0) + int(total)
        if title:
            display_titles.setdefault(d, set()).add(normalize_title(title))

    # canonical = most borrowed spelling in each group.
    groups = {}  # normalized_key to list of (display_name, total)
    for display, total in display_totals.items():
        groups.setdefault(normalize(display), []).append((display, total))

    raw_to_pass1 = {}      # raw display name to pass-1 canonical
    entities = {}          # pass-1 canonical
    for members in groups.values():
        canonical = max(members, key=lambda m: m[1])[0]  # most checkouts wins
        checkouts = sum(total for _, total in members)
        titles = set()
        for display, _ in members:
            raw_to_pass1[display] = canonical
            titles |= display_titles.get(display, set())
        entities[canonical] = {"checkouts": checkouts, "titles": titles}

    """
    normalize() can fail to merge spellings that differ only by a middle
    name/initial (ex"Octavia Butler" vs "Octavia E. Butler").
    confirm they're the same person by checking for an overlapping title,
    then merge using the middle name spelling
    """
    buckets = {}  # list of pass-1 canonical names
    for canonical in entities:
        key = first_last_key(canonical)
        if key is not None:
            buckets.setdefault(key, []).append(canonical)

    #checks for same titles
    uf = UnionFind(entities.keys())
    for members in buckets.values():
        if len(members) < 2:
            continue
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                a, b = members[i], members[j]
                if entities[a]["titles"] & entities[b]["titles"]:
                    uf.union(a, b)

    # build final canonical middle name break ties by checkouts.
    components = {}  #root to list of pass-1 canonical names
    for canonical in entities:
        components.setdefault(uf.find(canonical), []).append(canonical)

    pass1_to_final = {}
    for members in components.values():
        with_middle = [m for m in members if has_middle_name(m)]
        candidates = with_middle if with_middle else members
        final_canonical = max(candidates, key=lambda m: entities[m]["checkouts"])
        for m in members:
            pass1_to_final[m] = final_canonical

    author_map = {}
    for raw, pass1_canonical in raw_to_pass1.items():
        final_canonical = pass1_to_final[pass1_canonical]
        if raw != final_canonical:
            author_map[raw] = final_canonical

    OUT_MAP.write_text(json.dumps(author_map, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f"Wrote {len(author_map):,} name -> canonical mappings to {OUT_MAP}")
    print("Now run:  python3 data-prep/build_data.py")
    end_time = perf_counter()
    elapsed_time = end_time - start_time
    print(f"Elapsed time: {elapsed_time:.4f} seconds")


if __name__ == "__main__":
    main()
