// Resolve a book-cover thumbnail for a (title, author) via Open Library's free
// search + covers API (no key). Covers are hotlinked from Open Library — the
// same service library catalogs use — with graceful fallback when there's no
// match. Cached in-memory and in localStorage so we only query each work once.
//
// We don't have ISBNs for most rows (SPL only records them from ~2021), so we
// match on title + author, which is approximate — some covers will be a wrong
// edition or missing. Callers must handle a null result.

import { searchTitle } from "./cleanTitle.js";

const mem = new Map(); // key -> Promise<string|null>

// Versioned so old poisoned "" (no-cover) entries from stricter/messier queries
// are ignored after this fix.
function keyOf(title, author) {
	return `cover3:${(title || "").toLowerCase()}|${(author || "").toLowerCase()}`;
}

async function queryCover(title, author) {
	if (!title) return null;
	const params = new URLSearchParams({ title, limit: "1", fields: "cover_i" });
	if (author) params.set("author", author);
	try {
		const res = await fetch(`https://openlibrary.org/search.json?${params}`);
		if (!res.ok) return null;
		const data = await res.json();
		return data?.docs?.[0]?.cover_i ?? null;
	} catch {
		return null;
	}
}

async function resolve(title, author) {
	// Query with the cleaned-up title (catalog cruft breaks the match). Try with
	// the author first; if that finds nothing, retry title-only — Open Library's
	// author strings are often spelled differently than the SPL catalog's.
	const clean = searchTitle(title);
	let id = await queryCover(clean, author);
	if (id == null && author) id = await queryCover(clean, "");
	// -L (large, up to ~500px) instead of -M (~180px) so covers stay crisp on
	// retina displays and when shown at larger sizes.
	return id != null ? `https://covers.openlibrary.org/b/id/${id}-L.jpg` : null;
}

// Returns a Promise<string|null> (the cover URL, or null if none / on error).
export function coverUrl(title, author) {
	const k = keyOf(title, author);
	if (mem.has(k)) return mem.get(k);

	let cached = null;
	try {
		cached = localStorage.getItem(k);
	} catch {}
	// Only real hits are persisted (see below), so a stored value is always a URL.
	if (cached) {
		const p = Promise.resolve(cached);
		mem.set(k, p);
		return p;
	}

	const p = resolve(title, author).then((url) => {
		// Persist only successes — a miss might be a transient network/rate-limit
		// failure, so let it retry next session rather than caching a dead null.
		if (url) {
			try {
				localStorage.setItem(k, url);
			} catch {}
		}
		return url;
	});
	mem.set(k, p);
	return p;
}
