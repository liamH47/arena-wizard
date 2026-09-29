# 0005: Manual daily captures of 17Lands pages

Status: accepted 2026-09-28. Owner decision. Partly supersedes decision 0002 and the
embargo rule in `docs/plan.md` for private use within the limits below.

## Why

A new set's public 17Lands files arrive three to six weeks after release, and the JSON
endpoints wait on permission (decision 0002). Arena Directs usually run in a set's first
two weeks, so without this the app has no win-rate data for them at all. The owner
decided that a small group of friends may use what 17Lands already shows any visitor,
captured by hand at most once a day, to test whether data plus expert opinion makes them
better players. The app is private, not sold, and not distributed.

## What is allowed

A person opens 17lands.com in an ordinary browser and captures a card-data or deck-color
page, either as a screenshot or by selecting and copying the table as text. The app
imports that capture and uses its numbers.

## Limits, enforced in code where they can be

1. **By hand only.** No scripts, headless or automated browsers, scraping extensions, or
   calls to the 17Lands JSON endpoints. The capture is something a person does.
2. **At most one capture per set, 17Lands format, and UTC day.** Importing again the same
   day replaces that day's capture, to fix a mistake; it never adds a second one. The
   importer enforces this with a unique key on (set, format, UTC day).
3. **Only until the data is available another permitted way.** Once a set's public file
   for that format exists, or decision 0002 records endpoint permission covering it,
   captures for that set and format stop and the importer refuses them.
4. **Private.** Capture-derived numbers live only in the app's private database. They are
   never committed to the public repository, never used in the published eval report,
   test fixtures, or logs, and are shown only to signed-in, allow-listed users.
5. **Labelled.** Every number from a capture is labelled "17Lands site, captured by hand
   on {date}" with its sample size, and the 17Lands credit stays at the top of every page.
6. **Not commercial.** No sale, no ads, no payment of any kind, a handful of users.
7. **Revisited if 17Lands objects.** The Discord request (decision 0002) now tells 17Lands
   about this. If they reply that they do not want it, the owner revisits this decision.

## Which pages are worth capturing

The site shows regular Sealed card win rates as zero games (measured 2026-09-28), so the
useful captures are the card-data page for Arena Direct Sealed and for Premier Draft, and
the deck-color page for Sealed.

## Consulted

The owner, with the lead reviewer's analysis of the 17Lands usage guidelines and Terms of
Service.

## Dissent

data-source-steward's standing rule treats a source's explicit requests as hard stops, and
17Lands asks third-party tools not to present a new set's data before its 12th day on
Arena. The owner overruled it for private, non-distributed use within the limits above,
and chose to tell 17Lands rather than stay silent.

## Consequences for the plan

- Milestone 2 (FRA event mode) gains a capture importer for pasted table text, which
  parses deterministically. The owner plans to paste tables, so screenshot import is built
  only if pasting proves impractical, and then with the classical OCR approach planned for
  the pool screenshot importer, with no LLM.
- In the source chain, a capture takes the slot of the stream it shows: an Arena Direct
  capture stands where the Arena Direct endpoint would, a Premier Draft capture feeds the
  draft proxy, and a deck-color capture feeds the color-pair term. Its sample size sets its
  weight like any other source.
- The eval harness never sees capture data, because the published report must not
  redistribute it.
