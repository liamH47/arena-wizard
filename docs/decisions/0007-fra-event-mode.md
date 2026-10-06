# 0007: FRA event mode — values without the public Sealed file

Status: accepted 2026-09-29, except the item escalated to the owner below. Amends milestone
2 of `docs/plan.md`.

## Why the plan changed

The data-source steward's research (2026-09-29) found that no third-party expert grades can
be committed:

- **Terms.** Every source that grades FRA, SOS, or HOB card by card forbids scraping,
  reserves all rights, or restricts use:
  - TCGplayer (LSV and Martin Jůza);
  - MTG Arena Zone;
  - Limited Level-Ups, hosted as 17Lands tier lists;
  - Draftsim.
- **Copyright.** Courts have held expert numeric valuations copyrightable. Committing a
  reviewer's grade list would republish it under this repo's MIT license.
- **Format.** Every source grades for draft; none grades for sealed.
- **Dropped sources.**
  - Draftsim: its terms forbid use that "competes with the Service".
  - Lords of Limited: it has no lists for these sets.
  - Limited Resources: audio only, and robots.txt disallows it.

Third-party grades therefore enter only through decision 0005's importer: by hand, private,
labelled, and never committed.

A first proposal was then reviewed by seven specialists. Their findings, adjudicated below,
replaced about half of it.

## Consulted

The following reviewed read-only and in parallel on 2026-09-29:

- data-source-steward (research, then a follow-up);
- sealed-analyst (with a regret simulation on 300 sample pools per set, using the public
  Premier Draft files);
- recommendation-auditor;
- sealed-educator;
- pipeline-integrity-reviewer;
- edge-case-hunter (probes against the real card tables and snapshots);
- test-architect.

## Decisions

### Values: a Bayesian chain, not a fallback list

1. **Sources stack; they do not replace each other** (analyst BLOCKER, auditor; plan line
   134). In event mode, a card's value comes from Gaussian updates in points (q), layer by
   layer:
   - the prior (grades, or the rarity average when no grades are pasted);
   - Premier Draft win rates as a proxy;
   - Arena Direct or Sealed win rates.

   Each layer's weight is its inverse variance, and each value records how much weight
   each layer carries.

   The analyst's simulation, in q-points of regret (about 12 q per win-rate point):

   | Setup | SOS | HOB |
   |---|---|---|
   | Arena Direct shrunk to grades (the first proposal) | 34 | 21 |
   | Premier Draft alone | 21 | 14 |
   | Arena Direct on top of Premier Draft | 18 | 15 |

   So an early Arena Direct paste made decks worse under the first proposal.
2. **Event mode applies only when the public Sealed file is absent or embargoed.** With the
   file, values are computed exactly as in milestone 1. The public report and its decision
   digest do not move, which this PR's gate check proves.
3. **Grade layer** (analyst, auditor, edge-case-hunter):
   - Each grade source becomes z-scores over the set's spells.
   - The per-card mean across sources is re-standardized to unit spread.
   - Value: `q = center + slope × z + removal_bonus × removal + rare_bonus × (rare or mythic)`.
   - Defaults, uncalibrated: center −0.5, slope 2.0, σ 3.0, removal bonus +1.0, rare-or-mythic
     bonus +1.0.
   - The analyst conceded slope 2.0 and σ 3.0: slopes from 1.5 to 3.0 gave regret within 1
     q, and K = 275 sits on a flat optimum.
   - The bonuses are the analyst's measured draft-to-sealed gaps: sealed rewards removal and
     rares beyond their draft value. Two-drops and top end showed no gap, so the shape
     weights are not raised.
4. **Premier Draft layer**:
   - `q = 0.75 × 100 × (GIH WR − paste mean)`, plus the same two bonuses.
   - Structural σ 2.0, plus the sampling error.
   - The analyst measured card-value correlations of 0.75 (SOS) and 0.83 (HOB), and sealed
     values 0.69 to 0.83 times the draft values, from the public CC BY Premier Draft files.
   - A committed, reproducible fit is deferred (below).
   - A cached public Premier Draft file fills this layer ahead of any Premier Draft paste,
     under the embargo (steward N3, decision 0005 rule 4).
5. **Arena Direct and Sealed-paste layer:** `q = 100 × (GIH WR − paste mean)`, with
   binomial error. Arena Direct is preferred over a Sealed paste.
