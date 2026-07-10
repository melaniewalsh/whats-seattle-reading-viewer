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
META = PROJECT / "static" / "data" / "meta.json"
OUT = PROJECT / "static" / "overview.json"

SODA = "https://data.seattle.gov/resource/tmmm-ytt6.json"
APP_TOKEN = "bHWsGtRFRP9x8Hl8lYivqM1hQ"
# SPL MaterialType -> the format bucket the app uses everywhere else.
FMT_BUCKET = {"BOOK": "print", "EBOOK": "ebook", "AUDIOBOOK": "audiobook"}


def load_months():
    return json.loads(META.read_text())["months"]


def fetch_rows():
    params = urllib.parse.urlencode({
        "$select": "checkoutyear,checkoutmonth,materialtype,sum(checkouts) as total",
        "$where": "checkoutyear>=2018 and checkoutyear<=2022 and materialtype in('BOOK','EBOOK','AUDIOBOOK')",
        "$group": "checkoutyear,checkoutmonth,materialtype",
        "$limit": "5000",
        "$$app_token": APP_TOKEN,
    })
    with urllib.request.urlopen(f"{SODA}?{params}", timeout=60) as r:
        return json.load(r)


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
