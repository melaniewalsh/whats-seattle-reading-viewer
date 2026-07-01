<script>
	// StackedViewer.svelte
	// =============
	// Search an author -> see a line of their total checkouts -> tick individual
	// titles to chart them. You can also:
	//   • "Bundle" the ticked titles into ONE line (treat every edition / format
	//     of a work as a single thing), and
	//   • hide the author-total line to show only what you've ticked.
	import { onMount } from "svelte";
	import { base } from "$app/paths";
	import debounce from "lodash.debounce";
	import LineChart from "$components/StackedAreaChart.svelte";
	import Switch from "$components/ui/Switch.svelte";

	// Colors for individual title lines. The author-total line is ink-black,
	// and a bundle is drawn in the accent red.
	const TITLE_COLORS = [
		"#e3120b", "#1f7a4d", "#e58a00", "#6a4c93",
		"#0b7285", "#c2255c", "#5c940d", "#7048e8"
	];
	const INK = "var(--color-fg)";

	let authors = $state([]); // the search index
	let months = $state([]); // the shared month axis (from meta.json)
	let query = $state("");
	let results = $state([]);
	let current = $state(null); // loaded author object

	let groups = $state([]); // selection groups: { id, name, idxs: [] }
	let activeGroupId = $state(null); // which group the title checkboxes edit right now null means "single selection" mode
	let groupIdCounter = 0; // increasing id source for groups
	let singleIdxs = $state([]); // titles ticked while no group was active
	let titleFilter = $state(""); // text filter for the title list
	let showAuthorLine = $state(true);

	onMount(async () => {
		// Load the search index and the shared month axis together.
		const [a, m] = await Promise.all([
			fetch(`${base}/data/authors.json`).then((r) => r.json()),
			fetch(`${base}/data/meta.json`).then((r) => r.json())
		]);
		authors = a;
		months = m.months;
		// Show the most-borrowed author by default, so the page isn't empty.
		if (authors.length) await selectAuthor(authors[0]);
	});

	// Expand a sparse series ([[monthIndex, count], ...]) into a full array of
	// length months.length, filling the gaps with 0.
	function densify(sparse) {
		const arr = new Array(months.length).fill(0);
		for (const [i, v] of sparse) arr[i] = v;
		return arr;
	}

	// Filter the author list as the user types (debounced so it stays snappy).
	const runSearch = debounce((q) => {
		const needle = q.trim().toLowerCase();
		results =
			needle.length < 2
				? []
				: authors.filter((a) => a.name.toLowerCase().includes(needle)).slice(0, 25);
	}, 120);
	$effect(() => runSearch(query));

	async function selectAuthor(a) {
		const res = await fetch(`${base}/data/authors/${a.slug}.json`);
		const data = await res.json();
		// expand the sparse series the ETL produced into full arrays
		data.months = months;
		data.series = densify(data.series);
		data.titles.forEach((t) => {
			t.series = densify(t.series);
			t.format = t.fmt; // the ETL stores the short field name "fmt"
		});
		current = data;
		// reset the controls for the new author
		groups = [];
		activeGroupId = null;
		singleIdxs = [];
		titleFilter = "";
		showAuthorLine = true;
		query = "";
		results = [];
	}

	// Short label shown in a title's format badge.
	function formatLabel(f) {
		return { ebook: "ebook", audiobook: "audio", print: "print", other: "other" }[f] || f;
	}

	// ----- Selection groups -----
	// By default (no group active), ticking a title is a plain single
	// selection — just that one book, drawn as its own line. A title only
	// joins a group once you create a group (or click back onto an earlier
	// one) to make it "active" — then ticks add/remove titles from that
	// group instead. A title can only have one owner — group or single — at
	// a time, so picking it up somewhere new releases it from wherever it
	// was before. Clicking a chip in the groups panel re-activates that
	// group for editing, so you can always go back and adjust an earlier one.

	function addGroup() {
		const g = { id: ++groupIdCounter, name: "", idxs: [] };
		groups = [...groups, g];
		activeGroupId = g.id;
		return g;
	}

	function removeGroup(id) {
		groups = groups.filter((g) => g.id !== id);
		if (activeGroupId === id) {
			activeGroupId = groups.length ? groups[groups.length - 1].id : null;
		}
	}

	// strip a title out of every group and out of the single-selection list,
	// so it can be picked up fresh by whichever owner is claiming it next
	function releaseTitle(idx) {
		groups.forEach((g) => {
			if (g.idxs.includes(idx)) g.idxs = g.idxs.filter((i) => i !== idx);
		});
		if (singleIdxs.includes(idx)) singleIdxs = singleIdxs.filter((i) => i !== idx);
	}

	function toggleTitle(idx) {
		if (activeGroupId) {
			const g = groups.find((g) => g.id === activeGroupId);
			if (!g) return;
			if (g.idxs.includes(idx)) {
				g.idxs = g.idxs.filter((i) => i !== idx);
			} else {
				releaseTitle(idx);
				g.idxs = [...g.idxs, idx];
			}
		} else {
			// single-selection mode: no group is active
			if (singleIdxs.includes(idx)) {
				singleIdxs = singleIdxs.filter((i) => i !== idx);
			} else {
				releaseTitle(idx);
				singleIdxs = [...singleIdxs, idx];
			}
		}
	}

	// which group a title currently belongs to
	function groupForTitle(idx) {
		return groups.find((g) => g.idxs.includes(idx)) ?? null;
	}

	// is this title one of single selections
	function isSingleSelected(idx) {
		return singleIdxs.includes(idx);
	}

	// The 15 most-borrowed authors overall (authors.json is sorted by total),
	// shown as quick-pick buttons under the search box.
	const topAuthors = $derived(authors.slice(0, 15));

	// The title list, filtered by the little search box, sorted alphabetically so
	// editions/variations of the same work sit next to each other. We keep each
	// title's ORIGINAL index (used for selection and the per-title series).
	const filteredTitles = $derived(
		current
			? current.titles
					.map((t, idx) => ({ ...t, idx }))
					.filter(
						(t) => !titleFilter.trim() || t.title.toLowerCase().includes(titleFilter.trim().toLowerCase())
					)
					.sort((a, b) => a.title.localeCompare(b.title, undefined, { sensitivity: "base", numeric: true }))
			: []
	);

	// Currently-active group object (or null if none selected/created yet).
	const activeGroup = $derived(groups.find((g) => g.id === activeGroupId) ?? null);

	// Name a group is whatever the user typed, otherwise auto-name it after its
	// most-borrowed member (lowest original index = most checkouts), plus a
	// count of the rest.
	function groupLabel(g) {
		if (g.name.trim()) return g.name.trim();
		if (!current || !g.idxs.length) return "New group";
		const firstIdx = Math.min(...g.idxs);
		const firstTitle = current.titles[firstIdx].title;
		const extra = g.idxs.length - 1;
		return extra > 0 ? `${firstTitle}  +${extra} more` : firstTitle;
	}

	// When the author line is toggled off, show the group name(s) as the chart's title.
	const plotTitle = $derived(
		!showAuthorLine && groups.length ? groups.map(groupLabel).join(" · ") : ""
	);

    // StackedViewer.svelte
    const chartSeries = $derived.by(() => {
        if (!current) return [];

        const groupIndexOf = new Map();
        groups.forEach((g, gi) => {
            g.idxs.forEach((idx) => groupIndexOf.set(idx, gi));
        });

        const singleColorOf = new Map();
        singleIdxs.forEach((idx, i) => {
            singleColorOf.set(idx, TITLE_COLORS[i % TITLE_COLORS.length]);
        });

        let mapped = current.titles.map((t, idx) => {
            const gi = groupIndexOf.has(idx) ? groupIndexOf.get(idx) : -1;
            const isGrouped = gi !== -1;
            const isSingle = singleColorOf.has(idx);
            let color = "var(--color-gray-200)";
            if (isGrouped) color = TITLE_COLORS[gi % TITLE_COLORS.length];
            else if (isSingle) color = singleColorOf.get(idx);
            return {
                label: t.title,
                color,
                values: t.series,
                isSelected: isGrouped || isSingle, // Expose this flag for sorting and tooltip logic
                groupIndex: gi // which group this book belongs to (-1 if none/single)
            };
        });

        // Grouped/single-selected books sink to the bottom of the stack grouped ones cluster by group
        mapped.sort((a, b) => {
            if (a.isSelected !== b.isSelected) return a.isSelected ? -1 : 1;
            if (a.isSelected && a.groupIndex !== b.groupIndex) return a.groupIndex - b.groupIndex;
            return 0;
        });

        return mapped;
    });
