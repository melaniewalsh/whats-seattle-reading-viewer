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


def norm_title(t):
    """Key form: main title only (drop ':' subtitle and '(' qualifiers), lowercased."""
    return clean(t).split(":")[0].split("(")[0].strip().lower()


def norm_author(a):
    """Order-insensitive author key so 'Rowling, J. K.' == 'J. K. Rowling'."""
    return " ".join(sorted(re.findall(r"[a-z0-9]+", (a or "").lower())))


def main():
    files = glob.glob(str(ROOT / "authors" / "**" / "*.json"), recursive=True)
    # Collapse a book's edition/title-string variants AND an author's split
    # name-variant files into ONE entry, resolving to the highest-total file.
    agg = {}  # (normTitle, normAuthor) -> {total, best:(tot, display, slug, author)}
    for f in files:
        try:
            d = json.loads(Path(f).read_text())
        except Exception:  # noqa: BLE001
            continue
        slug = os.path.basename(f)[:-5]
        author = d.get("name", "")
        for t in d.get("titles", []):
            tot = int(t.get("total", 0) or 0)
            if tot <= 0:
                continue
            disp = clean(t.get("title", ""))
            if not disp:
                continue
            key = (norm_title(disp), norm_author(author))
            e = agg.setdefault(key, {"total": 0, "best": None})
            e["total"] += tot
            if e["best"] is None or tot > e["best"][0]:
                e["best"] = (tot, disp, slug, author)
    # Apply the threshold to the MERGED total, not per edition: a book whose
    # checkouts are split across print / ebook / audiobook (e.g. 317 + 201 + 161
    # + 88) must still be searchable even if no single edition reaches it.
    rows = [[e["best"][1], e["best"][2], e["best"][3], e["total"]]
            for e in agg.values() if e["total"] >= THRESHOLD]
    rows.sort(key=lambda r: -r[3])
    OUT.write_text(json.dumps(rows, separators=(",", ":")))
    print(f"Wrote {OUT}: {len(rows):,} titles (>= {THRESHOLD} checkouts), "
          f"{OUT.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
