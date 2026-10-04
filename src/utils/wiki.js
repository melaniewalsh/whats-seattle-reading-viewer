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

// A genre list fires dozens of lookups at once, each making several requests.
// Cap how many hit Wikipedia/Wikidata concurrently so the burst doesn't trip
// rate limits and drop summaries. Excess calls queue and run as slots free up.
let active = 0;
const waiting = [];
function acquire() {
	if (active < 6) {
		active++;
		return Promise.resolve();
	}
	return new Promise((resolve) => waiting.push(resolve));
}
function release() {
	const next = waiting.shift();
	if (next) next();
	else active--;
}
async function wfetch(url) {
	await acquire();
	try {
		return await fetch(url);
	} finally {
		release();
	}
}

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
		// Only persist real hits. A null here is frequently a transient network or
		// rate-limit failure during the initial burst of lookups (a genre list fires
		// dozens at once) — persisting it would hide a resolvable summary forever, even
		// for famous books. Nulls live only in this session's in-memory cache, so an
		// item that missed once is retried on the next page load.
		try {
			if (v) localStorage.setItem(key, JSON.stringify(v));
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
		const res = await wfetch(
			`https://en.wikipedia.org/api/rest_v1/page/summary/${encodeURIComponent(t)}?redirect=true`,
		);
		if (!res.ok) return null;
		const d = await res.json();
		if (!d || d.type === "disambiguation" || !d.extract) return null;
		return {
			title: d.title || t,
			// Wikipedia's one-line short description, e.g. "Irish author (born 1991)"
			// or "2018 novel by Sally Rooney" — shown under the page heading.
			description: d.description || null,
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
	return /\b(author|writer|novelist|poet|essayist|journalist|illustrator|cartoonist|comics|graphic novel|memoirist|playwright|screenwriter|editor|columnist|born)\b/.test(
		hay,
	);
}

// Rank an author's candidate Wikipedia titles from a name-scoped, occupation-biased
// search: an author/illustrator-qualified page first, then other qualified pages,
// then the bare name (which for ambiguous names is usually a disambiguation) last.
async function authorTitleCandidates(name) {
	const q = `intitle:"${name}" author OR writer OR novelist OR poet OR illustrator OR cartoonist OR journalist OR comics OR editor`;
	try {
		const res = await wfetch(
			`https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch=${encodeURIComponent(q)}&srnamespace=0&srlimit=8&format=json&origin=*`,
		);
		if (!res.ok) return [];
		const d = await res.json();
		const nameLower = name.trim().toLowerCase();
		const qual =
			/\((author|illustrator|writer|novelist|cartoonist|poet|comics|comic|editor|screenwriter|playwright|memoirist|journalist)\)/i;
		const rank = (t) => (qual.test(t) ? 0 : t.toLowerCase() === nameLower ? 2 : 1);
		return (d?.query?.search || [])
			.map((h) => h.title)
			.filter((t) => !/^list of /i.test(t))
			.sort((a, b) => rank(a) - rank(b));
	} catch {
		return [];
	}
}

// Catalog names often carry a middle initial the Wikipedia title omits
// ("Lincoln C. Peirce" vs "Lincoln Peirce"), so also try the name with lone
// middle initials stripped.
function nameVariants(name) {
	const n = (name || "").trim();
	const parts = n.split(/\s+/);
	const variants = [n];
	if (parts.length > 2) {
		const stripped = parts
			.filter((p, i) => i === 0 || i === parts.length - 1 || !/^[A-Za-z]\.?$/.test(p))
			.join(" ");
		if (stripped && stripped !== n) variants.push(stripped);
	}
	return variants;
}

// Author preview: direct name lookup across name variants (fast path), then an
// occupation-biased search that walks candidate pages until one reads like a
// writer/illustrator — so "Peter Brown" resolves to the children's illustrator,
// and "Lincoln C. Peirce" to the "Lincoln Peirce" cartoonist page.
export function wikiSummary(name) {
	return cached(`wiki6:${(name || "").trim().toLowerCase()}`, async () => {
		const variants = nameVariants(name);
		let firstDirect = null;
		for (const v of variants) {
			const direct = await summaryByTitle(v);
			if (direct && looksLikePerson(direct)) return direct;
			if (direct && !firstDirect) firstDirect = direct;
		}
		for (const v of variants) {
			for (const t of (await authorTitleCandidates(v)).slice(0, 4)) {
				const s = await summaryByTitle(t);
				if (s && looksLikePerson(s)) return s;
			}
		}
		return firstDirect;
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
		const sres = await wfetch(
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

		const eres = await wfetch(
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
function pickWorkTitle(hits, author, title = "") {
	const authorLower = (author || "").trim().toLowerCase();
	const titleLower = (title || "").trim().toLowerCase();
	// Articles ABOUT a book rather than the book itself: adaptations, its
	// characters, an authorship debate ("Frankenstein authorship question"), ...
	const bad =
		/\((disambiguation|film|tv series|miniseries|season|soundtrack|album|song|single|opera|play|musical|video game|band|character)\)|in popular culture$|authorship|adaptations?\b|^list of|bibliography|\bcharacters?\b/i;
	const good =
		/\((novel|memoir|book|novella|short story collection|autobiography|biography|poetry collection|comics?|manga)\)/i;
	const usable = hits.filter((t) => t.toLowerCase() !== authorLower && !bad.test(t));
	// The book's own article: "Title (novel)" first, then an article named
	// exactly the title, then any work-tagged hit, then the top hit.
	const base = (t) => t.replace(/\s*\([^)]*\)\s*$/, "").toLowerCase();
	return (
		usable.find((t) => good.test(t) && base(t) === titleLower) ||
		usable.find((t) => t.toLowerCase() === titleLower) ||
		usable.find((t) => good.test(t)) ||
		usable[0] ||
		null
	);
}

// Resolve a book to its English Wikipedia title via a title-scoped search that
// also requires the author — this disambiguates crowded titles ("Circe",
// "Educated") to the actual book rather than the myth/concept page.
async function enwikiTitleForWork(title, author) {
	const q = `intitle:"${title}" ${author}`.trim();
	try {
		const res = await wfetch(
			`https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch=${encodeURIComponent(q)}&srnamespace=0&srlimit=6&format=json&origin=*`,
		);
		if (!res.ok) return null;
		const d = await res.json();
		return pickWorkTitle((d?.query?.search || []).map((h) => h.title), author, title);
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

// Stricter than looksLikeWork: the resolved summary must actually name the author,
// so a different author's same-titled book (Douglas Preston's "Blasphemy" vs Sherman
// Alexie's) can't win when the fallbacks aren't author-constrained.
function mentionsAuthor(s, author) {
	if (!s) return false;
	const last = (author || "").trim().split(/\s+/).pop()?.toLowerCase() || "";
	if (last.length < 3) return true; // no usable surname -> can't verify, accept
	const hay = `${s.title || ""} ${s.description || ""} ${s.extract || ""}`.toLowerCase();
	return hay.includes(last);
}

// Manual summary overrides for works whose Wikipedia match fails — recent or niche
// books with no article (e.g. new poetry collections). Same shape as a Wikipedia
// summary ({ extract, url }) so callers use it unchanged. Keyed by the bare title
// (subtitle / "/ author" stripped), matched exactly or as a leading word-run so the
// catalog's subtitle doesn't matter.
const WORK_SUMMARY_OVERRIDES = {
	"you are here": {
		extract:
			"Edited by U.S. Poet Laureate Ada Limón, this anthology gathers fifty original poems on our relationship to the natural world by leading contemporary poets — published by Milkweed Editions in association with the Library of Congress.",
		url: "https://www.goodreads.com/book/show/192723639-you-are-here",
	},
	"water water": {
		extract:
			"A 2024 collection of sixty new poems by former U.S. Poet Laureate Billy Collins, finding wit, tenderness, and a whiff of mystery in the beauties and ironies of everyday life.",
		url: "https://www.penguinrandomhouse.com/books/743538/water-water-by-billy-collins/",
	},
};
function normSummaryKey(title) {
	return (title || "")
		.toLowerCase()
		.normalize("NFD").replace(/[̀-ͯ]/g, "")
		.replace(/\s*[:/].*$/, "")   // drop subtitle / statement of responsibility
		.replace(/\([^)]*\)/g, " ")
		.replace(/[^a-z0-9]+/g, " ")
		.replace(/^(a|an|the)\s+/, "")
		.trim();
}
function summaryOverrideFor(title) {
	const norm = normSummaryKey(title);
	if (!norm) return null;
	for (const key in WORK_SUMMARY_OVERRIDES) {
		if (norm === key || norm.startsWith(key + " ")) return WORK_SUMMARY_OVERRIDES[key];
	}
	return null;
}

// Work preview: a manual override first, then an author-constrained title search
// (trusted), then Wikidata and a plain-title lookup — both verified to actually name
// the author so a same-titled book by someone else never sneaks through.
export function wikiWork(title, author) {
	const ov = summaryOverrideFor(title);
	if (ov) return Promise.resolve(ov);
	return wikiWorkResolved(title, author);
}
function wikiWorkResolved(title, author) {
	const key = `wikiwork6:${(title || "").trim().toLowerCase()}|${(author || "").trim().toLowerCase()}`;
	return cached(key, async () => {
		const en = await enwikiTitleForWork(title, author);
		if (en) {
			const s = await summaryByTitle(en);
			if (s) return s;
		}
		const wd = await enwikiTitleFromWikidata(title, author);
		if (wd) {
			const s = await summaryByTitle(wd);
			if (s && mentionsAuthor(s, author)) return s;
		}
		const direct = await summaryByTitle(title);
		return direct && mentionsAuthor(direct, author) && looksLikeWork(direct, author) ? direct : null;
	});
}
