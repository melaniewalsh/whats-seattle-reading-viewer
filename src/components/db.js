// db.js
// -----------------------------------------------------------------------
// Loads the small static JSON files that data-prep/build_data.py writes:
//
//   meta.json                     -> { months: [...] }  shared x-axis
//   search-index.json             -> [[slug, name, total], ...] sorted total-DESC
//   authors/<shard>/<slug>.json   -> { name, total, series, titles }
//
// This replaces the previous sql.js-httpvfs approach (one ~500 MB
// library.sqlite3 the browser queried over HTTP range requests). That worked
// but a single drilldown was dozens of scattered range requests over R2's
// un-cached, rate-limited public URL -- slow, and it tripped the rate limiter.
// Here each author loads in ONE fetch of a few hundred bytes, which a CDN
// caches trivially, and search runs in-memory against one index loaded once.
//
// The exported functions keep the same names + shapes the viewer already
// consumes (getMonths / searchAuthors / getAuthor / densify), so nothing
// downstream had to change.
// -----------------------------------------------------------------------
import { base } from '$app/paths';

// In production the data lives in a PUBLIC Cloudflare R2 bucket (built +
// uploaded monthly by .github/workflows/build-data-to-r2.yml). In local dev we
// read the files `python3 data-prep/build_data.py` writes into static/data/.
const R2_BASE = 'https://pub-7559692ae8974bd6a6e7cc54db47a348.r2.dev';
const DATA_BASE = import.meta.env.PROD ? R2_BASE : `${base}/data`;

// The index files (month axis, search indexes, rankings, overview, Backlist
// Boomerangs) are replaced in place every month. R2 serves them with no
// Cache-Control header, so browsers otherwise guess a freshness window from
// Last-Modified -- often many hours -- and keep showing last month's index.
// "no-cache" makes the browser revalidate with the ETag on every load: a
// ~100-byte 304 when nothing changed, the new file when it did.
const FRESH = { cache: 'no-cache' };

// authors/<shard>/<slug>.json, where <shard> is the first two slug chars --
// must match write_author_files() in build_data.py.
function shardFor(slug) {
	return slug.slice(0, 2) || '__';
}

let monthsPromise = null;

/** Shared x-axis for every chart. Fetched once and cached for the session. */
// The "Top authors" tab dataset: top-N clustered authors per genre per year.
// { years:[...], genres:[...], data:{ genre:{ "<year>":[[slug,name,co],...],
//   "all":[...] } } }. Loaded lazily; missing file -> null (tab shows a notice).
let topAuthorsPromise = null;
export function getTopAuthors() {
	if (!topAuthorsPromise) {
		topAuthorsPromise = fetch(`${DATA_BASE}/top-authors.json`, FRESH)
			.then((r) => (r.ok ? r.json() : null))
			.catch(() => null);
	}
	return topAuthorsPromise;
}

// The "Backlist Boomerangs" dataset (data-prep/build_backlist.py): works whose
// checkouts jumped years after they first circulated, by boom year. Built by
// the monthly data workflow and uploaded to R2; a copy is bundled with the
// site as a fallback. Missing everywhere -> null.
let backlistPromise = null;
export function getBacklist() {
	if (!backlistPromise) {
		backlistPromise = (async () => {
			for (const url of [`${DATA_BASE}/backlist.json`, `${base}/backlist.json`]) {
				try {
					const r = await fetch(url, FRESH);
					if (r.ok) return await r.json();
				} catch { /* try the next source */ }
			}
			return null;
		})();
	}
	return backlistPromise;
}

// The "Top works" tab dataset: top-N clustered works per genre per year.
// { years, genres, data:{ genre:{ "<year>":[[title,author,slug,co],...], "all":[...] } } }
let topWorksPromise = null;
export function getTopWorks() {
	if (!topWorksPromise) {
		topWorksPromise = fetch(`${DATA_BASE}/top-works.json`, FRESH)
			.then((r) => (r.ok ? r.json() : null))
			.catch(() => null);
	}
	return topWorksPromise;
}

// Subject terms per genre (from genres.json, served at the Pages base — NOT R2).
// Powers the "Subject tags" line under a selected genre in the ranking tables.
let genreTermsPromise = null;
export function getGenreTerms() {
	if (!genreTermsPromise) {
		genreTermsPromise = fetch(`${base}/genres.json`, FRESH)
			.then((r) => (r.ok ? r.json() : null))
			.then((g) => {
				const m = {};
				for (const x of g?.genres || []) m[x.name] = [...(x.terms || []), ...(x.ficTerms || [])];
				return m;
			})
			.catch(() => ({}));
	}
	return genreTermsPromise;
}

