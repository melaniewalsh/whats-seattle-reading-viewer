// The site's logo + name, drawn in the top-right corner of exported chart
// images (Download > Image, Copy image, Share), so a chart that travels keeps
// its source -- like the publisher logo on Our World in Data's charts.
import { base } from "$app/paths";

let logoPromise = null;
function loadLogo() {
	if (!logoPromise) {
		logoPromise = new Promise((resolve) => {
			const img = new Image();
			img.onload = () => resolve(img);
			img.onerror = () => resolve(null);
			img.src = `${base}/favicon.png`;
		});
	}
	return logoPromise;
}

// Right-aligned at xRight; vertically centered on yMid.
export async function drawChartLogo(ctx, xRight, yMid) {
	const logo = await loadLogo();
	const label = "WHAT’S SEATTLE READING?";
	ctx.save();
	ctx.font = '700 11px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
	if ("letterSpacing" in ctx) ctx.letterSpacing = "0.8px";
	ctx.fillStyle = "#3f88cc";
	ctx.textAlign = "right";
	ctx.textBaseline = "middle";
	ctx.fillText(label, xRight, yMid + 0.5);
	const tw = ctx.measureText(label).width;
	if (logo) ctx.drawImage(logo, xRight - tw - 30, yMid - 12, 24, 24);
	ctx.restore();
}
