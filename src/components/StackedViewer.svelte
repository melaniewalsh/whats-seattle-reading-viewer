<script>
	// StackedViewer.svelte
	import { onMount } from "svelte";
	import debounce from "lodash.debounce";
	import LineChart from "$components/StackedAreaChart.svelte";
	import Switch from "$components/ui/Switch.svelte";
	import { getMonths, searchAuthors, getAuthor } from "$components/db.js";

	// Colors for title lines.
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
	let chartMode = $state("line"); // 'line' = author's total as one line (default); 'area' = stacked by title
	let titleSort = $state("borrowed"); // 'borrowed' = most checkouts first; 'alpha' = A–Z
	let isolatedKeys = $state([]); // when non-empty, the chart shows ONLY these series (keys 'g<id>' | 's<idx>'); multiple = compare
	let showAuthorTotal = $state(true); // show the author's aggregate total line in the line view
	let dragIdx = $state(null); // title index currently being dragged onto a group pill
	let dragOverId = $state(null); // group pill currently under the dragged title

	onMount(async () => {
		// The site queries a single SQLite database (static/data/library.sqlite3)
		// directly over HTTP range requests via sql.js-httpvfs -- see db.js.
		// months is the shared x-axis; the top authors seed the "Most borrowed"
		// chips (and an empty search returns the top authors by total).
		months = await getMonths();
		authors = await searchAuthors("", 25);
		// Show the most borrowed author by default, so the page isn't empty.
		if (authors.length) await selectAuthor(authors[0]);
	});

	// Expand a sparse series ([[monthIndex, count], ...]) into a full array of
	// length months.length, filling the gaps with 0.
	function densify(sparse) {
		const arr = new Array(months.length).fill(0);
		for (const [i, v] of sparse) arr[i] = v;
		return arr;
	}

	// The first letter of each word typed so far, e.g. "octavia b" -> ["O", "B"].
	// build_data.py buckets each author's file under authors/<INITIALS>/ where
	// intitals is the first letter of their first name + first letter of their
	// last name (e.g. "OB" for Octavia Butler), so these are the letters we use
	// to figure out which "folders" a given search could live in.
	function typedLetters(q) {
		return q
				.trim()
				.split(/\s+/)
				.filter(Boolean)
				.map((w) => w[0].toUpperCase());
	}

	// Filter the author list as the user types -- a full-text (or LIKE) query
	// against the authors table in the SQLite database.
	const runSearch = debounce(async (q) => {
		const needle = q.trim();
		if (needle.length < 2) {
			results = [];
			return;
		}
		results = await searchAuthors(needle, 25);
	}, 120);
	$effect(() => runSearch(query));

	async function selectAuthor(a) {
		// One author's drilldown (their series + every qualifying title) comes
		// from a couple of indexed queries into the SQLite database.
		const data = await getAuthor(a.slug);
		if (!data) return;
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
		chartMode = "line";
		isolatedKeys = [];
		showAuthorTotal = true;
		query = "";
		results = [];
	}

	// Short label shown in a title's format badge.
	function formatLabel(f) {
		return {ebook: "ebook", audiobook: "audio", print: "print", other: "other"}[f] || f;
	}

	// Make a new group. If titles are currently single-selected, seed the group
	// with them (so "select a few, then hit New group" bundles them in one go)
	// and clear the single selection.
	function addGroup() {
		const g = {id: ++groupIdCounter, name: "", idxs: [...singleIdxs]};
		singleIdxs = [];
		groups = [...groups, g];
		activeGroupId = g.id;
		return g;
	}

	function removeGroup(id) {
		groups = groups.filter((g) => g.id !== id);
		if (activeGroupId === id) {
			activeGroupId = groups.length ? groups[groups.length - 1].id : null;
		}
		isolatedKeys = isolatedKeys.filter((k) => k !== `g${id}`);
	}

	// Finish editing the active group (clearer "I'm done adding titles" action).
	function finishGroup() {
		activeGroupId = null;
	}

	// "Only" is a toggle you can apply to more than one line at once: the chart
	// shows just the isolated set, so ticking two titles' "Only" compares them
	// head to head. Clicking an already-isolated line drops it back out.
	function toggleIsolate(key) {
		isolatedKeys = isolatedKeys.includes(key)
				? isolatedKeys.filter((k) => k !== key)
				: [...isolatedKeys, key];
	}
	const isIsolated = (key) => isolatedKeys.includes(key);
	function clearIsolate() {
		isolatedKeys = [];
	}

	// Human label for a series key (used for the chart title while isolating).
	function keyLabel(key) {
		if (!current) return "";
		if (key.startsWith("g")) {
			const g = groups.find((g) => g.id === Number(key.slice(1)));
			return g ? groupLabel(g) : "";
		}
		if (key.startsWith("s")) return current.titles[Number(key.slice(1))]?.title ?? "";
		return "";
	}

	// Sum a set of title indices into one densified series (for a group's line).
	function sumSeries(idxs) {
		const out = new Array(months.length).fill(0);
		for (const idx of idxs) {
			const s = current.titles[idx].series;
			for (let i = 0; i < out.length; i++) out[i] += s[i];
		}
		return out;
	}

	const groupColor = (gi) => TITLE_COLORS[gi % TITLE_COLORS.length];
	const singleColor = (i) => TITLE_COLORS[i % TITLE_COLORS.length];

	// Drag-and-drop: drop a title onto a group pill to add it to that group.
	function dropOnGroup(id) {
		if (dragIdx === null) return;
		const g = groups.find((g) => g.id === id);
		if (g && !g.idxs.includes(dragIdx)) {
			releaseTitle(dragIdx);
			g.idxs = [...g.idxs, dragIdx];
		}
		dragIdx = null;
	}

	// strip a title out of every group and out of the single-selection list, so it can be picked up by whichever owner is claiming it next.
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

	// The title list, filtered by the little search box. Sorted either by most
	// borrowed (default -- matches the chart's biggest layers) or alphabetically
	// (so editions/variations of the same work sit next to each other). We keep
	// each title's original index for selection and the per-title series.
	const filteredTitles = $derived(
			current
					? current.titles
							.map((t, idx) => ({...t, idx}))
							.filter(
									(t) => !titleFilter.trim() || t.title.toLowerCase().includes(titleFilter.trim().toLowerCase())
							)
							.sort((a, b) =>
									titleSort === "alpha"
											? a.title.localeCompare(b.title, undefined, {sensitivity: "base", numeric: true})
											: b.total - a.total
							)
					: []
	);

	// Prolific authors have hundreds-to-thousands of titles (J.K. Rowling ~190,
	// James Patterson ~1500). Rendering a DOM row for every one janks or hangs
	// the tab, so only render the first slice and let the filter box find the
	// rest. Selected titles are always shown so a selection never "disappears".
	const TITLE_RENDER_CAP = 120;
	const visibleTitles = $derived.by(() => {
		if (filteredTitles.length <= TITLE_RENDER_CAP) return filteredTitles;
		const head = filteredTitles.slice(0, TITLE_RENDER_CAP);
		const seen = new Set(head.map((t) => t.idx));
		const selectedTail = filteredTitles
				.slice(TITLE_RENDER_CAP)
				.filter((t) => !seen.has(t.idx) && (isSingleSelected(t.idx) || groupForTitle(t.idx)));
		return [...head, ...selectedTail];
	});
	const hiddenTitleCount = $derived(filteredTitles.length - visibleTitles.length);

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

	// Chart title. When a series is isolated ("Only"), name it. Otherwise, in the
	// stacked-area view, show the group name(s).
	const plotTitle = $derived.by(() => {
		if (!current) return "";
		if (isolatedKeys.length) return isolatedKeys.map(keyLabel).filter(Boolean).join("  vs  ");
		if (chartMode === "area" && groups.length) return groups.map(groupLabel).join(" · ");
		return "";
	});

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
				groupIndex: gi, // which group this book belongs to (-1 if none/single)
				titleIdx: idx // original title index, for isolate filtering
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

	// The author's own total checkouts as one bold line -- the default view.
	const authorLine = $derived(
			current
					? {key: "author", label: current.name, color: INK, values: current.series, groupIndex: -2, isAggregate: true}
					: null
	);

	// Line-mode series (before isolation): the author's total, plus ONE
	// aggregated line per group (summed over its titles) and one line per
	// individually-ticked title.
	const lineParts = $derived.by(() => {
		if (!current) return [];
		const parts = showAuthorTotal ? [authorLine] : [];
		groups.forEach((g, gi) => {
			if (g.idxs.length) {
				parts.push({
					key: `g${g.id}`,
					label: groupLabel(g),
					color: groupColor(gi),
					values: sumSeries(g.idxs),
					groupIndex: gi,
					isGroup: true
				});
			}
		});
		singleIdxs.forEach((idx, i) => {
			parts.push({
				key: `s${idx}`,
				label: current.titles[idx].title,
				color: singleColor(i),
				values: current.titles[idx].series,
				isSingle: true
			});
		});
		return parts;
	});

	// The union of title indices the isolated keys refer to (null = show all).
	function isolatedIdxSet() {
		if (!isolatedKeys.length) return null;
		const set = new Set();
		for (const key of isolatedKeys) {
			if (key.startsWith("g")) {
				const g = groups.find((g) => g.id === Number(key.slice(1)));
				if (g) g.idxs.forEach((i) => set.add(i));
			} else if (key.startsWith("s")) {
				set.add(Number(key.slice(1)));
			}
		}
		return set;
	}

	// A prolific author can have 1000+ qualifying titles; drawing a stacked-area
	// layer for each one janks/hangs the tab. Keep the biggest AREA_LAYER_CAP
	// layers (plus anything the user selected) and roll the rest into one "Other
	// titles" band, so the stack total is preserved but stays fast to render.
	const AREA_LAYER_CAP = 30;
	function capAreaLayers(all) {
		if (all.length <= AREA_LAYER_CAP) return all;
		const kept = [];
		const rest = [];
		for (const s of all) {
			if (s.isSelected || kept.length < AREA_LAYER_CAP) kept.push(s);
			else rest.push(s);
		}
		if (!rest.length) return kept;
		const monthCount = months.length;
		const otherValues = new Array(monthCount).fill(0);
		for (const s of rest) for (let i = 0; i < monthCount; i++) otherValues[i] += s.values[i];
		kept.push({
			label: `Other titles (${rest.length})`,
			color: "var(--color-gray-200)",
			values: otherValues,
			isSelected: false,
			groupIndex: -1,
			titleIdx: -1
		});
		return kept;
	}

	// What the chart actually draws. "line": author total + per-group and
	// per-title lines. "area": the stacked-by-title chart (capped). Either way,
	// when a series is isolated we show only it.
	const displaySeries = $derived.by(() => {
		if (!current) return [];
		if (chartMode === "line") {
			if (isolatedKeys.length) return lineParts.filter((s) => isolatedKeys.includes(s.key));
			return lineParts;
		}
		// area mode
		const only = isolatedIdxSet();
		const areaAll = only ? chartSeries.filter((s) => only.has(s.titleIdx)) : chartSeries;
		return capAreaLayers(areaAll);
	});
