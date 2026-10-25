#!/usr/bin/env python3
"""Precompute the Genres tab as a 30-genre TAXONOMY with TWO views per genre:

  overlap[]   — raw union share: checkouts matching ANY of the genre's terms.
                Books are multi-tagged, so these overlap and (because tagging
                densified over time) mostly drift upward — nothing looks like
                it's falling. This is the "naive" view.
  other[]     — checkouts matching NO genre (total minus books matching any).

Output static/genres.json:
  { "months":[...], "total":[...],
    "genres":[ {"name","terms":[...],"overlap":[...],"examples":[...],
                "fmt":{"print":[...],"ebook":[...],"audiobook":[...]}} ],
    "other":[...],
    "byFormat":{"print":{"total":[...],"other":[...]}, "ebook":..., "audiobook":...} }
(each count split by format too, for the Genres tab's format buttons)

The queries are tens of KB -> GET 414s, so we POST
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
    # "Romanticism", and nonfiction erotica don't count. Only the romance words
    # themselves: "interpersonal attraction" and the same-sex relationship
    # headings were tried, but the books they added on top of these were mostly
    # literary fiction, films and thrillers (Hollinghurst, Tash Aw, Olivia Laing;
    # checked Oct 2026), and queer romances nearly all carry "romance" anyway.
    # Likewise NOT "man woman relationships" -- 5.3M checkouts, only ~8% romance.
    # "Love stories" is the Library of Congress heading for romance, so print
    # records (which rarely say "romance") need it; ebooks and audiobooks carry
    # the publishers' "FICTION / Romance / ..." terms instead.
    ("Romance", ["love stories"], ["romance languages"],
        ["romance", "romantic", "erotic"]),
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
    # Not just Asian AMERICAN fiction: aggregate the US-diaspora national-origin
    # headings ("Chinese Americans Fiction", etc.) AND the homeland/translated
    # literatures ("Chinese fiction" 33k, "Japanese fiction" 21k, ...) plus other
    # diaspora ("East Indians Fiction", "South Asians Fiction"). Uses only
    # heading forms that unambiguously mean Asian (avoids the bare "asian fiction"
    # substring, which would also match "cauc-ASIAN Fiction").
    ("Asian Fiction", [
        "asian americans fiction", "chinese americans fiction", "korean americans fiction",
        "japanese americans fiction", "vietnamese americans fiction", "filipino americans fiction",
        "taiwanese americans fiction", "hmong americans fiction", "bengali americans fiction",
        "chinese fiction", "japanese fiction", "korean fiction", "vietnamese fiction",
        "east indians fiction", "south asians fiction"], []),
    # Latino/Latin-American diaspora + homeland. No clean "Hispanic American
    # fiction" BISAC heading; deliberately NOT "Spanish fiction" (that's
    # literature from Spain, i.e. European, not Latino). ~30k.
    ("Hispanic & Latino Fiction", ["mexican americans fiction", "cuban americans fiction",
        "puerto ricans fiction", "hispanic americans fiction", "mexican fiction",
        "latin american fiction", "spanish american fiction"], []),
    # LC's "Indians of North America" is the (dated, contested) heading specific to
    # Native American fiction. Deliberately NOT "indigenous peoples fiction" -- that
    # is a GLOBAL heading (Aboriginal Australians, Pacific Islanders, Thai hill
    # peoples, etc.), so it would mislabel non-North-American Indigenous fiction. ~60k.
    ("Native American Fiction", ["indians of north america fiction"], []),
    # Broader GLOBAL Indigenous umbrella (Aboriginal Australian, Inuit, Pacific
    # Islander, Maori, and the pan-"Indigenous peoples" heading). Includes Indians
    # of North America too, so it's a true umbrella -- but since it sits AFTER
    # Native American, the partition routes North-American books to that specific
    # category and this catches the rest.
    ("Indigenous Fiction", ["indigenous peoples fiction", "indians of north america fiction",
        "aboriginal australians fiction", "inuit fiction", "pacific islanders fiction",
        "maori fiction"], []),
    # Transnational (not US-specific) already. ~79k.
    ("Jewish Fiction", ["jewish fiction", "jews fiction"], []),
    # Broadened to pull literary/classic/general fiction out of "Other" (Demon
    # Copperhead, Pachinko, Pride & Prejudice are tagged just "Fiction, Literature").
    # Sits late in priority, so genre fiction (Romance/Mystery/…) claims its books
    # first; excludes keep the broad "literature" term off kids' nonfiction.
    # Literary fiction proper + classics (Pride & Prejudice, Wuthering Heights).
    # Note: the bare "novels" form tag was dropped — it's applied so generically
    # (incl. manga/graphic-novel series like Pokémon) that it swept non-literary
    # books in here. Classics tagged ONLY "Novels" now fall to General Fiction.
    # "domestic fiction" and "psychological fiction" were dropped too (2026-09):
    # both are broad form tags that pull in plenty of commercial fiction
    # (thrillers, book-club and family sagas), not specifically literary work.
    # "short stories" was dropped too (2026-10): it's a form heading that also
    # lands on genre books (a print edition of the hockey romance Heated Rivalry
    # carries it), and one matching edition pulls in a whole work.
    ("Literary & Classic Fiction", ["literary fiction", "classic literature"], []),
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


# Nonfiction genres never count a record tagged as fiction: "Interplanetary
# voyages -- Fiction" made Dune "Travel", and novels about a period land in
# "History". (Subject ORDER can't do this: genre/form tags like "Science
# fiction" usually come last in a record, so "first tags only" drops real ones.)
NONFICTION_GENRES = {
    "Memoir & Biography", "True Crime", "Cooking & Food", "Self-Help",
    "Business & Economics", "Health & Fitness", "Psychology", "Politics & Government",
    "History", "Science & Nature", "Religion & Spirituality", "Travel",
    "Sports & Recreation", "Parenting & Family", "Art & Photography",
    "Crafts & Hobbies", "Home & Garden", "Computers & Technology", "Philosophy",
    "Essays & Society",
}


def _match(inc, exc, fic, nonfiction=False):
    parts = []
    if inc:
        parts.append(_like_any(inc))
    if fic:
        parts.append(f"({_like_any(fic)} AND {FICTION_GATE})")
    clause = "(" + " OR ".join(parts) + ")"
    if exc:
        clause += f" AND NOT {_like_any(exc)}"
    if nonfiction:
        clause += f" AND NOT {FICTION_GATE}"
    return clause


# Most Borrowed lists decide genre per BOOK: a book is in a genre when at least
# GENRE_SHARE of its checkouts (all editions, all years) come from records tagged
# with one of the genre's terms (build_top_works). A stray tag on a few records
# no longer files a book under it: "Interplanetary voyages" is on 2% of Dune's
# checkouts (not Travel), "Fantasy" on 17% of The Goldfinch's (not Fantasy), but
# on 33% of The Hunger Games' (Fantasy, as well as Science Fiction at 92%).
GENRE_SHARE = 0.25


def inclusion_clauses():
    """Per genre, just its INCLUDE terms (plain and fiction-gated), as a clause on
    `subjects` -- no exclusions or gates. Used on a book's top tags; the full
    overlap clause (exclusions, fiction gate) is still checked on all its tags."""
    out = {}
    for name, inc, exc, fic in map(_unpack, TAXONOMY):
        terms = list(inc) + list(fic)
        out[name] = _like_any(terms) if terms else "FALSE"
    return out


def overlap_clauses():
    return [(name, _match(inc, exc, fic, name in NONFICTION_GENRES)) for name, inc, exc, fic in map(_unpack, TAXONOMY)]


def partition_clauses():
    """Each genre matches its terms AND none of the EARLIER genres' base include
    terms. We deliberately don't fold earlier fiction-gated terms into the NOT:
    repeating the fiction gate in all 30-odd later clauses blows the query up past
    what Socrata will evaluate in time. The only cost is that a book matching a
    gated fantasy word AND a later genre (e.g. a vampire *horror*) is counted in
    both -- a small, acceptable overlap in line with the build's other approxs."""
    out, earlier = [], []
    for name, inc, exc, fic in map(_unpack, TAXONOMY):
        m = _match(inc, exc, fic, name in NONFICTION_GENRES)
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


