// Centered 3-month moving average (2 points at the ends).
export function avg3(a) {
	return a.map((_, i) => {
		let sum = 0, n = 0;
		for (let k = i - 1; k <= i + 1; k++) if (k >= 0 && k < a.length) { sum += a[k] || 0; n++; }
		return n ? sum / n : 0;
	});
}
