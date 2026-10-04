// Turn a chart's SVG into a titled PNG (a Blob) for Download > Image: a title
// and subtitle on top, the site logo top-right (its own row on a narrow chart),
// a wrapped swatch legend under the chart, and a source line at the bottom.
// Same layout as the author/book and genre charts' exports.
import { drawChartLogo, chartLogoWidth } from "$utils/chartLogo.js";

// Paint the SVG's scoped CSS onto a clone, so it survives being serialized.
const PROPS = ["fill", "stroke", "stroke-width", "stroke-dasharray", "stroke-linecap", "stroke-linejoin", "opacity", "font-family", "font-size", "font-weight", "text-anchor", "color", "paint-order", "fill-opacity", "stroke-opacity"];

export async function renderChartPng(src, { title = "", subtitle = "", legend = [], source = "What Is Seattle Reading?  ·  Seattle Public Library checkouts" } = {}) {
	if (!src) return null;
	const clone = src.cloneNode(true);
	const from = src.querySelectorAll("*");
	const to = clone.querySelectorAll("*");
	to.forEach((node, i) => {
		const cs = getComputedStyle(from[i]);
		node.setAttribute("style", PROPS.map((p) => `${p}:${cs.getPropertyValue(p)}`).join(";"));
	});
	const w = Math.round(src.clientWidth || src.viewBox.baseVal.width || 800);
	const h = Math.round(src.clientHeight || src.viewBox.baseVal.height || 400);
	clone.setAttribute("width", w);
	clone.setAttribute("height", h);
	clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
	const img = new Image();
	await new Promise((res, rej) => {
		img.onload = res;
		img.onerror = rej;
		img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(new XMLSerializer().serializeToString(clone));
	});

	const scale = 2, padX = 28, footH = 40;
	const canvas = document.createElement("canvas");
	const ctx = canvas.getContext("2d");
	const TITLE_FONT = '600 22px Georgia, "Times New Roman", serif';
	const LEG_FONT = '600 13px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
	// The logo sits beside the title when there's room, else on its own row.
	ctx.font = TITLE_FONT;
	const logoRow = ctx.measureText(title).width + 16 > w - chartLogoWidth(ctx) ? 30 : 0;
	const titleH = 68 + logoRow;
	// Wrap the legend to the chart's width first, to size the canvas.
	const legLH = 22, legSw = 12, legGapSw = 6, legGapItem = 20;
	const legLines = [];
	if (legend.length) {
		ctx.font = LEG_FONT;
		let line = [], lineW = 0;
		for (const it of legend) {
			const iw = legSw + legGapSw + ctx.measureText(it.label).width;
			if (lineW + iw > w && line.length) { legLines.push(line); line = []; lineW = 0; }
			line.push(it);
			lineW += iw + legGapItem;
		}
		if (line.length) legLines.push(line);
	}
	const legendH = legLines.length ? legLines.length * legLH + 12 : 0;

	canvas.width = (w + padX * 2) * scale;
	canvas.height = (h + titleH + legendH + footH) * scale;
	ctx.scale(scale, scale);
	ctx.fillStyle = "#ffffff";
	ctx.fillRect(0, 0, canvas.width, canvas.height);
	ctx.textBaseline = "alphabetic";
	ctx.fillStyle = "#1a1a1a";
	ctx.font = TITLE_FONT;
	ctx.fillText(title, padX, 34 + logoRow);
	ctx.fillStyle = "#666666";
	ctx.font = '13px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
	ctx.fillText(subtitle, padX, 54 + logoRow);
	await drawChartLogo(ctx, logoRow ? padX + chartLogoWidth(ctx) : padX + w, logoRow ? 18 : 26);
	ctx.drawImage(img, padX, titleH, w, h);
	if (legLines.length) {
		ctx.font = LEG_FONT;
		ctx.textBaseline = "middle";
		let ly = titleH + h + 18;
		for (const line of legLines) {
			let lx = padX;
			for (const it of line) {
				ctx.fillStyle = it.color;
				ctx.fillRect(lx, ly - legSw / 2, legSw, legSw);
				ctx.fillStyle = "#333333";
				ctx.fillText(it.label, lx + legSw + legGapSw, ly + 0.5);
				lx += legSw + legGapSw + ctx.measureText(it.label).width + legGapItem;
			}
			ly += legLH;
		}
		ctx.textBaseline = "alphabetic";
	}
	ctx.fillStyle = "#999999";
	ctx.font = '11px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
	ctx.fillText(source, padX, titleH + h + legendH + 24);
	return await new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
}

// Save a Blob as a file.
export function saveBlob(blob, name) {
	const a = document.createElement("a");
	a.href = URL.createObjectURL(blob);
	a.download = name;
	a.click();
	setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