export async function getMonths() {
	if (!monthsPromise) {
		monthsPromise = fetch(`${DATA_BASE}/meta.json`, FRESH)
			.then((r) => r.json())
			.then((m) => m.months);
	}
	return monthsPromise;
}

// Library-wide monthly totals for the default "all checkouts" landing view.
// Queried live from Seattle's Open Data (Socrata) API and aggregated
// server-side -- one small request, filtered to books/ebooks/audiobooks so it
// stays on-theme with the rest of the tool. The app token just identifies the
// app for a higher rate limit (public data; safe to ship). Passed as a query
// param, not a header, so the request stays a simple GET (no CORS preflight).
const SODA_RESOURCE = 'https://data.seattle.gov/resource/tmmm-ytt6.json';
const SODA_APP_TOKEN = 'bHWsGtRFRP9x8Hl8lYivqM1hQ';
let allCheckoutsPromise = null;

// MaterialType (as stored by SPL) -> the format bucket the app uses elsewhere.
const FMT_BUCKET = { BOOK: 'print', EBOOK: 'ebook', AUDIOBOOK: 'audiobook' };

// "Book" universe (print + ebook + audiobook), shared with build_genres.py.
const BOOK_UNIVERSE =
	"((usageclass = 'Physical' AND materialtype = 'BOOK') OR " +
	"(usageclass = 'Digital' AND upper(materialtype) IN ('EBOOK', 'AUDIOBOOK')))";

/**
 * Live monthly book-checkout counts for a genre defined by subject-heading
 * match terms (include OR'd, exclude AND-NOT'd) -- used when the user edits a
 * genre's terms in the Genres tab. Aggregated server-side, aligned to `months`.
 * This is a set-union count (each book once), so it can't be reassembled from
 * precomputed parts -- hence a live query. A few seconds per call.
 */
