# 0011: Card adjustments

Status: accepted 2026-09-30. Owner decision: adjustments are shared by the group and
record who changed them.

## Decision

- **What a friend can change.** Any allow-listed friend can mark a set's spell as a bomb or
  not a bomb, and/or move its value by up to ±10 points (kept to 0.1), with a note.
- **Where it's stored.** One row per (set, card) in `card_adjustments`, and every set or
  clear goes to the append-only `card_adjustment_log`. Setting the same values twice
  changes nothing and logs nothing. The last writer wins: a write that loses a race with
  another friend's insert or clear retries once, and a clear logs only if it removed a row.
- **What wins.** Adjustments apply last, in event mode only: automatic bombs, then the
  curated YAML, then the adjustment. The eval never sees them.
- **Rebuilds.** The build's inputs key covers only adjustments to the pool's cards, and only
  what changes a build (card, bomb, value). A note edit, a rename, or an adjustment to
  another card leaves everyone's builds current.
- **What a build shows.**
  - An adjusted value's line ends "adjusted +2.0 by Bob".
  - A bomb a friend added reads "(added by Bob)", and one a friend removed leaves the
    automatic count.
  - The Data block says how many of the pool's cards were adjusted.
- **Migration.** 0002 only adds tables, so a rolled-back build still boots (0008). Its
  downgrade refuses to drop rows, like 0001's; the guard is now shared.

## Panel

Reviewed by pipeline-integrity-reviewer, edge-case-hunter, event-night-reliability, and
test-architect.

**Accepted:**
- **Race handling:** retry once, and a clear logs only when it deleted a row. Tested.
- **Narrower build key**, flagged by three reviewers.
- **Labels:** bombs a friend added are labelled, and their removals leave the counts.
- **Data block:** a line for adjusted cards.
- **Values:** rounded to 0.1.
- **Tests:** stronger content, bounds, and build-key tests.

**Rejected:**
- **Row locks (`SELECT ... FOR UPDATE`).** SQLite has none. The only effect is that two
  identical concurrent saves both log, and the stored row is still right.
- **A named-constraint race test.** The retry test covers the race.

## The page (event-night-ux, edge-case-hunter)

**How adjusting works:**
- Each card value in "Why this deck" has an Adjust form, prefilled with what the group has
  saved. So a save never silently erases a friend's value or note.
- Saving does not reload the build: the deck being piloted keeps its list and result form,
  and the change applies at the next "Build again".
- Save waits while a build is running, and Clear needs something to clear.
- Pastes lists the set's adjustments, with who, when, and Clear.

**Rejected:**
- **Moving Adjust off the deck page** (event-night-ux). The approved plan puts it in the
  closed card-values list, which is off the Arena-list path.
- **A confirm before Clear on Pastes.** The log keeps what was cleared.

## Not adopted

- **Owner-only edits.** The group is a handful of friends, and the log names every change.
