# Title clustering: grouping editions into "works"

This document explains, in full, how the viewer clusters an author's many catalog
entries into **works**, and every decision behind it. If you just want the short
version, see the "Grouping editions into works" section of the [README](../README.md).

> **Two different "clustering" features — don't mix them up.**
> - **Author clustering** (`data-prep/cluster_authors.py`, Python, runs in the
>   data pipeline) merges different *spellings of a person's name* — "Octavia E.
>   Butler" vs "Butler, Octavia E." — into one author. It happens **once, server-
>   side**, before the data is built.
> - **Title clustering** (this doc; `src/components/StackedViewer.svelte`,
>   JavaScript, runs **in the browser**) groups an author's *editions of the same
>   book* — print, ebook, audiobook, reprints, translations — into one **work**.
>   It happens **live, per author, as you browse**, and you can correct it.

---

## 1. The problem

A single book shows up in the library catalog many times. Here are real entries
for one J.K. Rowling title:

```
Harry Potter and the Sorcerer's Stone: Harry Potter Series, Book 1 (unabridged) (Unabridged)   audio
Harry Potter and the sorcerer's stone / by J. K. Rowling ; illustrations by Mary Grandpre.     print
Harry Potter and the Sorcerer's Stone: Harry Potter Series, Book 1                             ebook
Harry Potter and the sorcerer's stone / J.K. Rowling ; illustrated by Jim Kay.                 print
```

These are all **one work** — the same story — but the catalog strings differ by
**boilerplate**: format tags, a "statement of responsibility" (`/ by … ;
illustrations by …`), a series/volume subtitle (`: … Book 1`), edition notes
(`(unabridged)`), and casing/punctuation. A reader wants to see "Sorcerer's
Stone" as **one line on the chart**, not four.

The insight that makes this tractable: the variation is almost entirely
**predictable boilerplate, not fuzzy human error**. So we don't need fuzzy string
matching or an ML model — we can *strip the boilerplate* down to a stable **work
key** and group entries that share it. Get the normalization right and simple
exact-match on the key handles ~85% of cases.

---

## 2. Design decisions (and why)

**Decision: do it in the browser, not the data pipeline.**
When you open an author, the browser already has that author's few dozen–few
hundred titles. Clustering them client-side means:
- **No rebuild to change the rules.** We can tune the normalizer and see the
  effect instantly, instead of waiting ~30 min for a full data rebuild.
- **It's per-author and interactive** — and, crucially, the reader can **revise**
  it (see §6). A wrong merge is never fatal; you drag a title out.

The alternative — precomputing a `work` key for every title in `build_data.py` —
is viable and would save a little client compute, but it couples every rule tweak
to a rebuild and makes user correction harder. If the rules ever fully stabilize,
moving the same normalization into the pipeline is a reasonable future step.

**Decision: rule-based normalization, not fuzzy matching.**
Because the noise is boilerplate, a handful of deterministic rules is more
predictable and debuggable than a similarity threshold (which risks silently
merging genuinely different books, or splitting on a threshold nobody can
explain). A cheap fuzzy pass could be added later for the long tail, but the
rules carry the load.

**Decision: "suggest, then revise."**
The clustering is a *starting point*, surfaced as editable selection groups. The
reader accepts it, or fixes it by dragging titles between groups. This is why an
occasional wrong merge is acceptable — the human is in the loop.

---

## 3. The algorithm: `normalizeWorkKey(title)`

Lives in `src/components/StackedViewer.svelte`. Each step, in order, with the
reason and an example:

| # | Step | Why | Example |
|---|------|-----|---------|
| 1 | Lowercase | case is meaningless for identity | `Sorcerer's` → `sorcerer's` |
| 2 | Fold accents (`NFD` + strip combining marks) | otherwise an accent gets dropped to a space and keys diverge | `galápagos` → `galapagos` (so it matches `Galapagos`) |
| 3 | Cut everything after ` / ` | drops the statement of responsibility (`/ by Author ; illustrations by …`) | `… stone / by J. K. Rowling …` → `… stone` |
| 4 | `&` → ` and ` | unify the two spellings of "and" | `beasts & where` → `beasts and where` |
| 5 | Remove parentheticals `(…)` | drops `(unabridged)`, `(Unabridged)`, etc. | `… stone (unabridged)` → `… stone` |
| 6 | **Loop:** strip a trailing `:`/`;` segment if it's edition/format **noise** — or an `or,` alternative title | removes series/volume/format subtitles and "aka" titles, but **stops** at a real distinguishing subtitle | `… stone: harry potter series, book 1` → `… stone`; `slaughterhouse-five: or, the children's crusade` → `slaughterhouse-five` |
| 7 | Remove standalone format words | `unabridged`, `audiobook`, `ebook`, `large print`, `compact disc`, `sound recording` | `… them the original screenplay` keeps content but format words go |
| 8 | Drop articles `the`/`a`/`an` | so `Look at the birdie` == `Look at Birdie` | `look at the birdie` → `look at birdie` |
| 9 | Remove apostrophes | `sorcerer's` → `sorcerers` | |
| 10 | Strip **all** non-alphanumerics (incl. spaces & hyphens) | word-boundary/hyphen differences don't matter | `Slaughter-House Five` == `Slaughterhouse-Five` |

The result for every Sorcerer's Stone entry above is the same key:
`harrypotterandsorcerersstone`.

