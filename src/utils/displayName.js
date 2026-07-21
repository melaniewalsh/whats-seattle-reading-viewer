// Tidy a catalog author name for display. Catalog names are inconsistent --
// all-lowercase ("mo willems"), "Lastname, First" ("Davis, Jim"), or normalized
// with initials split out ("j d vance"). Flip the comma form, Title-Case the
// words, and standardize initials to "J.D." style, while leaving already
// mixed-case names (McDonald, DeLillo) alone.
function titleCaseWord(w) {
	// A single letter is an initial -> uppercase ("j" -> "J"). This must NOT fire
	// for 2-letter names ("Mo", "Bo", "St"), which the old length<=2 rule broke.
	if (w.length === 1) return w.toUpperCase();
	if (w === w.toLowerCase() || w === w.toUpperCase()) {
		// Title-case, and also capitalize the letter after an apostrophe or hyphen
		// so "o'farrell" -> "O'Farrell", "crossley-holland" -> "Crossley-Holland".
		return w.toLowerCase().replace(/(^|[-'’])([a-z])/g, (_m, sep, c) => sep + c.toUpperCase());
	}
	return w;
}

const IS_INITIAL = /^[A-Za-z]\.?$/; // "J" or "J."

export function displayName(name) {
	if (!name) return name;
	let n = name.trim();
	// Drop a trailing life-dates clause ("Baldwin, James, 1924-1987").
	n = n.replace(/,\s*\d{4}(?:\s*-\s*\d{0,4})?\.?\s*$/, "");
	const comma = n.match(/^([^,]+),\s*(.+)$/);
	if (comma) n = `${comma[2].trim()} ${comma[1].trim()}`;

	const words = n.split(/\s+/).filter(Boolean).map(titleCaseWord);
	// Collapse runs of single-letter initials into "J.D." form (also normalizes
	// "J. K." -> "J.K." and adds a period to a lone middle initial).
	const out = [];
	for (let i = 0; i < words.length; ) {
		if (IS_INITIAL.test(words[i])) {
			let s = "";
			while (i < words.length && IS_INITIAL.test(words[i])) {
				s += words[i][0].toUpperCase() + ".";
				i++;
			}
			out.push(s);
		} else {
			out.push(words[i]);
			i++;
		}
	}
	return out.join(" ");
}