6. **Improvement when drawn is optional** (test-architect and edge-case-hunter BLOCKER):
   - Without never-seen columns, the improvement term is missing (None), never computed
     from zeros.
   - `format_means` no longer returns None for a paste without them.
   - The term comes from the top data layer that has never-seen games.
7. **Missing stays missing:** a count with a blank rate is treated as unseen, never as 0 wins
   (edge-case-hunter).
8. **Ungraded cards, when grades exist,** get `center + slope × (mean z of graded cards of
   their rarity)`. This puts them on the same scale as graded cards (auditor and
   edge-case-hunter).
9. **Grade sources are refused unless:**
   - they grade at least 80% of the set's spells;
   - their grades are not all equal;
   - they use one scale, letters or numbers (0 to 10), never mixed.

   `SB` ranks below `F`. `TBD` and blanks are left out.
10. **Bombs in event mode come from the curated list only.** A missing list prints "not
    assessed", never "0 bombs" (educator).

### What the player reads (educator's text, adapted)

11. **Every value carries a basis:**
    - win rates;
    - draft proxy;
    - grades;
    - a rarity-average grade;
    - rarity average.

    Explanations branch on the basis, never on whether a snapshot exists. A graded card
    lists each reviewer's own grade.
12. **A Data block opens every build.** It lists each source as used, stored-not-used, or
    missing, with the day copied and per-card game counts (never a summed total). It ends
    with the exact commands to add what is missing, the embargo note, and attribution
    naming only the sources used.
13. **Grades-only rankings never say "Ahead by X (standard error Y)".** They say "ranked
    above X on draft grades and deck shape" and call a toss-up within grade uncertainty,
    which is printed as assumed, not measured. Event mode lists at most five decks
    (edge-case-hunter measured up to 20 with σ 3.0).

### The paste store

14. **The key** (pipeline-integrity, test-architect, steward, edge-case-hunter converged) is
    `pastes/{SET}/{dataset}/{event_type or "grades"}/{source_id}/{import_day}.json`:
    - **Import day:** the UTC day, from an injected timezone-aware clock.
    - **`--copied-on`:** a label only. It may not be after the import day. Card data may
      not be dated before the set's Arena release.
    - **`--published-on`:** optional for grades, recording when the list was written.
15. **Sources are ids from a committed registry** (steward N1): the 17Lands card-data
    export, each TCGplayer and Limited Level-Ups reviewer, MTG Arena Zone, and `own-<name>`
    for the group's own lists. The registry refuses Draftsim, chunk.science, and
    limitedgrades.com (17Lands-derived). This settles slug collisions, spelling drift, and
    path traversal.
16. **`--event-type` is required for card data, with no default** (four reviewers). It
    must be Arena Direct Sealed, Sealed, or Premier Draft, and it is cross-checked: draft
    pick columns filled on a sealed paste are refused. *Amended 2026-10-06:* a real FRA
    Sealed export puts small counts in # Seen and # Picked, so only the average pick
    positions (ALSA, ATA) mark draft data.
17. **Everything is checked before writing, so a refused paste changes nothing:**
    - at least 90% of rows match the set's cards;
    - rows cover at least 80% of the set's spells;
    - card data has in-hand games;
    - no conflicting duplicate names;
    - no identical paste stored under another source.

    Names are matched after folding case, apostrophes, and dashes, and by back faces too.
    Replacing a paste with one under half its size needs `--replace`.
18. **Stored:**
    - parsed rows;
    - columns;
    - a parser version;
    - a sha256 of the decoded text;
    - the label, the link (never fetched), and dates.

    No raw text is stored, and no reviewer comments. Files are deterministic JSON, and an
    identical re-paste rewrites nothing. A paste from an older parser version is refused
    at read time with "paste it again".
19. **Automated data wins (0005 rule 4), enforced twice:**
    - at write time, a paste is refused when a public file the engine uses is cached for
      that set and event type and is past its embargo;
    - at read time, the source selection skips covered pastes.
20. **Privacy by construction** (test-architect BLOCKER, steward):
    - Store functions require a data directory; only `main` resolves it.
    - A data directory inside any git work tree is refused.
    - An autouse test fixture redirects every data, cache, and home path and blocks
      sockets.
    - A subprocess test proves the paste modules import no HTTP code.
    - The public eval takes no grades argument. A test fills a paste store and checks that
      the report is byte-identical.
