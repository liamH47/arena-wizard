# 0008: The web backend — auth, database, API, and boot (milestone 3a)

Status: accepted 2026-09-29. Milestone 3 ships as two slices. 3a is the backend: settings,
auth, database, migrations, API, and boot. 3b is the frontend, Dockerfile, Render and
Neon, keep-warm, and runbooks.

## Consulted

The following reviewed the 3a code read-only and in parallel, with probes against a
temporary SQLite app and timing on this machine:

- pipeline-integrity-reviewer;
- edge-case-hunter;
- event-night-reliability;
- data-source-steward.

test-architect reviews the tests before the PR.

## Scope decisions

1. **Web builds are event mode until milestone 4.** The server has no disk and no
   17Lands statistics in its database yet, so every web build uses the group's pastes
   (decision 0007). SOS and HOB data mode on the web arrives with the refresh job.
2. **The database is the group's paste store; the CLI's file store stays local.** Web
   pastes are shared by the allow-listed friends and record who pasted. The CLI keeps its
   private file store for offline use. The event runbook names the web app as the store of
   record once it is deployed.
3. **Pastes keep their rows in one JSON column,** not the plan's `paste_rows` table
   (pipeline-integrity endorsed this). The engine reads whole pastes, a same-day replace is
   one update, and "identical, nothing changed" is one comparison.

## Decisions from the review

### Privacy (decision 0005)

4. **Auth fails closed on Render** (steward BLOCKER, edge-case-hunter). Render sets
   `RENDER=true`, and the settings refuse to boot there unless `ARENA_WIZARD_ENV=prod`.
   Prod requires Google auth and a Postgres URL. Otherwise a deploy that forgot one
   variable would have served every pasted number to the internet.
5. **Bound parameters never appear in errors or logs** (steward, reliability,
   edge-case-hunter converged). Every engine sets `hide_parameters`, and a failed paste
   insert had been shown to carry card rows into the log text.
6. **Rule 4 holds on a server with no cache** (steward). Each set records its published
   public files (`public_files`: SOS and HOB have Sealed and Premier Draft). Past the
   embargo, pastes of the same data are refused and ignored on the web and in the CLI.
7. **Only whoever last pasted, or the owner, may delete a paste** (steward ruling).
   `OWNER_EMAIL` is required with Google auth. Deletions are logged in `paste_deletions`
   without the data, so the day's key is not blocked.
8. **The local database lives in the private data directory,** and the floor guard fails
   on any database file git would commit (steward).

### Correct builds after any change

9. **A build's key covers everything that can change it** (pipeline-integrity,
   reliability, edge-case-hunter converged). That is:
   - the pool;
   - each paste as stored, with rows, parser version, and dates;
   - a digest of every file in the installed package: code, set and scoring configs,
     card tables, curated lists, and the source registry;
   - whether the embargo has passed.

   The hand-bumped engine version had never been bumped, so an event-night hotfix would
   have kept serving pre-fix decks. A rebuild costs about 0.1 s.
10. **"Latest build" is the build for the pool as it stands now** (pipeline-integrity,
    edge-case-hunter converged; the hunter reproduced edit, revert, then reload showing the
    wrong decks). When no build matches, the newest is returned marked `current: false`.
11. **Pastes stored by an older parser are left out and named,** as the CLI's file store
    already does (pipeline-integrity, reliability).
12. **A paste is compare-and-set:** it is saved only if the key still holds what the check
    saw. Otherwise it is a 409 that changes nothing (pipeline-integrity).
13. **A pool keeps its create hash, as runs do.** An edit compares text, so a replayed
    create still matches and re-sending the same text changes nothing.

### Event night

14. **Database errors are visible:**
    - Each warming answer logs one line with the error class and SQLSTATE, never
      parameters.
    - `/readyz` shows the last database error and the deployed commit, without opening a
      session.
    - Credential, missing-database, and resource errors (SQLSTATE classes 28, 3D, 53)
      answer "database error" instead of an endless "warming" (reliability).
15. **A rollback can boot.** A database ahead of the build's newest migration is served
    without migrating. Every migration must leave the previous release working (nullable
    or defaulted additions, no drops or renames in one release), which migration 0001's
    docstring states (reliability).
