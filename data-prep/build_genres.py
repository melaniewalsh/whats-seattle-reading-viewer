#!/usr/bin/env python3
"""
Precompute monthly genre trends for the "Genres" tab, WITH each term's own line.

A genre = subject-heading match terms (include/exclude, from a Google Sheet).
For each genre we run ONE query that returns, per month: the genre UNION count
(all its terms, de-duplicated) plus a conditional-sum count for EACH include
term. So the app can show the genre line and let users toggle individual TERM
lines on the chart -- all precomputed, instant. (A term's union with the genre
can't be summed from parts, hence the union column; individual term lines are
independent and just add to the chart.)

Output  static/genres.json:
    { "months":[...], "total":[...],                     # all-book checkouts / mo
      "genres":[ { "name","exclude",
                   "gated":bool,                           # fiction-gated? (see below)
                   "union":[...],                          # the genre line
                   "terms":[ {"term","count":[...]} ],     # each include-term line
                   "examples":[title,...] } ] }            # top-10 titles it catches

Run:  python3 data-prep/build_genres.py
"""
import csv
import io
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "static" / "genres.json"
R2_META = "https://pub-7559692ae8974bd6a6e7cc54db47a348.r2.dev/meta.json"
SODA = "https://data.seattle.gov/resource/tmmm-ytt6.json"
APP_TOKEN = "bHWsGtRFRP9x8Hl8lYivqM1hQ"
SHEET_CSV = ("https://docs.google.com/spreadsheets/d/e/2PACX-1vS_Y38KSWCcTtWEKOQ3d3"
             "NH1HHt0AhzHadjp-t-9dueexs94Ltk-73kfjrHixH1rle1pwMRxAgsPUZ-/pub?output=csv")
BOOK = ("((usageclass = 'Physical' AND materialtype = 'BOOK') OR "
        "(usageclass = 'Digital' AND upper(materialtype) IN ('EBOOK', 'AUDIOBOOK')))")

# Some genres are defined by generic English words that also appear inside
# unrelated subjects: 'elf' matches "s-ELF-Improvement", 'magic' matches
# "The Life-Changing Magic of Tidying Up". Requiring the book to ALSO carry a
# real Fiction subject tag removes that leak -- but the tag "Nonfiction" itself
# contains the substring "fiction", so we must explicitly exclude it.
FICTION_GATE = ("(upper(subjects) like '%FICTION%' "
                "AND upper(subjects) not like '%NONFICTION%' "
                "AND upper(subjects) not like '%NON-FICTION%')")
# Apply the gate ONLY to genre-fiction genres. Poetry (poems aren't tagged
# "fiction"), nonfiction genres (Memoirs, True crime), and format/audience
# genres (Comics, Graphic novels, Juvenile, YA) must NOT be gated -- there it
# over-prunes. Verified against top-title samples before turning each one on.
FICTION_GATED = {"Fantasy", "Romance", "Mystery", "Thriller", "Horror",
                 "Science Fiction", "Historical fiction"}


def _get(url, timeout=300, tries=4):
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "spl-genres-builder/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8")
        except Exception as e:  # noqa: BLE001
            last = e
            print(f"    retry {attempt + 1}/{tries} after: {e}", flush=True)
            time.sleep(5 * (attempt + 1))
    raise last


def _q(soql):
    return json.loads(_get(f"{SODA}?{urllib.parse.urlencode({'$query': soql, '$$app_token': APP_TOKEN})}"))


def load_months():
    return json.loads(_get(R2_META))["months"]


def load_genre_groups():
    rows = list(csv.DictReader(io.StringIO(_get(SHEET_CSV))))
    groups = {}
    for r in rows:
        genre, term = (r.get("genre") or "").strip(), (r.get("term") or "").strip()
        if not genre or not term:
            continue
        role = "exclude" if (r.get("role") or "").strip().lower() == "exclude" else "include"
        groups.setdefault(genre, {"include": [], "exclude": []})[role].append(term)
    return groups


def _esc(v):
    return v.replace("'", "''").upper()


def _like(t):
    return f"upper(subjects) like '%{_esc(t)}%'"


