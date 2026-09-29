#!/usr/bin/env python3
"""
"Backlist Boomerangs": works that had a modest, settled readership and then, years
later, suddenly took off -- an adaptation, a BookTok wave, an author's death, a
news event.

For every work (an author's editions clustered with the same normalize_work_key
the site uses), look at each calendar year that is at least MIN_AGE_YEARS after
the work's first checkout and compare that year's mean monthly checkouts with
the mean of the preceding BASELINE_MONTHS, skipping the months when checkouts
were artificially low library-wide -- the 2020 COVID closures and the May-July
2024 ransomware outage -- which would otherwise make the following year look
like a comeback for everything. The work is a "boomer" in the year of its biggest jump if

    peak_mean - base_mean >= MIN_DELTA   (checkouts per month)
    peak_mean >= MIN_RATIO * base_mean
    peak-year total >= MIN_PEAK_TOTAL     (so 1 -> 12 a month doesn't count)

Runs after build_data.py in build-data-to-r2.yml (reads static/data/authors/),
takes ~10 s. Writes static/data/backlist.json (uploaded to R2 with the rest of
the data) and a bundled copy at static/backlist.json.

Output:
  { "through": "2026-08", "years": [2009, ...], "rules": {...},
    "data": { "2026": [ { "t": title, "a": author, "s": slug, "first": 2022,
                          "base": 4.1, "peak": 452, "delta": 448, "ratio": 110,
                          "yr": [[2022, 12], [2023, 40], ...] }, ... ] } }

Env: BACKLIST_DATA_DIR (default static/data), BACKLIST_MIN_RATIO, BACKLIST_MIN_DELTA.
"""
import json
import os
import sys
import glob
import types
import statistics
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
DATA_DIR = Path(os.environ.get("BACKLIST_DATA_DIR") or (PROJECT / "static" / "data"))
OUT_DATA = DATA_DIR / "backlist.json"
OUT_STATIC = PROJECT / "static" / "backlist.json"

MIN_DELTA = float(os.environ.get("BACKLIST_MIN_DELTA", 10))     # checkouts / month
MIN_RATIO = float(os.environ.get("BACKLIST_MIN_RATIO", 5))      # peak mean vs baseline mean
MIN_PEAK_TOTAL = 150      # checkouts in the boom year
MIN_AGE_YEARS = 2         # the boom must come >= 2 calendar years after the first checkout
BASELINE_MONTHS = 24
# Months skipped in both the baseline and the boom-year mean: the 2020 branch
# closures / tracking gap, and the 2024 ransomware outage (May-July 2024, when
# recorded checkouts fell to a fraction of normal).
SKIP_RANGES = [("2020-03", "2021-06"), ("2024-05", "2024-07")]
PER_YEAR = 100            # keep the top N per boom year

# The site's work clustering lives in build_data.py, which imports duckdb/dotenv
# at module load. Those are present in the workflow; locally, stub them so we
# can still import the one function we need.
sys.path.insert(0, str(HERE))
for _mod in ("duckdb", "boto3"):
    if _mod not in sys.modules:
        try:
            __import__(_mod)
        except ImportError:
            sys.modules[_mod] = types.ModuleType(_mod)
try:
    import dotenv  # noqa: F401
except ImportError:
    _d = types.ModuleType("dotenv"); _d.load_dotenv = lambda *a, **k: None; sys.modules["dotenv"] = _d
from build_data import normalize_work_key, clean_title_for_display  # noqa: E402

months = json.load(open(DATA_DIR / "meta.json"))["months"]
N = len(months)
YEAR = [int(m[:4]) for m in months]
SKIP = {i for i, m in enumerate(months) if any(lo <= m <= hi for lo, hi in SKIP_RANGES)}
YEAR_IDX = defaultdict(list)
for i, y in enumerate(YEAR):
    YEAR_IDX[y].append(i)
LAST_FULL_YEAR = YEAR[-1] if len(YEAR_IDX[YEAR[-1]]) >= 6 else YEAR[-1] - 1


