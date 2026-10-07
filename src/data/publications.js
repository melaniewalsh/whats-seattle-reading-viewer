// Academic publications from the What's Seattle Reading? project, newest first.
// Grouped by year (and month, when given) in the Publications view.
export const publications = [
	{
		year: "2026",
		title:
			"What’s Seattle Reading? An Interactive Viewer and Open Data Pipeline for Two Decades of Public Library Circulation.",
		url: "https://doi.org/10.1145/3805696.3848491",
		citation:
			"Melanie Walsh, Neel Gupta, E. Tiago Ramos, Alexis Martin, Karalee Harris, and Lurier Bao. ACM/IEEE Joint Conference on Digital Libraries (JCDL 2026).",
		doi: "https://doi.org/10.1145/3805696.3848491",
		links: [{ label: "Viewer", url: "https://www.whats-seattle-reading.com/" }],
		bibtex: `@inproceedings{walshWhatsSeattleReading2026,
  title = {What's {{Seattle Reading}}? {{An Interactive Viewer}} and {{Open Data Pipeline}} for {{Two Decades}} of {{Public Library Circulation}}},
  author = {Walsh, Melanie and Gupta, Neel and Ramos, E. Tiago and Martin, Alexis and Harris, Karalee and Bao, Lurier},
  booktitle = {ACM/IEEE Joint Conference on Digital Libraries (JCDL 2026)},
  year = {2026},
  doi = {10.1145/3805696.3848491},
  url = {https://www.whats-seattle-reading.com/}
}`,
	},
	{
		year: "2025",
		month: "December",
		title:
			"The Canon in Circulation: Tracking the Reception of Norton Anthology Authors in Library Checkout Data.",
		url: "https://doi.org/10.63744/P6qPH135jhY2",
		citation:
			"Neel Gupta, Daniella Maor, Karalee Harris, Emily Backstrom, Hongyuan Dong, and Melanie Walsh. Computational Humanities Research (2025): 1510–22.",
		doi: "https://doi.org/10.63744/P6qPH135jhY2",
		links: [
			{
				label: "Data",
				url: "https://seattle-library-checkout-data.s3.us-west-2.amazonaws.com/norton-anthology_spl-checkouts_2005-2025.csv",
			},
			{ label: "Code", url: "https://github.com/melaniewalsh/Canon-in-Circulation" },
		],
		bibtex: `@inproceedings{guptaCanonCirculationTracking2025,
  title = {The {{Canon}} in {{Circulation}}: {{Tracking}} the {{Reception}} of {{Norton Anthology Authors}} in {{Library Checkout Data}}},
  shorttitle = {The {{Canon}} in {{Circulation}}},
  booktitle = {Computational {{Humanities Research}}},
  author = {Gupta, Neel and Maor, Daniella and Harris, Karalee and Backstrom, Emily and Dong, Hongyuan and Walsh, Melanie},
  editor = {Arnold, Taylor and Fantoli, Margherita and Ros, {and} Ruben},
  year = 2025,
  volume = {3},
  pages = {1510--1522},
  doi = {10.63744/P6qPH135jhY2},
  urldate = {2025-12-10},
  url = {https://anthology.ach.org/volumes/vol0003/the-canon-in-circulation-tracking-reception-of-in/}
}`,
	},
	{
		year: "2025",
		month: "August",
		title:
			"Seattle Public Library's Open Checkout Data: What Can It Tell Us About Readers and Book Popularity More Broadly?",
		url: "https://doi.org/10.5334/johd.332",
		citation:
			"Neel Gupta, David Christensen, and Melanie Walsh. Journal of Open Humanities Data 11, no. 1 (2025).",
		doi: "https://doi.org/10.5334/johd.332",
		links: [
			{ label: "Data", url: "https://zenodo.org/records/15792698" },
			{
				label: "Code",
				url: "https://github.com/neelgupta2112/Seattle-Public-Library-Library-Checkout-Data",
			},
		],
		bibtex: `@article{guptaSeattlePublicLibrarys2025,
  title = {Seattle {{Public Library}}'s {{Open Checkout Data}}: {{What Can It Tell Us About Readers}} and {{Book Popularity More Broadly}}?},
  shorttitle = {Seattle {{Public Library}}'s {{Open Checkout Data}}},
  author = {Gupta, Neel and Christensen, David and Walsh, Melanie},
  year = 2025,
  month = aug,
  journal = {Journal of Open Humanities Data},
  volume = {11},
  number = {1},
  issn = {2059-481X},
  doi = {10.5334/johd.332},
  urldate = {2025-12-10},
  url = {https://openhumanitiesdata.metajnl.com/articles/10.5334/johd.332}
}`,
	},
	{
		year: "2022",
		title: "Where is all the book data?",
		url: "https://www.publicbooks.org/where-is-all-the-book-data/",
		citation: "Melanie Walsh. Public Books.",
	},
];
