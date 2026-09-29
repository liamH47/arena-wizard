---
name: verify
description: "Run the full local check suite, exactly what CI runs: backend lint, format, types, tests with the coverage gate, the coverage ratchet, the evaluation gate, and the frontend typecheck, lint, and build. Use before opening a PR, after any change, or when asked to verify, check, or confirm everything passes."
---

# Full local verification

Exactly the commands `.github/workflows/ci.yml` runs, in the same order, so green here
means a green PR. Run from the repository root. When CI gains a step, add it here in the
same change.

## 1. Backend

```
cd backend
uv sync --frozen
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run pytest --cov --cov-fail-under="$(cat coverage_floor.txt)"
```

The coverage gate is on the command line, not in `pyproject.toml`, so running a single
test file while iterating never fails on coverage. Run the whole command before a PR.

Then the Postgres tests and the migration check. CI runs Postgres as a service; locally,
point `AW_TEST_PG_URL` at any disposable Postgres (they skip when it is unset):

```
AW_TEST_PG_URL=postgresql+psycopg://user:pass@localhost:5432/db uv run pytest -m postgres --no-cov
ARENA_WIZARD_DATABASE_URL=sqlite:///./ci-migrations.db uv run alembic upgrade head
ARENA_WIZARD_DATABASE_URL=sqlite:///./ci-migrations.db uv run alembic check
uv run alembic upgrade head --sql > /dev/null
```

## 2. Coverage ratchet

```
cd backend
git fetch origin main
uv run python -m arena_wizard.devtools.floor_guard
```

Fails if `coverage_floor.txt` went down, if coverage-exclusion pragmas, `exclude_also`
entries, or `omit` entries grew relative to `origin/main`, or if CI stopped running the
coverage or evaluation gate. Raising the floor is fine and
is a one-line change that cites the measured number.

## 3. Evaluation gate

```
cd backend
git fetch origin main
uv run arena-wizard eval run --check --base origin/main
```

Regenerates the evaluation report from the committed samples and aggregates, fails if the
committed `eval/report.json` or `eval/report.md` differs, then applies the gate from
decision 0006 against `origin/main`'s report. After a scoring or engine change, run it
without `--check` to rewrite the report, and commit the report with the change.

## 4. Frontend

```
cd frontend
npm ci
npm run typecheck
npm run lint
npm run build
```

## Notes

- Node is pinned in `frontend/.nvmrc`; a different major version is a plausible source of
  "works locally, fails in CI".
- On Windows, `make` is not installed; run the commands directly. Everything here works in
  Git Bash.
- If a check fails, fix the cause. Never lower the floor, add a pragma, or widen an
  exclusion to get to green; the floor guard will refuse it anyway.
