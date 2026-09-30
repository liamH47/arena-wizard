# Database schema

Postgres in production (Neon), SQLite in tests. Migrations live in
`backend/src/arena_wizard/db/migrations/versions/` and change together with
`db/models.py` and this page. CI fails when the models and migrations differ (`alembic
check`). Every timestamp is stored and returned in UTC.

Revision `0002` (milestone 3, decisions 0007 and 0008; card adjustments, decision 0011).

## Tables

| Table | Key | Purpose |
|---|---|---|
| `users` | `user_id` (Google subject id, or `local` with auth off) | One row per friend who signed in: email, name, picture, and when they were first and last seen. |
| `pools` | `id` (the client's UUID) | A pasted Arena export, owned by one user. `body_hash` recognises a replayed create; `pool_hash` is the resolved pool, part of every build's inputs key. |
| `builds` | `id`; unique (`pool_id`, `inputs_key`) | One run of the builder, reused while nothing it depends on has changed. Holds the Data block (`data_lines`), the mode (`event` until milestone 4), and a refusal when no deck could be ranked. |
| `decks` | (`build_id`, `deck_index`) | One ranked deck: colors, splash, total, and the JSON the deck page renders. |
| `deck_runs` | `id` (the client's UUID) | A recorded result against a deck: wins, losses, event name, notes, and `extra` JSON for later fields. |
| `paste_deletions` | `id` | Who deleted which paste key, and when; never the pasted data. Kept apart from `pastes` so a deletion does not block that day's key (decision 0008). |
| `pastes` | `id`; unique (`set_code`, `dataset`, `event_type`, `source_id`, `import_day`) | Hand-pasted grades or 17Lands card data (decisions 0005 and 0007), shared by the group. `event_type` is `grades` for grade lists, so the key never holds a NULL. `rows` is one JSON column, so a same-day replace updates one row. It records who pasted, when, and when it was replaced. The server never fetches `url`. |
| `card_adjustments` | `id`; unique (`set_code`, `name`) | The group's current adjustment to one card (decision 0011): `bomb` is `add`, `remove`, or NULL; `q_delta` is a value change in points (±10). Records who changed it last and when. |
| `card_adjustment_log` | `id` | Every set or clear of an adjustment, append-only, with who and when. |

## What a delete does

| Foreign key | On delete |
|---|---|
| `pools.user_id` → `users` | restrict |
| `builds.pool_id` → `pools` | cascade |
| `decks.build_id` → `builds` | cascade |
| `deck_runs.(build_id, deck_index)` → `decks` | restrict |
| `deck_runs.user_id` → `users` | restrict |
| `pastes.pasted_by` → `users` | restrict |
| `paste_deletions.deleted_by` → `users` | restrict |
| `card_adjustments.updated_by` → `users` | restrict |
| `card_adjustment_log.changed_by` → `users` | restrict |

Indexes: `pools.user_id`, `deck_runs.user_id`, and `deck_runs (build_id, deck_index)`, so
a user's lists and a pool delete's restrict check never scan a table.

Deleting a pool takes its builds and decks with it. A recorded run protects its deck, so
deleting a pool someone played is refused with 409, never a silent loss.

## Every write, run twice

| Write | Natural key | On a second run |
|---|---|---|
| sign-in | `users.user_id` | Updates profile and `last_seen_at` |
| create pool | `pools.id` | Same body as the create: returns the pool (200), even after edits. Different body or another user: 409, unchanged. |
| edit pool | `pools.id` | Same text: no change. The create's body hash is kept. |
| build | (`pool_id`, `inputs_key`) | Returns the existing build. The key covers the pool, every paste as stored, adjustments to the pool's cards (not notes or who), the package's files, and whether the embargo has passed. |
| record run | `deck_runs.id` | Same body: returns the run (200), never undoing a later PATCH. Different body or another user: 409. |
| edit run | `deck_runs.id` | Only fields that differ change |
| paste | the pastes unique key | Identical: no change. Changed: one row updated in place, `replaced_at` set, but only if the row still holds what the check saw (otherwise 409). |
| set adjustment | (`set_code`, `name`) | Same values: no change and no log row. Changed: the row is updated and one log row added; the last writer wins. |
| clear adjustment | (`set_code`, `name`) | Deletes the row and logs it; a second clear is a no-op (204). |
| delete paste | the pastes unique key | Only whoever last pasted it, or the owner. Logged in `paste_deletions`. A second delete is 404. |

## Downgrades

A downgrade that would delete rows is refused unless
`ARENA_WIZARD_ALLOW_DESTRUCTIVE_DOWNGRADE=1` is set, and it cannot run as offline SQL.
Every migration must leave the previous release working, so a rolled-back build can boot:
the entrypoint serves a database that is ahead of the build without migrating.

## Deferred to milestone 4

The 17Lands statistics tables (`source_files`, `card_stats_daily`, `color_pair_daily`)
and `refresh_runs` arrive with the refresh job. Until then, web builds use event mode from
the group's pastes.
