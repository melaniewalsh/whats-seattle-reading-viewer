#!/usr/bin/env python3
"""
Find covers for the books the site shows without one, and record them in
data-prep/cover_cache.json (which the monthly build bakes into the rankings).

Most misses are series volumes whose catalog titles confuse Open Library's
search ("Babymouse. [7], Skater girl", "Naruto. Vol. 11, Impassioned efforts"),
or books whose lookup failed while Open Library was down and was cached as
"no cover". For each one this tidies the title, tries Open Library again, then
Apple Books, then Google Books, and only accepts a result whose title, author and volume number
match.

  python3 data-prep/fill_missing_covers.py --find    # look up misses (network), update the cache
  python3 data-prep/fill_missing_covers.py --apply   # write cached covers into static/data/top-works.json
                                                     # and backlist.json (no network)
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
CACHE = HERE / "cover_cache.json"
DATA = PROJECT / "static" / "data"
BACKLIST = [DATA / "backlist.json", PROJECT / "static" / "backlist.json"]
UA = {"User-Agent": "whats-seattle-reading cover build (melwalsh@uw.edu)"}
STOP = {"a", "an", "the", "and", "or", "of", "to", "in", "for", "is", "vol", "volume", "book"}


def key(title, author):
    return f"{title}\t{author or ''}"


def clean_title(t):
    """'Babymouse. [7], Skater girl' -> 'Babymouse 7 Skater girl';
    'Naruto. Vol. 11, Impassioned efforts' -> 'Naruto 11 Impassioned efforts'."""
    t = (t or "").split(" / ")[0]
    # Older records put the credits in the title: "A fly went by, by Mike
    # McClintock. Illustrated by ...", "Snow [by] Roy McKie and ...".
    t = re.split(r",\s+by\s|\.\s+Illustrated by|\s\[by\]\s", t, flags=re.I)[0]
    t = re.split(r"\s=\s", t)[0]
    t = re.sub(r"\[(?:\s*(?:vol(?:ume)?\.?|book|no\.?)\s*)?([0-9]+)[^\]]*\]", r" \1 ", t, flags=re.I)  # [7], [Volume 1, ...]
    t = re.sub(r"\[[^\]]*\]", " ", t)
    t = re.sub(r"\b(?:vol(?:ume)?|v|no|book|bk)\.?\s*(\d+)", r" \1", t, flags=re.I)
    t = re.sub(r"[:;,.\-–—()!?'\"]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def tokens(s):
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return [w for w in re.sub(r"[^a-z0-9 ]+", " ", s).split() if w not in STOP]


def surname(author):
    a = re.sub(r",?\s*\d{4}.*$", "", author or "").strip()
    parts = [p for p in re.split(r"[\s,]+", a) if p]
    return tokens(parts[-1])[0] if parts and tokens(parts[-1]) else ""


def split_volume(t):
    """'Babymouse 7 Skater girl' -> ('Babymouse', '7', 'Skater girl'); no number -> (t, '', '')."""
    m = re.match(r"^(.*?)\s(\d+)(?:\s(.*))?$", t)
    return (m.group(1), m.group(2), m.group(3) or "") if m else (t, "", "")


def matches(want_title, got_title, author, got_authors):
    sn = surname(author)
    if sn and not any(sn in tokens(a) for a in got_authors or []):
        return False
    got = set(tokens(got_title))
    series, num, sub = split_volume(want_title)
    cover = lambda words: bool(words) and sum(w in got for w in words) / len(words)
    if sub:  # a volume with its own title: that title matches, or series + number do
        return (cover(tokens(sub)) or 0) >= 0.8 or (num in got and (cover(tokens(series)) or 0) >= 0.75)
    if num and num not in got:  # a numbered volume without its own title: the number must match
        return False
    return (cover(tokens(series)) or 0) >= 0.75


def get_json(url):
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                return json.loads(r.read().decode())
        except Exception:  # noqa: BLE001
            time.sleep(2 * (attempt + 1))
    return None


def queries(title):
    """Search texts to try: the whole tidied title, the volume's own title, series + number."""
    series, num, sub = split_volume(title)
    out = [title] + ([sub] if sub else []) + ([f"{series} {num}"] if num else [])
    return list(dict.fromkeys(q for q in out if q))


def open_library(title, author):
    for text in queries(title):
        q = urllib.parse.urlencode({"q": text, "author": surname(author) or "", "limit": "10",
                                    "fields": "title,subtitle,author_name,cover_i"})
        d = get_json(f"https://openlibrary.org/search.json?{q}") or {}
        for doc in d.get("docs", []):
            full = " ".join(x for x in [doc.get("title"), doc.get("subtitle")] if x)
            if doc.get("cover_i") and matches(title, full, author, doc.get("author_name")):
                return f"https://covers.openlibrary.org/b/id/{doc['cover_i']}-L.jpg"
    return None


