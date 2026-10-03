# 0012: Rarely played cards start lower

Status: accepted 2026-10-03. Owner direction: "assume cards with less games are worse or at
least unreliable", after a planeswalker tutor topped an FRA build with no planeswalkers.

## Decision

- **Which cards.** Only cards with no expert grade, whose prior is their rarity's average.
- **The shift.** The prior moves `play_slope` (3.0) points per natural-log unit of the
  card's in-hand games over its rarity's median.
- **Which data.** Games come from the layer with the most games for that rarity, usually
  draft data.
- **Limits.** The log is clamped to [-2, +1]: a rarely played card starts up to 6 points
  lower, and a heavily played one up to 3 points higher.
- **Blank win rates.** Games whose win rate 17Lands left blank, which is what it does for
  thin samples, still count as plays. They are kept as `Snapshot.unrated`, never as 0 wins.
- **Cards missing from the data move 0**, labelled "no games in the data". A new card or a
  name mismatch is not known to be unplayed.
- **Graded cards keep their grade:** reviewers already price in playability.
- **Labels:** "rare average, -6.0: drafters rarely play it".
- **The eval never runs event mode**, so it is unaffected.

## Cards with no win rate are listed, not left out (owner, same day)

- **What the owner first asked:** leave out cards whose win rate 17Lands left blank for
  too few games.
- **The sealed-analyst's objection:** 17Lands blanks rates until roughly 400+ in-hand
  games. Early in a format, and with Arena Direct data alone, that would drop about 6 rares
  and mythics plus about 10 uncommons per pool, the likeliest bombs, and do it silently.
- **The owner's choice:** keep them in. They are valued at their rarity's average, lowered
  by the play-rate prior above, and listed under "No win rate yet" with an Adjust form each.
- **Which cards are listed:** only cards that no layer rates.

## Evidence

Inputs are the 17Lands public SOS and HOB Premier Draft and Sealed files, using the first
10% of draft games by date. Aggregates only, no card names.

**1. The target cards.** Pooled check on cards with under a quarter of their rarity's
median plays:

| Set | Cards | Pooled Sealed games | Sealed vs rarity (se) | Predicted before | Predicted after |
|---|---|---|---|---|---|
| SOS | 45 | 3,075 | -7.6 (0.9) | -2.6 | -6.0 |
| HOB | 10 | 1,481 | -14.5 (1.3) | -4.8 | -8.3 |

**2. All well-measured cards.** Cards with 300+ Sealed games; the RMSE change is paired,
with a 2,000-resample bootstrap over cards:

| Set | RMSE change | 95% interval |
|---|---|---|
| SOS | +0.03 | -0.04 to +0.09 (no detectable change) |
| HOB | -0.17 | -0.26 to -0.08 (better) |

**3. Play rate predicts value within a rarity.** Slope 3.2 on SOS and 4.9 to 5.8 on HOB, in
q per log unit; correlation 0.44 to 0.76.

**Caveat.** The slope was chosen at the low end of these same two sets, so this is
in-sample. FRA's first public file is the out-of-sample check.

## Panel

Reviewed by sealed-analyst, recommendation-auditor (with the sealed-educator lens), and
test-architect.

**Accepted:**
- Keep blank-rate plays (sealed-analyst; this was a blocker). Without it, the trigger card's
  thin paste row was dropped and escaped the change.
- A card missing from the data moves 0, with a visible label (auditor).
- Clearer labels.
- The pooled target-card check and the bootstrap (auditor).
- Tests for the median per rarity, the choice of layer, and the value in the grades branch
  (test-architect).

**Deferred:**
- **Widening the draft reading's error for rarely played cards** (sealed-analyst). In
  pastes, the thinnest cards have blank rates and so no reading at all. Both sets still
  predict above actual for rarely played cards, so fit the multiplier with the Phase 2
  studies.
- **A third set** (auditor). FRA's public file, when it appears.

**Separate PR:** a rule that depends on the pool, such as a tutor with no targets. That goes
in the card tag audit (PR5).
