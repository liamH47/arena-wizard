# 0012: Unplayed cards start lower

Status: accepted 2026-10-03. Owner direction: "assume cards with less games are worse or at
least unreliable", after a planeswalker tutor topped an FRA build with no planeswalkers.

## Decision

- **Which cards.** Only cards with no expert grade, whose prior is their rarity's average.
- **The shift.** The prior moves `play_slope` (3.0) points per natural-log unit of the
  card's in-hand games over its rarity's median.
- **Which data.** Games come from the layer with the most games, usually draft data.
- **Limits.** The log is clamped to [-2, +1], and a card absent from the data counts as
  never played. So an unplayed card starts 6 points lower, and a heavily played one up to
  3 points higher.
- **What it doesn't touch.** Graded cards keep their grade, and the eval never runs event
  mode.
- **The label.** A value's label says so: "rare average, -6.0 for how often it is played".

## Evidence

Counts and fits only, no card names. Inputs are the 17Lands public SOS and HOB Premier Draft
and Sealed files.

**1. Play rate predicts sealed value within a rarity.** Fit: a card's full-season Sealed win
rate against its rarity's mean, on the log of its draft in-hand games over its rarity's
median.

| Set | Draft data | Slope, q per log unit | Correlation |
|---|---|---|---|
| SOS | first 10% by date | +3.2 | 0.44 |
| SOS | full season | +3.2 | 0.53 |
| HOB | first 10% by date | +5.8 | 0.70 |
| HOB | full season | +4.9 | 0.76 |

The few cards played under a quarter as often as their rarity's median average 6 to 12
points below it.

**2. Event-mode values against full-season Sealed.** No grades, early draft data only.

| Set | Draft data | RMSE without | RMSE with | Correlation without | Correlation with |
|---|---|---|---|---|---|
| SOS | first 3% | 2.51 | 2.55 | 0.756 | 0.756 |
| SOS | first 10% | 2.37 | 2.40 | 0.786 | 0.785 |
| HOB | first 3% | 3.44 | 3.27 | 0.644 | 0.688 |
| HOB | first 10% | 2.91 | 2.74 | 0.772 | 0.797 |

The yardstick needs 300+ Sealed games per card. That leaves out most of the rarely played
cards this targets, so the table understates the gain for them.

The slope is set at 3.0, the low end of the measured slopes, because SOS gains nothing.
