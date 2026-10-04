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
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "static" / "data"
OUT = ROOT / "title-index.json"
THRESHOLD = int(os.environ.get("TITLE_MIN_CHECKOUTS", "1000"))  # all-time checkouts


def clean(t):
    t = (t or "").split(" / ")[0]
    t = re.sub(r"\s*[:(]?\s*\bunabridged\b\s*\)?", "", t, flags=re.I)
    return re.sub(r"\s*[.,;/:]\s*$", "", t).strip()


NOISE = re.compile(
    r"(book|bk|series|volume|vol|part|edition|unabridged|abridged|screenplay|read by|narrated|"
    r"illustrated|deluxe|anniversary|collector|special|movie|film|adapted|reissue|boxe?d? ?set|"
    r"complete|novel|novella|memoir|thriller|mystery|story|stories|tale|tales|romance|biography|"
    r"autobiography|poems|essays|playscript|litrpg|gamelit|\bscript\b|\bproduction|\bserie|"
    r"\blivre|\btome|\blibro|\btomo|\bedicion)",
    re.I,
)


def norm_title(t):
    """Work key -- the same rules as normalizeWorkKey in src/utils/workTitle.js,
    so search lists a book once ("Moby Dick" == "Moby-Dick, or, The whale")
    exactly as the book's own page groups its editions."""
    t = unicodedata.normalize("NFD", (t or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.split(" / ")[0]
    if re.search(r"\s=\s", t):
        t = re.split(r"\s=\s", t)[-1]
    t = re.sub(r",\s+or,\s+.*$", "", t, flags=re.I)
    t = t.replace("&", " and ")
    t = re.sub(r"\([^)]*\)", " ", t)
    t = re.sub(r"\s*\([^)]*$", " ", t)
    t = re.sub(r"\[[^\]]*\]", " ", t)
    t = re.sub(r"[,\s]+part\s+(\d+|one|two|three|four|five|six|seven|eight|nine|ten|i{1,3})\b.*$", " ", t, flags=re.I)
    while True:
        prev = t
        t = re.sub(
            r"[:;]\s*[^:;]*$",
            lambda m: " " if (NOISE.search(m.group(0)) or re.search(r"[:;]\s*or[\s,]", m.group(0), re.I)) else m.group(0),
            t,
        )
        if t == prev:
            break
    t = re.sub(r"\b(unabridged|abridged|audiobook|e-?book|large print|compact disc|sound recording)\b", " ", t)
    t = re.sub(r"\b(the|a|an)\b", " ", t)
    t = re.sub(r"['\u2019]", "", t)
    return re.sub(r"[^a-z0-9]+", "", t)


def bare_aliases(titles):
    """A bare title and its ONE subtitled version are the same work ("Freakonomics"
    == "Freakonomics: A Rogue Economist ..."); several subtitled versions mean a
    series ("Fancy Nancy: ..."), left apart. Same rule as bareTitleAliases in
    src/utils/workTitle.js. Returns {bare key: subtitled key}."""
    keys = {norm_title(clean(t)) for t in titles}
    subs = {}
    for t in titles:
        main = (t or "").split(" / ")[0]
        if ":" not in main:
            continue
        bare = norm_title(clean(main.split(":", 1)[0]))
        k = norm_title(clean(t))
        if bare and bare != k:
            subs.setdefault(bare, set()).add(k)
    return {b: next(iter(v)) for b, v in subs.items() if b in keys and len(v) == 1}


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
        aliases = bare_aliases([t.get("title", "") for t in d.get("titles", [])])
        for t in d.get("titles", []):
            tot = int(t.get("total", 0) or 0)
            if tot <= 0:
                continue
            disp = clean(t.get("title", ""))
            if not disp:
                continue
            k = norm_title(disp)
            key = (aliases.get(k, k), norm_author(author))
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
