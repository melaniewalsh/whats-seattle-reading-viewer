// workKey.cli.js
//
// Node-only CLI harness, split out of workKey.js so that the *shared*
// browser/frontend module never has to statically import a Node builtin.
// (workKey.js is imported by StackedViewer.svelte and bundled for the
// browser -- a top-level `import ... from "node:url"` in that file breaks
// the browser build even if the code path that uses it never runs there.)
//
// Lets non-JS callers (the Python accuracy-testing notebook) run the EXACT
// same normalizeWorkKey the frontend ships, instead of reimplementing it and
// risking drift. Reads a JSON array of titles from stdin, writes a JSON
// array of normalized work keys to stdout.
//
//   echo '["Harry Potter (Unabridged)", "Harry Potter: A Novel"]' | node workKey.cli.js
//   -> ["harrypotter","harrypotter"]
//
// NOTE: comparing import.meta.url to a hand-built `file://${argv[1]}` string
// breaks on Windows -- argv[1] is a raw Windows path ("C:\foo\workKey.cli.js")
// while import.meta.url is a properly encoded file:// URL
// ("file:///C:/foo/workKey.cli.js"), so the strings never matched, the CLI
// block silently never ran, and Node exited 0 with empty stdout. Use
// url.pathToFileURL() to build the comparison URL the same way Node does.
import { pathToFileURL } from "node:url";
import { normalizeWorkKey } from "../src/components/workKey.js";

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
	let input = "";
	process.stdin.setEncoding("utf8");
	process.stdin.on("data", (chunk) => (input += chunk));
	process.stdin.on("end", () => {
		const titles = JSON.parse(input || "[]");
		process.stdout.write(JSON.stringify(titles.map(normalizeWorkKey)));
	});
}
