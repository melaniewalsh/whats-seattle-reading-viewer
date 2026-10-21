#!/usr/bin/env python3
"""
Bake the home page's "Most borrowed last month" strip into the site.

The strip shows five books, but used to download the whole rankings file
(top-works.json, ~2.6 MB) and then hot-link Open Library's large cover images
(slow -- see host_covers.py) before anything appeared. This writes just those
five rows to src/data/home-top.json, which the site bundles, so the strip
renders immediately.

Covers are pointed at the R2-hosted "-M" thumbnails (the same ones
host_covers.py makes for Backlist Boomerangs): reused when already on R2, else
downloaded into static/cover-thumbs/ for the workflow to upload, else left on
Open Library at "-M" size.

Run AFTER build_data.py (needs static/data/top-works.json). Use --src to read
another copy of top-works.json (e.g. one downloaded from R2).
"""
import argparse
import json
import re
from pathlib import Path

from host_covers import THUMB_DIR, fetch_thumb, on_r2, r2_url

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
OUT = PROJECT / "src" / "data" / "home-top.json"
OL_ID = re.compile(r"covers\.openlibrary\.org/b/id/(\d+)-[SML]\.jpg")
N = 5


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(PROJECT / "static" / "data" / "top-works.json"))
    # Off the CI runner nothing uploads static/cover-thumbs/, so don't point a
    # cover at R2 unless it's already there.
    ap.add_argument("--no-download", action="store_true")
    args = ap.parse_args()

    d = json.loads(Path(args.src).read_text())
    overall = d["data"]["All genres"]
    # The current year so far (e.g. "2026"), else all time.
    year = str(max(d.get("years") or [0]))
    period = year if overall.get(year) else "all"
    rows = [list(r) for r in overall.get(period, [])[:N]]

    THUMB_DIR.mkdir(parents=True, exist_ok=True)
    for r in rows:
        m = OL_ID.search(r[4] if len(r) > 4 and r[4] else "")
        if not m:
            continue
        cid = m.group(1)
        if on_r2(cid) or (not args.no_download and fetch_thumb(cid)):
            r[4] = r2_url(cid)
        else:
            r[4] = f"https://covers.openlibrary.org/b/id/{cid}-M.jpg"

    out = {"year": period if period != "all" else None, "latestMonth": d.get("latestMonth"), "rows": rows}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n")
    print(f"Wrote {OUT.relative_to(PROJECT)}: {period} through {out['latestMonth']}, "
          f"{len(rows)} books, {sum('r2.dev' in (r[4] or '') for r in rows)} covers on R2")


if __name__ == "__main__":
    main()
