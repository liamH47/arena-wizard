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

This measures agreement, not accuracy: the reference is itself an automatic list, the
full-season Sealed file's list at the same 500-game floor. Counts only, no names. Precision
is flags also on the reference; recall is the reference's flags found.

| List | Flags | Precision | Recall |
|---|---|---|---|
| SOS Sealed, odd days vs even days (the ceiling) | 6 | 4/6 | 4/7 |
| SOS draft, first 10% of games by date | 9 | 8/9 | 8/10 |
| SOS draft, random 10%, three seeds | 9-10 | 6/10, 6/10, 6/9 | 6/10 each |
| SOS draft, full season | 13 | 7/13 | 7/10 |
| HOB Sealed, odd days vs even days (the ceiling) | 6 | 4/6 | 4/6 |
| HOB draft, first 10% of games by date | 6 | 2/6 | 2/7 |
| HOB draft, random 10%, three seeds | 4-7 | 3/7, 2/4, 2/4 | 2-3/7 |
| HOB draft, full season | 7 | 3/7 | 3/7 |

- **The ceiling.** Sealed agrees with itself only about two-thirds of the time, so no list
  can do much better.
- **SOS.** Draft data reaches that ceiling, and early data did too.
- **HOB.** Draft data agrees on about a third, a weak stand-in.
- **Why that's acceptable.** A wrong flag costs 1.5 points per copy, and builds name each
  bomb's source. So a friend can discount "from draft data" or fix it with an adjustment
  (decision 0011).
- **Unassessed cards.** A deck counts its spells under the floor ("N not assessed"), so
  "no bombs" is never claimed for cards that were not checked (recommendation-auditor).

## Not adopted

- **A higher threshold for draft data on HOB** (sealed-analyst): set-specific, and FRA is
  the target; revisit with FRA's first public file.
- **A committed command for the table** (recommendation-auditor): a one-off sanity check,
  not a gate. The method is above: `event_bomb_scores` on each file's day or game subset.

## Eval

Unchanged: the eval never runs event mode, and the decision digest matches main.
