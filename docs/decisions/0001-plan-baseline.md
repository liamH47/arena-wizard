# 0001: Plan baseline

Status: accepted 2026-09-28. The full plan is `docs/plan.md`; its section 18 is the
complete adjudication log. This record lists what the panel changed and who dissented, so
later decisions can cite it.

## Consulted

Six reviewers, run read-only and in parallel against the draft plan, each told to argue
only from its own domain: edge-case-hunter, test-architect, data-source steward, sealed
analyst, recommendation auditor, event-night reliability. Several ran real measurements
against the 17Lands files, Scryfall, and the 17Lands site.

## Agreed by consensus

- The 17Lands public files are the primary source; the JSON endpoints wait for permission
  (decision 0002), and a 12th-day embargo applies to every new set.
- FRA event mode runs on expert ratings, curated bombs, castability, curve, and rarity
  means, every value labelled.
- The eval gate compares against `origin/main`, never against a baseline the PR rewrites.
- Client-generated ids for pools and runs are scoped to the user and never upsert across
  users.
- The resolver reads committed card tables from package data; there is no `cards` table.
- Every window uses the Arena release date, not the paper date.

## Decisions (resolved after review)

1. **Consistency is a castability shortfall against 8 sources,** not a Karsten deficit
   (sealed analyst: the Karsten table charged every normal 9/8 deck 15 to 20 phantom
   points).
2. **Sources form a Bayesian prior chain** with `K_p = m(1-m) / residual_var` (sealed
   analyst: "first source above a floor" let a thin sample replace a better prior).
3. **Shrinkage targets the mean of the card's rarity within each source** (sealed analyst,
   edge-case-hunter: mythics accrue about a tenth of a common's games; Arena Direct
   players win more than the field).
4. **Arena Direct rows count only with a non-null rate and 500 or more games**
   (edge-case-hunter: rates are null below 500).
5. **The draft proxy comes from the PremierDraft public files,** disabled when unavailable
   or when cross-set R² is under 0.3 (edge-case-hunter: the unauthenticated endpoint
   returns at most 14 games per card).
6. **Card lists come from the 17Lands header when one exists** (edge-case-hunter: SOS
   pools contain ten Special Guests cards from a third set code).
7. **Decks are exactly 24/16 or 23/17,** hybrid castability comes from mana symbols, and
   the stats join uses the front-face name.
8. **Boot retries the database for 90 seconds, a cold database answers 503 warming, and
   downloads have timeouts and a run deadline** (event-night reliability).
9. **The coverage gate lives in CI and the verify skill,** starts at 100, and a floor guard
   makes it monotonic (test-architect).

## Review refinements

- The lead reviewer's report-tolerance and cards-table-seeding amendments were replaced
  by the test-architect's and edge-case-hunter's versions.
- The disagreement ledger, `within_pool_switch`, and `deck_score_lift` were added so the
  harness can show the engine being right when it disagrees with the crowd.

## Dissent

- **Proxy cutoff.** The sealed analyst wanted the proxy never disabled; edge-case-hunter
  showed a NaN fit passing the old check. Reconciled: disabled only when unavailable or
  under R² 0.3, weak under 0.5, weighted through `K_p` above that.
- **Keep-warm cadence.** The steward flagged that round-the-clock warmth uses 744 of 750
  free hours; reliability wanted warmth. Reconciled with a `KEEP_WARM` repository
  variable set only for event windows.
- **Where the ETL runs.** Reliability proposed running refresh on the Actions runner during
  events. Rejected as the default because the manual button and one code path are
  requirements; kept as the documented fallback.
- **Eval `paths` filter.** Reliability proposed skipping the eval for config-only changes.
  Rejected: config edits are exactly what must be measured.

## Erratum

None yet.
