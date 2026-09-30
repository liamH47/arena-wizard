# 0010: Automatic bombs in event mode

Status: accepted 2026-09-30. Owner decision. Amends 0007 #10 ("event mode uses the curated
list only").

## Decision

- **Automatic bombs in event builds.** They come from pasted win rates: the Arena Direct
  (or Sealed) paste first, else the Premier Draft paste. The same scoring and floors as the
  public-file path apply (at least 150 games in hand, at least 50 qualifying cards,
  threshold 2.0).
- **Labelled by source.** Each deck names each bomb's source ("automatic, from draft data"
  or "the group's list"), and the Data block gives the count and the source, never names.
- **The curated list still wins.** It adds and removes over the automatic list, as before.
- **Where names may appear.** Automatic names may appear in builds, but never in the eval
  report or any committed file while a set has no curated list (CLAUDE.md). So SOS and HOB
  lists can still be written blind.

## Evidence

Automatic lists from the whole season's public files, as counts only:

| Set | From the Sealed file | From the Premier Draft file | Both |
|---|---|---|---|
| SOS | 12 | 13 | 8 |
| HOB | 7 | 7 | 3 |

Draft data is a fair stand-in on SOS and a weak one on HOB, and early-event pastes are far
thinner than a season. Builds therefore say which layer each bomb came from, and the
group's list, or a card adjustment (decision 0011), overrides it.

## Eval

Unchanged: the eval never runs event mode, and the decision digest matches main.
