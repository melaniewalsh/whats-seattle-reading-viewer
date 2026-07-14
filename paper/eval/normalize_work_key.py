"""
normalize_work_key.py — Python port of the viewer's work-clustering key.

This is a faithful, line-by-line port of `normalizeWorkKey()` from
`src/components/StackedViewer.svelte` (the algorithm is documented in
docs/title-clustering.md). Titles that produce the same key are considered
editions of the same *work*.

IMPORTANT: if the JavaScript changes, this port must change with it. Each
step below is commented with the matching JS line so the two can be diffed
by eye.

Usage:
    python3 normalize_work_key.py "Some Title" "Another Title"   # print keys
    python3 normalize_work_key.py --self-test                    # run checks
"""

import re
import sys
import unicodedata

# JS: const NOISE = /(book|bk|series|...)/i;
NOISE = re.compile(
    r"(book|bk|series|volume|vol|part|edition|unabridged|abridged|screenplay"
    r"|read by|narrated|illustrated|deluxe|anniversary|collector|special"
    r"|movie|film|adapted|reissue|boxe?d? ?set|complete|novel|novella|memoir"
    r"|thriller|mystery|story|stories|tale|tales|romance|biography"
    r"|autobiography|poems|essays|playscript|\bscript\b|\bproduction|\bserie"
    r"|\blivre|\btome|\blibro|\btomo|\bedicion)",
    re.IGNORECASE,
)

# JS: /[:;]\s*or[\s,]/i  — an "or, ..." alternative title
OR_ALT = re.compile(r"[:;]\s*or[\s,]", re.IGNORECASE)

# JS: /[:;]\s*[^:;]*$/ — the trailing colon/semicolon segment
TRAILING_SEGMENT = re.compile(r"[:;]\s*[^:;]*$")


def normalize_work_key(title):
    """Normalize a raw catalog title to a work key (empty string if nothing survives)."""
    # JS: let t = (title || "").toLowerCase();
    t = (title or "").lower()

    # JS: t = t.normalize("NFD").replace(/[̀-ͯ]/g, "");
    # Fold accents to plain ASCII so "Galápagos" and "Galapagos" match.
    t = unicodedata.normalize("NFD", t)
    t = re.sub(r"[̀-ͯ]", "", t)

    # JS: t = t.split(" / ")[0];  — drop "/ by Author ; illustrations by ..."
    t = t.split(" / ")[0]

    # JS: if (/\s=\s/.test(t)) t = t.split(/\s=\s/).pop();
    # Bilingual records: "Original Title = English parallel title" -> keep English.
    if re.search(r"\s=\s", t):
        t = re.split(r"\s=\s", t)[-1]

    # JS: t = t.replace(/&/g, " and ");
    t = t.replace("&", " and ")

    # JS: t = t.replace(/\([^)]*\)/g, " ");  — drop "(unabridged)" etc.
    t = re.sub(r"\([^)]*\)", " ", t)

    # JS: t = t.replace(/\[[^\]]*\]/g, " ");  — drop "[sound recording]" etc.
    t = re.sub(r"\[[^\]]*\]", " ", t)

    # JS: do { ... } while (t !== prev);
    # Repeatedly strip a trailing ":"/";" segment if it's edition/format noise
    # or an "or, ..." alternative title; STOP at the first real subtitle.
    while True:
        m = TRAILING_SEGMENT.search(t)
        if not m:
            break
        seg = m.group(0)
        if NOISE.search(seg) or OR_ALT.search(seg):
            t = t[: m.start()] + " "
        else:
            break  # real subtitle -> keep it, stop stripping

    # JS: t = t.replace(/\b(unabridged|...)\b/g, " ");  — standalone format words
    t = re.sub(
        r"\b(unabridged|abridged|audiobook|e-?book|large print|compact disc|sound recording)\b",
        " ",
        t,
    )

    # JS: t = t.replace(/\b(the|a|an)\b/g, " ");  — drop articles
    t = re.sub(r"\b(the|a|an)\b", " ", t)

    # JS: t = t.replace(/['’]/g, "");  — sorcerer's -> sorcerers
    t = re.sub(r"['’]", "", t)

    # JS: t = t.replace(/[^a-z0-9]+/g, "");  — strip ALL non-alphanumerics
    t = re.sub(r"[^a-z0-9]+", "", t)

    return t


# ---------------------------------------------------------------------------
# Self-tests: the canonical examples from docs/title-clustering.md.
# ---------------------------------------------------------------------------

def self_test():
    # All four Sorcerer's Stone variants must collapse to one key.
    sorcerers = [
        "Harry Potter and the Sorcerer's Stone: Harry Potter Series, Book 1 (unabridged) (Unabridged)",
        "Harry Potter and the sorcerer's stone / by J. K. Rowling ; illustrations by Mary Grandpre.",
        "Harry Potter and the Sorcerer's Stone: Harry Potter Series, Book 1",
        "Harry Potter and the sorcerer's stone / J.K. Rowling ; illustrated by Jim Kay.",
    ]
    keys = {normalize_work_key(t) for t in sorcerers}
    assert keys == {"harrypotterandsorcerersstone"}, keys

    # Crimes of Grindelwald must stay DISTINCT from the base Fantastic Beasts.
    grindelwald = normalize_work_key(
        "Fantastic Beasts: The Crimes of Grindelwald: The Original Screenplay"
    )
    beasts = normalize_work_key("Fantastic Beasts and Where to Find Them")
    assert grindelwald == "fantasticbeastscrimesofgrindelwald", grindelwald
    assert grindelwald != beasts

    # "or, ..." alternative titles are stripped.
    assert normalize_work_key(
        "Slaughterhouse-Five: or, The Children's Crusade"
    ) == normalize_work_key("Slaughterhouse-Five")

    # Accent folding.
    assert normalize_work_key("Galápagos") == normalize_work_key("Galapagos")

    # Article dropping.
    assert normalize_work_key("Look at the birdie") == normalize_work_key(
        "Look at Birdie"
    )

    # Statement of responsibility + brackets.
    assert normalize_work_key(
        "Beloved / a novel by Toni Morrison ; [with a new foreword by the author]."
    ) == normalize_work_key("Beloved")

    # Bilingual parallel title clusters with the English work.
    assert normalize_work_key(
        "Harī Pottā to nazo no purinsu = Harry Potter and the half-blood prince"
    ) == normalize_work_key("Harry Potter and the Half-Blood Prince")

    print("All self-tests passed.")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] == "--self-test":
        self_test()
    else:
        for title in args:
            print(f"{normalize_work_key(title)}\t{title}")