21. **Input:**
    - `--file` or stdin, read as bytes and decoded through `decode_text`, capped at 5 MB;
    - a spreadsheet file, or anything that is not a text table, is refused as such;
    - an unquoted two-column list splits on the last comma, since 67 FRA names contain one.

    `pastes --set` lists what is stored and used, and `pastes --delete` retracts a paste.

### Gate and report

22. **Unchanged engine and config must give an unchanged decision digest** (test-architect).
    When the engine version and scoring config are unchanged from the base, a changed
    decision digest fails the gate. So "no scoring change without a config change" is
    proven on every PR.
23. **The public report gains a data-free baseline per set** (auditor, test-architect,
    steward):
    - agreement at 1 and 3, and paired flips against the engine;
    - the engine with no win rates and no grades: rarity, castability, curve, no bombs;
    - rarity averages taken leave-one-set-out, from the other set's card-weighted means.

    It is named a baseline, not a floor. It is kept under each set's metrics as
    `data_free_*`, outside the digest and the absolute gates.
24. **The floor guard also fails** if any tracked file carries the marker written into
    every private store file.

## Rejected

- **A `--clipboard` flag** (steward): it needs a clipboard dependency. `--file` with the
  17Lands CSV download is the documented Windows route, because PowerShell 5.1 pipes
  non-ASCII as `?`.
- **Storing raw paste text** (pipeline-integrity M6): the steward preferred not storing it,
  and it would keep Limited Level-Ups comment prose. A parser fix means pasting again.
- **Automatic bombs from pasted data** (educator M6, analyst m7): event mode uses the
  curated list only. That avoids showing automatic names before the group writes its list,
  and draft bombs overlapped sealed ones only 2 in 8 on HOB.

- **Dropping the improvement term for a card with in-hand games but no never-seen games**
  (the per-card half of test-architect B1). With some never-seen data in the source, such a
  card's never-seen rate shrinks to its rarity's, and the term is the ordinary Bayesian
  estimate, not a made-up number. Only a source with no never-seen games at all now leaves
  the term out. Keeping it also keeps the public report byte-identical.
- **Editing Appendix A of the plan** (steward R1): the appendix is the owner's settled
  brief and stays verbatim. The plan sections that implement it carry the amendment.
- **Refusing a paste because a set's Sealed file is pinned for the eval** (steward N3,
  second half): only locally cached public files count as covered. A Sealed paste of SOS
  or HOB is refused anyway for having no games.

## Deferred

- **The deck-color paste:** the pair term's weight is 0 (decision 0006).
- **A committed, reproducible Premier Draft proxy fit:** today's numbers are the analyst's
  scratch measurement; `known-broken.md` records this.
- **Correlated reviewer error in the gap uncertainty** (auditor M2). The text says "grade
  error only".
- **An isotonic grade map for top grades** (analyst m6).
- **The Bayesian chain in data mode:** milestone 7.

## Escalated to the owner

**A private expert-mode evaluation** (auditor, steward N4). Fitting the grade slope and σ,
and measuring grades-only decks against real outcomes, means running the eval harness on
pasted SOS and HOB grades. Decision 0005 says "the eval harness never sees pasted data".

The steward rules this needs an owner amendment:

- private runs only;
- output only to the private directory;
- never in CI;
- only two fitted numbers may be committed.

The auditor adds that it is only honest with grades written before each set's release,
which the owner would have to attest with `--published-on`.

Until the owner decides, the grade numbers stay at their uncalibrated defaults and are
printed as assumed.

## Owner actions

- **Sign in to 17Lands and paste FRA Premier Draft card data daily from 2026-10-01:** Table
  view, filters cleared, Ever in Hand and Not Seen ticked. The analyst measured this as
  worth about one win-rate point per deck over grades alone.
- **Paste FRA grades:** Limited Level-Ups via "Download CSV", and TCGplayer by hand.
- **Write `config/bombs/FRA.yaml` with the friends**, `provenance: own`, before pasting any
  FRA win rates.
- **Ask Limited Level-Ups** for their pre-release SOS and HOB lists and permission to commit
  them.
- **Decide the escalation above.**

## Dissent

- **The steward on reading from stdin at all:** stdin makes `curl | arena-wizard paste`
  easy. Kept, because the person still runs the command. The help text quotes 0005 limit 1,
  and nothing in the repo invokes `paste`.
- **The auditor on uncalibrated defaults:** the auditor would print no toss-up labels at
  all until calibration. Kept, labelled "assumed", because erring toward "toss-up" is the
  humble direction.
