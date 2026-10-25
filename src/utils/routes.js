// The site's URLs. The convention: each page is a path (/genres, /trends),
// and what that page shows is a query setting (?author=…, ?year=2026,
// ?format=ebook). Index.svelte maps each path to its view; every link and
// address-bar update goes through here so the two never drift apart.
import { base } from "$app/paths";

// view name (as Index.svelte calls it) -> path
export const PATHS = {
	home: "",
	search: "trends",
	compare: "compare",
	rankings: "most-borrowed",
	genres: "genres",
	overview: "overview",
	backlist: "backlist-boomerangs",
	subject: "subject",
	guide: "guide",
	about: "about",
	cite: "cite",
	made: "how-we-made-this",
	publications: "publications",
	norton: "norton-anthology",
	spl500: "top-500-novels"
};

const VIEW_OF = Object.fromEntries(Object.entries(PATHS).map(([view, p]) => [p, view]));

// Every page path, for prerendering (src/routes/[[page]]/+page.js).
export const PAGE_SLUGS = Object.values(PATHS).filter(Boolean);

export const pathFor = (view) => `${base}/${PATHS[view] ?? ""}`;

// The view a pathname names ("/genres" -> "genres"), or null for an unknown one.
export function viewOfPath(pathname) {
	const p = (pathname || "").slice(base.length).replace(/^\/+|\/+$/g, "").replace(/\.html$/, "");
	return p in VIEW_OF ? VIEW_OF[p] : null;
}

// Point a URL object at a page, keeping its query settings.
export function setPage(url, view) {
	url.pathname = pathFor(view);
	url.searchParams.delete("tab");
	return url;
}
