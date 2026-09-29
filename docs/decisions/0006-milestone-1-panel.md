# 0006: Milestone 1 panel review, scoring corrections, and the merge gate

Status: accepted 2026-09-29. Reviewed the milestone-1 branch (CLI deck builder and
evaluation harness) before its PR.

## Consulted

sealed-analyst, sealed-educator, recommendation-auditor, pipeline-integrity-reviewer,
edge-case-hunter, and test-architect, run read-only and in parallel against the same
commit. The analyst and auditor ran their own regressions on the committed eval data; the
edge-case-hunter probed a clean `git archive` copy with all 1,200 sample pools; the
pipeline reviewer corrupted a scratch cache to test `build-set`.

## Agreed by consensus

- The held-out construction is sound at the row level: statistics come only from games on
  or before each file's split day, and sample pools start after it.
- Every sample pool builds into a legal 40-card deck, and output is identical across
  `PYTHONHASHSEED` values.
- The parser and resolver handled every Arena export quirk tried, including Special Guests.
- `build-set` is byte-identical on re-run, and the cached counts match a fresh recount.

## Decisions

### Scoring (config version 0.3)

1. **A splashed card costs 5.0 score points, and a splash needs 3 real land sources**
   (analyst, BLOCKER). The engine splashed in 73 to 75% of pools against 19 to 31% of
   players. A regression of player builds put a splash at about 4 win-rate points, roughly
   21 q-points per splashed card, against the 3 the engine charged. `splash_min_sources`
   was never read, and fixers counted as sources; both are fixed.
2. **The pair term's weight is 0** (analyst). It double-counts card quality, is
   selection-biased toward pairs only strong pools play, and gave unplayed pairs the
   average. It is the only change that raised agreement on both sets. It returns only when
   re-estimated as a residual over what the deck's cards predict.
3. **Automatic bombs re-standardize the summed z-scores** (analyst). The unstandardized sum
   named five to six "bombs" per pool, including commons. Now about one per pool, and a
   third of pools have none.
4. **Improvement-when-drawn is centred on the rarity's mean,** not the format's (analyst,
   minor).
5. **The YAML states the units**: about 12 q-points equal one win-rate point (analyst). The
   shape weights stay hand-set until milestone 7 fits them by penalized regression; today
   their spread across player builds is under 3 points against 27 for card quality.
6. **Shrinkage priors measured by method of moments**: 180 games for win rate in hand, 350
   for improvement when drawn, 300 for pairs.

### Engine correctness (edge-case-hunter)

7. **A spell with no mana cost is cast by its suspend cost,** else it needs one source of
   each of its colors. Living End was being played in every deck of 6 SOS pools.
8. **Lands with restricted or chosen-color mana are not duals.** Great Hall of the
   Biblioplex and Room of Refuge counted as sources of every color.
9. **Basics split by total sources, not basics,** with at least six sources for each main
   color the spells use. The heavier color no longer ends up with fewer sources.
10. **Pool files in UTF-16 and cp1252 decode,** and `--format` offers only formats with a
    scoring config.

### What the player reads (educator)

11. **`build` refuses to rank without statistics** and says how to load them, instead of
    picking cards alphabetically (educator and edge-case-hunter converged).
12. **Statistics for a set inside the 17Lands embargo are treated as absent,** with the date
    and a link.
13. **Values more than 20% prior show both the observed and the used rate;** cards with no
    games are named.
14. **Comparisons print the actual sums and the cards unique to each deck,** and the
    standard error now includes the pair term and duplicate copies. The text says it covers
    sample sizes only.
15. **Bombs say whether they are automatic or curated.** Warnings are grouped, so the
    alternate-printing notes no longer bury an unrecognised line.

### Pipeline (pipeline-integrity and test-architect converged)

16. **Pre-split counts are derived from the same bytes that were hashed and pinned.** A
    counts file from another download could previously pass under the pinned hash.
17. **The game cache recounts when the counting code's version changes,** and downloads
    again when the file is missing or its hash differs, even with a matching ETag.
18. **Every write is atomic with fsync** (`fileio.py`), and report comparison keeps
    booleans distinct from numbers.

### The merge gate (auditor and test-architect converged)

