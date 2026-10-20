// A stable {#each} key for list[i]: key(list[i]), plus a count when the same
// key already came up earlier in the list, so repeats stay unique.
export function eachKey(list, i, key) {
	const k = key(list[i]);
	let n = 0;
	for (let j = 0; j < i; j++) if (key(list[j]) === k) n++;
	return n ? `${k}\u0000${n}` : k;
}
