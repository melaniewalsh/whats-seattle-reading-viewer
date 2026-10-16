#!/usr/bin/env python3
"""Fetch one author's monthly Seattle Public Library checkouts from the public
data (hosted on Cloudflare R2) and print their time series.

Usage:
    python examples/fetch_author.py "james baldwin"

Requires: requests  (pip install requests)

Data layout on R2:
  meta.json                        {"months": ["2005-04", ...]}  -- the shared x-axis
  search-index.json                [[slug, name, total], ...]    -- every author
  authors/<slug[:2]>/<slug>.json   one author: total series + per-title breakdown

Author slugs are normalized and may carry a
disambiguating year, e.g. "james-baldwin-1924", so you need to look up the slug in
search-index.json rather than guessing it. 

"""
import sys
import requests

BASE = "https://pub-7559692ae8974bd6a6e7cc54db47a348.r2.dev"


def main(query: str) -> None:
    months = requests.get(f"{BASE}/meta.json", timeout=30).json()["months"]
    index = requests.get(f"{BASE}/search-index.json", timeout=60).json()

    # Names in the index are lowercased canonical forms; match on a substring.
    q = query.lower()
    match = next(((slug, name, total) for slug, name, total in index if q in name), None)
    if not match:
        sys.exit(f"No author matching {query!r} in the index.")
    slug, name, total = match

    author = requests.get(f"{BASE}/authors/{slug[:2]}/{slug}.json", timeout=30).json()

    # Expand the sparse [[monthIndex, count], ...] series against the month axis.
    counts = [0] * len(months)
    for i, c in author["series"]:
        counts[i] = c

    print(f"{author['name']} — {total:,} checkouts all-time")
    for ym, c in zip(months, counts):
        if c:
            print(f"  {ym}\t{c}")

    # Each author file also has `titles` (per-title breakdown, same sparse
    # encoding), `variants` (raw name spellings merged into this author), and
    # `subjects`. To pull the whole corpus instead, download the tarball from the
    # repository's Releases page rather than looping every slug here.


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "james baldwin")
