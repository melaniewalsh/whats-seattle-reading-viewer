#!/usr/bin/env python3
"""
Host the site's cover thumbnails on R2 instead of hot-linking Open Library:
Backlist Boomerangs (backlist.json) and the Most Borrowed lists
(top-works.json, the 5th column of each row).

build_backlist.py bakes an Open Library cover URL into every listed work, but
covers.openlibrary.org is slow to serve (a median ~4.6 s per image in a
2026-09 test, each a 320x500 "-L" image shown 54 px wide), so the page filled
in its covers over many seconds. This step:

  1. collects the Open Library cover ids in static/data/backlist.json and
     static/data/top-works.json,
  2. checks which ones are already on R2 (HEAD on the public URL; a cover id's
     image never changes, so once uploaded it's reused every month),
  3. downloads the missing ones at "-M" size (~180 px wide, ~10-20 KB) into
     static/cover-thumbs/ for the workflow to upload to R2 under covers/,
  4. rewrites each cover to the R2 URL (leaving the Open Library URL for any
     thumbnail that couldn't be fetched): each work's "c" in both copies of
     backlist.json, and each row's cover in top-works.json.

Besides speed, this keeps covers up when Open Library's cover server is down
(it hung for hours in October 2026).

The monthly data build's `rclone sync` must exclude covers/** so it doesn't
delete these.

Run AFTER build_data.py and build_backlist.py; the workflow then uploads
static/cover-thumbs/ (and top-works.json with the rest of static/data).
"""
import json
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
DATA_DIR = PROJECT / "static" / "data"
FILES = [DATA_DIR / "backlist.json", PROJECT / "static" / "backlist.json"]
THUMB_DIR = PROJECT / "static" / "cover-thumbs"
R2_PUBLIC = "https://pub-7559692ae8974bd6a6e7cc54db47a348.r2.dev"
UA = {"User-Agent": "whats-seattle-reading cover build (melwalsh@uw.edu)"}
OL_ID = re.compile(r"covers\.openlibrary\.org/b/id/(\d+)-[SML]\.jpg")


def r2_url(cid):
    return f"{R2_PUBLIC}/covers/{cid}-M.jpg"


def on_r2(cid):
    try:
        req = urllib.request.Request(r2_url(cid), method="HEAD", headers=UA)
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status == 200
    except Exception:
        return False


def fetch_thumb(cid):
    # ?default=false -> 404 instead of a blank placeholder when there's no image.
    url = f"https://covers.openlibrary.org/b/id/{cid}-M.jpg?default=false"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
            body = r.read()
        if len(body) < 1000:  # not a real cover
            return False
        (THUMB_DIR / f"{cid}-M.jpg").write_bytes(body)
        return True
    except Exception:
        return False


def host(ids):
    """The cover ids now on R2: already there, or downloaded for upload."""
    with ThreadPoolExecutor(max_workers=16) as ex:
        hosted = {cid for cid, ok in zip(ids, ex.map(on_r2, ids)) if ok}
    missing = [cid for cid in ids if cid not in hosted]
    print(f"  already on R2: {len(hosted)}; to download: {len(missing)}", flush=True)
    THUMB_DIR.mkdir(parents=True, exist_ok=True)
    fetched = set()
    if missing:
        with ThreadPoolExecutor(max_workers=6) as ex:
            for i, (cid, ok) in enumerate(zip(missing, ex.map(fetch_thumb, missing)), 1):
                if ok:
                    fetched.add(cid)
                if i % 200 == 0 or i == len(missing):
                    print(f"  [{i}/{len(missing)}] downloaded {len(fetched)}", flush=True)
    return hosted | fetched


def backlist():
    src = FILES[0] if FILES[0].exists() else FILES[1]
    data = json.loads(src.read_text())
    rows = [r for lst in data["data"].values() for r in lst]
    ids = sorted({m.group(1) for r in rows if r.get("c") for m in [OL_ID.search(r["c"])] if m})
    print(f"{len(ids)} Open Library cover ids in {src.name}", flush=True)
    good = host(ids)
    changed = 0
    for r in rows:
        m = OL_ID.search(r.get("c") or "")
        if m and m.group(1) in good:
            r["c"] = r2_url(m.group(1))
            changed += 1
    text = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    for f in FILES:
        if f.parent.is_dir():
            f.write_text(text)
    print(f"{changed}/{len(rows)} Backlist works now point at R2 thumbnails", flush=True)


def top_works():
    src = DATA_DIR / "top-works.json"
    if not src.exists():
        print("no top-works.json here; skipping the Most Borrowed covers", flush=True)
        return
    data = json.loads(src.read_text())
    rows = [r for g in data["data"].values() for lst in g.values() for r in lst if len(r) > 4 and r[4]]
    ids = sorted({m.group(1) for r in rows for m in [OL_ID.search(r[4])] if m})
    print(f"{len(ids)} Open Library cover ids in {src.name}", flush=True)
    good = host(ids)
    changed = 0
    for r in rows:
        m = OL_ID.search(r[4])
        if m and m.group(1) in good:
            r[4] = r2_url(m.group(1))
            changed += 1
    src.write_text(json.dumps(data, separators=(",", ":"), ensure_ascii=False))
    print(f"{changed}/{len(rows)} Most Borrowed rows now point at R2 thumbnails", flush=True)


def main():
    backlist()
    top_works()
    n = len(list(THUMB_DIR.glob("*.jpg"))) if THUMB_DIR.exists() else 0
    print(f"{n} new files in {THUMB_DIR.relative_to(PROJECT)}", flush=True)


if __name__ == "__main__":
    main()
