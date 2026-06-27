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
Write a JSON file at etl/author_map.json shaped like:

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
After you create etl/author_map.json, add a step there that replaces each
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
    python3 etl/cluster_authors.py
then re-run the main ETL:
    python3 etl/build_data.py
"""

import json
import re
from pathlib import Path

import duckdb

PROJECT_DIR = Path(__file__).resolve().parent.parent
RAW_CSV = PROJECT_DIR / "data" / "raw" / "Checkouts_by_Title_2018-2022_15-checkouts.csv"
OUT_MAP = PROJECT_DIR / "etl" / "author_map.json"


def clean_display(name: str) -> str:
    """The display name, matching how build_data.py cleans authors (drop the
    trailing life dates, keep case + punctuation). Map keys must be in THIS form
    so the ETL's CLUSTERING HOOK can match them."""
    return re.sub(r",\s*[0-9]{4}.*$", "", str(name)).strip()


def normalize(name: str) -> str:
    """A rough key for deciding two names are the same. STUDENT: make this smarter."""
    n = clean_display(name).lower()
    # TODO: flip "lastname, first" -> "first lastname"  (this is what merges
    #       "Octavia E. Butler" with "Butler, Octavia E." — the main task!)
    # TODO: strip middle initials? handle "Jr."? ignore accents?
    n = re.sub(r"[^a-z0-9 ]", "", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


def main():
    con = duckdb.connect()
    # Get each distinct raw author and their total checkouts.
    rows = con.execute(
        """
        SELECT Creator AS name, sum(Checkouts) AS total
        FROM read_csv_auto(?, ignore_errors=true)
        WHERE Creator IS NOT NULL
        GROUP BY Creator
        """,
        [str(RAW_CSV)],
    ).fetchall()

    # Several raw strings can share one display name (e.g. with/without dates).
    # Add up their checkouts per display name first.
    display_totals = {}
    for name, total in rows:
        d = clean_display(name)
        display_totals[d] = display_totals.get(d, 0) + int(total)

    # Group display names that share a normalized key; canonical = most-borrowed.
    groups = {}  # normalized_key -> list of (display_name, total)
    for display, total in display_totals.items():
        groups.setdefault(normalize(display), []).append((display, total))

    author_map = {}
    for members in groups.values():
        if len(members) < 2:
            continue  # nothing to merge
        canonical = max(members, key=lambda m: m[1])[0]  # most checkouts wins
        for display, _ in members:
            if display != canonical:
                author_map[display] = canonical

    OUT_MAP.write_text(json.dumps(author_map, indent=2, ensure_ascii=False))
    print(f"Wrote {len(author_map):,} name -> canonical mappings to {OUT_MAP}")
    print("Now run:  python3 etl/build_data.py")


if __name__ == "__main__":
    main()
