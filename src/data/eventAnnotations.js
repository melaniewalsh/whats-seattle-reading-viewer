// The two library-wide events that put a visible dent in every checkout
// series. Each chart shades the affected months (month..end) in gray with a
// short two-line label at the top; hovering or focusing the label shows the
// blurb. Shared by every chart on the site so the wording stays in one place.
export const EVENT_ANNOTATIONS = [
	{
		month: "2020-03",
		end: "2021-04",
		year: 2020,
		label: "COVID-19 closure",
		short: ["Covid", "closures"],
		tiny: "COVID", // one word, for small charts
		blurb: "Beginning on March 13, 2020, the SPL halted physical checkouts, and progressively reintroduced them over the next year until a full re-opening on July 1, 2021.",
		url: "https://web.archive.org/web/20241209044138/https://www.spl.org/about-us/library-impact/2020-impact-report/a-look-back"
	},
	{
		month: "2024-05",
		end: "2024-07",
		year: 2024,
		label: "Ransomware attack",
		short: ["Ransomware", "outage"],
		tiny: "Outage",
		blurb: "A May 2024 ransomware attack knocked the library's systems offline for months — including the systems that record checkouts — so this drop partly reflects lost tracking, not just lost borrowing.",
		url: "https://www.kuow.org/stories/seattle-public-library-goes-low-tech-after-cyberattack-knocks-out-most-digital-services"
	}
];
