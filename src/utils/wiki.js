// Fetch a short Wikipedia preview (thumbnail + first lines of the article) for an
// author or work, for the hover cards in the ranking tables. Uses Wikipedia's
// free, CORS-enabled REST summary endpoint — no key. Cached in-memory and in
// localStorage so each name is fetched once.
//
// Matching is by title/name (with redirect following), so it's approximate:
// popular authors resolve cleanly, but ambiguous or page-less titles return
// null. Disambiguation pages are treated as "no match" so we never show the
// wrong person/book. Callers must handle a null result.

const mem = new Map(); // key -> Promise<summary|null>

function keyOf(q) {
	return `wiki:${(q || "").trim().toLowerCase()}`;
}

async function resolve(query) {
	const title = (query || "").trim();
	if (!title) return null;
	try {
		const res = await fetch(
			`https://en.wikipedia.org/api/rest_v1/page/summary/${encodeURIComponent(title)}?redirect=true`,
		);
		if (!res.ok) return null;
		const d = await res.json();
		if (!d || d.type === "disambiguation" || !d.extract) return null;
		return {
			title: d.title || title,
			extract: d.extract,
			thumbnail: d.thumbnail?.source || null,
			url:
				d.content_urls?.desktop?.page ||
				`https://en.wikipedia.org/wiki/${encodeURIComponent(title)}`,
		};
	} catch {
		return null;
	}
}

// Returns a Promise<summary|null>, where summary is {title, extract, thumbnail, url}.
export function wikiSummary(query) {
	const k = keyOf(query);
	if (mem.has(k)) return mem.get(k);

	let cached = null;
	try {
		cached = localStorage.getItem(k);
	} catch {}
	if (cached !== null) {
		const p = Promise.resolve(cached ? JSON.parse(cached) : null);
		mem.set(k, p);
		return p;
	}

	const p = resolve(query).then((v) => {
		try {
			localStorage.setItem(k, v ? JSON.stringify(v) : "");
		} catch {}
		return v;
	});
	mem.set(k, p);
	return p;
}
