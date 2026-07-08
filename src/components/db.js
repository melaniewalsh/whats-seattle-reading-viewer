// db.js
// -----------------------------------------------------------------------
// Talks to the single static/data/library.sqlite3 file built by
// data-prep/build_data.py, using sql.js-httpvfs so the browser only ever
// downloads the handful of database *pages* a query actually touches
// (via HTTP Range requests) instead of the whole file. See:
// https://phiresky.github.io/blog/2021/hosting-sqlite-databases-on-github-pages/
//
// This replaces the old "fetch authors.json, then fetch
// authors/<INITIALS>/<slug>.json per click" flow -- there's no search
// index or per-author file to fetch anymore, just SQL queries against one
// file that GitHub Pages serves as a normal static asset (GitHub Pages'
// CDN supports Range requests out of the box).
//
// npm install sql.js-httpvfs
// -----------------------------------------------------------------------
import pkg from 'sql.js-httpvfs';
import { base } from '$app/paths';
const { createDbWorker } = pkg;

// Path to the built database, served at /data on the site (see build_data.py
// OUT_DIR). `base` is '' locally and '/<repo>' on GitHub Pages project sites,
// so this resolves correctly in both.
// In production the full database is served from a PUBLIC Cloudflare R2 bucket
// (built + uploaded monthly by .github/workflows/build-data-to-r2.yml). R2 must
// have public read + a CORS rule that allows this site to make Range requests
// (see the README "Deploy" section). In local dev we use the sample DB you
// build into static/data/ with `python3 data-prep/build_data.py`.
//
const R2_DB_URL = "https://pub-7559692ae8974bd6a6e7cc54db47a348.r2.dev/library.sqlite3";
const DB_URL = import.meta.env.PROD ? R2_DB_URL : `${base}/data/library.sqlite3`;

// sql.js-httpvfs needs its own worker + wasm files reachable by URL. Vite
// resolves these to hashed, fingerprinted asset URLs at build time.
const WORKER_URL = new URL('sql.js-httpvfs/dist/sqlite.worker.js', import.meta.url);
const WASM_URL = new URL('sql.js-httpvfs/dist/sql-wasm.wasm', import.meta.url);

let workerPromise = null;

function getWorker() {
	if (!workerPromise) {
		workerPromise = createDbWorker(
			[
				{
					from: 'inline',
					config: {
						serverMode: 'full',
						url: DB_URL,
						requestChunkSize: 8192
					}
				}
			],
			WORKER_URL.toString(),
			WASM_URL.toString()
		);
	}
	return workerPromise;
}

// Whether the build produced an FTS5 search index (build_data.py falls back
// to a plain LIKE-based index when the local sqlite3 lacks FTS5). Checked
// once and cached so every search after the first doesn't pay for a failed
// query + catch.
let hasFtsPromise = null;
async function hasFts5() {
	if (!hasFtsPromise) {
		hasFtsPromise = (async () => {
			const worker = await getWorker();
			try {
				await worker.db.query(
					"SELECT 1 FROM sqlite_master WHERE type='table' AND name='authors_fts'"
				);
				const rows = await worker.db.query(
					"SELECT name FROM sqlite_master WHERE type='table' AND name='authors_fts'"
				);
				return rows.length > 0;
			} catch (error) {
				console.error("No FTS5 available:", error);
				return false;
			}
		})();
	}
	return hasFtsPromise;
}

let monthsPromise = null;

/** Shared x-axis for every chart. fetched once and cached for the session. */
export async function getMonths() {
	if (!monthsPromise) {
		monthsPromise = (async () => {
			const worker = await getWorker();
			const rows = await worker.db.query("SELECT value FROM meta WHERE key = 'months'");
			return JSON.parse(rows[0].value);
		})();
	}
	return monthsPromise;
}

/**
 * Search authors by name (used by the search-as-you-type box). Empty/blank
 * query returns the top authors by total checkouts, so there's always
 * something sensible to show before the user types anything.
 */
export async function searchAuthors(query, limit = 20) {
	const worker = await getWorker();
	const q = (query ?? '').trim();

	if (!q) {
		return worker.db.query('SELECT slug, name, total FROM authors ORDER BY total DESC LIMIT ?', [
			limit
		]);
	}

	if (await hasFts5()) {
		// Trailing "*" makes it a prefix match on the last (partially-typed)
		// word, which is what you want while someone is still typing.
		const ftsQuery = q
			.split(/\s+/)
			.map((w) => `${w.replace(/["*]/g, '')}*`)
			.join(' ');
		return worker.db.query(
			`SELECT a.slug, a.name, a.total
			 FROM authors_fts f
			 JOIN authors a ON a.id = f.rowid
			 WHERE authors_fts MATCH ?
			 ORDER BY a.total DESC
			 LIMIT ?`,
			[ftsQuery, limit]
		);
	}

	// Fallback: plain substring match against the btree index build_data.py
	// creates on authors(name COLLATE NOCASE) when FTS5 isn't available.
	return worker.db.query(
		'SELECT slug, name, total FROM authors WHERE name LIKE ? ORDER BY total DESC LIMIT ?',
		[`%${q}%`, limit]
	);
}

/**
 * Load one author's full drilldown: their own sparse series plus every
 * qualifying title's sparse series. Mirrors the shape the old
 * authors/<INITIALS>/<slug>.json files used, so callers (and the chart
 * component) don't need to change how they consume it.
 */


export async function getAuthor(slug) {
	const worker = await getWorker();
	const authorRows = await worker.db.query(
		'SELECT id, name, total, series FROM authors WHERE slug = ?',
		[slug]
	);
	if (authorRows.length === 0) return null;
	const author = authorRows[0];

	const titleRows = await worker.db.query(
	'SELECT title, total, fmt, series FROM titles WHERE author_id = ? ORDER BY total DESC',
	[author.id]
	);

	return {
		name: author.name,
		total: author.total,
		series: JSON.parse(author.series),
		titles: titleRows.map((t) => ({
			title: t.title,
			total: t.total,
			fmt: t.fmt,
			series: JSON.parse(t.series)
		}))
	};
}

/**
 * Unpack a sparse [[monthIndex, count], ...] series into a dense,
 * zero-filled array the length of the shared month axis -- what
 * StackedAreaChart's `values` prop expects.
 */
export function densify(sparseSeries, monthCount) {
	const out = new Array(monthCount).fill(0);
	for (const [mi, c] of sparseSeries) out[mi] = c;
	return out;
}