</script>

<div class="viewer">
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

			<div class="mode-toggle" role="group" aria-label="Chart type">
				<button
						type="button"
						class:active={chartMode === "line"}
						onclick={() => (chartMode = "line")}
				>Total (line)</button>
				<button
						type="button"
						class:active={chartMode === "area"}
						onclick={() => (chartMode = "area")}
				>By title (stacked)</button>
			</div>

			{#if plotTitle}
				<p class="plot-title">{plotTitle}</p>
			{/if}
			<LineChart months={current.months} series={displaySeries} mode={chartMode}/>

			{#if groups.some((g) => g.idxs.length) || singleIdxs.length}
				<ul class="legend">
					{#if chartMode === "line"}
						<li class="legend-item" class:dim={!showAuthorTotal || isolatedKeys.length}>
							<span class="sw" style="background:{INK}"></span>
							<span class="lg-name">{current.name} — total</span>
							<button
									class="only-btn"
									title={showAuthorTotal ? "Hide the author's total line" : "Show the author's total line"}
									onclick={() => (showAuthorTotal = !showAuthorTotal)}
							>{showAuthorTotal ? "Hide" : "Show"}</button>
						</li>
					{/if}
					{#each groups as g, gi (g.id)}
						{#if g.idxs.length}
							<li class="legend-item" class:dim={isolatedKeys.length && !isIsolated(`g${g.id}`)}>
								<span class="sw" style="background:{groupColor(gi)}"></span>
								<span class="lg-name">{groupLabel(g)}</span>
								<button
										class="only-btn"
										class:on={isIsolated(`g${g.id}`)}
										title="Show only this group (click more than one to compare)"
										onclick={() => toggleIsolate(`g${g.id}`)}
								>Only</button>
							</li>
						{/if}
					{/each}
					{#each singleIdxs as idx, i (idx)}
						<li class="legend-item" class:dim={isolatedKeys.length && !isIsolated(`s${idx}`)}>
							<span class="sw" style="background:{singleColor(i)}"></span>
							<span class="lg-name">{current.titles[idx].title}</span>
							<button
									class="only-btn"
									class:on={isIsolated(`s${idx}`)}
									title="Show only this title (click more than one to compare)"
									onclick={() => toggleIsolate(`s${idx}`)}
							>Only</button>
						</li>
					{/each}
					{#if isolatedKeys.length}
						<li class="legend-item">
							<button class="show-all-btn" onclick={clearIsolate}>Show all</button>
						</li>
					{/if}
				</ul>
				{#if isolatedKeys.length === 1}
					<p class="compare-hint">Click “Only” on another line to compare them side by side.</p>
				{/if}
			{/if}
			<div class="groups-panel">
				<div class="groups-header">
					<span class="groups-label">Selection groups</span>
					<button class="new-group" onclick={addGroup}>Make a new group of related titles</button>
				</div>

				{#if groups.length}
					<ul class="group-chips">
						{#each groups as g, gi (g.id)}
							<li class="group-chip-row">
								<button
										class="group-chip"
										class:active={g.id === activeGroupId}
										class:drag-over={dragOverId === g.id}
										style="--chip-color: {TITLE_COLORS[gi % TITLE_COLORS.length]}"
										onclick={() => (activeGroupId = activeGroupId === g.id ? null : g.id)}
										ondragover={(e) => { e.preventDefault(); dragOverId = g.id; }}
										ondragleave={() => (dragOverId === g.id && (dragOverId = null))}
										ondrop={(e) => { e.preventDefault(); dropOnGroup(g.id); dragOverId = null; }}
								>
									<span class="chip-sw"></span>
									<span class="chip-name">{groupLabel(g)}</span>
									<span class="chip-count">{g.idxs.length}</span>
								</button>
								<button class="chip-remove" title="Delete group" onclick={() => removeGroup(g.id)}>×
								</button>
							</li>
						{/each}
					</ul>
				{/if}

				{#if activeGroup}
					<div class="editing-banner">
						<span class="editing-text">
							Adding titles to <strong>{groupLabel(activeGroup)}</strong> — tick titles below,
							or drag them onto the group.
						</span>
						<button class="done-btn" onclick={finishGroup}>Done</button>
					</div>
					<div class="bundle-name">
						<label for="group-name-input">Name this group</label>
						<input
								id="group-name-input"
								type="text"
								bind:value={activeGroup.name}
								placeholder={groupLabel(activeGroup)}
						/>
					</div>
				{:else if groups.length}
					<p class="editing-hint">Click a group to edit it, or drag a title onto a group to add it.</p>
				{/if}
			</div>

			<div class="titles">
				<div class="titles-header">
					<input
							class="title-filter"
							type="search"
							placeholder="Filter titles…"
							bind:value={titleFilter}
							autocomplete="off"
					/>
					<div class="sort-toggle" role="group" aria-label="Sort titles">
						<span class="sort-label">Sort:</span>
						<button
								type="button"
								class:active={titleSort === "borrowed"}
								onclick={() => (titleSort = "borrowed")}
						>Most borrowed</button>
						<button
								type="button"
								class:active={titleSort === "alpha"}
								onclick={() => (titleSort = "alpha")}
						>A–Z</button>
					</div>
				</div>
				<ul class="title-list">
					{#each visibleTitles as t (t.idx)}
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
						<li
								class="title-row"
								class:dragging={dragIdx === t.idx}
								draggable={groups.length > 0}
								ondragstart={() => (dragIdx = t.idx)}
								ondragend={() => { dragIdx = null; dragOverId = null; }}
						>
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
									<span class="other-group-dot"
										  title="In “{owner ? groupLabel(owner) : t.title}”"></span>
								{/if}
								<span class="t-name">{t.title}</span>
								<span class="badge badge-{t.format}">{formatLabel(t.format)}</span>
								<span class="t-count">{t.total.toLocaleString()}</span>
							</label>
						</li>
					{/each}
				</ul>
				{#if hiddenTitleCount > 0}
					<p class="titles-more">
						Showing the top {visibleTitles.length} titles. {hiddenTitleCount.toLocaleString()} more —
						type in the filter above to find a specific one.
					</p>
				{/if}
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

	.legend-item {
		max-width: none;
	}

	.legend-item.dim {
		opacity: 0.4;
	}

	.legend-item .lg-name {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		max-width: 240px;
	}

	.only-btn {
		flex: none;
		font-family: var(--font-sans);
		font-size: 0.7rem;
		font-weight: 600;
		padding: 2px 8px;
		border-radius: 999px;
		border: 1px solid var(--color-border);
		background: var(--color-white);
		color: var(--color-fg-light);
		cursor: pointer;
	}

	.only-btn:hover {
		border-color: var(--color-fg-light);
		color: var(--color-fg);
	}

	.only-btn.on {
		background: var(--color-fg);
		border-color: var(--color-fg);
		color: var(--color-white);
	}

	.show-all-btn {
		font-family: var(--font-sans);
		font-size: 0.72rem;
		font-weight: 600;
		padding: 3px 12px;
		border-radius: 999px;
		border: 1px solid var(--color-fg);
		background: var(--color-fg);
		color: var(--color-white);
		cursor: pointer;
	}

	.show-all-btn:hover {
		opacity: 0.85;
	}

	.compare-hint {
		font-family: var(--font-sans);
		font-size: 0.78rem;
		color: var(--color-fg-light);
		margin: 6px 2px 0;
	}

	.editing-banner {
		display: flex;
		align-items: center;
		gap: 12px;
		margin: 12px 0 0;
		padding: 10px 12px;
		border-radius: var(--radius-sm);
		background: var(--color-white);
		border: 1.5px solid var(--color-fg);
	}

	.editing-text {
		flex: 1;
		font-family: var(--font-sans);
		font-size: 0.82rem;
		color: var(--color-fg);
	}

	.done-btn {
		flex: none;
		font-family: var(--font-sans);
		font-size: 0.85rem;
		font-weight: 600;
		padding: 6px 18px;
		border-radius: 999px;
		border: none;
		background: var(--color-fg);
		color: var(--color-white);
		cursor: pointer;
	}

	.done-btn:hover {
		opacity: 0.85;
	}

	.group-chip.drag-over {
		border-color: var(--chip-color, var(--color-fg));
		background: var(--chip-color, var(--color-fg));
		color: var(--color-white);
		box-shadow: 0 0 0 3px rgba(0, 0, 0, 0.08);
	}

	.title-row[draggable="true"] {
		cursor: grab;
	}

	.title-row.dragging {
		opacity: 0.5;
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

	/* chart type toggle (line vs stacked area) + title sort toggle share a look */
	.mode-toggle {
		display: inline-flex;
		gap: 0;
		margin: 0 0 14px;
		border: 1px solid var(--color-border);
		border-radius: 999px;
		overflow: hidden;
		font-family: var(--font-sans);
	}

	.mode-toggle button {
		padding: 6px 16px;
		font-size: 0.85rem;
		background: var(--color-white);
		border: none;
		color: var(--color-fg-light);
		cursor: pointer;
	}

	.mode-toggle button + button {
		border-left: 1px solid var(--color-border);
	}

	.mode-toggle button.active {
		background: var(--color-fg);
		color: var(--color-white);
		font-weight: 600;
	}

	/* title list */
	.titles-header {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 10px;
		margin-bottom: 8px;
	}

	.title-filter {
		flex: 1;
		min-width: 180px;
		padding: 9px 12px;
		font-family: var(--font-sans);
		font-size: 0.9rem;
		background: var(--color-input-bg);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
	}

	.sort-toggle {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		font-family: var(--font-sans);
		font-size: 0.8rem;
	}

	.sort-label {
		color: var(--color-fg-light);
	}

	.sort-toggle button {
		padding: 5px 10px;
		font-size: 0.8rem;
		background: var(--color-white);
		border: 1px solid var(--color-border);
		border-radius: 999px;
		color: var(--color-fg-light);
		cursor: pointer;
	}

	.sort-toggle button.active {
		background: var(--color-fg);
		border-color: var(--color-fg);
		color: var(--color-white);
		font-weight: 600;
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

	.titles-more {
		font-family: var(--font-sans);
		font-size: 0.8rem;
		color: var(--color-fg-light);
		margin: 8px 2px 0;
	}

	.hint {
		font-family: var(--font-sans);
		color: var(--color-fg-light);
		text-align: center;
		margin-top: 28px;
	}
</style>
