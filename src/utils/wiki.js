// Wikipedia previews (thumbnail + first lines) for the ranking-table hover cards.
// Authors are looked up by name; works go through Wikidata first so we match the
// actual book entity (disambiguated by "book/novel" + author) instead of whatever
// generic page happens to share the title. All endpoints are free and CORS-enabled;
// results are cached in-memory and in localStorage so each name is fetched once.
//
// Matching is still approximate — page-less or ambiguous titles return null, and
// disambiguation pages are treated as "no match" so we never show the wrong page.
// Callers must handle a null result.

const mem = new Map();

function cached(key, producer) {
	if (mem.has(key)) return mem.get(key);

	let stored = null;
	try {
		stored = localStorage.getItem(key);
	} catch {}
	if (stored !== null) {
		const p = Promise.resolve(stored ? JSON.parse(stored) : null);
		mem.set(key, p);
		return p;
	}

	const p = producer().then((v) => {
		try {
			localStorage.setItem(key, v ? JSON.stringify(v) : "");
		} catch {}
		return v;
	});
	mem.set(key, p);
	return p;
}

// Fetch the REST summary for an exact article title.
async function summaryByTitle(title) {
	const t = (title || "").trim();
	if (!t) return null;
	try {
		const res = await fetch(
			`https://en.wikipedia.org/api/rest_v1/page/summary/${encodeURIComponent(t)}?redirect=true`,
		);
		if (!res.ok) return null;
		const d = await res.json();
		if (!d || d.type === "disambiguation" || !d.extract) return null;
		return {
			title: d.title || t,
			extract: d.extract,
			thumbnail: d.thumbnail?.source || null,
			url:
				d.content_urls?.desktop?.page ||
				`https://en.wikipedia.org/wiki/${encodeURIComponent(t)}`,
		};
	} catch {
		return null;
	}
}

// Author preview: look up by display name (redirects followed).
export function wikiSummary(query) {
	return cached(`wiki:${(query || "").trim().toLowerCase()}`, () => summaryByTitle(query));
}

// Use Wikidata to resolve a book title (+ author) to its English Wikipedia title.
async function enwikiTitleFromWikidata(title, author) {
	const api = "https://www.wikidata.org/w/api.php";
	const isWork = (d) =>
		/\b(book|novel|novella|memoir|non[- ]?fiction|nonfiction|graphic novel|manga|poetry|poem|play|short story|story collection|anthology|essay|comic|picture book|children's book|autobiography|biography)\b/i.test(
			d || "",
		);
	try {
		const sres = await fetch(
			`${api}?action=wbsearchentities&search=${encodeURIComponent(title)}&language=en&uselang=en&type=item&limit=7&format=json&origin=*`,
		);
		if (!sres.ok) return null;
		const sdata = await sres.json();
		const cands = sdata?.search || [];
		if (!cands.length) return null;

		const last = (author || "").trim().split(/\s+/).pop()?.toLowerCase() || "";
		// Prefer a candidate that reads like a written work AND names the author;
		// then any written work; then any candidate that names the author.
		const pick =
			(last &&
				cands.find(
					(c) => isWork(c.description) && (c.description || "").toLowerCase().includes(last),
				)) ||
			cands.find((c) => isWork(c.description)) ||
			(last && cands.find((c) => (c.description || "").toLowerCase().includes(last))) ||
			null;
		if (!pick) return null;

		const eres = await fetch(
			`${api}?action=wbgetentities&ids=${pick.id}&props=sitelinks&sitefilter=enwiki&format=json&origin=*`,
		);
		if (!eres.ok) return null;
		const edata = await eres.json();
		return edata?.entities?.[pick.id]?.sitelinks?.enwiki?.title || null;
	} catch {
		return null;
	}
}

// Work preview: resolve via Wikidata (book/author aware), falling back to a plain
// title lookup if Wikidata has nothing useful.
export function wikiWork(title, author) {
	const key = `wikiwork:${(title || "").trim().toLowerCase()}|${(author || "").trim().toLowerCase()}`;
	return cached(key, async () => {
		const en = await enwikiTitleFromWikidata(title, author);
		if (en) {
			const s = await summaryByTitle(en);
			if (s) return s;
		}
		return summaryByTitle(title);
	});
}
