# Arena Wizard

Sealed-deck recommendations for MTG Arena Best-of-One sealed. FastAPI and a pure Python
engine in `backend/`, React in `frontend/`.

**Read `docs/plan.md` before designing anything.** It is the approved plan; section 18 is
the panel adjudication log and Appendix A is the settled brief. Do not re-open anything
settled there or in `docs/decisions/`. `docs/roadmap.md` says which milestone is current.

## Checks

Run the `verify` skill before every PR; it is exactly what CI runs. The coverage gate is
branch coverage at `backend/coverage_floor.txt` (100), passed on the command line, never
in pytest `addopts`. The floor only rises. Never add a coverage pragma, an `exclude_also`
entry, or an `omit` entry to reach green; `floor_guard` will fail the PR.

## Code rules

- Python 3.13, uv, ruff (with Google docstrings on everything outside tests), `mypy
  --strict`. Every function has a docstring and full type hints.
- Domain objects are `@dataclass(frozen=True, slots=True)`. Pydantic only at the API
  boundary and for settings.
- Pure core, I/O at the edges: `fetch_*` does I/O, `compute_*` is pure, `main()` only
  wires them and is never unit-tested. Every fetch takes a `SourceContext` so tests inject
  `httpx.MockTransport` and a fake clock.
- Every write answers "what happens if this runs twice?" Idempotency tests must fail for a
  non-idempotent implementation: non-zero output, equal checksum on re-run, changed
  checksum when a source value changes.
- Missing data is `None`, never zero. Degrade visibly.
- Always pass `encoding="utf-8"` (and `newline="\n"` when writing). This host is Windows
  and its default encoding garbles card names like "Dáin" without raising.

## Data rules

- 17Lands public files are the only automated 17Lands source until decision 0002
  records permission. Never call the 17Lands JSON endpoints before that.
- Decision 0005 allows manual data entry from any source: a user pastes a table they
  copied by hand. The app never fetches it itself. Each paste names its source and date,
  at most one per source, set, dataset, and UTC day, and permitted automated data replaces
  it once available. Pasted data stays in the private database: never in the repo, the
  eval report, fixtures, or logs; fixtures use made-up numbers in the same layout.
- Respect `SetConfig.embargo_until` for everything except data a user pasted in.
- Attribution stays at the top of every page and the top of the README.
- Production never calls Scryfall; card tables are regenerated with
  `uv run arena-wizard sync-cards` and reviewed as a diff.
- Verify card facts against Scryfall, never from memory.

## Specialist panel

Agents live in `.claude/agents/`, plus the user-level `edge-case-hunter` and
`test-architect`. Run them read-only and in parallel, each arguing only from its own
domain; adjudicate every finding in writing (accept, reject with reason, or escalate to the
owner once). Record the result in `docs/decisions/NNNN-slug.md`. Required panels:

- Scoring model or weights: sealed-analyst, sealed-educator, recommendation-auditor,
  test-architect. Paste the eval delta into the decision.
- ETL or schema: pipeline-integrity-reviewer, test-architect, edge-case-hunter, plus
  data-source-steward when a source is involved.
- User data: pipeline-integrity-reviewer, edge-case-hunter, event-night-reliability.
- A new data source or a permission change: data-source-steward,
  pipeline-integrity-reviewer, card-data-verifier.
- Curated bombs or ratings: sealed-analyst and card-data-verifier, authored before the
  automatic list is shown, never in the same PR as a scoring change.
- Pages: event-night-ux, edge-case-hunter.

## Git

- Kebab-case branches, one PR per milestone slice, Summary and Test plan sections.
- Imperative commit subjects with the why and the evidence in the body.
- Keep the `Co-Authored-By: Claude ...` trailer. Never put Claude session URLs, email
  addresses, or the allow-list anywhere in the repo, including commits and PR bodies.
- Commit at every checkpoint; finish by opening the PR.
