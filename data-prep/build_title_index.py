#!/usr/bin/env python3
"""Build a TITLE search index for the "By title" reverse-lookup tab.

Walks the already-built per-author files (static/data/authors/**/*.json) and emits
static/data/title-index.json: [[title, slug, author, total], ...] sorted by total
DESC, for every title above a checkout threshold. A high threshold keeps the index
small enough to load + substring-search in the browser (like the author index).

Editions of the same title (print / ebook / "(unabridged)") are merged so a title
appears once and resolves to its author. Run AFTER the author files exist.
"""
import glob
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "static" / "data"
OUT = ROOT / "title-index.json"
THRESHOLD = int(os.environ.get("TITLE_MIN_CHECKOUTS", "1000"))  # all-time checkouts


def clean(t):
    t = (t or "").split(" / ")[0]
    t = re.sub(r"\s*[:(]?\s*\bunabridged\b\s*\)?", "", t, flags=re.I)
    return re.sub(r"\s*[.,;/:]\s*$", "", t).strip()


def main():
    files = glob.glob(str(ROOT / "authors" / "**" / "*.json"), recursive=True)
    agg = {}  # (titleLower, slug) -> [display, slug, author, total]
    for f in files:
        try:
            d = json.loads(Path(f).read_text())
        except Exception:  # noqa: BLE001
            continue
        slug = os.path.basename(f)[:-5]
        author = d.get("name", "")
        for t in d.get("titles", []):
            tot = int(t.get("total", 0) or 0)
            if tot < THRESHOLD:
                continue
            disp = clean(t.get("title", ""))
            if not disp:
                continue
            key = (disp.lower(), slug)
            if key in agg:
                agg[key][3] += tot
            else:
                agg[key] = [disp, slug, author, tot]
    rows = sorted(agg.values(), key=lambda r: -r[3])
    OUT.write_text(json.dumps(rows, separators=(",", ":")))
    print(f"Wrote {OUT}: {len(rows):,} titles (>= {THRESHOLD} checkouts), "
          f"{OUT.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
