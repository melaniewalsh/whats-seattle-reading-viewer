// Subject pages: a subject heading's URL slug. Must match subject_slug() in
// data-prep/build_data.py, which names the files.
export function subjectSlug(term) {
	return (term || "")
		.toLowerCase()
		.normalize("NFKD")
		.replace(/[̀-ͯ]/g, "")
		.replace(/[^a-z0-9]+/g, "-")
		.replace(/^-+|-+$/g, "")
		.slice(0, 80);
}
