<script>
	// The site's logo in the top-right of a chart's toolbar row, so a
	// screenshot of the chart carries its source (like Our World in Data's).
	import { base } from "$app/paths";
	let { inset = 0 } = $props(); // the chart's right margin, to end at the plot's edge
</script>

<img class="chart-logo" src="{base}/favicon.png" alt="What Is Seattle Reading?" title="What Is Seattle Reading?" width="26" height="26" style="margin-right: {Math.max(0, inset - 2)}px" />

<style>
	.chart-logo { display: block; width: 26px; height: 26px; flex: none; user-select: none; }
	/* On phones the toolbar wraps and the site header (with the logo) is just above. */
	@media (max-width: 560px) { .chart-logo { display: none; } }
</style>
