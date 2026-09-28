#!/usr/bin/env python3
"""
Precompute the default "All Seattle checkouts" overview series.

The landing view of the viewer is a library-wide checkouts line (with a
by-format stacked-area option). Computing it live from the Socrata API on every
page load means aggregating ~51M rows server-side, which takes MINUTES (and
often times out), so we bake it into a tiny static file the app loads instantly.

The file must line up with the month axis the site uses (meta.json). That axis
grows by one month every time build-data-to-r2.yml runs, so this script runs as
part of that workflow, right after build_data.py, and its output is uploaded to
R2 next to meta.json. It is INCREMENTAL: months already in the previous output
are kept, and only the newest few months are (re)fetched -- a couple of seconds
instead of a multi-minute full aggregation. Pass --full to rebuild every month.

Output shape (read by getAllCheckouts in src/components/db.js):

    { "months": ["2006-01", ...],
      "total": [...], "print": [...], "ebook": [...], "audiobook": [...] }

Writes BOTH static/data/overview.json (uploaded to R2 with the rest of the
data) and static/overview.json (bundled with the site as a fallback).

Run:  python3 data-prep/build_overview.py [--full]
"""
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
DATA_DIR = PROJECT / "static" / "data"
OUT_DATA = DATA_DIR / "overview.json"       # -> R2 (via rclone sync of static/data/)
OUT_STATIC = PROJECT / "static" / "overview.json"  # -> bundled with the site
LOCAL_META = DATA_DIR / "meta.json"

# When there's no freshly built meta.json on disk (running locally without a
# data build), align to the deployed axis on R2 instead.
R2_META = "https://pub-7559692ae8974bd6a6e7cc54db47a348.r2.dev/meta.json"
SODA = "https://data.seattle.gov/resource/tmmm-ytt6.json"
APP_TOKEN = "bHWsGtRFRP9x8Hl8lYivqM1hQ"
# SPL MaterialType -> the format bucket the app uses everywhere else.
FMT_BUCKET = {"BOOK": "print", "EBOOK": "ebook", "AUDIOBOOK": "audiobook"}
KEYS = ("total", "print", "ebook", "audiobook")
# Always re-fetch this many of the newest already-known months, since SPL's
# figures for a recent month can still shift slightly after first publication.
REFRESH_TAIL = 2


def _get(url, timeout=600):
    req = urllib.request.Request(url, headers={"User-Agent": "spl-overview-builder/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def load_months():
    if LOCAL_META.exists():
        print(f"month axis: {LOCAL_META}")
        return json.loads(LOCAL_META.read_text())["months"]
    print(f"month axis: {R2_META}")
    return _get(R2_META)["months"]


def load_previous(months):
    """Previous output as {month: {total, print, ebook, audiobook}}, or {}."""
    for path in (OUT_DATA, OUT_STATIC):
        if not path.exists():
            continue
        try:
            prev = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        n = len(prev.get("total", []))
        if not n:
            continue
        # Older outputs had no "months" key; they were aligned to the axis
        # from index 0, so treat them as a prefix of the current axis.
        prev_months = prev.get("months") or months[:n]
        if len(prev_months) != n:
            continue
        print(f"previous output: {path} ({n} months)")
        return {m: {k: prev[k][i] for k in KEYS} for i, m in enumerate(prev_months)}
    return {}


def fetch_rows(where_extra=None):
    where = "materialtype in('BOOK','EBOOK','AUDIOBOOK')"
    if where_extra:
        where += f" AND ({where_extra})"
    params = urllib.parse.urlencode({
        "$select": "checkoutyear,checkoutmonth,materialtype,sum(checkouts) as total",
        "$where": where,
        "$group": "checkoutyear,checkoutmonth,materialtype",
        "$limit": "50000",
        "$$app_token": APP_TOKEN,
    })
    return _get(f"{SODA}?{params}")


def months_where(month_keys):
    """SoQL predicate selecting exactly these 'YYYY-MM' months."""
    parts = []
    for m in month_keys:
        y, mo = m.split("-")
        parts.append(f"(checkoutyear={int(y)} AND checkoutmonth={int(mo)})")
    return " OR ".join(parts)


def main():
    full = "--full" in sys.argv
    months = load_months()
    idx = {m: i for i, m in enumerate(months)}
    known = {} if full else load_previous(months)

    missing = [m for m in months if m not in known]
    # Also refresh the newest few months we already have.
    have = [m for m in months if m in known]
    refresh = have[-REFRESH_TAIL:] if have else []
    todo = sorted(set(missing) | set(refresh))

    out = {k: [0] * len(months) for k in KEYS}
    for m, vals in known.items():
        if m in idx and m not in todo:
            for k in KEYS:
                out[k][idx[m]] = vals[k]

    if todo:
        if len(todo) == len(months):
            print(f"fetching all {len(months)} months (full aggregation, this takes a while)...")
            rows = fetch_rows()
        else:
            print(f"fetching {len(todo)} months: {todo[0]} .. {todo[-1]}")
            rows = fetch_rows(months_where(todo))
        for row in rows:
            key = f"{row['checkoutyear']}-{int(row['checkoutmonth']):02d}"
            if key not in idx or key not in todo:
                continue
            i = idx[key]
            v = int(float(row.get("total", 0)))
            bucket = FMT_BUCKET.get(row.get("materialtype"))
            if bucket:
                out[bucket][i] += v
            out["total"][i] += v
    else:
        print("nothing to fetch -- previous output already covers the month axis")

    out = {"months": months, **out}
    text = json.dumps(out, separators=(",", ":"))
    OUT_STATIC.write_text(text)
    written = [OUT_STATIC]
    if DATA_DIR.is_dir():
        OUT_DATA.write_text(text)
        written.append(OUT_DATA)
    for p in written:
        print(f"Wrote {p}")
    print(f"total {sum(out['total']):,} checkouts across {len(months)} months "
          f"({months[0]} .. {months[-1]})")


if __name__ == "__main__":
    main()
