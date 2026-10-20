// Small counts, which could point to a single reader, are coarsened:
// - a line whose busiest month had fewer than QUIET_PEAK checkouts is shown
//   as yearly totals, not month by month;
// - on an author's page, books with fewer than SMALL_TOTAL checkouts in all
//   are listed together as one row instead of one row each.
export const QUIET_PEAK = 5;
export const SMALL_TOTAL = 25;

// True when a line has checkouts but never QUIET_PEAK or more in a month.
export function isQuiet(values) {
	let peak = 0;
	for (const v of values || []) if (v > peak) peak = v;
	return peak > 0 && peak < QUIET_PEAK;
}

// Sum a monthly axis ("YYYY-MM") and its series into one point per year,
// labelled "YYYY-01" so the chart's year ticks still line up.
export function toYearly(months, seriesList) {
	const years = [];
	const at = months.map((m) => {
		const y = m.slice(0, 4);
		if (years[years.length - 1] !== y) years.push(y);
		return years.length - 1;
	});
	return {
		months: years.map((y) => `${y}-01`),
		series: seriesList.map((s) => {
			const values = new Array(years.length).fill(0);
			s.values.forEach((v, i) => { values[at[i]] += v || 0; });
			return { ...s, values };
		})
	};
}
