#!/usr/bin/env python3
"""
Precompute the default "All Seattle checkouts" overview series.

The landing view of the viewer is a library-wide checkouts line (with a
by-format stacked-area option). Computing it live from the Socrata API on every
page load takes a few seconds (it aggregates ~51M rows server-side), so instead
we bake it once into a tiny static file the app loads instantly.

The 2018-2022 window the app charts is historical and fixed, so this only needs
re-running if that month axis ever changes. Output shape matches getAllCheckouts
in src/components/db.js:

    { "total": [...], "print": [...], "ebook": [...], "audiobook": [...] }

Run:  python3 data-prep/build_overview.py
"""
import json
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
OUT = PROJECT / "static" / "overview.json"

# The overview must line up with the SAME month axis the deployed site uses,
# which is the meta.json in the R2 bucket (the full-history build), not the
# small local dev copy. Fetch that so overview.json covers every year.
R2_META = "https://pub-7559692ae8974bd6a6e7cc54db47a348.r2.dev/meta.json"
SODA = "https://data.seattle.gov/resource/tmmm-ytt6.json"
APP_TOKEN = "bHWsGtRFRP9x8Hl8lYivqM1hQ"
# SPL MaterialType -> the format bucket the app uses everywhere else.
FMT_BUCKET = {"BOOK": "print", "EBOOK": "ebook", "AUDIOBOOK": "audiobook"}


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "spl-overview-builder/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def load_months():
    return _get(R2_META)["months"]


def fetch_rows():
    # All years (the axis runs ~2006-2026), books/ebooks/audiobooks.
    params = urllib.parse.urlencode({
        "$select": "checkoutyear,checkoutmonth,materialtype,sum(checkouts) as total",
        "$where": "materialtype in('BOOK','EBOOK','AUDIOBOOK')",
        "$group": "checkoutyear,checkoutmonth,materialtype",
        "$limit": "50000",
        "$$app_token": APP_TOKEN,
    })
    return _get(f"{SODA}?{params}")


def main():
    months = load_months()
    idx = {m: i for i, m in enumerate(months)}
    out = {k: [0] * len(months) for k in ("total", "print", "ebook", "audiobook")}
    for row in fetch_rows():
        key = f"{row['checkoutyear']}-{int(row['checkoutmonth']):02d}"
        if key not in idx:
            continue
        i = idx[key]
        v = int(float(row.get("total", 0)))
        bucket = FMT_BUCKET.get(row.get("materialtype"))
        if bucket:
            out[bucket][i] += v
        out["total"][i] += v
    OUT.write_text(json.dumps(out, separators=(",", ":")))
    print(f"Wrote {OUT} — total {sum(out['total']):,} checkouts across {len(months)} months")


if __name__ == "__main__":
    main()
