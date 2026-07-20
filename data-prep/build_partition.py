#!/usr/bin/env python3
"""Precompute the Genres tab as a 30-genre TAXONOMY with TWO views per genre:

  overlap[]   — raw union share: checkouts matching ANY of the genre's terms.
                Books are multi-tagged, so these overlap and (because tagging
                densified over time) mostly drift upward — nothing looks like
                it's falling. This is the "naive" view.
  partition[] — first-match share: each checkout is assigned to the FIRST genre
                it matches in priority order (rest -> "Other"), so the shares sum
                to 100% and declines become real and visible.

The viewer toggles between the two. Output static/genres.json:
  { "months":[...], "total":[...],
    "genres":[ {"name","terms":[...],"overlap":[...],"partition":[...],"examples":[...]} ],
    "other":[...] }                                  # Other's partition counts

The first-match query is ~64KB (cumulative NOT clauses) -> GET 414s, so we POST
to the SODA v3 endpoint. Whole-history subject scans time out, so we go a year at
a time (GROUP BY checkoutmonth for monthly resolution).

Run:  python3 data-prep/build_partition.py          # full
      python3 data-prep/build_partition.py 2024 2025 # quick test on 2 years
"""
import collections
import json
import sys
import time
import urllib.request
from pathlib import Path

from build_genres import load_months, BOOK  # reuse month index + book universe

OUT = Path(__file__).resolve().parent.parent / "static" / "genres.json"
QUERY_URL = "https://data.seattle.gov/api/v3/views/tmmm-ytt6/query.json"
APP_TOKEN = "bHWsGtRFRP9x8Hl8lYivqM1hQ"

