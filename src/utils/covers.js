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
	return `cover6:${(title || "").toLowerCase()}|${(author || "").toLowerCase()}`;
}

// Token-overlap (Jaccard) between two titles, ignoring punctuation and a few
// stopwords. Used to check that a search result is really the same title.
const TITLE_STOP = new Set(["a", "an", "the", "and", "or", "of", "to", "in", "for", "is"]);
function titleTokens(s) {
	return new Set(
		(s || "")
			.toLowerCase()
			.replace(/[^a-z0-9 ]+/g, " ")
			.split(/\s+/)
			.filter((t) => t && !TITLE_STOP.has(t))
	);
}
function titleSimilarity(a, b) {
	const A = titleTokens(a), B = titleTokens(b);
	if (!A.size || !B.size) return 0;
	let inter = 0;
	for (const t of A) if (B.has(t)) inter++;
	return inter / (A.size + B.size - inter);
}

async function queryCover(title, author) {
	if (!title) return null;
	// Use a general `q=` search (title + author as free text) rather than the
	// field-scoped `title=`/`author=` params. Field-scoped search only matches
	// exact edition records and misses Open Library's merged "work" — e.g. it
	// returns an obscure 1-edition "Sorcerer's Stone" record instead of the
	// canonical Harry Potter work (cataloged under "Philosopher's Stone").
	const params = new URLSearchParams({
		q: author ? `${title} ${author}` : title,
		limit: "10",
		fields: "cover_i,edition_count,readinglog_count,title",
	});
	try {
		const res = await fetch(`https://openlibrary.org/search.json?${params}`);
		if (!res.ok) return null;
		const data = await res.json();
		const docs = (data?.docs || []).filter((d) => d.cover_i != null);
		if (!docs.length) return null;
		// Keep only results whose title actually matches the one we asked for. A
		// bare popularity sort collapses a whole series onto its most-borrowed
		// volume — every "Harry Potter …" query returns book 1, the runaway
		// favorite. The token-overlap gate still accepts genuine variants of the
		// same title (Sorcerer's ↔ Philosopher's). If nothing clears the gate,
		// fall back to all results so an odd title still gets some cover.
		const gated = docs.filter((d) => titleSimilarity(title, d.title) >= 0.6);
		const pool = gated.length ? gated : docs;
		// Among same-title results, prefer the most popular edition — it has the
		// cleanest, highest-res cover scan.
		pool.sort(
			(a, b) =>
				(b.readinglog_count || 0) - (a.readinglog_count || 0) ||
				(b.edition_count || 0) - (a.edition_count || 0)
		);
		return pool[0].cover_i ?? null;
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
