// The two library-wide events that put a visible dent in every checkout
// series: a "?" marker sits above each one on the charts, and hovering (or
// focusing) it explains the dip. Shared by every chart on the site so the
// wording stays in one place.
export const EVENT_ANNOTATIONS = [
	{
		month: "2020-03",
		year: 2020,
		label: "COVID-19 closure",
		blurb: "Seattle closed all physical library branches in March 2020 to slow the spread of COVID-19, so in-person checkouts dropped sharply (digital borrowing kept going).",
		url: "https://web.archive.org/web/20241209044138/https://www.spl.org/about-us/library-impact/2020-impact-report/a-look-back"
	},
	{
		month: "2024-05",
		year: 2024,
		label: "Ransomware attack",
		blurb: "A May 2024 ransomware attack knocked the library's systems offline for months — including the systems that record checkouts — so this drop partly reflects lost tracking, not just lost borrowing.",
		url: "https://www.kuow.org/stories/seattle-public-library-goes-low-tech-after-cyberattack-knocks-out-most-digital-services"
	}
];
