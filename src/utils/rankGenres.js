// Genres shown by DEFAULT in the "Most Borrowed" rankings — the gallery rows and
// the top of the filter dropdown — in this order. Every other genre in the data
// stays filterable (see extraGenres), just tucked under a divider. Genres are
// shown under their regular data names.
//
// "Kids' Books" is the data's "Juvenile Fiction". "Crime Fiction" isn't a
// distinct genre in the data (closest: Mystery / True Crime), so it's omitted.
export const RANK_GENRES = [
	"Romance",
	"Fantasy",
	"Science Fiction",
	"Juvenile Fiction",
	"Literary & Classic Fiction",
	"Mystery",
	"Thriller & Suspense",
	"Juvenile Nonfiction",
	"Horror",
	"Western",
	"Self-Help",
	"Politics & Government",
	"Computers & Technology",
	"Poetry",
	// Not a genre: every book by the 93 authors in the Norton Anthology of
	// American Literature, Volume E (src/data/curated-lists.json).
	"Canonical American Authors (1945—Present)",
];

// Genres left off the site for now (the data still has them): the ethnic and
// racial fiction categories. Hidden from Most Borrowed, the Genres timeline,
// and the genre links on book pages.
export const HIDDEN_GENRES = new Set([
	"African American Fiction",
	"Asian Fiction",
	"Hispanic & Latino Fiction",
	"Native American Fiction",
	"Indigenous Fiction",
	"Jewish Fiction",
]);

// The default/curated genres present in the data, ordered; "All genres" first.
export function curateGenres(available) {
	const set = new Set(available || []);
	const out = set.has("All genres") ? ["All genres"] : [];
	for (const g of RANK_GENRES) if (set.has(g) && !HIDDEN_GENRES.has(g)) out.push(g);
	return out;
}

// Every other genre in the data (still filterable, shown under a divider), A–Z.
export function extraGenres(available) {
	const shown = new Set(["All genres", ...RANK_GENRES]);
	return (available || []).filter((g) => !shown.has(g) && !HIDDEN_GENRES.has(g)).sort();
}

// Genres display under their regular names.
export const genreLabel = (g) => g;
