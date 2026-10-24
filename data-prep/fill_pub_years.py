#!/usr/bin/env python3
"""
Original publication years for the books in the rankings, from Wikipedia /
Wikidata, so the site can show "Parable of the Sower (1993)".

For each work it searches Wikipedia for "title author", keeps a page only if
its title matches the book and its short description or Wikidata author
names the right author, and takes the earliest publication date (Wikidata
P577), else a year at the start of the description ("1993 novel by ...").
Results are cached in data-prep/pubyear_cache.json, so each build only looks
up new books.

  python3 data-prep/fill_pub_years.py --find    # look up new works (network)
  python3 data-prep/fill_pub_years.py --apply   # add the year as a 6th column to
                                                # top-works.json and subject pages
"""
import argparse
import json
import re
import time
import unicodedata
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
CACHE = HERE / "pubyear_cache.json"
DATA = PROJECT / "static" / "data"
UA = {"User-Agent": "whats-seattle-reading build (melwalsh@uw.edu)"}
WIKI = "https://en.wikipedia.org/w/api.php"
WIKIDATA = "https://www.wikidata.org/w/api.php"
STOP = {"a", "an", "the", "and", "of", "to", "in", "for", "novel", "book"}


def key(title, author):
    return f"{title}\t{author or ''}"


def tokens(s):
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return [w for w in re.sub(r"[^a-z0-9 ]+", " ", s).split() if w not in STOP]


def main_title(t):
    """'The Swimmers: A novel / Julie Otsuka' -> 'The Swimmers'."""
    t = (t or "").split(" / ")[0]
    t = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", t)
    return re.split(r"[:;]", t)[0].strip()


def surname(author):
    a = re.sub(r",?\s*\d{4}.*$", "", author or "").strip()
    parts = [p for p in re.split(r"[\s,]+", a) if p]
    return tokens(parts[-1])[0] if parts and tokens(parts[-1]) else ""


def get_json(url, params):
    for attempt in range(3):
        try:
            req = urllib.request.Request(url + "?" + urllib.parse.urlencode(params), headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode())
        except Exception:  # noqa: BLE001
            time.sleep(2 * (attempt + 1))
    return None


ADAPTATION = re.compile(r"\b(film|translation|tv|television|series|miniseries|album|song|musical|opera|video game|play|episode|soundtrack)\b", re.I)


def title_matches(want, page_title):
    w, got = tokens(want), set(tokens(re.sub(r"\([^)]*\)", " ", page_title)))
    return bool(w) and sum(x in got for x in w) / len(w) >= 0.8 and len(got - set(w)) <= 2


def wikidata_year_and_authors(qid):
    d = get_json(WIKIDATA, {"action": "wbgetentities", "ids": qid, "props": "claims", "format": "json"}) or {}
    claims = (d.get("entities", {}).get(qid, {}) or {}).get("claims", {})
    years = []
    for c in claims.get("P577", []):
        t = (((c.get("mainsnak") or {}).get("datavalue") or {}).get("value") or {}).get("time", "")
        m = re.match(r"[+](\d{4})", t)
        if m:
            years.append(int(m.group(1)))
    authors = [((c.get("mainsnak") or {}).get("datavalue") or {}).get("value", {}).get("id") for c in claims.get("P50", [])]
    return (min(years) if years else None), [a for a in authors if a]


def author_labels(qids):
    if not qids:
        return []
    d = get_json(WIKIDATA, {"action": "wbgetentities", "ids": "|".join(qids[:20]), "props": "labels", "languages": "en", "format": "json"}) or {}
    return [((e.get("labels") or {}).get("en") or {}).get("value", "") for e in d.get("entities", {}).values()]


def find_one(k):
    title, author = k.split("\t")
    want, sn = main_title(title), surname(author)
    if not want:
        return k, None
    d = get_json(WIKI, {"action": "query", "format": "json", "generator": "search", "gsrsearch": f"{want} {sn}".strip(),
                        "gsrlimit": "5", "prop": "pageprops|description", "ppprop": "wikibase_item"}) or {}
    pages = sorted((d.get("query") or {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
    for p in pages:
        if not title_matches(want, p.get("title", "")):
            continue
        desc = p.get("description", "") or ""
        paren = " ".join(re.findall(r"\(([^)]*)\)", p.get("title", "")))
        if ADAPTATION.search(paren) or ADAPTATION.search(desc.split(" by ")[0]):
            continue  # a film, translation or other adaptation, not the book
        qid = (p.get("pageprops") or {}).get("wikibase_item")
        year, authors = wikidata_year_and_authors(qid) if qid else (None, [])
        ok = bool(sn) and sn in tokens(desc)
        if not ok and sn and authors:
            ok = any(sn in tokens(lbl) for lbl in author_labels(authors))
        if not ok:
            continue
        if year is None:
            m = re.match(r"^(\d{4})\b", desc)
            year = int(m.group(1)) if m else None
        # The best matching page decides: no year there means no year (not a
        # later page's, e.g. a translation's).
        return k, (year if year and 1000 < year <= 2100 else None)
    return k, None


def works():
    out = set()
    tw = DATA / "top-works.json"
    if tw.exists():
        d = json.loads(tw.read_text())
        out |= {(r[0], r[1]) for g in d["data"].values() for lst in g.values() for r in lst}
    return out


def find(limit=None):
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    todo = sorted(key(*w) for w in works() if key(*w) not in cache)
    todo = todo[:limit] if limit else todo
    print(f"{len(todo)} works to look up", flush=True)
    found = 0
    with ThreadPoolExecutor(max_workers=6) as ex:
        for i, (k, y) in enumerate(ex.map(find_one, todo), 1):
            cache[k] = y
            found += bool(y)
            if i % 250 == 0 or i == len(todo):
                print(f"  [{i}/{len(todo)}] found {found}", flush=True)
                CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=0, sort_keys=True) + "\n")
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=0, sort_keys=True) + "\n")
    print(f"found years for {found} of {len(todo)}", flush=True)


def apply():
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}

    def patch(rows):
        n = 0
        for r in rows:
            y = cache.get(key(r[0], r[1]))
            while len(r) < 5:
                r.append(None)
            if len(r) == 5:
                r.append(y)
            else:
                r[5] = y
            n += bool(y)
        return n

    tw = DATA / "top-works.json"
    if tw.exists():
        d = json.loads(tw.read_text())
        n = patch([r for g in d["data"].values() for lst in g.values() for r in lst])
        tw.write_text(json.dumps(d, separators=(",", ":"), ensure_ascii=False))
        print(f"top-works.json: {n} rows with a publication year", flush=True)
    sdir = DATA / "subjects"
    if sdir.is_dir():
        n = 0
        for f in sdir.glob("*.json"):
            d = json.loads(f.read_text())
            n += patch(d.get("rows", []))
            f.write_text(json.dumps(d, separators=(",", ":"), ensure_ascii=False))
        print(f"subject pages: {n} rows with a publication year", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--find", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    if a.find:
        find(a.limit)
    if a.apply:
        apply()
