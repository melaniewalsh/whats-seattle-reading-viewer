// Work titles: the "work key" that collapses a book's many editions into one
// work, and a readable display name. Shared by the trends viewer and Compare.
import { titleCase } from "$utils/titleCase.js";

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
	// Audiobooks are often split into "Title, Part 1" / "Title, Part 2" (occasionally
	// "Title Part 1"). Strip a trailing part marker — requiring a number/number-word
	// after "part" so real titles like "The Best Part of My Day" aren't touched — so
	// the parts cluster with each other and with the single-file/print edition.
	t = t.replace(/[,\s]+part\s+(\d+|one|two|three|four|five|six|seven|eight|nine|ten|i{1,3})\b.*$/i, " ");
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
	// Drop a subtitle after the first colon -- but not from a title that is
	// itself numbers around a colon, like Ben Lerner's "10:04".
	const clock = t.trim().match(/^\d+:\d+/);
	t = clock ? clock[0] + t.trim().slice(clock[0].length).replace(/\s*:\s*.*$/, "") : t.replace(/\s*:\s*.*$/, "");
	t = t.replace(/[,\s]+part\s+(\d+|one|two|three|four|five|six|seven|eight|nine|ten|i{1,3})\b.*$/i, ""); // drop "…, Part 1" audiobook split
	t = t.replace(/\([^)]*\)/g, "").replace(/\s+/g, " ").trim();
	return titleCase(t);
}
