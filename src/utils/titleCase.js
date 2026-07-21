// Title-case a catalog work title for display. Catalog titles arrive in mixed
// forms — ALL CAPS, all lowercase, or sentence case — so normalize to title
// case: capitalize principal words, keep short function words lowercase (except
// first/last and after a colon), and leave already-mixed-case tokens (real
// capitalization like "McDonald", "iPhone") untouched.
//
// Use for DISPLAY only — pass raw titles to the Wikipedia / cover lookups.

const SMALL = new Set([
	"a", "an", "and", "as", "at", "but", "by", "for", "from", "if", "in", "into",
	"nor", "of", "off", "on", "onto", "or", "over", "per", "the", "to", "up",
	"via", "vs", "with", "yet",
]);

function capitalize(w) {
	// Leave already-mixed-case words alone (real caps: "McDonald", "iPhone", "DiCamillo").
	if (w !== w.toLowerCase() && w !== w.toUpperCase()) return w;
	// Capitalize the first letter and letters after a hyphen/slash/paren — but NOT
	// after an apostrophe, so possessives stay lowercase ("Sorcerer's", not "Sorcerer'S").
	return w
		.toLowerCase()
		.replace(/(^|[-/(])([a-z])/g, (_m, sep, c) => sep + c.toUpperCase());
}

export function titleCase(title) {
	if (!title) return title;
	const tokens = title.trim().split(/\s+/);
	let forceNext = true; // capitalize the first word (and any word after a colon)
	return tokens
		.map((tok, i) => {
			const isLast = i === tokens.length - 1;
			const bare = tok.replace(/[^A-Za-z'’-]/g, "").toLowerCase();
			const force = forceNext || isLast;
			forceNext = /[:;]$/.test(tok); // next word starts a subtitle -> capitalize it
			if (!force && SMALL.has(bare)) return tok.toLowerCase();
			return capitalize(tok);
		})
		.join(" ");
}
