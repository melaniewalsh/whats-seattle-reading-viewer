// Curated, ordered set of genres surfaced in the "Most Borrowed" rankings, with
// the short display labels used in the UI. The underlying value stays the data's
// genre name (so filtering/deep-links keep working); only the label is friendly.
// Only genres actually present in the loaded data appear; "All genres" leads.
//
// Note: "Crime Fiction" isn't a distinct genre in the data (the closest are
// Mystery and True Crime), so it isn't included here.
export const RANK_GENRES = [
	{ genre: "Romance", label: "Romance" },
	{ genre: "Fantasy", label: "Fantasy" },
	{ genre: "Science Fiction", label: "Science Fiction" },
	{ genre: "Juvenile Fiction", label: "Kids' Books" },
	{ genre: "Literary & Classic Fiction", label: "Literary & Classic" },
	{ genre: "Mystery", label: "Mystery" },
	{ genre: "Thriller & Suspense", label: "Thriller" },
	{ genre: "Juvenile Nonfiction", label: "Juvenile Nonfiction" },
	{ genre: "Horror", label: "Horror" },
	{ genre: "Western", label: "Western" },
	{ genre: "Self-Help", label: "Self-Help" },
	{ genre: "Politics & Government", label: "Politics" },
	{ genre: "Computers & Technology", label: "Computers" },
	{ genre: "Poetry", label: "Poetry" },
];

const LABELS = new Map(RANK_GENRES.map((r) => [r.genre, r.label]));

// Order the available genres to the curated whitelist; "All genres" first.
export function curateGenres(available) {
	const set = new Set(available || []);
	const out = set.has("All genres") ? ["All genres"] : [];
	for (const { genre } of RANK_GENRES) if (set.has(genre)) out.push(genre);
	return out;
}

export const genreLabel = (g) => LABELS.get(g) || g;