</script>

<div class="viewer">
	<!-- ===== Search ===== -->
	<div class="search">
		<input
			type="search"
			placeholder="Search an author — try Octavia Butler, or Mo Willems"
			bind:value={query}
			autocomplete="off"
		/>
		{#if results.length}
			<ul class="results">
				{#each results as a}
					<li>
						<button onclick={() => selectAuthor(a)}>
							<span>{a.name}</span>
							<span class="count">{a.total.toLocaleString()}</span>
						</button>
					</li>
				{/each}
			</ul>
		{/if}
	</div>

	<!-- quick-pick: the 10 most-borrowed authors -->
	{#if topAuthors.length}
		<div class="top-authors">
			<span class="quick-label">Most borrowed:</span>
			{#each topAuthors as a}
				<button
					class="chip"
					class:current={current && current.name === a.name}
					onclick={() => selectAuthor(a)}
				>
					{a.name}
				</button>
			{/each}
		</div>
	{/if}

	<!-- ===== Selected author ===== -->
	{#if current}
		<div class="author">
			<h2>{current.name}</h2>
			<p class="meta">
				{current.total.toLocaleString()} checkouts · {current.titles.length} titles
			</p>

			{#if plotTitle}
				<p class="plot-title">{plotTitle}</p>
			{/if}
			<LineChart months={current.months} series={chartSeries} />

			<!-- legend -->
			<ul class="legend">
                {#each groups as g, gi (g.id)}
                    {#if g.idxs.length}
                        <li><span class="sw" style="background:{TITLE_COLORS[gi % TITLE_COLORS.length]}"></span>{groupLabel(g)}</li>
                    {/if}
                {/each}
                {#each singleIdxs as idx, i (idx)}
                    <li><span class="sw" style="background:{TITLE_COLORS[i % TITLE_COLORS.length]}"></span>{current.titles[idx].title}</li>
                {/each}
            </ul>

			<!-- options -->
			<div class="options">
				<Switch bind:checked={showAuthorLine} labelText="Author total trend" />
			</div>
			<div class="groups-panel">
				<div class="groups-header">
					<span class="groups-label">Selection groups</span>
					<button class="new-group" onclick={addGroup}>+ New group</button>
				</div>

				<ul class="group-chips">
					<li class="group-chip-row">
						<button
							class="group-chip single-chip"
							class:active={activeGroupId === null}
							onclick={() => (activeGroupId = null)}
						>
							<span class="chip-name">Single selection</span>
							{#if singleIdxs.length}
								<span class="chip-count">{singleIdxs.length}</span>
							{/if}
						</button>
					</li>
					{#each groups as g, gi (g.id)}
						<li class="group-chip-row">
							<button
								class="group-chip"
								class:active={g.id === activeGroupId}
								style="--chip-color: {TITLE_COLORS[gi % TITLE_COLORS.length]}"
								onclick={() => (activeGroupId = g.id)}
							>
								<span class="chip-sw"></span>
								<span class="chip-name">{groupLabel(g)}</span>
								<span class="chip-count">{g.idxs.length}</span>
							</button>
							<button class="chip-remove" title="Delete group" onclick={() => removeGroup(g.id)}>×</button>
						</li>
					{/each}
				</ul>

				{#if activeGroup}
					<div class="bundle-name">
						<label for="group-name-input">Name this group</label>
						<input
							id="group-name-input"
							type="text"
							bind:value={activeGroup.name}
							placeholder={groupLabel(activeGroup)}
						/>
					</div>
					<p class="editing-hint">
						Editing <strong>{groupLabel(activeGroup)}</strong> — tick titles below to add or remove them.
					</p>
				{:else}
					<p class="editing-hint">Single selection — each ticked title below gets its own line. Create a group above to combine titles into one.</p>
				{/if}
			</div>

			<div class="titles">
				<input
					class="title-filter"
					type="search"
					placeholder="Filter titles…"
					bind:value={titleFilter}
					autocomplete="off"
				/>
				<ul class="title-list">
					{#each filteredTitles as t}
						{@const owner = groupForTitle(t.idx)}
						{@const ownerIdx = owner ? groups.indexOf(owner) : -1}
						{@const single = isSingleSelected(t.idx)}
						{@const singleIdx = single ? singleIdxs.indexOf(t.idx) : -1}
						{@const ownerColor = owner
							? TITLE_COLORS[ownerIdx % TITLE_COLORS.length]
							: single
								? TITLE_COLORS[singleIdx % TITLE_COLORS.length]
								: ""}
						{@const isCurrentOwner = activeGroupId ? owner?.id === activeGroupId : single}
						<li>
							<label
								class:selected={owner !== null || single}
								style={ownerColor ? `--chip-color:${ownerColor}` : ""}
							>
								<input
									type="checkbox"
									checked={isCurrentOwner}
									onchange={() => toggleTitle(t.idx)}
								/>
								{#if (owner || single) && !isCurrentOwner}
									<span class="other-group-dot" title="In “{owner ? groupLabel(owner) : t.title}”"></span>
								{/if}
								<span class="t-name">{t.title}</span>
								<span class="badge badge-{t.format}">{formatLabel(t.format)}</span>
								<span class="t-count">{t.total.toLocaleString()}</span>
							</label>
						</li>
					{/each}
				</ul>
			</div>
		</div>
	{:else}
		<p class="hint">Start typing an author's name above.</p>
	{/if}
</div>


<style>
	.viewer {
		max-width: 720px;
		margin: 0 auto;
	}

	/* The starter's reset hides native checkboxes this turns them
	   back on so the ticked/unticked state is visible. */
	.viewer input[type="checkbox"] {
		appearance: auto;
		-webkit-appearance: auto;
		width: 17px;
		height: 17px;
		accent-color: var(--color-fg);
		background: none;
		flex: none;
		cursor: pointer;
	}

	.search {
		position: relative;
	}
	.search input {
		width: 100%;
		padding: 14px 16px;
		font-family: var(--font-sans);
		font-size: 1.05rem;
		background: var(--color-input-bg);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
	}
	.search input:focus {
		outline: 2px solid var(--color-focus);
		outline-offset: 1px;
	}
	.results {
		list-style: none;
		margin: 6px 0 0;
		padding: 6px;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-white);
		max-height: 340px;
		overflow-y: auto;
		position: absolute;
		width: 100%;
		z-index: var(--z-top);
		box-shadow: 0 6px 20px rgba(0, 0, 0, 0.08);
	}
	.results button {
		width: 100%;
		display: flex;
		justify-content: space-between;
		gap: 12px;
		padding: 9px 12px;
		background: none;
		border: none;
		border-radius: var(--radius-sm);
		font-family: var(--font-sans);
		font-size: 0.95rem;
		text-align: left;
		cursor: pointer;
		color: var(--color-fg);
	}
	.results button:hover {
		background: var(--color-gray-100);
	}
	.results .count {
		color: var(--color-fg-light);
		font-variant-numeric: tabular-nums;
	}

	.author {
		margin-top: 36px;
	}
	.author h2 {
		font-family: var(--font-serif);
		font-size: 2rem;
		line-height: 1.1;
		margin: 0;
	}
	.author .meta {
		font-family: var(--font-sans);
		color: var(--color-fg-light);
		margin: 4px 0 20px;
	}
	.plot-title {
		font-family: var(--font-serif);
		font-size: 1.3rem;
		line-height: 1.2;
		text-align: center;
		margin: 0 0 8px;
	}

	.legend {
		list-style: none;
		display: flex;
		flex-wrap: wrap;
		gap: 6px 18px;
		margin: 12px 0 0;
		padding: 0;
		font-family: var(--font-sans);
		font-size: 0.82rem;
	}
	.legend li {
		display: flex;
		align-items: center;
		gap: 6px;
		max-width: 320px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.legend .sw {
		width: 12px;
		height: 12px;
		border-radius: 2px;
		flex: none;
	}

	/* options row */
	.options {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 10px;
		margin: 18px 0 14px;
		font-family: var(--font-sans);
		font-size: 0.9rem;
	}
	.bundle-name {
		display: flex;
		align-items: center;
		gap: 10px;
		margin: 12px 0 0;
		font-family: var(--font-sans);
		font-size: 0.85rem;
	}
	.bundle-name label {
		font-weight: 600;
		white-space: nowrap;
	}
	.bundle-name input {
		flex: 1;
		min-width: 0;
		padding: 8px 12px;
		font-family: var(--font-sans);
		font-size: 0.9rem;
		background: var(--color-input-bg);
		border: 1.5px solid var(--color-border);
		border-radius: var(--radius-sm);
	}
	.bundle-name input:focus {
		outline: none;
		border-color: #e3120b;
	}

	.groups-panel {
		margin: 4px 0 18px;
		padding: 14px 16px;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-gray-100);
	}
	.groups-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 10px;
	}
	.groups-label {
		font-family: var(--font-sans);
		font-size: 0.78rem;
		font-weight: 700;
		color: var(--color-fg-light);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
	.new-group {
		font-family: var(--font-sans);
		font-size: 0.85rem;
		font-weight: 600;
		padding: 6px 14px;
		border-radius: 999px;
		border: 1.5px solid var(--color-fg);
		background: var(--color-fg);
		color: var(--color-white);
		cursor: pointer;
	}
	.new-group:hover {
		opacity: 0.85;
	}
	.group-chips {
		list-style: none;
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		margin: 12px 0 0;
		padding: 0;
	}
	.group-chip-row {
		display: flex;
		align-items: stretch;
	}
	.group-chip {
		display: flex;
		align-items: center;
		gap: 7px;
		font-family: var(--font-sans);
		font-size: 0.85rem;
		padding: 6px 10px 6px 8px;
		border-radius: 999px 0 0 999px;
		border: 1.5px solid var(--color-border);
		border-right: none;
		background: var(--color-white);
		color: var(--color-fg);
		cursor: pointer;
		max-width: 220px;
		transition: background 0.12s, border-color 0.12s, color 0.12s;
	}
	.group-chip:hover {
		border-color: var(--chip-color, var(--color-fg-light));
	}
	.group-chip.active {
		border-color: var(--chip-color);
		background: var(--chip-color);
		color: var(--color-white);
	}
	.group-chip.active .chip-sw {
		background: var(--color-white);
	}
	/* the "Single selection" chip stands alone (no remove button beside it)
	   and has no group color of its own, so it gets its own shape + active
	   treatment */
	.group-chip.single-chip {
		border-radius: 999px;
		border-right: 1.5px solid var(--color-border);
		border-style: dashed;
		padding: 6px 14px;
	}
	.group-chip.single-chip:hover {
		border-color: var(--color-fg-light);
	}
	.group-chip.single-chip.active {
		background: var(--color-fg);
		border-color: var(--color-fg);
		border-style: solid;
		color: var(--color-white);
	}
	.chip-sw {
		width: 9px;
		height: 9px;
		border-radius: 2px;
		flex: none;
		background: var(--chip-color);
	}
	.chip-name {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.chip-count {
		flex: none;
		opacity: 0.75;
		font-variant-numeric: tabular-nums;
	}
	.chip-remove {
		font-family: var(--font-sans);
		font-size: 0.95rem;
		line-height: 1;
		padding: 0 10px;
		border: 1.5px solid var(--color-border);
		border-radius: 0 999px 999px 0;
		background: var(--color-white);
		color: var(--color-fg-light);
		cursor: pointer;
	}
	.chip-remove:hover {
		color: #e3120b;
		border-color: #e3120b;
	}
	.editing-hint {
		font-family: var(--font-sans);
		font-size: 0.82rem;
		color: var(--color-fg-light);
		margin: 12px 0 0;
	}
	.editing-hint strong {
		color: var(--color-fg);
	}
	.other-group-dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		flex: none;
		background: var(--chip-color, var(--color-fg-light));
	}

	/* top-author quick-pick chips (under the search box) */
	.top-authors {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 8px;
		margin: 14px 0 4px;
		font-family: var(--font-sans);
	}
	.quick-label {
		font-size: 0.82rem;
		font-weight: 600;
		color: var(--color-fg-light);
	}
	.chip {
		font-family: var(--font-sans);
		font-size: 0.82rem;
		padding: 4px 12px;
		border-radius: 999px;
		border: 1px solid var(--color-border);
		background: var(--color-white);
		color: var(--color-fg);
		cursor: pointer;
	}
	.chip:hover {
		background: var(--color-gray-100);
		border-color: var(--color-fg-light);
	}
	.chip.current {
		background: var(--color-fg);
		border-color: var(--color-fg);
		color: var(--color-white);
	}

	/* title list */
	.title-filter {
		width: 100%;
		padding: 9px 12px;
		font-family: var(--font-sans);
		font-size: 0.9rem;
		background: var(--color-input-bg);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		margin-bottom: 8px;
	}
	.title-list {
		list-style: none;
		margin: 0;
		padding: 0;
		max-height: 280px;
		overflow-y: auto;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
	}
	.title-list li + li label {
		border-top: 1px solid var(--color-gray-100);
	}
	.title-list label {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 9px 12px;
		cursor: pointer;
		font-family: var(--font-sans);
		font-size: 0.9rem;
	}
	.title-list label:hover {
		background: var(--color-gray-100);
	}
	.title-list label.selected {
		background: var(--color-gray-100);
		font-weight: 600;
		box-shadow: inset 3px 0 0 0 var(--chip-color, var(--color-fg));
	}
	.title-list .t-name {
		flex: 1;
		min-width: 0;
	}
	.title-list .t-count {
		color: var(--color-fg-light);
		font-variant-numeric: tabular-nums;
	}

	.badge {
		flex: none;
		font-size: 0.66rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		padding: 2px 8px;
		border-radius: 999px;
		white-space: nowrap;
	}
	.badge-ebook {
		background: #e7f0ff;
		color: #1c4ed8;
	}
	.badge-audiobook { 
		background: #f3eafe;
		color: #7048e8;
	}
	.badge-print {
		background: #eaf6ee;
		color: #1f7a4d;
	}
	.badge-other {
		background: var(--color-gray-100);
		color: var(--color-fg-light);
	}
	.hint {
		font-family: var(--font-sans);
		color: var(--color-fg-light);
		text-align: center;
		margin-top: 28px;
	}
</style>
