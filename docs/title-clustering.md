# Title clustering: grouping editions into "works"

This document explains how the viewer clusters an author's many catalog entries into **works**.

> **Author clustering** (`data-prep/cluster_authors.py`) merges different *spellings of a person's name* — "Octavia E. Butler" vs "Butler, Octavia E." — into one author. It happens **once, server- side**, before the data is built.
>
> **Title clustering** ( `src/components/StackedViewer.svelte`, JavaScript, **in browser**) groups an author's editions of the same book into one **work**. It happens **live, per author, as the user browses**, and can be edited.

------------------------------------------------------------------------

## Motivation

A single book can show up in the library catalog many times. Here are real entries for one J.K. Rowling title:

```         
Harry Potter and the Sorcerer's Stone: Harry Potter Series, Book 1 (unabridged) (Unabridged)   audio
Harry Potter and the sorcerer's stone / by J. K. Rowling ; illustrations by Mary Grandpre.     print
Harry Potter and the Sorcerer's Stone: Harry Potter Series, Book 1                             ebook
Harry Potter and the sorcerer's stone / J.K. Rowling ; illustrated by Jim Kay.                 print
```

------------------------------------------------------------------------

## `normalizeWorkKey(title)`

In `src/components/StackedViewer.svelte`.

| \# | Step | Example |
|----------------|-----------------|--------------------------|
| 1 | Lowercase | `Sorcerer's` → `sorcerer's` |
| 2 | Fold accents (`NFD` + strip combining marks) | `galápagos` → `galapagos` (so it matches `Galapagos`) |
| 3 | Cut everything after `/` | `… stone / by J. K. Rowling …` → `… stone` |
| 4 | `&` → `and` | `beasts & where` → `beasts and where` |
| 5 | Remove parentheticals `(…)` | `… stone (unabridged)` → `… stone` |
| 6 | **Loop:** strip a trailing `:`/`;` segment if it's edition/format **noise** — or an `or,` alternative title | `… stone: harry potter series, book 1` → `… stone`; `slaughterhouse-five: or, the children's crusade` → `slaughterhouse-five` |
| 7 | Remove standalone format words | `… them the original screenplay` keeps content but format words go |
| 8 | Drop articles `the`/`a`/`an` | `look at the birdie` → `look at birdie` |
| 9 | Remove apostrophes |  |
| 10 | Strip all non-alphanumerics (incl. spaces & hyphens) | `Slaughter-House Five` == `Slaughterhouse-Five` |

The result for every Sorcerer's Stone entry above is the same key: `harrypotterandsorcerersstone`.

### 

## `cleanTitleForDisplay(title)`

The work *key* is normalized like so (`harrypotterandsorcerersstone`), so we also clean title for display.