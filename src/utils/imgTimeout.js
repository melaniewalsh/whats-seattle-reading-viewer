// An attachment for cover <img>s: if the image hasn't loaded a few seconds
// after it scrolls into view, call onFail (show a fallback). Open Library's
// cover server sometimes hangs instead of failing, and then the browser's
// own error event doesn't come for minutes, leaving a blank box.
export function imgTimeout(onFail, ms = 5000) {
	return (img) => {
		let timer;
		const io = new IntersectionObserver((entries) => {
			if (!entries.some((e) => e.isIntersecting)) return;
			io.disconnect();
			timer = setTimeout(() => {
				if (!(img.complete && img.naturalWidth)) onFail();
			}, ms);
		});
		io.observe(img);
		return () => {
			io.disconnect();
			clearTimeout(timer);
		};
	};
}
