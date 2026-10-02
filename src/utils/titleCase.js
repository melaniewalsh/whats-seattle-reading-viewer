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

// Acronyms to restore when a title arrives ALL CAPS (and so can't tell us which
// words were acronyms). Kept short and unambiguous: no "US" (us), "AIDS" (aids)
// or "LA" (la).
const ACRONYMS = new Set([
	"AI", "CIA", "FBI", "NASA", "USA", "UK", "NYC", "DNA", "ADHD", "PTSD", "OCD",
	"LGBT", "LGBTQ", "HIV", "CEO", "WWII", "BBC", "NFL", "NBA",
	"II", "III", "IV", "VI", "VII", "VIII", "IX", "XI", "XII",
]);

// Ordinary words a catalog sometimes writes in caps for emphasis ("AN
// Accidental Man", "It IS About Islam"); title-case them like any other word.
const NOT_ACRONYMS = new Set([
	"A", "AN", "THE", "AND", "OF", "TO", "IN", "ON", "AT", "BY", "FOR", "OR", "IS",
	"IT", "ME", "MY", "WE", "NO", "GO", "BE", "DO", "SO", "UP", "HE", "YOU", "ALL",
	"NEW", "WHY", "HOW", "ONE", "LOVE",
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
	const allCaps = title === title.toUpperCase();
	let forceNext = true; // capitalize the first word (and any word after a colon)
	return tokens
		.map((tok, i) => {
			const isLast = i === tokens.length - 1;
			// Keep acronyms: a short all-caps word in a title that isn't itself
			// all caps was written that way on purpose ("The AI con", "U.S.",
			// "World War II"); in an all-caps title, only the known ones.
			const core = tok.replace(/[^A-Za-z]/g, "");
			if (core.length >= 2 && core.length <= 5 && core === core.toUpperCase()) {
				const dotted = tok.includes("."); // "I.T.", "U.P."
				if ((!allCaps && (dotted || !NOT_ACRONYMS.has(core))) || ACRONYMS.has(core)) {
					forceNext = /[:;]$/.test(tok);
					return tok;
				}
			}
			const bare = tok.replace(/[^A-Za-z'’-]/g, "").toLowerCase();
			const force = forceNext || isLast;
			forceNext = /[:;]$/.test(tok); // next word starts a subtitle -> capitalize it
			if (!force && SMALL.has(bare)) return tok.toLowerCase();
			return capitalize(tok);
		})
		.join(" ");
}