export async function queryGenreMonthly(includeTerms, excludeTerms, months) {
	const esc = (t) => t.replace(/'/g, "''").toUpperCase();
	const anyLike = (ts) => ts.map((t) => `upper(subjects) like '%${esc(t)}%'`).join(' OR ');
	if (!includeTerms.length) return new Array(months.length).fill(0);
	let where = `(${anyLike(includeTerms)})`;
	if (excludeTerms.length) where += ` AND NOT (${anyLike(excludeTerms)})`;
	where += ` AND ${BOOK_UNIVERSE}`;
	const soql = `SELECT checkoutyear, checkoutmonth, sum(checkouts) AS c WHERE ${where} `
		+ `GROUP BY checkoutyear, checkoutmonth LIMIT 50000`;
	const params = new URLSearchParams({ '$query': soql, '$$app_token': SODA_APP_TOKEN });
	const res = await fetch(`${SODA_RESOURCE}?${params}`);
	if (!res.ok) throw new Error(`genre query failed: ${res.status}`);
	const rows = await res.json();
	const idx = new Map(months.map((m, i) => [m, i]));
	const out = new Array(months.length).fill(0);
	for (const r of rows) {
		const key = `${r.checkoutyear}-${String(r.checkoutmonth).padStart(2, '0')}`;
		if (idx.has(key)) out[idx.get(key)] = Number(r.c) || 0;
	}
	return out;
}

/**
 * Book/ebook/audiobook checkouts per month, aligned to getMonths(). Returns
 * both the grand total (for the default line) and a per-format breakdown (for
 * the stacked-area view): { total: [...], print: [...], ebook: [...],
 * audiobook: [...] }. Served from the precomputed overview.json; only months
 * that file doesn't cover yet are aggregated live.
 */
// Live Socrata aggregation of book/ebook/audiobook checkouts by month and
// format. Over the whole dataset this is ~51M rows and takes MINUTES (it
// regularly exceeds two minutes and times out), so callers restrict it to the
// handful of months the precomputed file doesn't cover yet.
async function fetchCheckoutsLive(months, onlyMonths = null) {
	let where = "materialtype in('BOOK','EBOOK','AUDIOBOOK')";
	if (onlyMonths) {
		const parts = onlyMonths.map((m) => {
			const [y, mo] = m.split('-');
			return `(checkoutyear=${Number(y)} AND checkoutmonth=${Number(mo)})`;
		});
		where += ` AND (${parts.join(' OR ')})`;
	}
	const params = new URLSearchParams({
		'$select': 'checkoutyear,checkoutmonth,materialtype,sum(checkouts) as total',
		'$where': where,
		'$group': 'checkoutyear,checkoutmonth,materialtype',
		'$limit': '50000',
		'$$app_token': SODA_APP_TOKEN
	});
	const res = await fetch(`${SODA_RESOURCE}?${params}`);
	if (!res.ok) throw new Error(`SODA request failed: ${res.status}`);
	const rows = await res.json();
	const idx = new Map(months.map((m, i) => [m, i]));
	const zero = () => new Array(months.length).fill(0);
	const out = { total: zero(), print: zero(), ebook: zero(), audiobook: zero() };
	for (const r of rows) {
		const key = `${r.checkoutyear}-${String(r.checkoutmonth).padStart(2, '0')}`;
		const i = idx.get(key);
		if (i === undefined) continue;
		const bucket = FMT_BUCKET[r.materialtype];
		const v = Number(r.total) || 0;
		if (bucket) out[bucket][i] += v;
		out.total[i] += v;
	}
	return out;
}

// The precomputed overview (data-prep/build_overview.py): built by the monthly
// data workflow and uploaded to R2 next to meta.json, with a copy bundled into
// the site as a fallback. Returns null if neither is available.
async function fetchPrecomputedOverview() {
	for (const url of [`${DATA_BASE}/overview.json`, `${base}/overview.json`]) {
		try {
			const pre = await fetch(url, FRESH).then((r) => (r.ok ? r.json() : null));
			if (pre && Array.isArray(pre.total) && pre.total.length) return pre;
		} catch { /* try the next source */ }
	}
	return null;
}

export async function getAllCheckouts() {
	if (!allCheckoutsPromise) {
		allCheckoutsPromise = (async () => {
			const months = await getMonths();
			const keys = ['total', 'print', 'ebook', 'audiobook'];
			const pre = await fetchPrecomputedOverview();
			if (!pre) {
				// No precomputed file at all (a fresh checkout before any build):
				// the slow full aggregation is the only option.
				return fetchCheckoutsLive(months);
			}
			// Align the file to the month axis by month key. Older files have
			// no "months" list; they were built as a prefix of the axis.
			const preMonths = Array.isArray(pre.months) && pre.months.length === pre.total.length
				? pre.months
				: months.slice(0, pre.total.length);
			const at = new Map(preMonths.map((m, i) => [m, i]));
			const out = {};
			for (const k of keys) out[k] = new Array(months.length).fill(0);
			const missing = [];
			months.forEach((m, i) => {
				const j = at.get(m);
				if (j === undefined) { missing.push(m); return; }
				for (const k of keys) out[k][i] = Number(pre[k]?.[j]) || 0;
			});
			// The data build can add a month before the overview file catches
			// up. Fill just that gap live (seconds) rather than redoing all of
			// it (minutes); if even that fails, show what we have.
			if (missing.length) {
				try {
					const tail = await fetchCheckoutsLive(months, missing);
					for (const m of missing) {
						const i = months.indexOf(m);
						for (const k of keys) out[k][i] = tail[k][i];
					}
				} catch (e) {
					console.warn('overview: could not fill missing months live', missing, e);
				}
			}
			return out;
		})();
	}
	return allCheckoutsPromise;
}

// Junk "authors": the raw data dumps every checkout with a missing/unknown
// author name into a single placeholder ("NA"), which balloons into a 75 MB,
// 132k-title file that crashes the tab if it's fetched + charted. It's the #1
// entry by total, so the auto-load-top-author-on-open behaviour would hit it
// every time. Drop these from the index so they can't be shown or auto-loaded.
// (build_data.py also excludes them at the source now; this is the belt to that
// suspenders, and keeps already-built indexes safe.)
const JUNK_AUTHOR_NAMES = new Set(['', 'NA', 'N/A', 'Unknown', 'unknown', 'Various', 'various']);

// The search index: [[slug, name, total], ...] sorted total-DESC. Loaded once
// (a few MB, gzipped on the wire + CDN-cached), then every keystroke searches
// it in memory. We also cache a parallel lowercased-name array so the
// per-keystroke substring scan doesn't re-lowercase 350k names each time.
let indexPromise = null;
function getIndex() {
	if (!indexPromise) {
		indexPromise = fetch(`${DATA_BASE}/search-index.json`, FRESH)
			.then((r) => r.json())
			.then((all) => {
				const rows = all.filter((r) => !JUNK_AUTHOR_NAMES.has(r[1]));
				// Precompute each name's alphanumeric "words" (punctuation + dates
				// split out) for punctuation-insensitive word matching in search.
				const words = rows.map((r) => r[1].toLowerCase().split(/[^a-z0-9]+/).filter(Boolean));
				return { rows, words };
			});
	}
	return indexPromise;
}

/**
 * Search authors by name (used by the search-as-you-type box). An empty query
 * returns the top authors by total checkouts, so there's always something
 * sensible to show before the user types. Because the index is pre-sorted
 * total-DESC, the first `limit` matches we hit are already the most-borrowed.
 */
// True when query word `t` is a prefix of the concatenation of one-or-more
// consecutive name words starting at a word boundary. This makes search ignore
// punctuation and spacing: "greenberg" clears the middle initial in
// "cathy l greenberg", "leguin" matches "le"+"guin" in "ursula k le guin", and
// "steph" still prefix-matches "stephen" -- while "king" never matches inside
// "hawking" (matching only ever starts at a word boundary).
function wordSpanMatch(words, t) {
	for (let i = 0; i < words.length; i++) {
		let acc = '';
		for (let k = i; k < words.length && acc.length < t.length; k++) acc += words[k];
		if (acc.startsWith(t)) return true;
	}
	return false;
}

// "Surprise me": a random author to explore. Picked from the most-borrowed
// pool (the index is sorted total-DESC) so the result is someone with a real
// trend to show, not a one-off catalog record.
export async function randomAuthor() {
	const { rows } = await getIndex();
	if (!rows.length) return null;
	const pool = Math.min(rows.length, 3000);
	const r = rows[Math.floor(Math.random() * pool)];
	return { slug: r[0], name: r[1], total: r[2] };
}

// A random title from the By-title index (already limited to well-borrowed
// titles, so anything here is worth showing).
export async function randomTitle() {
	const { rows } = await getTitleIndex();
	if (!rows.length) return null;
	const r = rows[Math.floor(Math.random() * rows.length)];
	return { title: r[0], slug: r[1], author: r[2], total: r[3] };
}

export async function searchAuthors(query, limit = 20) {
	const { rows, words } = await getIndex();
	// Split the query into alphanumeric words too, so punctuation the user types
	// ("ursula k. le guin") is ignored and word order doesn't matter.
	const terms = (query ?? '').toLowerCase().split(/[^a-z0-9]+/).filter(Boolean);

	const out = [];
	for (let i = 0; i < rows.length; i++) {
		if (terms.length && !terms.every((t) => wordSpanMatch(words[i], t))) continue;
		const [slug, name, total] = rows[i];
		out.push({ slug, name, total });
		if (out.length >= limit) break;
	}
	return out;
}

// The TITLE index for the "By title" reverse-lookup: [[title, slug, author,
// total], ...] sorted total-DESC, only titles above a checkout threshold (so it
// stays small). Loaded lazily on first title search. Missing file -> empty.
let titleIndexPromise = null;
function getTitleIndex() {
	if (!titleIndexPromise) {
		titleIndexPromise = fetch(`${DATA_BASE}/title-index.json`, FRESH)
			.then((r) => (r.ok ? r.json() : []))
			.then((rows) => {
				// Each author's indexed books, most-borrowed first (rows are sorted
				// by total), so an author search can list their books too.
				const bySlug = new Map();
				rows.forEach((r) => {
					if (!bySlug.has(r[1])) bySlug.set(r[1], []);
					bySlug.get(r[1]).push(r);
				});
				return { rows, lower: rows.map((r) => r[0].toLowerCase()), bySlug };
			})
			.catch(() => ({ rows: [], lower: [], bySlug: new Map() }));
	}
	return titleIndexPromise;
}

/**
 * Search titles by name (the "By title" tab). Returns {title, slug, author,
 * total} — `slug` is the author to open. Empty query -> top titles by checkouts.
 */
// The lowest all-time checkout count present in the title index (the build
// threshold, i.e. only titles at/above this are searchable). Read from the data
// so the UI note stays accurate whatever the build used.
export async function titleIndexMin() {
	const { rows } = await getTitleIndex();
	return rows.length ? rows[rows.length - 1][3] : 0;
}

export async function searchTitles(query, limit = 20) {
	const { rows, lower } = await getTitleIndex();
	const q = (query ?? '').trim().toLowerCase();
	const out = [];
	for (let i = 0; i < rows.length; i++) {
		if (q && !lower[i].includes(q)) continue;
		const [title, slug, author, total] = rows[i];
		out.push({ title, slug, author, total });
		if (out.length >= limit) break;
	}
	return out;
}

// How well `text` matches the query `needle` (both lowercased), used to rank
// authors and works together in the unified search box: exact > prefix >
// word-boundary > substring. Popularity (total) only breaks ties within a tier,
// so a good textual match always outranks a merely-more-popular weak one.
function matchTier(text, needle) {
	const t = (text || "").toLowerCase();
	if (t === needle) return 4;
	if (t.startsWith(needle)) return 3;
	const esc = needle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
	if (new RegExp("\\b" + esc).test(t)) return 2;
	if (t.includes(needle)) return 1;
	return 0;
}

/**
 * Unified search over BOTH authors and works for the single search box. Returns a
 * merged, relevance-ranked list where each item carries a `kind` ("author" or
 * "work") so the caller can label it and route the click to the right view.
 * Works come from the popularity-limited title index (same as searchTitles); an
 * obscure work is still reachable via its author.
 */
// The bare title without its subtitle / "/ statement of responsibility", so a
// catalog title like "James : a novel / Percival Everett." matches "james" as an
// exact hit rather than a mere prefix.
function bareTitle(title) {
	return (title || "").toLowerCase().split(/\s*[:/]/)[0].replace(/[^a-z0-9 ]+/g, " ").trim();
}

export async function searchAll(query, limit = 60) {
	const needle = (query ?? "").trim().toLowerCase();
	if (needle.length < 2) return [];
	const [authorRows, titleRows] = await Promise.all([
		searchAuthors(query, limit),
		searchTitles(query, limit),
	]);
	const byTierThenTotal = (a, b) => b.tier - a.tier || (b.total || 0) - (a.total || 0);
	const authors = authorRows
		.map((a) => ({ kind: "author", slug: a.slug, name: a.name, total: a.total, tier: matchTier(a.name, needle) }))
		.sort(byTierThenTotal);
	const works = titleRows
		.map((t) => ({ kind: "work", slug: t.slug, title: t.title, author: t.author, total: t.total, tier: Math.max(matchTier(t.title, needle), matchTier(bareTitle(t.title), needle)) }))
		.sort(byTierThenTotal);
	// Merge by match tier; within an equal tier, alternate author/work so a popular
	// author (whose raw total dwarfs any single book) never buries an equally-good
	// title match, and vice versa.
	const out = [];
	let ai = 0, wi = 0, turn = 0;
	while ((ai < authors.length || wi < works.length) && out.length < limit) {
		const a = authors[ai], w = works[wi];
		if (!w || (a && a.tier > w.tier)) { out.push(a); ai++; }
		else if (!a || w.tier > a.tier) { out.push(w); wi++; }
		else if (turn++ % 2 === 0) { out.push(a); ai++; }
		else { out.push(w); wi++; }
	}
	// Searching an author by name also lists their most-borrowed books, right
	// under them (marked `under` so the dropdown can indent them). Only for the
	// best-matching author, and only on a real name match ("rooney", "sally r").
	const top = authors.find((a) => a.tier >= 2);
	if (!top || needle.length < 3) return out;
	const { bySlug } = await getTitleIndex();
	const theirs = (bySlug.get(top.slug) || []).slice(0, 4)
		.map(([title, slug, author, total]) => ({ kind: "work", slug, title, author, total, under: top.slug }));
	if (!theirs.length) return out;
	const same = (a, b) => a.kind === "work" && a.slug === b.slug && a.title === b.title;
	const rest = out.filter((r) => !theirs.some((t) => same(r, t)));
	const at = rest.indexOf(top);
	return [...rest.slice(0, at + 1), ...theirs, ...rest.slice(at + 1)].slice(0, limit + theirs.length);
}

/**
 * Load one author's full drilldown in a single fetch: their own sparse series
 * plus every qualifying title's sparse series. Same shape the old
 * authors/<INITIALS>/<slug>.json files (and the SQLite getAuthor) returned, so
 * the chart component consumes it unchanged. Returns null if not found.
 */
export async function getAuthor(slug) {
	const res = await fetch(`${DATA_BASE}/authors/${shardFor(slug)}/${slug}.json`);
	if (!res.ok) return null;
	const a = await res.json();
	return {
		name: a.name,
		total: a.total,
		series: a.series,
		titles: a.titles,
		subjects: a.subjects, // top subject-heading terms for the author (may be absent in older data)
		variants: a.variants // raw catalog spellings merged into this author (absent when not clustered)
	};
}

/**
 * Unpack a sparse [[monthIndex, count], ...] series into a dense, zero-filled
 * array the length of the shared month axis -- what StackedAreaChart's `values`
 * prop expects.
 */
export function densify(sparseSeries, monthCount) {
	const out = new Array(monthCount).fill(0);
	for (const [mi, c] of sparseSeries) out[mi] = c;
	return out;
}