# (genre, include terms, exclude terms). Order = priority (first match wins).
TAXONOMY = [
    ("Comics & Graphic Novels", ["graphic novel", "comic", "manga", "cartoons and comics"], []),
    # Split from the old "Children's & Juvenile": genuinely-young picture/early-reader
    # books, kept above the genre buckets so a picture book about dragons stays here.
    ("Picture Books & Early Readers", ["picture book", "board book", "beginning reader", "stories in rhyme"], []),
    # Young Adult sits ABOVE Juvenile Fiction so a teen book tagged "young adult"
    # (e.g. the ebook of ACOTAR / The Hate U Give) routes to YA, not the kids' bucket.
    ("Young Adult", ["young adult fiction", "young adult literature"], []),
    # Broad LC "…Juvenile fiction" bucket. NOTE: LC juvenile spans children -> teen,
    # so print teen books that carry only "Juvenile fiction" (e.g. print ACOTAR) land
    # here; we can't peel those out at the record level without pooling by title.
    ("Juvenile Fiction", ["juvenile fiction"], []),
    # Kids' nonfiction, above the broad Nonfiction umbrella so it isn't swallowed.
    ("Juvenile Nonfiction", ["juvenile nonfiction"], []),
    # Gate the romance terms on a Fiction tag so "Romance languages",
    # "Romanticism", and nonfiction erotica don't count. Add the same-sex
    # relationship LC headings (small, ~60-70% romance) to catch queer romance.
    # Deliberately NOT "man woman relationships" -- that heading is 5.3M checkouts
    # and only ~8% romance (it blankets literary fiction, e.g. Atonement), so it
    # would swamp Romance with general fiction.
    ("Romance", [], ["romance languages"],
        ["romance", "romantic", "erotic", "man man relationships", "woman woman relationships"]),
    # "fantasy" always; the evocative words only when a Fiction tag is present
    # (so "magic" doesn't grab "The Magic of Tidying Up", "elf" ≠ "self-help").
    ("Fantasy", ["fantasy"], [], ["vampire", "fairies", "magic", "fairy", "dragon", "wizard",
        "witch", "unicorn", "werewolf", "werewolves", "elves", "elf"]),
    # evocative terms only with a Fiction tag ("alien" would otherwise catch
    # immigration/legal nonfiction — "Illegal aliens", "Alien labor").
    ("Science Fiction", ["science fiction", "dystopia"], [], ["alien", "time travel", "cyborg"]),
    ("Horror", ["horror"], []),
    ("Mystery", ["mystery", "detective"], []),
    ("Thriller & Suspense", ["thriller", "suspense"], []),
    ("Historical Fiction", ["historical fiction"], []),
    # "western" gated by fiction so it doesn't catch "Western Europe"/"western US".
    ("Western", ["western stories", "westerns"], [], ["western", "cowboys"]),
    ("Mythology & Folklore", ["mythology", "folklore", "fairy tale", "legends"], []),
    ("Humor", ["humor", "humorous stories"], []),
    # Identity-fiction categories, just above the general Literary catch-all so
    # literary LGBTQIA+/Black fiction lands here rather than in the generic bucket.
    ("LGBTQIA+ Fiction", [], [], ["lgbtqia", "lgbt", "gay", "lesbian", "homosexual",
        "bisexual", "transgender", "queer"]),
    ("African American Fiction", ["african american fiction"], []),
    # Broadened to pull literary/classic/general fiction out of "Other" (Demon
    # Copperhead, Pachinko, Pride & Prejudice are tagged just "Fiction, Literature").
    # Sits late in priority, so genre fiction (Romance/Mystery/…) claims its books
    # first; excludes keep the broad "literature" term off kids' nonfiction.
    # Literary fiction proper + classics (Pride & Prejudice, Wuthering Heights).
    ("Literary & Classic Fiction", ["literary fiction", "domestic fiction", "psychological fiction",
        "short stories", "classic literature", "novels"], []),
    # The broad BISAC "Literature" tag = contemporary general / book-club fiction
    # (Demon Copperhead, Lessons in Chemistry) — NOT the same as literary fiction,
    # so it gets its own bucket, just after the specific one claims the classics.
    ("General Fiction", ["literature"],
        ["juvenile literature", "childrens literature", "young adult literature"]),
    ("Memoir & Biography", ["biography & autobiography", "memoir", "autobiography",
        "autobiographies", "biographies"], []),
    ("True Crime", ["true crime"], []),
    ("Cooking & Food", ["cooking", "cookbook", "cookery"], []),
    ("Self-Help", ["self-improvement", "self-help", "self help", "personal development", "new age"], []),
    ("Business & Economics", ["business", "economics", "finance"], []),
    ("Health & Fitness", ["health & fitness", "diet", "wellness"], []),
    ("Psychology", ["psychology"], []),
    ("Politics & Government", ["politics", "political science", "government"], []),
    ("History", ["history"], []),
    ("Science & Nature", ["science", "nature", "natural history"], []),
    ("Religion & Spirituality", ["religion", "spiritual"], []),
    ("Travel", ["travel", "voyages"], []),
    ("Sports & Recreation", ["sports", "athletics"], []),
    ("Parenting & Family", ["parenting", "family & relationships"], []),
    ("Art & Photography", ["art history", "photography", "painting", "drawing"], []),
    ("Crafts & Hobbies", ["knitting", "crafts", "quilting", "sewing"], []),
    ("Home & Garden", ["gardening", "home design", "interior decoration", "house & home"], []),
    ("Computers & Technology", ["computers", "computer technology", "programming"], []),
    ("Philosophy", ["philosophy"], []),
    ("Drama & Performing Arts", ["drama", "plays", "theater", "performing arts"], []),
    # After Travel, so travel guidebooks stay in Travel; catches the rest of the
    # reference/study material pooling in "Other".
    ("Reference & Study", ["foreign language study", "guidebooks", "reference"], []),
    ("Poetry", ["poetry", "poems"], []),
    ("Essays & Society", ["essays", "sociology", "social science"], []),
    # ---- FAST genre/form + broad umbrellas -----------------------------------
    # Promoted from the top tags in "Other". Placed LATE so the specific topical
    # genres above claim their books first; these then sweep up the residual that
    # was pooling in "Other". "=art"/"=fiction" are whole-term matches (see
    # _one_like) so they don't false-match "Martial arts" / "Nonfiction".
    ("Literary Criticism", ["literary criticism"], []),
    ("Art", ["=art"], []),
    ("Illustrated Works", ["illustrated works"], []),
    ("Informational Works", ["informational works"], []),
    ("Instructional & Educational Works", ["instructional and educational works"], []),
    ("Readers Publications", ["readers publications", "readers (publications)"], []),
    # The two broad umbrellas, LAST, so everything specific is claimed first and
    # these split the remaining general fiction / general nonfiction out of Other.
    ("Fiction", ["=fiction"], []),
    ("Nonfiction", ["nonfiction", "non-fiction"], []),
]


