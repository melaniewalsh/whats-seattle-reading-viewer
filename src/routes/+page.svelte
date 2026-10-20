<script>
	import { setContext } from "svelte";
	import Meta from "$components/Meta.svelte";
	import Index from "$components/Index.svelte";
	import copy from "$data/copy.json";

	const { title, description, url, keywords } = copy;
	setContext("copy", copy);
</script>

<Meta {title} {description} {url} {keywords} />
<Index />