def post_by_month(select, where, yr):
    """One year's rows, GROUP BY checkoutmonth and materialtype (print, ebook,
    audiobook). If the whole year times out on the city's portal (it did in Oct
    2026), ask for it a quarter at a time."""
    try:
        return post(f"SELECT checkoutmonth, materialtype, {select} WHERE checkoutyear = {yr} AND {where} "
                    f"GROUP BY checkoutmonth, materialtype", tries=2)
    except Exception as e:  # noqa: BLE001
        print(f"    {yr}: whole year timed out ({e}); fetching by quarter", flush=True)
    rows = []
    for q in range(4):
        ms = ", ".join(str(m) for m in range(3 * q + 1, 3 * q + 4))
        rows += post(f"SELECT checkoutmonth, materialtype, {select} WHERE checkoutyear = {yr} "
                     f"AND checkoutmonth IN ({ms}) AND {where} GROUP BY checkoutmonth, materialtype")
    return rows


# BOOK (see build_genres) keeps three material types; each is one format.
FORMATS = {"BOOK": "print", "EBOOK": "ebook", "AUDIOBOOK": "audiobook"}


def _row_slot(row, idx, yr):
    """(month index, format) for a by-month-and-format row, or None."""
    key = f"{yr}-{int(row['checkoutmonth']):02d}"
    f = FORMATS.get((row.get("materialtype") or "").strip().upper())
    return (idx[key], f) if key in idx and f else None


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

    FMTS = list(FORMATS.values())
    total_f = {f: [0] * N for f in FMTS}
    classified_f = {f: [0] * N for f in FMTS}
    over_f = {f: [[0] * N for _ in TAXONOMY] for f in FMTS}
    oclauses, pclauses = overlap_clauses(), partition_clauses()
    any_genre = " OR ".join(f"({c})" for _, c in oclauses)

    for yr in years:
        for row in post_by_month(f"sum(checkouts) AS total, sum(case({any_genre}, checkouts, true, 0)) AS classified", BOOK, yr):
            slot = _row_slot(row, idx, yr)
            if not slot:
                continue
            j, f = slot
            total_f[f][j] += int(float(row.get("total", 0) or 0))
            classified_f[f][j] += int(float(row.get("classified", 0) or 0))
        ocases = ", ".join(f"sum(case({c}, checkouts, true, 0)) AS o{i}" for i, (n, c) in enumerate(oclauses))
        for row in post_by_month(ocases, BOOK, yr):
            slot = _row_slot(row, idx, yr)
            if not slot:
                continue
            j, f = slot
            for i in range(len(TAXONOMY)):
                over_f[f][i][j] += int(float(row.get(f"o{i}", 0) or 0))
        total = [sum(total_f[f][j] for f in FMTS) for j in range(N)]
        classified = [sum(classified_f[f][j] for f in FMTS) for j in range(N)]
        asg = sum(classified[idx[f"{yr}-{m:02d}"]] for m in range(1, 13) if f"{yr}-{m:02d}" in idx)
        tot = sum(total[idx[f"{yr}-{m:02d}"]] for m in range(1, 13) if f"{yr}-{m:02d}" in idx)
        print(f"  {yr}: {tot:>9,} checkouts, {100 * asg / max(1, tot):4.1f}% classified", flush=True)

    # Books matching no genre. (Summing the first-match partition instead double
    # counts fiction-gated matches and went negative from 2020 on.)
    other = [total[j] - classified[j] for j in range(N)]
    over = [[sum(over_f[f][i][j] for f in FMTS) for j in range(N)] for i in range(len(TAXONOMY))]
    by_format = {f: {"total": total_f[f], "other": [total_f[f][j] - classified_f[f][j] for j in range(N)]} for f in FMTS}

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
                           "fmt": {f: over_f[f][i] for f in FMTS}, "examples": titles[:10]})
        oshare = 100 * sum(over[i]) / max(1, sum(total))
        print(f"  [{i + 1:>2}/{len(TAXONOMY)}] {name:26s} {oshare:4.1f}%", flush=True)

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
                               "otherTags": other_tags, "byFormat": by_format},
                              separators=(",", ":")))
    print(f"Wrote {OUT}", flush=True)


if __name__ == "__main__":
    main()