16. **Migrations take a transaction-scoped advisory lock on Postgres,** so two instances
    booting at once migrate in turn. It is transaction-scoped because a session lock does
    not survive Neon's pooler (reliability). The migration engine is disposed afterwards.
17. **Every sign-in failure returns to the login page with a reason:** cancelled, state,
    Google, denied, or warming. It is never raw JSON on a full-page navigation, and a
    network error reaching Google is an exchange error (edge-case-hunter, reliability).
18. **Hardening** (edge-case-hunter):
    - Request bodies over 6 MB get 413 before anything buffers them.
    - Text with NUL or unpaired surrogates is refused.
    - Integer ids are bounded.
    - Paste links must be http or https.
    - A non-ASCII cookie reads as signed out, not a 500.
    - A `%` in the database URL survives Alembic.
    - HEAD works on health checks and pages.
    - Bare `/api` is a JSON 404, and `/index.html` is never cached.
    - A write that still conflicts after its retry is a 409, never a 500.
19. **Prepared statements are off** (reliability). They are harmless through Neon's pooler
    either way, and off removes the risk.

### From the test review (test-architect)

The review ran 28 mutants against a 100%-covered suite. 13 survived, and two probes
reproduced real bugs.

20. **The paste compare-and-set is enforced by the database** (BLOCKER). A conditional
    `UPDATE ... WHERE text_sha256 = <what the check saw>`, with a 409 when no row matches.
    The Python-side check had let a losing save overwrite the winner's rows while leaving
    `pasted_by` as the winner. That misattributes data and breaks the delete rule.
21. **The expected hash comes from the stored row, stale or not.** A paste an older parser
    stored had been permanently un-replaceable: every re-paste was a 409, the exact
    event-night case after a parser fix.
22. **Oversized bodies get 413 through real routes.** FastAPI had been turning the cut-off
    stream into a 400. The middleware now answers 413 itself.
23. **The package digest is a tested function of a directory tree,** with length-prefixed
    entries so no two trees hash alike.
24. **A value the database refuses is a 422,** and paste links refuse NUL characters like
    every other text field.
25. **The API and repository tests also run against CI's Postgres,** through one
    database-URL seam, so the production dialect exercises the whole write surface. The
    Postgres-only tests prove the advisory lock blocks a second migrator, that production
    errors hide parameters, and that timestamps come back in UTC under another session
    time zone.

## Rejected

- **No client-side pooling (`NullPool`)** (steward m3): Neon documents that idle
  connections do not keep its compute awake (cited by edge-case-hunter). Pooling with
  pre-ping and a five-minute recycle saves a TLS handshake per request.
- **A `pastes --push` bridge from the CLI store to the database** (pipeline-integrity M4):
  the web app is the store of record once deployed, which is simpler than keeping two
  stores in sync. The web Data block and paste messages now point at the Pastes page.
- **Tombstones for deleted pools and runs** (pipeline-integrity m8): a replayed create
  after a delete re-creates the row. That is accepted and documented. The frontend
  treats a 404 on a retried delete as success.

## Deferred

- **Stripping pasted numbers from stored builds when a paste is deleted** (steward m2).
  Deleting a paste already makes every later build and "latest" answer ignore it.
  Retroactively editing old builds needs a build-to-paste link.
- **Loading only the pastes a build uses** (steward m4). Egress is about 1.3 GB a month at
  100 paste-reading requests a day, under the 5 GB limit.
- **The keep-warm workflow, the Dockerfile's bytecode and unbuffered output, header
  attribution computed from each build's sources, the paste form's "by hand" notice, the
  frontend's warming banner, and the Google consent-screen owner steps:** slice 3b.

## Budget

No new external calls. The steward's arithmetic for October:

| Service | Estimate | Free limit |
|---|---|---|
| Render | about 53 instance hours | 750 |
| Neon compute | about 11 to 14 CU-hours at 0.25 CU | 100 |
| Neon storage | under 70 MB | 0.5 GB |
| Neon egress | about 1.3 GB | 5 GB |

Pinning Neon to 0.25 CU is load-bearing: at 2 CU the same use exceeds 100 CU-hours.
