# 0004: Milestone 0 panel review

Status: accepted 2026-09-28. Reviewed the milestone-0 branch before merge.

## Consulted

data-source-steward, pipeline-integrity-reviewer, card-data-verifier, and test-architect,
run read-only and in parallel. The test-architect ran mutants on a scratch copy; the
steward read Scryfall's current rate-limit page; the verifier checked the tables against
Scryfall card by card.

## Agreed by consensus

- The card tables are correct: SOS's ten Special Guests, FRA's ten, HOB without Hobbit
  Eternal, and a twelve-card sample across layouts all matched Scryfall.
- The sync is a full replace, deduplicated by Scryfall id and totally ordered, so re-runs
  are byte-identical.
- No code calls a 17Lands JSON endpoint.

## Decisions

1. **One 0.5-second spacing for every Scryfall call** (steward, BLOCKER): `/cards/named`
   is now limited to 2 per second like search, and named lookups interleaved with searches
   could have outrun it at 0.1 seconds. Supersedes the "other Scryfall 100 ms" figure in
   `docs/plan.md`.
2. **A 429 never backs off for less than 30 seconds** (steward): Scryfall's lockout is 30
   seconds whatever Retry-After says.
3. **The floor guard's git wiring moved out of `main()`** (test-architect, BLOCKER): two
   mutants that disabled the ratchet passed every test because `main()` is excluded from
   coverage. `collect_rules` and `check` now run against real temporary repositories.
4. **The guard counts every pragma spelling coverage honours, refuses shadowing config
   files, compares the whole coverage scope, fails closed on git errors, checks the CI gate
   command, and compares with the PR's own base branch** (test-architect).
5. **Throttle and back-off tests assert when requests were sent,** not how long the code
   slept (test-architect).
6. **A configured Scryfall query that matches nothing fails the sync,** instead of silently
   shrinking a table (pipeline-integrity).
7. **A removal test:** a printing Scryfall stops returning must disappear, which an upsert
   would miss (pipeline-integrity).
8. **Atomic writes compared as bytes** (pipeline-integrity): a file cut inside a multibyte
   character crashed the next sync.
9. **Name-lookup fallbacks keep only printings with the set's own codes**
   (pipeline-integrity): a later reprint must not leak into an older set's table.
10. **Image URLs are stored without Scryfall's cache-busting timestamp**
    (pipeline-integrity): a rescan would otherwise rewrite every table. The re-sync changed
    exactly one line per printing.
11. **Each Scryfall search checks its total against `total_cards`** (pipeline-integrity).
12. **Golden tests pin each header's size and assert FRA has none yet** (test-architect):
    a truncated header would otherwise make "every name resolves" trivially true.
13. **The permission request lists every poll with exact counts** (steward): at most 10
    requests a day, 6 outside an Arena Direct.
14. **Attribution:** 17Lands is credited for statistics and Scryfall for card data and
    images (steward).

## Escalated to the owner

- **License** (steward, MAJOR): the repo has none, so it is not legally open source. The
  README and the permission request no longer say it is. Choosing one is the owner's call.
- **Required status checks** (test-architect): the ratchet only blocks a merge if the
  checks are required in GitHub's branch settings.

## Recorded, not changed

- **FRA 35 Plan for All Outcomes** has no Arena tag on Scryfall (card-data-verifier). It is
  in `docs/known-broken.md` rather than added by hand, because hand-adding a card Scryfall
  says is not on Arena would be a guess.

## Dissent

None. The unused `postgres` pytest marker was removed rather than kept with an unmet
"forced in CI" claim; it returns with the first Postgres test.
