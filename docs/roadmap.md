# Roadmap

The full plan is `docs/plan.md`. This page tracks where each milestone stands and records
decisions so they are not re-litigated.

## Milestones

| # | Milestone | Status |
|---|---|---|
| 0 | Bootstrap: tooling, CI, verify skill, agents, decision log, card tables | done |
| 1 | CLI slice with the evaluation harness | in review |
| 2 | FRA event mode (expert ratings, curated bombs, embargo, manual data entry) | planned |
| 3 | Web app and deploy | planned |
| 4 | Refresh, keep-warm, observability | planned |
| 5 | Trends and bombs pages | planned |
| 6 | Screenshot importer | planned |
| 7 | Tuning round | planned |

## Owner actions outstanding

- Post the 17Lands permission request in `docs/decisions/0002-17lands-api-permission.md`
  and record the reply.
- Write `config/bombs/SOS.yaml` and `HOB.yaml` with the friends, from set reviews with
  citations, before seeing the automatic list. The report withholds the automatic names
  until then; do not run `build` on a sample pool or read the bomb code's output first.
- Check whether the Arena phone client can export a Limited-event deck.

## Decisions already made

Recorded so they are not re-litigated:

- **Bo1 Sealed only in v1, with format as a first-class field** — Traditional sealed can be
  added without a rewrite.
- **Arena export text is the primary input; a classical screenshot importer is in v1
  scope** — desktop export is confirmed, phone export is not.
- **No LLM in v1** — parsing, building, scoring, and explanations are deterministic.
- **Zero added hosting cost** — Render free, Neon free, GitHub Actions schedules.
- **Public repo from the start; no session URLs, emails, or the allow-list in it.**
- **17Lands public files are the only automated source until permission is recorded** —
  decision 0002.
- **Users may paste data in by hand from any source: labelled, private, one paste per
  source, set, dataset, and UTC day, replaced by permitted automated data** — decision 0005.
- **Committed card tables, Special Guests selected by date, no `arena_id` dependency** —
  decision 0003; `tests/golden/test_packaged_card_tables.py` enforces it.
- **Coverage gate in CI and verify, never in pytest addopts; floor only rises** —
  `arena_wizard.devtools.floor_guard` enforces it, including pragma spellings, shadowing
  config files, and the CI command itself (decision 0004).
- **Every Scryfall call shares one 0.5-second spacing, and a 429 never backs off for less
  than 30 seconds** — decision 0004; `tests/unit/test_http.py` enforces it.
- **Every date window uses the Arena release date** — about half of each set's 17Lands
  games predate the paper release.
- **The merge gate checks outcomes and ratchets imitation** — decision 0006;
  `tests/unit/test_gate.py` enforces the basis-point boundaries. Every set needs legal decks
  for every pool, a deck score that predicts wins better than raw win rate in hand,
  agreement no more than 300 bp below that baseline, no more than 1,000 bp more splashing
  than players, and 0.5 to 1.5 automatic bombs per pool. Against the base, the data pins
  may not change and paired flips may not lose a net 300 bp.
- **The base report is read fail-closed from the target branch, and accepted exceptions
  expire with the base's decision digest** — decision 0006; `tests/unit/test_base.py`.
- **A splash costs 5.0 score points and needs three real land sources; the pair term's
  weight is 0** — decision 0006, measured on the eval set.
- **`build` refuses to rank decks without statistics, and treats embargoed statistics as
  absent** — decision 0006; `tests/unit/test_commands.py`.
- **Automatic bomb names stay out of the report until curated lists exist** — decision
  0006.
