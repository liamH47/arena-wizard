# 0010: Automatic bombs in event mode

Status: accepted 2026-09-30. Owner decision. Amends 0007 #10 ("event mode uses the curated
list only").

## Decision

- **Automatic bombs in event builds, from pasted win rates.** Each card takes its score
  from the most direct layer with enough games for it: the Arena Direct (or Sealed) paste,
  else the Premier Draft paste. So a thin Arena Direct paste cannot push out the draft data
  that can see rares (sealed-analyst).
- **A 500-game floor for pasted data** (`event.bomb_min_games`). At 150 games in hand, a
  win rate's noise is about as large as the real spread between cards, so about half the
  flags would be luck. The public-file path keeps 150. Both need 50 qualifying cards and a
  threshold of 2.0.
- **Labelled by source.** Each deck names each bomb's source ("automatic, from draft data"
  or "the group's list"), and the Data block gives the count and the source, never names.
- **The curated list still wins.** It adds and removes over the automatic list, as before.
- **Where names may appear.** Automatic names may appear in builds, but never in the eval
  report or any committed file while a set has no curated list (CLAUDE.md). So SOS and HOB
  lists can still be written blind.

## Evidence

Draft-based lists at the 500-game floor, compared with the full-season Sealed list, as
counts only (no names):

| Set | Draft data used | Flagged | Also on the Sealed list |
|---|---|---|---|
| SOS | 10% | 10 | 6 of 10 |
| SOS | 100% | 13 | 7 of 10 |
| HOB | 10% | 7 | 3 of 7 |
| HOB | 100% | 7 | 3 of 7 |

The list is as good on a tenth of a season as on all of it: about 60% of flags match on
SOS and about 40% on HOB. A wrong flag costs at most 1.5 points, about 0.12 win-rate
points. Builds say which layer each bomb came from, and the group's list, or a card
adjustment (decision 0011), overrides it.

## Not adopted

- **A higher threshold for draft data on HOB** (sealed-analyst): set-specific, and FRA is
  the target; revisit with FRA's first public file.

## Eval

Unchanged: the eval never runs event mode, and the decision digest matches main.
