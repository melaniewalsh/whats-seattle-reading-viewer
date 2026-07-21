// Resolve a book-cover thumbnail for a (title, author) via Open Library's free
// search + covers API (no key). Covers are hotlinked from Open Library — the
// same service library catalogs use — with graceful fallback when there's no
// match. Cached in-memory and in localStorage so we only query each work once.
//
// We don't have ISBNs for most rows (SPL only records them from ~2021), so we
// match on title + author, which is approximate — some covers will be a wrong
// edition or missing. Callers must handle a null result.

const mem = new Map(); // key -> Promise<string|null>

function keyOf(title, author) {
	return `cover:${(title || "").toLowerCase()}|${(author || "").toLowerCase()}`;
}

async function resolve(title, author) {
	const params = new URLSearchParams({
		title: title || "",
		author: author || "",
		limit: "1",
		fields: "cover_i",
	});
	try {
		const res = await fetch(`https://openlibrary.org/search.json?${params}`);
		if (!res.ok) return null;
		const data = await res.json();
		const id = data?.docs?.[0]?.cover_i;
		return id ? `https://covers.openlibrary.org/b/id/${id}-M.jpg` : null;
	} catch {
		return null;
	}
}

// Returns a Promise<string|null> (the cover URL, or null if none / on error).
export function coverUrl(title, author) {
	const k = keyOf(title, author);
	if (mem.has(k)) return mem.get(k);

	let cached = null;
	try {
		cached = localStorage.getItem(k);
	} catch {}
	if (cached !== null) {
		const p = Promise.resolve(cached || null);
		mem.set(k, p);
		return p;
	}

	const p = resolve(title, author).then((url) => {
		try {
			localStorage.setItem(k, url || "");
		} catch {}
		return url;
	});
	mem.set(k, p);
	return p;
}
