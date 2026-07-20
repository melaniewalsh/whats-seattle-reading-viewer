// workKey.js
//
// Single source of truth for clustering catalog title variants into one "work".
// Used directly by the frontend (StackedViewer.svelte) and, via Node subprocess,
// by the Python accuracy-testing notebook (see normalize_work_key.py). Edit the
// logic here ONLY -- both sides update automatically, so there's nothing to keep
// in sync by hand.

// The same book shows up many times (print / audio / ebook / illustrated /
// unabridged), differing only in cataloging boilerplate. Strip that boilerplate
// to a "work key" so all the editions of one work collapse to the same string.
// e.g. every "Harry Potter and the Sorcerer's Stone ..." variant ->
//      "harry potter and the sorcerers stone".
export function normalizeWorkKey(title) {
	let t = (title || "").toLowerCase();
	// Fold accents to plain ASCII so "Galápagos" and "Galapagos" match
	// (otherwise "á" gets stripped to a space and the keys diverge).
	t = t.normalize("NFD").replace(/[̀-ͯ]/g, "");
	t = t.split(" / ")[0]; // drop "/ by Author ; illustrations by ..."
	// Bilingual catalog records use "Original Title = English parallel title"
	// (e.g. "Harī Pottā ... = Harry Potter and the half-blood prince"). Keep the
	// English parallel title so foreign editions cluster with the English work.
	if (/\s=\s/.test(t)) t = t.split(/\s=\s/).pop();
	// Classic alternate-title form "Main Title, or, The Alternate Title"
	// (Slaughterhouse-Five, or, The Children's Crusade; Moby-Dick, or, The
	// Whale) -- drop everything from ", or, " on so an edition catalogued with
	// the alt-title clusters with plain "Slaughterhouse-Five". The SECOND comma
	// is the tell: alt-titles write ", or, X" while lists write ", or X"
	// ("Beg, Borrow, or Steal"), so requiring it avoids over-matching.
	t = t.replace(/,\s+or,\s+.*$/i, "");
	t = t.replace(/&/g, " and "); // "beasts & where" -> "beasts and where"
	t = t.replace(/\([^)]*\)/g, " "); // drop "(unabridged)" etc.
	// Some catalog titles have an UNCLOSED paren, e.g. "The Inn at Rose Harbor
	// (with bonus short story: Rose Harbor Series, Book 1" -- the balanced rule
	// above misses it, so also strip a dangling "(" clause to end of string.
	t = t.replace(/\s*\([^)]*$/, " ");
	t = t.replace(/\[[^\]]*\]/g, " "); // drop cataloging brackets: "[text ]", "[sound recording]", etc.
	// Repeatedly strip a trailing ":"/";" segment when it's edition/format noise
	// (series/book/volume, "the original screenplay", "read by <narrator>",
	// illustrated/anniversary editions, "a novel", etc.) OR an "or, ..."
	// alternative title (e.g. "Slaughterhouse-Five: or, The Children's Crusade"
	// is the same book). Stop at the first segment that's a real distinct
	// subtitle (e.g. "The Crimes of Grindelwald"), so those stay separate.
	const NOISE = /(book|bk|series|volume|vol|part|edition|unabridged|abridged|screenplay|read by|narrated|illustrated|deluxe|anniversary|collector|special|movie|film|adapted|reissue|boxe?d? ?set|complete|novel|novella|memoir|thriller|mystery|story|stories|tale|tales|romance|biography|autobiography|poems|essays|playscript|litrpg|gamelit|\bscript\b|\bproduction|\bserie|\blivre|\btome|\blibro|\btomo|\bedicion)/i;
	let prev;
	do {
		prev = t;
		t = t.replace(/[:;]\s*[^:;]*$/, (seg) => (NOISE.test(seg) || /[:;]\s*or[\s,]/i.test(seg) ? " " : seg));
	} while (t !== prev);
	t = t.replace(/\b(unabridged|abridged|audiobook|e-?book|large print|compact disc|sound recording)\b/g, " ");
	t = t.replace(/\b(the|a|an)\b/g, " "); // drop articles so "Look at the birdie" == "Look at Birdie"
	t = t.replace(/['’]/g, ""); // sorcerer's -> sorcerers
	// Remove ALL non-alphanumerics INCLUDING spaces/hyphens, so word-boundary
	// differences don't matter ("Slaughter-House Five" == "Slaughterhouse-Five").
	t = t.replace(/[^a-z0-9]+/g, "");
	return t;
}

// A readable name for a work, taken from its best-known edition's title.
export function cleanTitleForDisplay(title) {
	let t = (title || "").split(" / ")[0];
	t = t.replace(/\s*:\s*.*$/, ""); // drop subtitle after the first colon
	t = t.replace(/\([^)]*\)/g, "").replace(/\s+/g, " ").trim();
	return t;
}