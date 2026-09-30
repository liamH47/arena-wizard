# 0011: Card adjustments

Status: accepted 2026-09-30. Owner decision: adjustments are shared by the group and
record who changed them.

## Decision

- **What a friend can change.** Any allow-listed friend can mark a set's spell as a bomb or
  not a bomb, and/or move its value by up to ±10 points, with a note.
- **Where it's stored.** One row per (set, card) in `card_adjustments`, and every set or
  clear goes to the append-only `card_adjustment_log`. Setting the same values twice
  changes nothing and logs nothing; the last writer wins.
- **What wins.** Adjustments apply last, in event mode only: automatic bombs, then the
  curated YAML, then the adjustment. The eval never sees them.
- **Rebuilds.** The build's inputs key covers the set's adjustments, so a change makes the
  deck page offer a rebuild.
- **What a build shows.** An adjusted value's line ends "adjusted +2.0 by Bob".
- **Migration.** 0002 only adds tables, so a rolled-back build still boots (0008). Its
  downgrade refuses to drop rows, like 0001's; the guard is now shared.

## Not adopted

- **Owner-only edits.** The group is a handful of friends, and the log names every change.
