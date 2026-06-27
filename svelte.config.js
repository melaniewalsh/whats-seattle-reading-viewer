import adapterStatic from "@sveltejs/adapter-static";
import { sveltePreprocess } from "svelte-preprocess";
import autoprefixer from "autoprefixer";

const preprocess = sveltePreprocess({
	postcss: {
		plugins: [autoprefixer]
	}
});

const config = {
	compilerOptions: {
		runes: true
	},
	preprocess,
	kit: {
		adapter: adapterStatic({ strict: false }),
		// On GitHub Pages the site lives at /<repo-name>/, so set a base path.
		// The deploy workflow passes BASE_PATH; locally it's empty (served at /).
		paths: {
			base: process.env.BASE_PATH || ""
		},
		prerender: {
			// The starter's optional social-share <meta> images aren't present;
			// don't fail the build over them.
			handleHttpError: ({ path, message }) => {
				if (path.includes("/assets/social-")) return;
				throw new Error(message);
			}
		}
	}
};

export default config;