def _one_like(t):
    """One subject match. A term prefixed with "=" matches a WHOLE comma-delimited
    subject term (e.g. "=art" hits the "Art" heading but NOT "Martial arts" or
    "Departments"; "=fiction" hits a bare "Fiction" tag but NOT "Nonfiction" or
    "Historical fiction"). Whole-term matching also keeps these short words from
    poisoning later genres' NOT clauses (a substring "fiction" would wrongly
    exclude every "Nonfiction" book)."""
    t = t.strip()
    if t.startswith("="):
        u = t[1:].upper().replace("'", "''")
        return ("(upper(subjects) = '{u}' OR upper(subjects) like '{u},%' "
                "OR upper(subjects) like '%, {u},%' OR upper(subjects) like '%, {u}')").format(u=u)
    return f"upper(subjects) like '%{t.upper()}%'"


def _like_any(terms):
    return "(" + " OR ".join(_one_like(t) for t in terms) + ")"


# Require a real Fiction subject tag but NOT "Nonfiction" (which contains the
# substring "fiction"). Used to gate generic words like "magic"/"elf" that would
# otherwise catch self-help ("The Magic of Tidying Up", "Self-Improvement").
FICTION_GATE = ("(upper(subjects) like '%FICTION%' AND upper(subjects) not like '%NONFICTION%' "
                "AND upper(subjects) not like '%NON-FICTION%')")


def _unpack(entry):
    """A genre = (name, include, exclude[, fiction_gated]). `fic` terms only count
    when the record also carries a Fiction tag."""
    name, inc, exc = entry[0], entry[1], entry[2]
    fic = entry[3] if len(entry) > 3 else []
    return name, inc, exc, fic


def _match(inc, exc, fic):
    parts = []
    if inc:
        parts.append(_like_any(inc))
    if fic:
        parts.append(f"({_like_any(fic)} AND {FICTION_GATE})")
    clause = "(" + " OR ".join(parts) + ")"
    if exc:
        clause += f" AND NOT {_like_any(exc)}"
    return clause


def overlap_clauses():
    return [(name, _match(inc, exc, fic)) for name, inc, exc, fic in map(_unpack, TAXONOMY)]


def partition_clauses():
    """Each genre matches its terms AND none of the EARLIER genres' base include
    terms. We deliberately don't fold earlier fiction-gated terms into the NOT:
    repeating the fiction gate in all 30-odd later clauses blows the query up past
    what Socrata will evaluate in time. The only cost is that a book matching a
    gated fantasy word AND a later genre (e.g. a vampire *horror*) is counted in
    both -- a small, acceptable overlap in line with the build's other approxs."""
    out, earlier = [], []
    for name, inc, exc, fic in map(_unpack, TAXONOMY):
        m = _match(inc, exc, fic)
        out.append((name, f"({m}) AND NOT {_like_any(sorted(set(earlier)))}" if earlier else m))
        earlier += inc
    return out


def post(soql, tries=4):
    body = json.dumps({"query": soql}).encode()
    last = None
    for a in range(tries):
        try:
            req = urllib.request.Request(
                QUERY_URL, data=body, method="POST",
                headers={"Content-Type": "application/json", "X-App-Token": APP_TOKEN,
                         "User-Agent": "spl-partition/1.0"})
            with urllib.request.urlopen(req, timeout=200) as r:
                return json.loads(r.read().decode())
        except Exception as e:  # noqa: BLE001
            last = e
            print(f"    retry {a + 1}/{tries}: {e}", flush=True)
            time.sleep(5 * (a + 1))
    raise last


def _clean(title):
    t = (title or "").split(" / ")[0].strip()
    return t


