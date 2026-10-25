// One prerendered HTML file per page (/genres, /trends, ...); they all render
// the same app, which reads the path to pick the view (src/utils/routes.js).
import { error } from "@sveltejs/kit";
import { PAGE_SLUGS } from "$utils/routes.js";

export function entries() {
	return [{ page: "" }, ...PAGE_SLUGS.map((page) => ({ page }))];
}

export function load({ params }) {
	if (params.page && !PAGE_SLUGS.includes(params.page)) error(404, "Not found");
}
