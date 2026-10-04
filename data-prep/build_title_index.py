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
# Co-written books filed under ANOTHER author, per co-author (see coauthor_names).
COAUTH_OUT = ROOT / "coauthors.json"
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


# Edition wording in the main title -- same rule as EDITION_WORDS in
# src/utils/workTitle.js ("Freakonomics Revised and Expanded" == "Freakonomics").
EDITION_WORDS = re.compile(
    r"^([^:;]*?)[\s,]+(?:revised and (?:expanded|updated)|revised(?: and updated)? edition|expanded(?: and updated)? edition|updated edition|new edition|special edition|deluxe edition|collector'?s edition|illustrated edition|(?:\d+(?:st|nd|rd|th)|tenth|fifteenth|twentieth|twenty-fifth|thirtieth|fortieth|fiftieth|seventy-fifth|hundredth) anniversary edition|anniversary edition|movie tie-in(?: edition)?|tie-in edition|young readers'? edition)(?=\s*(?:[:;(]|$))",
    re.I,
)


def norm_title(t):
    """Work key -- the same rules as normalizeWorkKey in src/utils/workTitle.js,
    so search lists a book once ("Moby Dick" == "Moby-Dick, or, The whale")
    exactly as the book's own page groups its editions."""
    t = unicodedata.normalize("NFD", (t or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.split(" / ")[0]
    t = EDITION_WORDS.sub(r"\1", t)
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


NAME_RE = re.compile(r"^[A-Z][\w.'\u2019-]*(\s+[A-Z][\w.'\u2019-]*){1,3}$")


def coauthor_names(raw_title, surname):
    """All the authors in a record's credit line ("Freakonomics ... / Steven D.
    Levitt and Stephen J. Dubner."), when it names several, including this file's
    author (by surname). Same rule as bookAuthors in StackedViewer.svelte."""
    if " / " not in (raw_title or ""):
        return None
    line = raw_title.split(" / ", 1)[1].split(";")[0]
    line = re.sub(r"^(written |story )?by\s+", "", line, flags=re.I)
    line = re.sub(r"[.\s]+$", "", line).strip()
    if re.search(r"illustrat|translat|edited|editor|introduc|foreword|with ", line, re.I):
        return None
    names = [n.strip() for n in re.split(r"\s*,\s*(?:and\s+|&\s+)?|\s+and\s+|\s+&\s+", line) if n.strip()]
    if not 2 <= len(names) <= 4 or not all(NAME_RE.match(n) for n in names):
        return None
    if not any(surname in n.lower() for n in names):
        return None
    return tuple(names)


def name_key(n):
    """'Stephen J. Dubner' / 'stephen j dubner, 1963' -> 'stephen j dubner'."""
    return " ".join(re.findall(r"[a-z]+", (n or "").split(",")[0].lower()))


def norm_author(a):
    """Order-insensitive author key so 'Rowling, J. K.' == 'J. K. Rowling'."""
    return " ".join(sorted(re.findall(r"[a-z0-9]+", (a or "").lower())))


def main():
    files = glob.glob(str(ROOT / "authors" / "**" / "*.json"), recursive=True)
    # Collapse a book's edition/title-string variants AND an author's split
    # name-variant files into ONE entry, resolving to the highest-total file.
    agg = {}  # (normTitle, normAuthor) -> {total, best:(tot, display, slug, author)}
    # Co-authors: name -> author slug, from the author index (bigger wins).
    slug_by_name = {}
    try:
        for r in json.loads((ROOT / "search-index.json").read_text()):
            k = name_key(r[1])
            if k and (k not in slug_by_name or r[2] > slug_by_name[k][1]):
                slug_by_name[k] = (r[0], r[2])
    except Exception:  # noqa: BLE001
        pass
    coauth = {}  # co-author slug -> {(title, primary slug): [primary name, total]}
    # The site's curated groupings (src/data/work-overrides.json: {slug: [[title,
    # ...], ...]}) -- e.g. all 72 "Adventures of Sherlock Holmes" volumes -- so
    # search lists those books once, too.
    try:
        overrides = json.loads((Path(__file__).resolve().parent.parent / "src" / "data" / "work-overrides.json").read_text())
    except Exception:  # noqa: BLE001
        overrides = {}
    for f in files:
        try:
            d = json.loads(Path(f).read_text())
        except Exception:  # noqa: BLE001
            continue
        slug = os.path.basename(f)[:-5]
        author = d.get("name", "")
        aliases = bare_aliases([t.get("title", "") for t in d.get("titles", [])])
        # Curated groupings: every listed title takes its group's first title's key.
        for group in overrides.get(slug, []) or []:
            if group:
                head = norm_title(clean(group[0]))
                for title in group:
                    k0 = norm_title(clean(title))
                    if k0 and k0 != head:
                        aliases[k0] = head
        surname = (author.split(",")[0].split() or [""])[-1].lower()
        works = {}  # work key -> [total, best (tot, display), Counter of credit lines]
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
            w = works.setdefault(key[0], [0, None, {}])
            w[0] += tot
            if w[1] is None or tot > w[1][0]:
                w[1] = (tot, disp)
            names = coauthor_names(t.get("title", ""), surname)
            if names:
                w[2][names] = w[2].get(names, 0) + 1
        for total, best, lines in works.values():
            if not lines or total < 50:
                continue
            names = max(lines.items(), key=lambda kv: kv[1])[0]
            for n in names:
                hit = slug_by_name.get(name_key(n))
                if not hit or hit[0] == slug or surname in n.lower():
                    continue
                coauth.setdefault(hit[0], {})[(best[1], slug)] = [author, total]
    # Apply the threshold to the MERGED total, not per edition: a book whose
    # checkouts are split across print / ebook / audiobook (e.g. 317 + 201 + 161
    # + 88) must still be searchable even if no single edition reaches it.
    rows = [[e["best"][1], e["best"][2], e["best"][3], e["total"]]
            for e in agg.values() if e["total"] >= THRESHOLD]
    rows.sort(key=lambda r: -r[3])
    OUT.write_text(json.dumps(rows, separators=(",", ":")))
    # Each co-author's top co-written books filed under someone else:
    # {slug: [[title, primary author slug, primary author name, checkouts], ...]}
    co_out = {
        cs: [[t, ps, nm, tot] for (t, ps), (nm, tot) in sorted(books.items(), key=lambda kv: -kv[1][1])[:12]]
        for cs, books in coauth.items()
    }
    COAUTH_OUT.write_text(json.dumps(co_out, separators=(",", ":"), ensure_ascii=False))
    print(f"Wrote {COAUTH_OUT}: co-written books for {len(co_out):,} authors, "
          f"{COAUTH_OUT.stat().st_size // 1024} KB")
    print(f"Wrote {OUT}: {len(rows):,} titles (>= {THRESHOLD} checkouts), "
          f"{OUT.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
