"""
normalize_work_key.py

Thin wrapper around the frontend's workKey.js. Rather than reimplementing the
title-clustering rules in Python (which is exactly how the two versions drifted
before), this shells out to Node and runs the SAME normalizeWorkKey the Svelte
frontend imports. If someone edits normalizeWorkKey in workKey.js, the
accuracy-testing notebook picks up the change automatically -- there's no
second copy to remember to update.

Requires Node.js on PATH.
"""
import json
import subprocess
from functools import lru_cache
from pathlib import Path

# We shell out to workKey.cli.js, NOT workKey.js directly. workKey.js is the
# pure, browser-safe module StackedViewer.svelte imports (via the $components
# alias) -- it has no Node dependencies. workKey.cli.js is a thin Node-only
# wrapper next to it that imports normalizeWorkKey from workKey.js and adds
# the stdin/stdout CLI harness; keeping that harness out of workKey.js is what
# stops a Node builtin (node:url) from breaking the frontend bundle. Adjust
# this path if the file layout changes -- it should point at the CLI wrapper
# sitting next to the SAME workKey.js StackedViewer.svelte imports.

CURRENT_DIR = Path(__file__).resolve().parent
WORK_KEY_JS = Path(__file__).resolve().parent / "workKey.cli.js"

def normalize_work_key_batch(titles: list[str]) -> list[str]:
    """Normalize many titles in a single Node process call.

    Prefer this over normalize_work_key() for any bulk work (a whole CSV
    column, etc.) -- spawning Node per title is slow, spawning it once for
    a batch is not.
    """
    if not titles:
        return []
    proc = subprocess.run(
        ["node", str(WORK_KEY_JS)],
        input=json.dumps(titles),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"workKey.cli.js failed (is Node installed and on PATH?):\n{proc.stderr}"
        )
    return json.loads(proc.stdout)


@lru_cache(maxsize=None)
def normalize_work_key(title: str) -> str:
    """Normalize a single title.

    Cached since polars' map_elements calls this once per row and many
    catalog titles repeat across rows (multiple checkouts of the same book).
    For a whole column, normalize_work_key_batch() is still faster on a cold
    cache since it makes one Node call instead of many.
    """
    return normalize_work_key_batch([title])[0]