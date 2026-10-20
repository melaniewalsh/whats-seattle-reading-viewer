// Loads the Norton-anthology case-study data (Seattle Public Library checkouts,
// 2005–2025, for works by authors in Volume E of The Norton Anthology of
// American Literature) and shapes it the way our chart components expect:
// a shared `months` axis plus per-title and per-author monthly series.
//
// Source CSVs live in the whats-seattle-reading repo. We fetch + aggregate once
// and cache the promise. (~7 MB monthly file — fine for a one-time case-study
// load; can be pre-aggregated to JSON later if we want it snappier.)
import { csvParse } from "d3";

const MONTHLY_URL =
	"https://raw.githubusercontent.com/melaniewalsh/whats-seattle-reading/refs/heads/main/data/title-checkouts-per-month.csv";

let promise = null;

export function getNortonData() {
	if (promise) return promise;
	promise = (async () => {
		const res = await fetch(MONTHLY_URL);
		if (!res.ok) throw new Error(`Norton data ${res.status}`);
		const rows = csvParse(await res.text());

		// Month axis ("YYYY-MM"), sorted.
		const monthSet = new Set();
		for (const r of rows) monthSet.add(r.CheckoutDate.slice(0, 7));
		const months = [...monthSet].sort();
		const mi = new Map(months.map((m, i) => [m, i]));

		// One entry per work (title + creator), with a dense monthly series.
		const titleMap = new Map();
		for (const r of rows) {
			const title = r["Normalized.Title"];
			const author = r["Normalized.Creator"];
			const key = `${title}|||${author}`;
			let t = titleMap.get(key);
			if (!t) {
				t = {
					title,
					author,
					norton: r["Work.In.Norton"] === "True",
					values: new Array(months.length).fill(0),
					total: 0,
				};
				titleMap.set(key, t);
			}
			const c = +r.Checkouts || 0;
			t.values[mi.get(r.CheckoutDate.slice(0, 7))] += c;
			t.total += c;
		}
		const titles = [...titleMap.values()];

		// Aggregate works up to their author.
		const authorMap = new Map();
		titles.forEach((t, idx) => {
			let a = authorMap.get(t.author);
			if (!a) {
				a = {
					name: t.author,
					values: new Array(months.length).fill(0),
					total: 0,
					titleIdxs: [],
					norton: false,
				};
				authorMap.set(t.author, a);
			}
			for (let i = 0; i < months.length; i++) a.values[i] += t.values[i];
			a.total += t.total;
			a.titleIdxs.push(idx);
			if (t.norton) a.norton = true;
		});
		const authors = [...authorMap.values()].sort((x, y) => y.total - x.total);
		titles.sort((x, y) => y.total - x.total);

		return { months, titles, authors };
	})().catch((e) => { promise = null; throw e; });
	return promise;
}
