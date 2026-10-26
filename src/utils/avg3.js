// Centered 3-month moving average (2 points at the ends). A missing month
// (null: a gap in the line) stays missing and isn't averaged in.
export function avg3(a) {
	return a.map((v, i) => {
		if (v == null) return null;
		let sum = 0, n = 0;
		for (let k = i - 1; k <= i + 1; k++) if (k >= 0 && k < a.length && a[k] != null) { sum += a[k]; n++; }
		return n ? sum / n : 0;
	});
}
