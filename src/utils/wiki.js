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

// Does this summary describe a person / writer (vs a same-named place or concept)?
function looksLikePerson(s) {
	if (!s) return false;
	const hay = `${s.description || ""} ${s.extract || ""}`.toLowerCase();
	return /\b(author|writer|novelist|poet|essayist|journalist|illustrator|cartoonist|memoirist|playwright|screenwriter|editor|columnist|born)\b/.test(
		hay,
	);
}

// Find an author's English Wikipedia title via a name-scoped, writer-biased search.
async function enwikiTitleForAuthor(name) {
	const q = `intitle:"${name}" author OR writer OR novelist OR poet OR illustrator OR journalist`;
	try {
		const res = await fetch(
			`https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch=${encodeURIComponent(q)}&srnamespace=0&srlimit=6&format=json&origin=*`,
		);
		if (!res.ok) return null;
		const d = await res.json();
		const bad = /\(disambiguation\)|^list of /i;
		const hits = (d?.query?.search || []).map((h) => h.title).filter((t) => !bad.test(t));
		return hits[0] || null;
	} catch {
		return null;
	}
}

// Author preview: direct name lookup (fast path), with a writer-biased search to
// rescue ambiguous names, always falling back to the direct result.
export function wikiSummary(name) {
	return cached(`wiki2:${(name || "").trim().toLowerCase()}`, async () => {
		const direct = await summaryByTitle(name);
		if (direct && looksLikePerson(direct)) return direct;
		const en = await enwikiTitleForAuthor(name);
		if (en) {
			const s = await summaryByTitle(en);
			if (s && looksLikePerson(s)) return s;
		}
		return direct;
	});
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

// Pick the most book-like article title from a set of Wikipedia search hits.
function pickWorkTitle(hits, author) {
	const authorLower = (author || "").trim().toLowerCase();
	const bad =
		/\((disambiguation|film|tv series|miniseries|season|soundtrack|album|song|single|opera|play|musical|video game|band|character)\)|in popular culture$/i;
	const good =
		/\((novel|memoir|book|novella|short story collection|autobiography|biography|poetry collection|comics?|manga)\)/i;
	const usable = hits.filter((t) => t.toLowerCase() !== authorLower && !bad.test(t));
	return usable.find((t) => good.test(t)) || usable[0] || null;
}

// Resolve a book to its English Wikipedia title via a title-scoped search that
// also requires the author — this disambiguates crowded titles ("Circe",
// "Educated") to the actual book rather than the myth/concept page.
async function enwikiTitleForWork(title, author) {
	const q = `intitle:"${title}" ${author}`.trim();
	try {
		const res = await fetch(
			`https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch=${encodeURIComponent(q)}&srnamespace=0&srlimit=6&format=json&origin=*`,
		);
		if (!res.ok) return null;
		const d = await res.json();
		return pickWorkTitle((d?.query?.search || []).map((h) => h.title), author);
	} catch {
		return null;
	}
}

// Safety net for the last-resort plain-title lookup: only trust it if the summary
// actually reads like this author's book (names the author, or a work keyword),
// so "Circe" never resolves to the Greek myth, "Educated" never to education, etc.
function looksLikeWork(s, author) {
	if (!s) return false;
	const hay = (s.extract || "").toLowerCase();
	const last = (author || "").trim().split(/\s+/).pop()?.toLowerCase();
	if (last && last.length > 2 && hay.includes(last)) return true;
	return /\b(novel|memoir|book|novella|non-?fiction|graphic novel|poetry|short stor|anthology|autobiography|biography)\b/.test(
		hay,
	);
}

// Work preview: title-scoped Wikipedia search (author-aware) first, then Wikidata,
// then a plain-title lookup guarded by looksLikeWork so we never show a same-named
// non-book page.
export function wikiWork(title, author) {
	const key = `wikiwork2:${(title || "").trim().toLowerCase()}|${(author || "").trim().toLowerCase()}`;
	return cached(key, async () => {
		const en = (await enwikiTitleForWork(title, author)) || (await enwikiTitleFromWikidata(title, author));
		if (en) {
			const s = await summaryByTitle(en);
			if (s) return s;
		}
		const direct = await summaryByTitle(title);
		return looksLikeWork(direct, author) ? direct : null;
	});
}