def main():
    test_years = [int(a) for a in sys.argv[1:]] or None
    months = load_months()
    idx = {m: i for i, m in enumerate(months)}
    N = len(months)
    years = test_years or sorted({int(m[:4]) for m in months})
    print(f"{len(TAXONOMY)} genres, {N} months, years {years[0]}..{years[-1]}"
          + (" (TEST)" if test_years else ""), flush=True)

    total = [0] * N
    over = [[0] * N for _ in TAXONOMY]
    part = [[0] * N for _ in TAXONOMY]
    oclauses, pclauses = overlap_clauses(), partition_clauses()

    for yr in years:
        pcases = ", ".join(f"sum(case({c}, checkouts, true, 0)) AS p{i}" for i, (n, c) in enumerate(pclauses))
        for row in post(f"SELECT checkoutmonth, sum(checkouts) AS total, {pcases} "
                        f"WHERE checkoutyear = {yr} AND {BOOK} GROUP BY checkoutmonth"):
            key = f"{yr}-{int(row['checkoutmonth']):02d}"
            if key not in idx:
                continue
            j = idx[key]
            total[j] = int(float(row.get("total", 0) or 0))
            for i in range(len(TAXONOMY)):
                part[i][j] = int(float(row.get(f"p{i}", 0) or 0))
        ocases = ", ".join(f"sum(case({c}, checkouts, true, 0)) AS o{i}" for i, (n, c) in enumerate(oclauses))
        for row in post(f"SELECT checkoutmonth, {ocases} "
                        f"WHERE checkoutyear = {yr} AND {BOOK} GROUP BY checkoutmonth"):
            key = f"{yr}-{int(row['checkoutmonth']):02d}"
            if key not in idx:
                continue
            j = idx[key]
            for i in range(len(TAXONOMY)):
                over[i][j] = int(float(row.get(f"o{i}", 0) or 0))
        asg = sum(sum(part[i][idx[f"{yr}-{m:02d}"]] for m in range(1, 13) if f"{yr}-{m:02d}" in idx) for i in range(len(TAXONOMY)))
        tot = sum(total[idx[f"{yr}-{m:02d}"]] for m in range(1, 13) if f"{yr}-{m:02d}" in idx)
        print(f"  {yr}: {tot:>9,} checkouts, {100 * asg / max(1, tot):4.1f}% classified", flush=True)

    other = [total[j] - sum(part[i][j] for i in range(len(TAXONOMY))) for j in range(N)]

    # Examples: top first-match titles over the last few years. Scoping to recent
    # years keeps the subject scan from timing out AND surfaces current favorites.
    ex_since = years[-1] - 2
    genres_out = []
    for i, entry in enumerate(TAXONOMY):
        name, inc, exc, fic = _unpack(entry)
        cond = pclauses[i][1]
        titles = []
        for row in post(f"SELECT title, sum(checkouts) AS c WHERE {cond} AND {BOOK} "
                        f"AND checkoutyear >= {ex_since} GROUP BY title ORDER BY c DESC LIMIT 15"):
            t = _clean(row.get("title"))
            if t and t.lower() != "<unknown title>":
                titles.append(t)
        genres_out.append({"name": name, "terms": inc, "ficTerms": fic, "overlap": over[i],
                           "partition": part[i], "examples": titles[:10]})
        oshare = 100 * sum(over[i]) / max(1, sum(total))
        pshare = 100 * sum(part[i]) / max(1, sum(total))
        print(f"  [{i + 1:>2}/{len(TAXONOMY)}] {name:26s} overlap {oshare:4.1f}% / partition {pshare:4.1f}%", flush=True)

    # Top titles + top subject tags in "Other" (matching no genre), so the
    # unclassified bucket is legible: what it's made of and what's in it.
    not_any = "NOT (" + " OR ".join(f"({c})" for _, c in overlap_clauses()) + ")"
    other_examples = []
    for row in post(f"SELECT title, sum(checkouts) AS c WHERE {not_any} AND {BOOK} "
                    f"AND checkoutyear >= {ex_since} GROUP BY title ORDER BY c DESC LIMIT 15"):
        t = _clean(row.get("title"))
        if t and t.lower() != "<unknown title>":
            other_examples.append(t)
    tag_yr = years[-2] if len(years) > 1 else years[-1]  # a recent FULL year
    tagc, other_tot = collections.Counter(), 0
    for row in post(f"SELECT subjects, sum(checkouts) AS c WHERE checkoutyear = {tag_yr} "
                    f"AND {not_any} AND {BOOK} GROUP BY subjects ORDER BY c DESC LIMIT 3000"):
        w = int(float(row.get("c", 0) or 0))
        other_tot += w
        for p in (row.get("subjects") or "").split(","):
            p = p.strip().lower()
            if p and not p.replace(" ", "").isdigit():
                tagc[p] += w
    other_tags = [[t, round(100 * c / max(1, other_tot), 1)] for t, c in tagc.most_common(12)]
    print(f"  Other: {len(other_examples)} example titles, {len(other_tags)} tags", flush=True)

    OUT.write_text(json.dumps({"months": months, "total": total, "genres": genres_out,
                               "other": other, "otherExamples": other_examples[:10],
                               "otherTags": other_tags},
                              separators=(",", ":")))
    print(f"Wrote {OUT}", flush=True)


if __name__ == "__main__":
    main()