def denom_series(idx):
    out = [0] * len(idx)
    for row in _q(f"SELECT checkoutyear, checkoutmonth, sum(checkouts) AS c WHERE {BOOK} "
                  f"GROUP BY checkoutyear, checkoutmonth LIMIT 50000"):
        key = f"{int(row['checkoutyear'])}-{int(row['checkoutmonth']):02d}"
        if key in idx:
            out[idx[key]] = int(float(row["c"]))
    return out


def _genre_where(include, exclude, gate=""):
    """The subject-match WHERE fragment for a genre (union of includes, minus
    excludes, optionally AND a gate). Shared by the series and example queries."""
    where = "(" + " OR ".join(_like(t) for t in include) + ")"
    if exclude:
        where += " AND NOT (" + " OR ".join(_like(t) for t in exclude) + ")"
    if gate:
        where += f" AND {gate}"
    return where


def top_examples(include, exclude, gate="", n=10):
    """Top-N most-checked-out titles for a genre -- a concrete sense of what it
    catches. One aggregated request; `<Unknown Title>` rows are dropped."""
    where = _genre_where(include, exclude, gate)
    soql = (f"SELECT title, sum(checkouts) AS c WHERE {where} AND {BOOK} "
            f"GROUP BY title ORDER BY c DESC LIMIT {n + 5}")
    out = []
    for row in _q(soql):
        t = (row.get("title") or "").strip()
        if t and t.lower() != "<unknown title>":
            out.append(t)
    return out[:n]


def genre_series(include, exclude, idx, years, gate=""):
    """Returns (union[], [term_count[] per include term]).

    A whole-history subject scan (upper(subjects) LIKE '%term%') has no index and
    times out at 300s. Querying ONE YEAR at a time scans ~1/N of the rows, so each
    query returns in a few seconds and the build is reliable. Results accumulate
    into the month-indexed arrays.

    `gate` is an optional extra WHERE clause (e.g. FICTION_GATE) applied to both
    the union and every per-term count, so all lines stay consistent.
    """
    where = _genre_where(include, exclude, gate)
    cases = ", ".join(f"sum(case({_like(t)}, checkouts, true, 0)) AS t{i}" for i, t in enumerate(include))
    union = [0] * len(idx)
    terms = [[0] * len(idx) for _ in include]
    for yr in years:
        soql = (f"SELECT checkoutmonth, sum(checkouts) AS u, {cases} "
                f"WHERE checkoutyear = {yr} AND {where} AND {BOOK} "
                f"GROUP BY checkoutmonth LIMIT 50000")
        for row in _q(soql):
            key = f"{yr}-{int(row['checkoutmonth']):02d}"
            if key not in idx:
                continue
            j = idx[key]
            union[j] = int(float(row.get("u", 0) or 0))
            for i in range(len(include)):
                terms[i][j] = int(float(row.get(f"t{i}", 0) or 0))
    return union, terms


def main():
    months = load_months()
    idx = {m: i for i, m in enumerate(months)}
    groups = load_genre_groups()
    print(f"{len(groups)} genres, {len(months)} months ({months[0]}..{months[-1]})", flush=True)

    years = sorted({int(m[:4]) for m in months})
    total = denom_series(idx)
    print(f"  all-book denominator done ({len(years)} years: {years[0]}..{years[-1]})", flush=True)

    genres_out = []
    for gi, (name, terms) in enumerate(groups.items(), 1):
        gate = FICTION_GATE if name in FICTION_GATED else ""
        union, term_series = genre_series(terms["include"], terms["exclude"], idx, years, gate)
        examples = top_examples(terms["include"], terms["exclude"], gate)
        genres_out.append({
            "name": name, "exclude": terms["exclude"], "gated": bool(gate), "union": union,
            "terms": [{"term": t, "count": term_series[i]} for i, t in enumerate(terms["include"])],
            "examples": examples,
        })
        share = sum(union) / max(1, sum(total)) * 100
        print(f"  [{gi:>2}/{len(groups)}] {name:28s} {len(terms['include']):>2} terms, {share:.2f}% of all books", flush=True)
        # Write after each genre so a mid-run interruption still leaves valid,
        # if partial, output (and lets me eyeball progress in the app).
        OUT.write_text(json.dumps({"months": months, "total": total, "genres": genres_out},
                                  separators=(",", ":")))

    print(f"Wrote {OUT} ({len(months)} months, {len(genres_out)} genres)", flush=True)


if __name__ == "__main__":
    main()
