# Evaluating the Viewer: A Three-Part Series

We're submitting the [What Is Seattle Reading?](https://melaniewalsh.github.io/whats-seattle-reading-viewer/) viewer to [JCDL 2026](https://2026.jcdl.org/) (the ACM/IEEE Joint Conference on Digital Libraries), and the submission needs something it doesn't have yet: an **evaluation**. The viewer's clustering algorithms make thousands of judgment calls — this spelling is the same author as that one, these five catalog entries are all the same book — and right now, our only evidence for how well they work is "we eyeballed it and it seems pretty good." Reviewers will want numbers. Producing those numbers, rigorously, is your mission next week.

Here's the fun part: evaluation is real research. You'll build a benchmark comparison, run an annotation study, and do the kind of error analysis that turns "the algorithm is 91% accurate" into "the algorithm is 91% accurate, and here is exactly where and why it fails." This work will appear in the submitted paper(s), and contributors will be credited accordingly.

## The Secret Weapon

Normally, evaluating clustering means paying humans to create a **gold standard** — a trusted set of right answers. We get to skip that: for [a previous paper](https://doi.org/10.63744/P6qPH135jhY2), a UW team manually clustered the checkout data for all 93 authors in the *Norton Anthology of American Literature* — hand-unified author name variants (`Normalized.Creator`) and hand-reconciled works (`Normalized.Title`). That paper even says the dataset can "serve as a benchmark for future *Work*-level clustering approaches." We'll be the first to use it that way.

## The Three Parts

Work through them in order — Part 1 introduces ideas (gold standards, precision/recall, error analysis) that Parts 2 and 3 build on.

| | What | Format | Rough effort |
|---|---|---|---|
| **1** | [Evaluating the Work Clustering](01-evaluating-work-clustering.ipynb) — score the viewer's title-into-works algorithm against the gold standard, with scikit-learn | Jupyter notebook | ~1 day, mostly computational |
| **2** | [Auditing the Author Clustering](02-auditing-author-clustering.ipynb) — a stratified annotation study of the 450k-entry author map, plus recall against the gold standard | Jupyter notebook + annotation | ~1 day incl. ~2 hrs annotating (needs **two people**) |
| **3** | [Measuring the Correction Burden](03-measuring-correction-burden.md) — how much human fixing do the viewer's auto-suggested groups actually need? | Live viewer + spreadsheet | an afternoon of (structured) clicking |

**If time runs short, Part 1 is the priority** — it produces the single number the paper most needs.

## Setup

- Python 3 with `pip install pandas scikit-learn jupyter`
- Clone the repo and work in `paper/eval/` on a branch; open a PR when done
- Start by running the ported algorithm's self-test — it should print `All self-tests passed.`:

  ```
  python3 normalize_work_key.py --self-test
  ```

- Don't commit the gold-standard CSV (the notebooks load it from its public URL)

## Ground Rules

A few principles that apply to all three parts — they're what make the difference between numbers and *defensible* numbers:

1. **Evaluate what exists, don't improve it.** If you spot a bug in `normalize_work_key.py` or a better clustering rule, write it down and tell us — but don't change the code you're evaluating. Published numbers must describe the algorithm the viewer actually runs.
2. **Decisions before data.** Random seeds fixed, sample sizes chosen, and author lists locked *before* anyone looks at results. (Each part walks you through this.)
3. **When the data surprises you, flag it — loudly and early.** A gold-standard column that doesn't mean what we thought, name formats that don't line up between files, a filter that changes the numbers: these aren't obstacles to route around, they're findings. The comparison is only as good as our understanding of what we're comparing against.
4. **Keep the vivid examples.** Percentages persuade reviewers; examples convince them. Every part asks you to save 2–3 concrete failure cases.

## Timeline

Results are needed by **Friday, July 24**, so they can be written into the papers during the final week before the July 31 deadline. If you're blocked, say so on day one, not day four. ☕
