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
	return `cover8:${(title || "").toLowerCase()}|${(author || "").toLowerCase()}`;
}

const TITLE_STOP = new Set(["a", "an", "the", "and", "or", "of", "to", "in", "for", "is"]);
function titleTokens(s) {
	return (s || "")
		.toLowerCase()
		.replace(/[^a-z0-9 ]+/g, " ")
		.split(/\s+/)
		.filter((t) => t && !TITLE_STOP.has(t));
}
// Fraction of the REQUESTED title's words that appear in the result's title.
// Containment (not symmetric Jaccard) so a subtitle on the result — "Still Life
// (A Three Pines Mystery)" — doesn't dilute the score, while a different volume
// in a series (sharing only boilerplate like "Harry Potter") still falls short.
function titleContainment(requested, found) {
	const A = titleTokens(requested);
	if (!A.length) return 0;
	const B = new Set(titleTokens(found));
	let inter = 0;
	for (const t of A) if (B.has(t)) inter++;
	return inter / A.length;
}

// Study guides, summaries, and workbooks masquerade as the real book (and can be
// weirdly popular), so drop them entirely.
const JUNK_RE = /\b(summary|summaries|study\s?guide|analysis|sparknotes|cliffs?notes|workbook|conversation starters|quicklet|instaread|blinkist|bookrags|trivia[- ]on)\b/i;
function isJunk(d) {
	if (JUNK_RE.test(d.title || "")) return true;
	return (d.author_name || []).some((a) => JUNK_RE.test(a));
}
// Prefer editions that include English (or have no language recorded) over
// Spanish-only / other-language work records.
function hasEnglish(d) {
	return !d.language || d.language.includes("eng");
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
		limit: "20",
		fields: "key,cover_i,edition_count,readinglog_count,title,language,author_name",
	});
	try {
		const res = await fetch(`https://openlibrary.org/search.json?${params}`);
		if (!res.ok) return null;
		const data = await res.json();
		const docs = (data?.docs || []).filter((d) => d.cover_i != null && !isJunk(d));
		if (!docs.length) return null;
		// Keep only results whose title actually matches the one we asked for. A
		// bare popularity sort collapses a whole series onto its most-borrowed
		// volume — every "Harry Potter …" query returns book 1, the runaway
		// favorite. Containment still accepts genuine variants of the same title
		// (Sorcerer's ↔ Philosopher's). If nothing clears the gate, fall back to
		// all results so an odd title still gets some cover.
		const gated = docs.filter((d) => titleContainment(title, d.title) >= 0.6);
		const pool = gated.length ? gated : docs;
		// Prefer a work with an English edition, then the most popular one.
		pool.sort(
			(a, b) =>
				(hasEnglish(b) ? 1 : 0) - (hasEnglish(a) ? 1 : 0) ||
				(b.readinglog_count || 0) - (a.readinglog_count || 0) ||
				(b.edition_count || 0) - (a.edition_count || 0)
		);
		return pool[0] ?? null;
	} catch {
		return null;
	}
}

// A work's default cover_i can be a foreign-language edition even when English
// editions exist (e.g. Game Changer's cover is the French "Sortie de zone").
// When the work is multilingual, check its editions: if the default cover
// positively belongs to a non-English edition, swap in an English edition's
// cover. Conservative — we only swap on a confirmed non-English owner, so good
// English defaults (whose owning edition isn't language-tagged) are left alone.
async function englishCover(doc) {
	const cover = doc.cover_i;
	const langs = doc.language;
	if (!doc.key || !langs || langs.every((l) => l === "eng")) return cover;
	try {
		const res = await fetch(`https://openlibrary.org${doc.key}/editions.json?limit=50`);
		if (!res.ok) return cover;
		const entries = (await res.json())?.entries || [];
		let ownerLangs = null;
		const engCovers = [];
		for (const e of entries) {
			const el = (e.languages || []).map((l) => (l.key || "").split("/").pop());
			const covers = (e.covers || []).filter((c) => c && c > 0);
			if (el.includes("eng")) engCovers.push(...covers);
			if (covers.includes(cover)) ownerLangs = el;
		}
		if (ownerLangs && !ownerLangs.includes("eng") && engCovers.length) return engCovers[0];
		return cover;
	} catch {
		return cover;
	}
}

async function resolve(title, author) {
	// Query with the cleaned-up title (catalog cruft breaks the match). Try with
	// the author first; if that finds nothing, retry title-only — Open Library's
	// author strings are often spelled differently than the SPL catalog's.
	const clean = searchTitle(title);
	let doc = await queryCover(clean, author);
	if (!doc && author) doc = await queryCover(clean, "");
	if (!doc) return null;
	const id = await englishCover(doc);
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
