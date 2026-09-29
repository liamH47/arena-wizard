# Known broken or incomplete — do not paper over

Each entry names the gap, where it lives, and what would close it. Remove an entry in the
same change that fixes it.

- **FRA's card table is not checked against a 17Lands header.** No FRA file exists yet.
  Closes when `arena-wizard sync-cards --set FRA` runs after 17Lands publishes one and the
  golden test starts covering FRA's header.
- **FRA 35 Plan for All Outcomes is missing from FRA's card table.** On 2026-09-28
  Scryfall listed it for paper and MTGO but not Arena, so the `game:arena` query skips it.
  If it is in Arena packs, its export line will not resolve. Closes when Scryfall tags it or
  the FRA header proves it absent; `sync-cards` exits 1 on it once a header exists.
- **FRA's non-basic pool range is a guess** (78 to 86 in `config/sets/FRA.yaml`). Closes
  when a FRA Sealed file can be measured.
- **Curated bomb lists for SOS and HOB do not exist yet,** so bomb F1 is not measured and
  the automatic list is uncalibrated. Closes when the owner writes `config/bombs/SOS.yaml`
  and `HOB.yaml` without viewing the automatic names (decision 0006).
- **The splash bound in `engine/builder.py` is admissible only while `splash_card`
  outweighs `creature_balance + two_drop + three_drop`** (5.0 against 1.6 today). It leaves
  those terms out. A tuning round that lowers the splash charge below them must add them to
  the bound or drop the pruning.
- **Shrinkage priors were estimated on the full files,** including post-split games. The
  report says so. Closes when they are re-estimated on pre-split games (decision 0006).
- **Three-color decks are never built.** The builder makes two-color decks with at most one
  splash; 5% of SOS and 10% of HOB players ran three colors. Also, near-mono pools return
  the same spells under different second colors at rank 3 or lower.
- **The within-pool switch cannot be measured on SOS** (10 eligible pools after the split)
  and is confounded by build order on HOB. Reported, never gated.
- **The Premier Draft proxy numbers are a scratch measurement.** Slope 0.75, error 2.0,
  and the removal and rarity bonuses came from the sealed-analyst's scripts on the public
  SOS and HOB files (decision 0007), not from committed code. Closes when an
  `eval proxy-fit` command reproduces them from pinned public files.
- **Grade-to-value numbers are uncalibrated defaults** (slope 2.0, error 3.0). Builds say
  so. Closes when the owner decides the escalation in decision 0007 and a private
  expert-mode evaluation fits them.
- **Correlated reviewer error is not in the gap uncertainty.** Reviewer bias shared across
  a color or archetype makes grades-only gaps less certain than printed. The text says
  "grade error only".
- **Rarity is per printing.** A card whose printings differ in rarity (Gardenize: rare as
  #103, mythic as #406) gets a slightly different rarity adjustment depending on which
  printing was opened.
- **The FastAPI test client emits a Starlette deprecation warning** asking for `httpx2`.
  Harmless today; revisit when upgrading Starlette.
