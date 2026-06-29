# Learning resources

A curated starting point for the two technologies this project is built on:
**Svelte** (the website) and **DuckDB** (the data prep). Flagged where things
match *our* stack, since that's where people get tripped up.

---

## Svelte / SvelteKit

The website (`src/`) is built with **Svelte 5** (using "runes") and **SvelteKit**.

**Start here, in order:**

1. **[Official interactive tutorial](https://svelte.dev/tutorial)** — runs in your
   browser, no setup. The single best starting point. It teaches Svelte 5 **runes**
   (`$state`, `$derived`, `$props`), which is exactly what `Viewer.svelte` uses.
2. **[Svelte docs](https://svelte.dev/docs/svelte)** and
   **[SvelteKit docs](https://svelte.dev/docs/kit)** — reference these after the
   tutorial. The [runes section](https://svelte.dev/docs/svelte/what-are-runes) is
   the key concept.

**Going deeper:**

- **[Joy of Code](https://joyofcode.xyz/)** — friendly, practical SvelteKit
  tutorials and YouTube videos.
- **[Svelte Society recipes](https://sveltesociety.dev/recipes)** — small,
  copy-pasteable examples.
- **[The Pudding's svelte-starter](https://github.com/the-pudding/svelte-starter)**
  — the template this project is built on; its README explains the structure.

> ⚠️ **Heads-up:** Svelte 5 (released late 2024) changed the syntax. Older
> tutorials and Stack Overflow answers use `export let`, `$:`, and stores instead
> of runes. If something doesn't match our code, check the date — prefer
> material from 2025 onward.

---

## DuckDB

The data prep (`data-prep/build_data.py`) uses **DuckDB**, which runs SQL directly
on CSV files — fast even on tens of millions of rows.

**Start here, in order:**

1. **[DuckDB docs](https://duckdb.org/docs/)** — clean and example-driven.
2. **[Python API guide](https://duckdb.org/docs/api/python/overview)** — exactly how
   our script uses DuckDB (`duckdb.connect()`, `read_csv_auto`, `.fetchall()`).
3. **[DuckDB guides](https://duckdb.org/docs/guides/overview)** — short,
   task-focused walkthroughs (importing CSVs, querying, exporting).

**Going deeper:**

- **[MotherDuck learning hub](https://motherduck.com/learn-more/)** — the company
  behind DuckDB; practical articles, including "DuckDB vs pandas" comparisons that
  are handy if you already know pandas.
- **[DuckDB "Friendly SQL"](https://duckdb.org/docs/sql/dialect/friendly_sql)** —
  the niceties that make its SQL pleasant to write.

---

## SQL basics (the foundation DuckDB runs on)

DuckDB *is* SQL, so if you're new to SQL, start with the fundamentals:

- **[SQLBolt](https://sqlbolt.com/)** — free, interactive, browser-based. Best for
  absolute beginners.
- **[Mode SQL Tutorial](https://mode.com/sql-tutorial/)** — a bit more in-depth and
  analysis-oriented.

---

## How this maps to the code

| If you want to work on… | Learn… | The files |
|---|---|---|
| **Author clustering** (student task 2) | DuckDB + SQL + a little Python | `data-prep/build_data.py`, `data-prep/cluster_authors.py` |
| **Full-dataset ingestion** (student task 1) | DuckDB | `data-prep/build_data.py` |
| **The UI and charts** | Svelte 5 + a little [d3](https://d3js.org/) | `src/components/Viewer.svelte`, `src/components/LineChart.svelte` |

See the [README](README.md) for the two student projects in detail.
