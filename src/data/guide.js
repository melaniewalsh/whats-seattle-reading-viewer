// The "How to read this data" guide (src/components/Guide.svelte): one entry
// per step. Edit the text freely. `chart` names the graphic shown beside the
// step (see Guide.svelte), or `image` shows a picture from static/; `link`
// adds a "try it" button that opens that part of the site.
export const GUIDE_TITLE = "How to Read Seattle's Checkouts";
export const GUIDE_DEK = "A short walk through what this data is, what the site shows, and what to keep in mind.";

export const GUIDE_STEPS = [
	{
		chart: "total",
		title: "Every checkout, every month",
		text: "The Seattle Public Library publishes how many times each title was checked out, every month since April 2005: print books, ebooks and audiobooks. That adds up to more than 120 million checkouts. Each record names a title, an author, a format and subject headings. Nothing in it is connected to individual patrons."
	},
	{
		chart: "formats",
		title: "Print, ebooks and audiobooks",
		text: "Split by format, the same data tells a story of its own. Ebooks and audiobooks grew steadily, then jumped in 2020 when the branches closed for COVID, and they have stayed near the top since. The shaded bands mark the COVID closures and the 2024 ransomware outage, when checkouts weren't recorded normally.",
		link: { label: "Explore the overview", tab: "overview" }
	},
	{
		chart: "author",
		title: "One author's checkouts over time",
		text: "Search any author to see their checkouts month by month. Octavia E. Butler's line climbs through the 2010s and spikes in spring 2024, when Parable of the Sower was the library's Seattle Reads pick. The faint bars behind the line are each month's count; the line is a 3-month average.",
		link: { label: "See Octavia E. Butler's page", author: "octavia-e-butler" }
	},
	{
		chart: "editions",
		title: "One book, many editions",
		text: "The library's data lists every edition separately. Parable of the Sower appears under more than a dozen catalog records: ebooks and audiobooks from different publishers, print copies (one with a foreword by N. K. Jemisin), a graphic novel adaptation, and Spanish and Chinese translations. The site groups these into one work so a book's whole readership counts together. On a book's page, the By edition button splits the line back apart, and the edition list gives each one's publisher, year and format. The grouping is automatic, so check that list when a number looks off.",
		link: { label: "See Parable of the Sower's editions", title: "Parable of the Sower", titleAuthor: "octavia-e-butler" }
	},
	{
		chart: "compare",
		title: "Compare authors and books",
		text: "Type a comma between names to put several authors or books on one chart. Here Octavia E. Butler and Ursula K. Le Guin, two science fiction writers, over twenty years.",
		link: { label: "Try a comparison", compare: ["a~octavia-e-butler", "a~ursula-k-le-guin-1929"] }
	},
	{
		chart: "romance",
		title: "Genres rise and fall",
		text: "Every record carries Library of Congress or BISAC subject headings. Grouping those headings into genres shows how Seattle's tastes shift: romance, for example, went from about 7% of book checkouts in 2015 to about 14% in 2025.",
		link: { label: "Explore genres", tab: "genres" }
	},
	{
		image: "home/borrowed.jpg",
		title: "The most-borrowed books",
		text: "Most Borrowed ranks books and authors by checkouts for any year, for last month, or for all time, overall and by genre. Editions are grouped into works here too.",
		link: { label: "See Most Borrowed", tab: "works" }
	},
	{
		image: "home/backlist.jpg",
		title: "Books that come back",
		text: "Backlist Boomerangs finds books whose checkouts suddenly jumped years after they first circulated: a film adaptation, a viral moment, an award, a death, a city-wide reading program.",
		link: { label: "See Backlist Boomerangs", tab: "backlist" }
	},
	{
		image: "home/trends.jpg",
		title: "Subjects and books",
		text: "On any book or author page, the subject tags under the title open lists of the most-borrowed books on that subject, and every book links to its own page with its editions, formats and checkout history.",
		link: { label: "Search for a book", tab: "search" }
	},
	{
		note: true,
		title: "What to keep in mind",
		text: "Checkouts count borrowing, not reading, and not holds or renewals. Grouping editions into works is automatic and imperfect. Subject headings are the library's catalog terms, with their own history and blind spots. And to protect readers' privacy, very small counts are shown by year, and books with fewer than 25 checkouts aren't listed one by one.",
		link: { label: "Read about the data and methods", tab: "about" }
	}
];
