// Strip cataloging cruft from a raw SPL work title.
//
// Catalog titles often carry a "statement of responsibility" tacked onto the
// title string — sometimes with a MARC " / " separator, but in this data often
// with a bare " By Author. Illustrated by …" — plus bracketed volume notes and
// parenthetical edition tags. Two cleaners:
//   cleanWorkTitle — for DISPLAY (keep the human title, drop the responsibility)
//   searchTitle    — for LOOKUPS (more aggressive: also drop subtitle/brackets)

// Remove a trailing statement of responsibility appended to the title.
function stripResponsibility(t) {
	// "Title / by Author ; illustrated by …" — everything after " / ".
	t = t.split(/\s+\/\s+/)[0];
	// "Title! By Theo. LeSieg. Illustrated by Roy McKie." — a responsibility
	// clause that follows sentence-ending punctuation and starts a capitalized
	// name. Keep the punctuation; drop the clause. (Requires a preceding . ! or ?
	// and a capital after "by", so real titles like "Death by Black Hole" survive.)
	t = t.replace(/([.!?])\s+[Bb]y\s+[A-Z].*$/, "$1");
	return t.trim();
}

// Collapse whitespace and trim trailing separators/punctuation.
function tidy(t) {
	return t.replace(/\s+/g, " ").replace(/[\s.,;:/!?-]+$/, "").trim();
}

// Human-facing title: drop the responsibility statement, keep subtitle + volume.
export function cleanWorkTitle(raw) {
	const t = stripResponsibility((raw || "").trim());
	return tidy(t) || (raw || "").trim();
}

// Lookup key for Open Library / Wikipedia: strip harder — bracketed volume
// notes, parenthetical edition tags, and any subtitle after a colon — so the
// core title matches the catalog's canonical record.
export function searchTitle(raw) {
	let t = stripResponsibility((raw || "").trim());
	t = t.replace(/\s*[[(][^\])]*[\])]/g, " "); // "[Volume 1, Days Gone Bye]", "(Unabridged)"
	t = t.replace(/\s*:\s.*$/, ""); // subtitle after ": "
	return tidy(t) || cleanWorkTitle(raw);
}
