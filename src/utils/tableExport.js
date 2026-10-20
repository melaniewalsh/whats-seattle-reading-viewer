// Share / copy helpers for the Most Borrowed ranking tables (TopWorks,
// TopAuthors): the top-10 table drawn to a PNG, and the Share menu's actions.
import { saveBlob } from "$utils/chartImage.js";
import { compactNumber } from "$utils/format.js";

// System + Georgia fonts so the image renders reliably on canvas without
// waiting on webfonts.
const IMG_SANS = '-apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif';

function ellipsize(ctx, s, maxW) {
	if (ctx.measureText(s).width <= maxW) return s;
	while (s.length > 1 && ctx.measureText(s + "…").width > maxW) s = s.slice(0, -1);
	return s + "…";
}

// Draw a ranking table to a PNG Blob (null when there are no rows).
//   rows   : the ranked rows
//   count  : (row) -> checkouts
//   name   : (row) -> [main line, optional smaller second line]
//   column : the name column's header ("WORK", "AUTHOR")
//   rowH   : row height; lineDy: the main line's baseline within the row
export async function renderTableBlob({ title, subtitle, column, rows, count, name, rowH, lineDy }) {
	const list = rows;
	if (!list.length) return null;
	const scale = 2, W = 640, padX = 32;
	const titleH = 92, headH = 30, footH = 44;
	const H = titleH + headH + rowH * list.length + footH;
	const canvas = document.createElement("canvas");
	canvas.width = W * scale;
	canvas.height = H * scale;
	const ctx = canvas.getContext("2d");
	ctx.scale(scale, scale);
	ctx.fillStyle = "#ffffff";
	ctx.fillRect(0, 0, W, H);
	ctx.textBaseline = "alphabetic";

	// Title + subtitle
	ctx.fillStyle = "#1a1a1a";
	ctx.font = '600 24px Georgia, "Times New Roman", serif';
	ctx.fillText(ellipsize(ctx, title, W - padX * 2), padX, 46);
	ctx.fillStyle = "#666666";
	ctx.font = `13px ${IMG_SANS}`;
	ctx.fillText(subtitle, padX, 68);

	// Header row. The count column is [abbreviated number][data bar], matching
	// the on-screen table.
	const rightX = W - padX;
	const barTrackW = 150;
	const barX0 = rightX - barTrackW; // bars start here, grow rightward
	const numX = barX0 - 14; // right edge of the right-aligned number
	const numColLeft = numX - 54; // left edge of the number label
	let y = titleH;
	ctx.fillStyle = "#999999";
	ctx.font = `700 11px ${IMG_SANS}`;
	ctx.textAlign = "left";
	ctx.fillText("#", padX, y);
	ctx.fillText(column, padX + 40, y);
	ctx.fillText("CHECKOUTS", numColLeft, y);
	ctx.strokeStyle = "#dddddd";
	ctx.lineWidth = 1;
	ctx.beginPath();
	ctx.moveTo(padX, y + 9);
	ctx.lineTo(rightX, y + 9);
	ctx.stroke();

	// Rows
	y += headH;
	const max = Math.max(...list.map(count)) || 1;
	list.forEach((r, i) => {
		const baseY = y + rowH * i;
		const lineY = baseY + lineDy; // the main line — count/bar align to it
		const n = count(r);
		ctx.fillStyle = "#999999";
		ctx.font = `13px ${IMG_SANS}`;
		ctx.textAlign = "left";
		ctx.fillText(String(i + 1), padX, lineY);
		// abbreviated count, right-aligned
		ctx.fillStyle = "#1a1a1a";
		ctx.font = `600 14px ${IMG_SANS}`;
		ctx.textAlign = "right";
		ctx.fillText(compactNumber(n), numX, lineY);
		// data bar
		ctx.fillStyle = "#3f88cc";
		ctx.beginPath();
		ctx.roundRect(barX0, lineY - 13, Math.max((n / max) * barTrackW, 4), 16, 3);
		ctx.fill();
		// name (+ second line)
		const [main, sub] = name(r);
		ctx.textAlign = "left";
		const nameMaxW = numColLeft - 12 - (padX + 40);
		ctx.fillStyle = "#1a1a1a";
		ctx.font = `600 15px ${IMG_SANS}`;
		ctx.fillText(ellipsize(ctx, main, nameMaxW), padX + 40, lineY);
		if (sub) {
			ctx.fillStyle = "#777777";
			ctx.font = `13px ${IMG_SANS}`;
			ctx.fillText(ellipsize(ctx, sub, nameMaxW), padX + 40, baseY + 39);
		}
		ctx.strokeStyle = "#eeeeee";
		ctx.beginPath();
		ctx.moveTo(padX, baseY + rowH);
		ctx.lineTo(rightX, baseY + rowH);
		ctx.stroke();
	});

	// Footer
	ctx.fillStyle = "#999999";
	ctx.font = `11px ${IMG_SANS}`;
	ctx.fillText("What’s Seattle Reading?  ·  Seattle Public Library checkouts", padX, H - 18);
	return await new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
}

// The phone's share sheet with the table image; elsewhere, save the image.
// render() -> Promise<Blob|null>; flash(msg, ms) shows the toast.
export async function shareTableImage(render, name, { link, text }, flash) {
	const blob = await render();
	if (!blob) return;
	const file = new File([blob], name, { type: "image/png" });
	if (navigator.canShare && navigator.canShare({ files: [file] })) {
		try {
			await navigator.share({ files: [file], title: text, text: `${text}\n${link}` });
		} catch {}
		return;
	}
	saveBlob(blob, name);
	flash("Image saved — attach it to your post", 3200);
}

// Copy the table image; where the browser can't copy images, save it instead.
// The clipboard gets the render's promise right away (Safari needs the write
// to start inside the click).
export async function copyTableImage(render, name, flash) {
	try {
		if (!(navigator.clipboard && window.ClipboardItem)) throw new Error("no clipboard");
		await navigator.clipboard.write([new ClipboardItem({ "image/png": render() })]);
		flash("Table image copied to clipboard", 2600);
	} catch {
		const blob = await render();
		if (blob) saveBlob(blob, name);
		flash("Image saved (clipboard unavailable)", 2600);
	}
}

export async function copyPageLink(flash) {
	try {
		await navigator.clipboard.writeText(window.location.href);
		flash("Link copied!", 2000);
	} catch {
		flash("Couldn’t copy. Copy the link from the address bar.", 3200);
	}
}
