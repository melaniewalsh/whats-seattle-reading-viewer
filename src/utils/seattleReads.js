// Seattle Reads, the library's citywide book club: the pick for each year
// (src/data/seattle-reads.json). Matched to a work by its work key and author slug.
import { picks } from "$data/seattle-reads.json";
import { normalizeWorkKey } from "$utils/workTitle.js";

export const SEATTLE_READS = "Seattle Reads";
export const SEATTLE_READS_URL = "https://www.spl.org/programs-and-services/authors-and-books/seattle-reads/seattle-reads-past-years";

// Keyed on the main title (before any colon): the site often shows a book
// without its subtitle ("You Are Here", not "You Are Here: Poetry in ...").
const mainKey = (title) => normalizeWorkKey(String(title).split(":")[0]);
const byKey = new Map(picks.map(([year, title, slug]) => [`${mainKey(title)}|${slug}`, year]));

// The year a book was the Seattle Reads pick, or null.
export function seattleReadsYear(title, slug) {
	if (!title || !slug) return null;
	return byKey.get(`${mainKey(title)}|${slug}`) ?? null;
}