def analyze(path):
    try:
        d = json.load(open(path))
    except Exception:
        return []
    works = defaultdict(lambda: [0] * N)
    best_title = {}
    for t in d.get("titles", []):
        k = normalize_work_key(t["title"])
        if not k:
            continue
        s = works[k]
        for i, v in t["series"]:
            if i < N:
                s[i] += v
        if k not in best_title or t["total"] > best_title[k][1]:
            best_title[k] = (t["title"], t["total"])
    slug = Path(path).stem
    out = []
    for k, s in works.items():
        first = next((i for i, v in enumerate(s) if v > 0), None)
        if first is None:
            continue
        first_year = YEAR[first]
        best = None
        for y in range(first_year + MIN_AGE_YEARS, LAST_FULL_YEAR + 1):
            idx = YEAR_IDX[y]
            # The BASELINE_MONTHS most recent non-skipped months before the year
            # (reaching further back when a gap is in the way, so 2022 still gets
            # a pre-pandemic baseline). The boom year's mean also leaves out the
            # skipped months, so 2024's rate isn't dragged down by the outage.
            base_idx = [i for i in range(idx[0] - 1, -1, -1) if i not in SKIP][:BASELINE_MONTHS]
            cur_idx = [i for i in idx if i not in SKIP]
            if len(base_idx) < 12 or len(cur_idx) < 6:
                continue
            base = statistics.mean(s[i] for i in base_idx)
            cur = statistics.mean(s[i] for i in cur_idx)
            delta = cur - base
            if delta >= MIN_DELTA and cur >= MIN_RATIO * max(base, 0.5) and sum(s[i] for i in idx) >= MIN_PEAK_TOTAL:
                if best is None or delta > best[0]:
                    best = (delta, y, base, cur)
        if not best:
            continue
        delta, y, base, cur = best
        yearly = [[yy, sum(s[i] for i in YEAR_IDX[yy])] for yy in sorted(YEAR_IDX)]
        # Monthly rate in the year it was first borrowed, counting from the
        # first checkout month (so a December debut isn't averaged over 11
        # empty months). Shown as "N x more than when first borrowed in YYYY".
        first_months = [i for i in YEAR_IDX[first_year] if i >= first]
        first_rate = statistics.mean(s[i] for i in first_months) if first_months else 0
        out.append({
            "t": clean_title_for_display(best_title[k][0]) or best_title[k][0],
            "a": d.get("name", ""),
            "s": slug,
            "first": first_year,
            "year": y,
            "base": round(base, 1),
            "peak": round(cur),
            "delta": round(delta),
            "ratio": round(cur / max(base, 0.5), 1),
            "firstRate": round(first_rate, 1),
            "firstRatio": round(cur / max(first_rate, 0.5), 1),
            "total": sum(s),
            "yr": yearly,
        })
    return out


def main():
    files = glob.glob(str(DATA_DIR / "authors" / "*" / "*.json"))
    print(f"scanning {len(files):,} author files in {DATA_DIR} (months through {months[-1]})")
    rows = []
    with ProcessPoolExecutor() as ex:
        for chunk in ex.map(analyze, files, chunksize=200):
            rows.extend(chunk)
    by_year = defaultdict(list)
    for r in rows:
        by_year[r["year"]].append(r)
    data = {}
    for y in sorted(by_year):
        lst = sorted(by_year[y], key=lambda r: -r["delta"])[:PER_YEAR]
        data[str(y)] = lst
    out = {
        "through": months[-1],
        "years": sorted(by_year),
        "rules": {"minDelta": MIN_DELTA, "minRatio": MIN_RATIO, "minPeakTotal": MIN_PEAK_TOTAL,
                  "minAgeYears": MIN_AGE_YEARS, "baselineMonths": BASELINE_MONTHS,
                  "skipped": SKIP_RANGES},
        "data": data,
    }
    text = json.dumps(out, separators=(",", ":"), ensure_ascii=False)
    OUT_STATIC.write_text(text)
    written = [OUT_STATIC]
    if DATA_DIR.is_dir():
        OUT_DATA.write_text(text)
        written.append(OUT_DATA)
    for p in written:
        print(f"wrote {p} ({len(text) // 1024} KB)")
    print(f"{len(rows):,} boomers across {len(by_year)} years; per year: " +
          ", ".join(f"{y}:{len(v)}" for y, v in sorted(by_year.items())))
    for y in sorted(by_year)[-3:]:
        print(f"--- {y}")
        for r in data[str(y)][:8]:
            print(f"  {r['delta']:>5}/mo  {r['base']:>6} -> {r['peak']:>5} ({r['ratio']}x)  {r['t'][:50]} | {r['a']}")


if __name__ == "__main__":
    main()
