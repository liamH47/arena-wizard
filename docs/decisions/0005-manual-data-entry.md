# 0005: Manual data entry

Status: accepted 2026-09-28. Owner decision. Partly supersedes decision 0002 and the
embargo rule in `docs/plan.md` for data a user pastes in by hand, within the limits below.

## Why

Automated sources arrive late or not at all: a set's public 17Lands files come three to six
weeks after release, the 17Lands endpoints wait on permission (decision 0002), and other
useful data (other statistics sites, tier lists, a friend's own ratings) has no feed at all.
Arena Directs run in a set's first two weeks. The owner decided that the group may paste
data in by hand from any source, to test whether data plus expert opinion makes them better
players. The app is private, not sold, and not distributed.

## What is allowed

A signed-in user brings data in by hand, from any source, in either of two ways:

- **Upload a file they exported,** such as the CSV from the "Download as CSV" link on
  17Lands' card data page (the site names it `card-ratings-YYYY-MM-DD.csv`).
- **Paste text they copied,** such as the output of that page's "Copy to clipboard"
  option, a selected table, a tier list, or the group's own ratings.

Both go through the same importer and the same limits; "paste" below means either. The app
parses the data and uses its numbers.

## Limits, enforced in code where they can be

1. **By hand only.** The app never fetches the data itself; a person clicks the export or
   copies the table. No scripts, headless or
   automated browsers, scraping extensions, or calls to a source's undocumented API feed the
   paste importer. Copying and pasting is something a person does.
2. **Every paste names its source.** The user records the source (for example "17Lands card
   data, Arena Direct Sealed"), an optional link, and the date the data was copied. Every
   number from a paste is labelled with that source, date, and its sample size when the
   source gives one.
3. **At most one paste per source, set, dataset, and UTC day.** Pasting again the same day
   replaces that day's paste, to fix a mistake; it never adds a second one. The importer
   enforces this with a unique key, which also keeps day-by-day history clean.
4. **Automated, permitted data wins.** Once a permitted automated source covers the same
   data (a 17Lands public file for that set and format, or endpoint access recorded in
   decision 0002), the importer refuses further pastes of it and the engine uses the
   automated data instead.
5. **Private.** Pasted data lives only in the app's private database. It is never committed
   to the public repository, never used in the published eval report, test fixtures, or
   logs, and is shown only to signed-in, allow-listed users. Test fixtures use made-up
   numbers in the same layout.
6. **Not commercial.** No sale, no ads, no payment of any kind, a handful of users.
7. **Sources' own wishes.** The 17Lands permission request (decision 0002) tells 17Lands
   about this; if they object, the owner revisits the decision. For any other source, the
   data-source steward checks its terms when a parser for its layout is added.

## Formats

Each source layout needs a parser, and each parser is tested with made-up data in that
layout. Parsers accept comma- or tab-separated text and strip a byte-order mark (17Lands'
CSV export starts with one). The first are the 17Lands card-data export and the deck-color
table, because they carry the win rates. The export is not known to record which set,
format, or date range was selected on the page, so the user picks those in the app, and the
importer checks the card names against that set's card table.

17Lands shows regular Sealed card win rates as zero games (measured 2026-09-28), so the
useful 17Lands pages are the card-data page for Arena Direct Sealed and for Premier Draft,
and the deck-color page for Sealed. A generic layout (card name plus
named value columns, for tier lists and the group's own grades) follows. Screenshot import
is built only if pasting proves impractical, and then with classical OCR, no LLM.

## Consulted

The owner, with the lead reviewer's analysis of the 17Lands usage guidelines and Terms of
Service. The owner first scoped this to 17Lands captures, then generalized it to any source
the same day.

## Dissent

data-source-steward's standing rule treats a source's explicit requests as hard stops, and
17Lands asks third-party tools not to present a new set's data before its 12th day on
Arena. The owner overruled it for private, non-distributed use within the limits above,
and chose to tell 17Lands rather than stay silent.

## Consequences for the plan

- Milestone 2 (FRA event mode) gains the paste importer and the 17Lands parsers; the
  generic parser can follow in the same milestone or later.
- In the source chain, a paste takes the slot of the data it holds: a 17Lands Arena Direct
  paste stands where the Arena Direct endpoint would, a Premier Draft paste feeds the draft
  proxy, a deck-color paste feeds the color-pair term, and ratings or tier lists sit with
  the expert ratings. Its sample size, when it has one, sets its weight like any other
  source.
- The eval harness never sees pasted data, because the published report must not
  redistribute it.
