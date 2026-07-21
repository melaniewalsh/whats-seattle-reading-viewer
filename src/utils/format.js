// Compact number formatting for the ranking tables:
//   40,000 -> "40k"   99,262 -> "99.3k"   128,000 -> "128k"   1,240,000 -> "1.2M"
// Keeps one decimal below 100k / 10M, drops it when whole, and leaves values
// under 1,000 as-is. Pair with a title attribute holding the full number.
export function compactNumber(n) {
	if (n == null || isNaN(n)) return "";
	const abs = Math.abs(n);
	if (abs >= 1e6) {
		const v = n / 1e6;
		return (abs >= 1e7 ? Math.round(v) : +v.toFixed(1)) + "M";
	}
	if (abs >= 1e3) {
		const v = n / 1e3;
		return (abs >= 1e5 ? Math.round(v) : +v.toFixed(1)) + "k";
	}
	return n.toLocaleString();
}
