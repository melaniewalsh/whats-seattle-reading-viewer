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

// authors/<shard>/<slug>.json, where <shard> is the first two slug chars --
// must match write_author_files() in build_data.py.
function shardFor(slug) {
	return slug.slice(0, 2) || '__';
}

let monthsPromise = null;

/** Shared x-axis for every chart. Fetched once and cached for the session. */
export async function getMonths() {
	if (!monthsPromise) {
		monthsPromise = fetch(`${DATA_BASE}/meta.json`)
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

/**
 * Book/ebook/audiobook checkouts per month, aligned to getMonths(). Returns
 * both the grand total (for the default line) and a per-format breakdown (for
 * the stacked-area view): { total: [...], print: [...], ebook: [...],
 * audiobook: [...] }.
 */
export async function getAllCheckouts() {
	if (!allCheckoutsPromise) {
		allCheckoutsPromise = (async () => {
			const months = await getMonths();
			// Fast path: a tiny precomputed file (data-prep/build_overview.py),
			// served from the app's own origin -- loads instantly instead of
			// waiting seconds for the live API to aggregate ~51M rows.
			try {
				const pre = await fetch(`${base}/overview.json`).then((r) => (r.ok ? r.json() : null));
				if (pre && Array.isArray(pre.total) && pre.total.length === months.length) return pre;
			} catch { /* fall through to the live API */ }
			// Fallback: live Socrata aggregation (works before the file is built).
			const params = new URLSearchParams({
				'$select': 'checkoutyear,checkoutmonth,materialtype,sum(checkouts) as total',
				'$where': "checkoutyear>=2018 and checkoutyear<=2022 and materialtype in('BOOK','EBOOK','AUDIOBOOK')",
				'$group': 'checkoutyear,checkoutmonth,materialtype',
				'$limit': '5000',
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
		indexPromise = fetch(`${DATA_BASE}/search-index.json`)
			.then((r) => r.json())
			.then((all) => {
				const rows = all.filter((r) => !JUNK_AUTHOR_NAMES.has(r[1]));
				return { rows, lower: rows.map((r) => r[1].toLowerCase()) };
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
export async function searchAuthors(query, limit = 20) {
	const { rows, lower } = await getIndex();
	const q = (query ?? '').trim().toLowerCase();

	const out = [];
	for (let i = 0; i < rows.length; i++) {
		if (q && !lower[i].includes(q)) continue;
		const [slug, name, total] = rows[i];
		out.push({ slug, name, total });
		if (out.length >= limit) break;
	}
	return out;
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
		titles: a.titles
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
