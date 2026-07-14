# Measuring the Correction Burden

*Part 3 of 3 in our evaluation of the [What Is Seattle Reading?](https://melaniewalsh.github.io/whats-seattle-reading-viewer/) viewer.*

This last part needs no code at all — just the live viewer, a spreadsheet, and your judgment. It might be the most important of the three.

## Why This Number Matters

Parts 1 and 2 measured how *accurate* our clustering algorithms are. But the viewer makes a subtler claim, and it's the one we most want to defend in the paper: the design philosophy of **"suggest, then revise."** The algorithm proposes work groups; the human corrects them by drag and drop. The bet behind that design is that machine suggestions are good enough that correcting them is *much* cheaper than clustering by hand from scratch.

Is that bet true? To find out, we measure the **correction burden**: when the viewer auto-suggests work groups for an author, how much fixing does a careful human actually have to do?

At the end, we want to be able to write two numbers in the paper:

> *"N% of auto-proposed work groups required no correction; the median author required M corrections."*

## Before You Start: Agree on the Author List

We'll audit **20 authors**, chosen *before anyone looks at any results*. This matters: if we pick authors as we go, it's human nature to (even unconsciously) drift toward authors that make the tool look good. Locking the list in advance is what makes the numbers honest.

⚠️ **Heads up!** No swapping authors after you've seen their groups — even if one turns out to be boring or bizarre. Boring and bizarre are data.

Build the list together with this recipe:

| How many | What kind | Why |
|------------------------|------------------------|------------------------|
| 3 | Known stress tests: **J. K. Rowling, James Patterson, Kurt Vonnegut** | Prolific, messy catalogs — where the algorithm works hardest |
| \~12 | Mid-size authors (a few dozen titles) | The typical case — most of what users actually look up |
| \~5 | Smaller authors (a handful of titles) | The easy(?) case — let's verify it's actually easy |

Mix genres and eras; include some authors of translated work if you can. Write the final list in the shared spreadsheet **before** the first author is opened.

## The Protocol, Step by Step

For each author on the list:

1.  Open the [viewer](https://melaniewalsh.github.io/whats-seattle-reading-viewer/) and search for the author.
2.  Click **"✨ Show top work groups."** The viewer proposes up to 5 groups — each one is a claim: *"these titles are all editions of the same work."*
3.  Now audit each proposed group against the full title list (use the filter box and the **Sort: By work** option to see everything). For each group, ask:
    -   Does this group contain any title that **doesn't belong** (a false merge)?
    -   Is there a title elsewhere in the list that **should be in** this group but isn't (a false split)?
4.  Fix what's wrong — actually do the fixes in the interface, because we're measuring the *work of fixing* — and **count your actions** as you go (see "What counts" below).
5.  Record the numbers in the spreadsheet before moving to the next author. Add a one-line note about anything interesting: a funny failure, a group you weren't sure about, a fix that took real thought.

**A worked example.** Suppose the viewer proposes a Vonnegut group containing:

```         
Slaughterhouse-Five
Slaughterhouse-Five: or, The Children's Crusade (Unabridged)
Slaughterhouse-five, or, The children's crusade: a duty-dance with death
Cat's Cradle
```

The first three are genuinely one work — but *Cat's Cradle* is an interloper. You drag it out. That's **one group audited, one correction, group not fully correct**. If instead the group had contained only the three *Slaughterhouse-Five* variants and no *Slaughterhouse* title was stranded elsewhere in the list, that's **one group audited, zero corrections, fully correct**.

## What Counts as a Correction

Count each of these as **one** correction:

-   Dragging a title **out of** a proposed group
-   Dragging a title **into** a proposed group
-   **Merging** two groups that are actually the same work
-   **Splitting** one group into two (count it as one correction plus one per title you had to move — record what you did in the notes)

Do **not** count:

-   **Renaming** a group — that's cosmetic, not a clustering error
-   Corrections to a group **you** created — we're grading the machine's suggestions, not yours
-   Scrolling, filtering, or general looking around

Judgment call you'll hit quickly: *translations*. If a Spanish edition of a novel sits ungrouped, is that a false split? For consistency with Part 1's gold standard (which clustered translations with their works): **yes, count it** — but tally translation-related corrections in their own spreadsheet column, so the paper can report them separately. The algorithm doesn't attempt translations, and it's fairer to report that as a known scope limit than to hide it in the average.

## The Spreadsheet

One row per author. Set it up (and share it with the team) before starting:

| Column | What goes in it |
|------------------------------------|------------------------------------|
| `author` | Author name |
| `size_class` | stress / mid / small |
| `n_groups_proposed` | How many groups "Show top work groups" created |
| `n_groups_fully_correct` | Groups needing zero corrections |
| `n_corrections` | Total corrections (per "What counts" above) |
| `n_translation_corrections` | The subset of corrections involving translations |
| `minutes_spent` | Rough time on this author, start to finish |
| `notes` | One line: anything interesting |

💡 **Tip:** `minutes_spent` is secretly one of the most persuasive columns. "A careful audit of a messy author takes four minutes" says more about suggest-then-revise than any percentage.

## Reporting

When all 20 authors are done, compute:

1.  **% of auto-groups requiring no correction** = sum of `n_groups_fully_correct` ÷ sum of `n_groups_proposed`
2.  **Median corrections per author** (report the stress-test authors separately — they'll be outliers, and that's the story: even the worst case is only *M* drags)
3.  The same two numbers **excluding translation corrections**, for the scope-limits discussion

## What to Upload

-   [ ] The completed spreadsheet (exported as CSV into `paper/eval/`)
-   [ ] The three headline numbers above
-   [ ] 2–3 sentences on the most interesting failures — what kind of mistake should a future version of the algorithm fix first?