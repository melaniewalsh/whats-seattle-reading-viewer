// Build "look it up elsewhere" search URLs for an author or title. Used by the
// author/title drilldown header and the (toggleable) per-row lookup in the
// ranking tables. Search URLs, so they always resolve even without an exact id.
export function lookupUrls(q) {
	const e = encodeURIComponent(q || "");
	return {
		wikipedia: `https://en.wikipedia.org/wiki/Special:Search?search=${e}`,
		goodreads: `https://www.goodreads.com/search?q=${e}`,
		librarything: `https://www.librarything.com/search.php?search=${e}`,
		worldcat: `https://search.worldcat.org/search?q=${e}`,
	};
}
