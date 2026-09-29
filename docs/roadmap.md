# Roadmap

The full plan is `docs/plan.md`. This page tracks where each milestone stands and records
decisions so they are not re-litigated.

## Milestones

| # | Milestone | Status |
|---|---|---|
| 0 | Bootstrap: tooling, CI, verify skill, agents, decision log, card tables | in review |
| 1 | CLI slice with the evaluation harness | next |
| 2 | FRA event mode (expert ratings, curated bombs, embargo) | planned |
| 3 | Web app and deploy | planned |
| 4 | Refresh, keep-warm, observability | planned |
| 5 | Trends and bombs pages | planned |
| 6 | Screenshot importer | planned |
| 7 | Tuning round | planned |

## Owner actions outstanding

- Post the 17Lands permission request in `docs/decisions/0002-17lands-api-permission.md`
  and record the reply.
- Write `config/bombs/SOS.yaml` and `HOB.yaml` with the friends, from set reviews with
  citations, before seeing the automatic list.
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
- **17Lands public files only until permission is recorded** — decision 0002.
- **Committed card tables, Special Guests selected by date, no `arena_id` dependency** —
  decision 0003; `tests/golden/test_packaged_card_tables.py` enforces it.
- **Coverage gate in CI and verify, never in pytest addopts; floor only rises** —
  `arena_wizard.devtools.floor_guard` enforces it.
- **Every date window uses the Arena release date** — about half of each set's 17Lands
  games predate the paper release.