_apple_lock = __import__("threading").Lock()
_apple_last = [0.0]


def apple_books(title, author):
    """Apple Books search (no key; about 20 requests a minute, so calls are
    spaced out). Artwork is resized to 400 px on the long side."""
    series, num, sub = split_volume(title)
    term = f"{series} {sub}" if sub else f"{series} Vol. {num}" if num else series
    if surname(author):
        term += f" {surname(author)}"
    best = None
    for entity in ("ebook", "audiobook"):
        with _apple_lock:
            wait = 3.2 - (time.time() - _apple_last[0])
            if wait > 0:
                time.sleep(wait)
            _apple_last[0] = time.time()
        d = get_json("https://itunes.apple.com/search?" + urllib.parse.urlencode({"term": term, "entity": entity, "limit": "10"})) or {}
        for r in d.get("results", []):
            name = r.get("trackName") or r.get("collectionName") or ""
            art = r.get("artworkUrl100")
            if art and matches(title, name, author, [r.get("artistName") or ""]):
                extra = len(set(tokens(name)) - set(tokens(title)))  # prefer the closest title
                if best is None or extra < best[0]:
                    best = (extra, re.sub(r"/\d+x\d+bb\.", "/400x400bb.", art))
        if best:
            break
    return best[1] if best else None


def google_books(title, author):
    for text in queries(title):
        q = text + (f" inauthor:{surname(author)}" if surname(author) else "")
        d = get_json("https://www.googleapis.com/books/v1/volumes?" + urllib.parse.urlencode({"q": q, "maxResults": "10", "printType": "books"})) or {}
        for it in d.get("items", []):
            v = it.get("volumeInfo", {})
            img = (v.get("imageLinks") or {}).get("thumbnail")
            full = " ".join(x for x in [v.get("title"), v.get("subtitle")] if x)
            if img and matches(title, full, author, v.get("authors")):
                return f"https://books.google.com/books/content?id={it['id']}&printsec=frontcover&img=1&zoom=1"
    return None


def find_one(k):
    title, author = k.split("\t")
    t = clean_title(title)
    return k, open_library(t, author) or apple_books(t, author) or google_books(t, author)


def shown_works():
    """(title, author) of every book the rankings and Backlist show."""
    out = set()
    tw = DATA / "top-works.json"
    if tw.exists():
        d = json.loads(tw.read_text())
        out |= {(r[0], r[1]) for g in d["data"].values() for lst in g.values() for r in lst}
    return out


def find(limit=None):
    cache = json.loads(CACHE.read_text())
    todo = sorted(k for k, v in cache.items() if v is None)
    # Backlist Boomerangs finds its own covers; add the ones it couldn't.
    for f in BACKLIST:
        if f.exists():
            for lst in json.loads(f.read_text())["data"].values():
                for r in lst:
                    k = key(r.get("t"), r.get("a"))
                    if not r.get("c") and not cache.get(k) and k not in todo:
                        todo.append(k)
            break
    shown = {key(*w) for w in shown_works()}
    if shown:
        todo = [k for k in todo if k in shown] + [k for k in todo if k not in shown]
    todo = todo[:limit] if limit else todo
    print(f"{len(todo)} cached misses to retry", flush=True)
    found = 0
    with ThreadPoolExecutor(max_workers=4) as ex:
        for i, (k, url) in enumerate(ex.map(find_one, todo), 1):
            if url:
                cache[k] = url
                found += 1
            if i % 50 == 0 or i == len(todo):
                print(f"  [{i}/{len(todo)}] found {found}", flush=True)
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=0, sort_keys=True) + "\n")
    print(f"found covers for {found} of {len(todo)}", flush=True)


def apply():
    cache = json.loads(CACHE.read_text())
    tw = DATA / "top-works.json"
    if tw.exists():
        d = json.loads(tw.read_text())
        n = 0
        for g in d["data"].values():
            for lst in g.values():
                for r in lst:
                    if len(r) > 4 and not r[4] and cache.get(key(r[0], r[1])):
                        r[4] = cache[key(r[0], r[1])]
                        n += 1
        tw.write_text(json.dumps(d, separators=(",", ":"), ensure_ascii=False))
        print(f"top-works.json: filled {n} covers", flush=True)
    for f in BACKLIST:
        if not f.exists():
            continue
        d = json.loads(f.read_text())
        n = 0
        for lst in d["data"].values():
            for r in lst:
                if not r.get("c") and cache.get(key(r.get("t"), r.get("a"))):
                    r["c"] = cache[key(r.get("t"), r.get("a"))]
                    n += 1
        f.write_text(json.dumps(d, separators=(",", ":"), ensure_ascii=False))
        print(f"{f.name}: filled {n} covers", flush=True)


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