### The `:`/`;` noise list (step 6)

A trailing colon/semicolon segment is stripped **only** if it looks like edition
or format boilerplate. The current noise vocabulary:

```
book, bk, series, volume, vol, part, edition, unabridged, abridged, screenplay,
read by, narrated, illustrated, deluxe, anniversary, collector, special, movie,
film, adapted, reissue, box(ed) set, complete, novel, novella, memoir, thriller,
mystery, story, stories, tale, tales, romance, biography, autobiography, poems, essays
```

…plus the pattern `: or, …` / `; or, …` for alternative titles.

**Why a stop-at-real-subtitle loop and not "cut everything after the first
colon"?** Because some colon-subtitles are the *distinguishing* part of the
title. The loop strips trailing noise segments repeatedly, but the moment it hits
a segment that *isn't* on the noise list, it stops:

- `Fantastic Beasts: The Crimes of Grindelwald: The Original Screenplay`
  → strip `: the original screenplay` (has "screenplay") → then
  `: the crimes of grindelwald` is **not** noise → **stop**.
  Key: `fantasticbeastscrimesofgrindelwald` — correctly **separate** from the main
  "Fantastic Beasts and Where to Find Them".

If we naively cut at the first colon, "Crimes of Grindelwald" would collapse into
the base title and two different books would wrongly merge.

---

## 4. Display names: `cleanTitleForDisplay(title)`

The work *key* is a normalized blob (`harrypotterandsorcerersstone`) — fine for
matching, useless for reading. So a work's **shown name** is derived separately
from its best-known (most-borrowed) edition's raw title: cut the statement of
responsibility (` / …`) and the subtitle (after the first `: `), drop
parentheticals, tidy whitespace. That turns
`Harry Potter and the Sorcerer's Stone: … Book 1 (Unabridged)` into
**"Harry Potter and the Sorcerer's Stone"**.

---

## 5. Where the data comes from

Clustering operates on the titles inside one author's file
(`static/data/authors/<shard>/<slug>.json`, hosted on R2). Note that
`build_data.py` already drops titles borrowed fewer than **`MIN_TITLE_CHECKOUTS`
(50)** times from an author's per-title breakdown (their total still counts them),
so the long tail of once-or-twice-borrowed editions never reaches the clusterer.

---

## 6. How it surfaces in the UI

All in `StackedViewer.svelte`:

- **"✨ Show top work groups"** — `autoGroupByWork()` buckets the author's titles
  by work key, keeps works with **2+ editions**, takes the **top 5 by total
  checkouts** (`MAX_AUTO_GROUPS = 5`, capped so the line chart stays readable),
  and seeds those as editable selection groups — one aggregated line per work.
- **The "Add to plot" column** — a per-row checkbox plots that single edition;
  under a multi-edition work's name, an **"add whole work"** button plots *all*
  its editions as one line (`toggleWork` / `isWorkPlotted`, backed by the
  `workGroups` map of work key → edition indices).
- **"Sort: By work"** — orders the title table so editions of a work sit together,
  with the work name shown once per group (sortable A–Z or by total checkouts).

### Suggest, then revise

Whatever the clusterer proposes is just editable groups. If it splits or merges
something wrongly, the reader **drags a title between groups**, **drags one group
pill onto another to merge them**, deletes a group, or renames it. The algorithm
is never the last word.

---

## 7. Performance guards

An author can have thousands of titles (James Patterson ~1,500). To keep the tab
responsive:
- The title table renders at most **`TITLE_RENDER_CAP` (120)** rows (filter to
  find the rest).
- The stacked-area chart draws at most **`AREA_LAYER_CAP` (30)** layers, rolling
  the remainder into an "Other titles" band.

---

## 8. Known limitations & edge cases

- **Textbook vs. screenplay.** "Fantastic Beasts and Where to Find Them" (the
  in-universe textbook) and "…: The Original Screenplay" normalize together under
  the current rules — arguably they're different works. This is a judgment call;
  the reader can split them.
- **Similar display names.** Because the display name cuts at the first colon, two
  genuinely distinct works can *look* similarly named even when correctly kept
  apart (e.g. a "Fantastic Beasts" screenplay vs. "Fantastic Beasts: The Crimes of
  Grindelwald" both shorten toward "Fantastic Beasts"). The chart still treats
  them as separate lines.
- **Aggressive stripping can rarely over-merge.** Dropping articles and all
  non-alphanumerics is what lets `Slaughter-House Five` == `Slaughterhouse-Five`
  and `Look at the birdie` == `Look at Birdie`, but it could, in principle, merge
  two very short titles that differ only by an article or spacing. Rare in
  practice, and correctable.
- **This is not author disambiguation.** Garbled *author* names (e.g. a mangled
  canonical name) come from `cluster_authors.py`, not this code.

---

## 9. Tuning it

Everything is in `src/components/StackedViewer.svelte`:
- `normalizeWorkKey()` — the matching rules (the `NOISE` regex is the usual place
  to add a new edition/format keyword).
- `cleanTitleForDisplay()` — the shown work name.
- `MAX_AUTO_GROUPS` — how many works "Show top work groups" plots.

Because it's client-side, edit, save, and reload — no data rebuild needed. When a
change looks right across a few messy authors (Rowling, Patterson, Vonnegut are
good stress tests), commit it and it deploys with the next site push.
