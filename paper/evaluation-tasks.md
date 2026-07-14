# Evaluating the Viewer's Clustering — Student Tasks

> **📣 Students: start in [`eval/`](eval/README.md) instead.** The tasks below have been expanded into a slowed-down, three-part guided series — two Jupyter notebooks and a protocol document — with worked examples and runnable code. This page remains as the compact instructor-facing summary.

We're submitting the SPL viewer to [JCDL 2026](https://2026.jcdl.org/) (deadline **July 31**), and the papers need an evaluation section. Right now the README says the work clustering handles "~85% of cases" — that's a guess. Your job next week is to replace guesses with numbers.

**The key shortcut:** we already have a gold standard. For [the CHR paper](https://doi.org/10.63744/P6qPH135jhY2), the team *manually* clustered checkout data for the 93 authors in the *Norton Anthology of American Literature* (NAAL) — hand-curated author name variants and 1,603 hand-reconciled works, recorded in the `Normalized.Creator` and `Normalized.Title` columns of the dataset:

```
https://seattle-library-checkout-data.s3.us-west-2.amazonaws.com/norton-anthology_spl-checkouts_2005-2025.csv
```

That paper explicitly says the dataset can "serve as a benchmark for future Work-level clustering approaches." We're going to be the first to use it that way. Most of the evaluation is therefore **computational, not new annotation labor**.

There are three tasks. Task 1 is the priority if time runs short.

---

## Task 1 — Work clustering vs. the NAAL gold standard *(cheap, strong — do this first)*

**Question:** How well does the viewer's automatic work clustering match human judgment?

**What to do:**

1. The clustering algorithm has **already been ported to Python** for you: [`paper/eval/normalize_work_key.py`](eval/normalize_work_key.py). It's a verified line-by-line port of `normalizeWorkKey()` from `src/components/StackedViewer.svelte` (checked against the JavaScript on a shared test set; run `python3 normalize_work_key.py --self-test` to confirm it still passes). The algorithm itself is documented step-by-step in [`docs/title-clustering.md`](../docs/title-clustering.md). **Do not "improve" the port** — the whole point is to evaluate what the viewer actually does. If you spot a bug, flag it; don't silently fix it.
2. Download the NAAL gold CSV (URL above). For each of the 93 authors, take the **raw** titles and run them through `normalize_work_key()`. Titles that share a key = one predicted cluster.
3. Compare predicted clusters against the manual `Normalized.Title` clusters, **within each author** (the algorithm only ever clusters within one author, so don't compare across authors).
4. Score with **pairwise precision, recall, and F1** — the standard for entity resolution. See "Computing the metrics" below.
5. Report overall (micro-averaged over all pairs) and per-author, so we can name the hardest authors.

### Computing the metrics (Task 1)

The idea: turn the clustering into a binary classification problem over **pairs of titles**, then use `sklearn` to score it. For every pair of titles by the same author:

- the gold label is `1` if the humans put them in the same work (`Normalized.Title` matches), else `0`;
- the predicted label is `1` if the algorithm gave them the same work key, else `0`.

Then **precision** = of the pairs the algorithm merged, what fraction the humans also merged (false merges hurt this); **recall** = of the pairs the humans merged, what fraction the algorithm found (false splits hurt this); **F1** = their harmonic mean.

Use `sklearn.metrics` rather than hand-rolling the arithmetic — it's less error-prone and reviewers trust it:

```python
from itertools import combinations
from sklearn.metrics import precision_recall_fscore_support

y_true, y_pred = [], []
for author, titles in titles_by_author.items():   # titles: list of (raw_title, gold_work_id)
    keys = {t: normalize_work_key(t) for t, _ in titles}
    gold = dict(titles)
    for (t1, _), (t2, _) in combinations(titles, 2):
        y_true.append(int(gold[t1] == gold[t2]))
        y_pred.append(int(keys[t1] == keys[t2] and keys[t1] != ""))

p, r, f1, _ = precision_recall_fscore_support(
    y_true, y_pred, average="binary", zero_division=0
)
print(f"pairwise precision={p:.3f} recall={r:.3f} F1={f1:.3f}")
```

Notes:

- **Empty keys**: if `normalize_work_key()` returns `""` for a title, treat it as its own singleton cluster (that's what the `keys[t1] != ""` guard does) — don't let all empty-key titles merge with each other.
- **Per-author scores**: run the same computation per author (skip authors with fewer than 2 titles). Sort ascending by F1 to find the 5 hardest authors for the paper.
- **Sanity check**: also report `sklearn.metrics.adjusted_rand_score` computed per author over the cluster labels (gold work id vs. predicted key). It should tell the same story as pairwise F1; if it doesn't, something is wrong with the pair construction. Adjusted Rand goes in a footnote at most — pairwise P/R/F1 is the headline.
- **Class imbalance is expected**: most pairs are "different work," so accuracy is meaningless here — that's exactly why we report precision/recall on the positive (same-work) class only (`average="binary"`).

**Watch out for:**
- The gold data may already be filtered (e.g., print/ebook/audiobook only). Match its filtering before comparing.
- Keep a list of the algorithm's failures (false merges and false splits, with examples). The paper needs 1–2 illustrative error examples, and any fixable pattern you spot could improve the algorithm itself.

**Deliverable:** a script in `paper/eval/` (e.g., `eval_work_clustering.py`), a results table (overall P/R/F1 + the 5 worst authors), and a short list of characteristic errors.

---

## Task 2 — Author clustering precision audit *(small, manual)*

**Question:** When the pipeline merges two author-name spellings, is it right?

The pipeline's output is `data-prep/author_map.json` — 449,942 mappings from raw name → canonical name.

**Part A: Precision (manual annotation)**

1. Draw a **stratified sample of ~200 mappings**. Stratify by the canonical author's total checkouts (use `search-index.json` totals, or recompute): mistakes on popular authors matter more than on the long tail. Suggested split: 50 from the top decile of checkout volume, then 50 / 50 / 50 stepping down. Sample with a fixed random seed and save the sample as a CSV so it's reproducible.
2. **Two annotators** independently judge each mapping: *is the raw name and the canonical name the same person?* Labels: `correct` / `incorrect` / `unsure`. Ground rules:
   - Search the name + a title if unsure (the SPL catalog, Wikipedia, VIAF are all fair game).
   - Different real people who share a name (e.g., two different "John Smith"s) merged together = `incorrect`.
   - Judge the *merge*, not the canonical spelling — if the canonical form is ugly but it's the same person, that's `correct`.
3. Compute **precision** (correct / (correct + incorrect)) per stratum and overall, and **inter-annotator agreement** on the double-annotated set using `sklearn.metrics.cohen_kappa_score(annotator_a_labels, annotator_b_labels)`. Resolve disagreements by discussion; report the *pre-resolution* kappa (that's the honest number — agreement after discussion is always inflated). Exclude `unsure` items from the precision denominator but report how many there were.

**Part B: Recall (against the gold standard — no new annotation)**

Recall is hard to measure directly (you can't audit merges that never happened), so estimate it with the NAAL data: the CHR team hand-collected the name variants for each of the 93 authors (e.g., "Toni Morrison" / "Morrison, Toni" / "Morrison, Toni, 1931–2019"). For each gold variant set, check: does `author_map.json` map all variants to a single canonical name? Report the fraction of variants correctly unified, and list the misses.

**Deliverable:** the sample CSV with both annotators' labels, a small script for Part B, and a results paragraph: *"precision X% on a stratified sample of 200 (κ = …); recall Y% against the NAAL curated variants."*

---

## Task 3 — Correction burden in the viewer *(an afternoon of clicking)*

**Question:** When the viewer auto-suggests work groups, how often does a human need to fix them? This is the number behind the paper's "suggest, then revise" design claim.

1. Pick **~20 authors stratified by title count**: a few very prolific/messy ones (**J. K. Rowling, James Patterson, Kurt Vonnegut** — our known stress tests), a majority of mid-size authors, a few small ones. Fix the list in advance and write it down — no swapping authors after seeing results.
2. For each author, on the [live viewer](https://melaniewalsh.github.io/whats-seattle-reading-viewer/): click **"✨ Show top work groups"**, then inspect each auto-proposed group against the title list.
3. Count, per author, in a shared spreadsheet:
   - number of auto-proposed groups,
   - number of groups that were **fully correct** (no action needed),
   - number of **corrections** required — where a correction = dragging a title out of/into a group, merging two groups, or splitting one. (Renaming a group does **not** count; that's cosmetic.)
   - one-line notes on any interesting failure.
4. Report: **% of auto-groups requiring no correction** and **median corrections per author**.

**Deliverable:** the spreadsheet + the two headline numbers.

---

## Logistics

- **Setup:** Python 3 with `pip install pandas scikit-learn`. The ported clustering function is already in `paper/eval/normalize_work_key.py` — start by running its `--self-test`.
- **Timeline:** results needed by **Friday, July 24** so they can go into the papers the week before the July 31 deadline.
- **Where things live:** put scripts and outputs in `paper/eval/` on a branch; open a PR when done. Don't commit the raw NAAL CSV (link it in the script instead).
- **Questions / blockers:** if the gold data doesn't behave as described here (missing columns, unexpected filtering), flag it early rather than working around it silently — the comparison is only as good as our understanding of the gold standard.
- **Credit:** this evaluation will appear in the JCDL submission(s), and contributors will be acknowledged/authored accordingly.