19. **Outcome measures gate; imitation only ratchets.** The fixed "beat every naive
    baseline by 500 bp" rule could not pass on SOS, where "most playable spells" matches
    players 99.1% of the time because pools are college-seeded. Every set must now show:
    - every pool gets a legal deck;
    - the engine's deck score predicts player wins better than raw win rate in hand (AUC
      margin above zero, pool-clustered bootstrap);
    - agreement no more than 300 bp below the raw-win-rate baseline;
    - no more than 1,000 bp more splashing than players;
    - 0.5 to 1.5 automatic bombs per pool.
20. **Against the base report,** the pinned data may not change, no metric may disappear or
    turn None, and paired flips at 1 and at 3 may not lose a net 300 bp of pools.
21. **The base is read fail-closed.** An unreadable ref raises; only a ref that exists but
    has no report yet counts as no base. CI checks out with `fetch-depth: 0`.
22. **Accepted exceptions expire.** An `eval/accepted.json` entry counts only while its
    `base_digest` matches the base report's decision digest and its decision file exists.
23. **The eval job runs on every PR** with no paths filter, and the floor guard fails a PR
    that drops the eval command from CI.

### Report

24. **Automatic bomb names are withheld from the report** until the curated SOS and HOB
    lists exist, so the friends write those lists without seeing the automatic one.
25. **Added metrics:**
    - within-pool switch, split by build order;
    - a table of confidence by splash;
    - pair agreement at 3;
    - deck overlap at the player's pair;
    - the share of pools and games after the split.

## Measured result

Out of sample, 600 pools per set, config 0.3:

| Metric | SOS | HOB |
|---|---|---|
| Pair agreement at 1 | 87.8% | 44.6% |
| Raw win rate in hand at 1 | 82.5% | 43.9% |
| Most playable spells at 1 | 99.1% | 17.1% |
| Pair agreement at 3 | 97.8% | 68.2% |
| Engine / player splash share | 7.5% / 18.7% | 27.2% / 30.5% |
| Deck-score AUC margin over raw win rate (95% interval) | +0.018 (0.003 to 0.031) | +0.029 (0.014 to 0.043) |
| Automatic bombs per pool | 0.95 | 1.07 |
| Legality | 1.0 | 1.0 |

The analyst's splash sweep, before the other fixes, on all 600 pools:

| | SOS | HOB |
|---|---|---|
| Engine splash share | 73% to 22% | 75% to 40% |
| Pair agreement | 86.9% to 87.7% | 44.8% to 44.3% |

## Rejected

- **A paths filter on the eval job** (reliability, in the plan): config edits are exactly
  what must be measured.
- **Owner review on `accepted.json` via CODEOWNERS** (test-architect): with a single owner
  who also authors the PRs, a required code-owner review cannot be satisfied. The expiring
  digest covers the self-exemption risk instead.

## Deferred

- **Rebuild lift and bomb F1:** bomb F1 needs the curated lists; rebuild lift lands with the
  tuning round.
- **Mono-color plus splash decks:** near-mono pools only show the problem at rank 3 or
  lower in the sample.
- **Re-estimating the priors on pre-split games only:** they were estimated on the full
  files, and the report says so.
- **Fitting shape weights by penalized regression:** milestone 7.
- **An absolute agreement floor file:** the per-PR ratchet allows 300 bp at a time; revisit
  if two consecutive PRs spend it.

## Known limits stated in the report

- The skill bucket covers each player's whole history, including sample games, so the skill
  adjustment uses only players with 50 or more games.
- The within-pool switch is confounded by build order: players abandon losing builds.
  SOS has only 10 eligible pools after the split. It is reported, never gated.
- Pair agreement counts two-color first decks only; three-color players cannot match.

## Dissent

- **sealed-analyst on the most-playables baseline.** The analyst wanted agreement to be at
  least the best naive baseline minus 3 points, failing SOS today "because leaving a pair
  with 15 more playables is almost never right." The auditor and test-architect held that a
  baseline matching players 99.1% of the time measures pool seeding, not deck quality, and
  that a gate the current engine cannot pass would only be bypassed. The gate uses the
  outcome measure instead; the SOS shortfall (1 pool gained against 69 lost to "most
  playable spells") stays visible in the report as a flip count.
- **The splash guard is one-sided.** The analyst proposed staying within ±10 points of
  strong players. SOS now splashes 11.2 points less than players, which fails a two-sided
  guard. Splashing less is allowed because the measured cost of a splash is about 4
  win-rate points; the observed miscalibration was over-splashing.
- **The auditor on the 5.0 splash weight:** it was chosen on this sample and should be
  confirmed on a fresh split. Agreed; milestone 7 re-fits it on SOS and validates on HOB.
