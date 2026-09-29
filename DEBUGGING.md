# Debugging the deployed app

Start here. One command explains most outages:

```
curl -s $APP_URL/readyz
```

It never opens a database session, so it answers even while Neon sleeps.

| Field | What it tells you |
|---|---|
| `commit` | The deployed commit. Is the fix you expect live? |
| `boot_at` | When this instance started. A time a minute ago means it just woke from sleep or restarted. |
| `last_db_error` | The last database error any request hit since boot, or `null`. |

When `last_db_error` is set, its `sqlstate` class says what kind of failure it is:

| SQLSTATE class | Meaning | What friends see | Fix |
|---|---|---|---|
| `08…` or none | Can't connect: Neon waking, or a network blip | "Waking the database" banner, then it works | Wait. It retries for a minute. |
| `28…` | Credentials rejected | "Database error" | The Neon password changed: update `ARENA_WIZARD_DATABASE_URL` in Render. |
| `3D…` | Database does not exist | "Database error" | Wrong database name in the URL. |
| `53…` | Out of resources: disk, connections, or the compute quota | "Database error" | Check Neon's usage page: CU-hours and storage. |

Then check the database itself:

```
curl -s "$APP_URL/readyz?deep=1"
```

This does one `SELECT 1`. The answer is `"database":"ok"`, a 503 while Neon wakes, or a 500
with `database_error`.

## Where to look next

- **Render → Logs.** Boot prints `database not ready (attempt N, …)` while it waits (up to
  90 s), then `migrating from … to …`, then uvicorn's startup. Each database error a request
  hits logs one `database unavailable: <class> sqlstate=<code> …` line. Pasted data never
  appears in logs.
- **Neon console.** It shows whether the compute is active or idle, and the month's
  CU-hours and storage against the free limits (100 CU-hours, 0.5 GB).
- **The uptime monitor** (docs/runbooks/deploy.md) emails the owner when `/healthz` stops
  answering. GitHub → Actions → Keep warm never fails (a failed check would block Render's
  deploys); a ping that did not answer within 90 s shows as a warning in that run's summary.

## Common failures

- **A blank tab for 30 to 60 seconds.** The free instance was asleep. During events, set
  the repository variable `KEEP_WARM=true` (`docs/runbooks/deploy.md`).
- **Boot refused, naming variables.** The settings fail closed. On Render,
  `ARENA_WIZARD_ENV=prod` requires Google auth, `OWNER_EMAIL`, and a Postgres URL. The log
  names each missing one.
- **"database error" everywhere.** The table above. Most often, the Neon quota is used up
  (class 53) or the password was reset (class 28).
- **Sign-in returns to the login page with `error=`:**

  | Reason | Meaning |
  |---|---|
  | `denied` | The address is not in `ALLOWED_EMAILS`. |
  | `state` | The sign-in took over 10 minutes, or two tabs raced; start again. |
  | `google` | The code exchange failed; check the client secret. |
  | `cancelled` | The friend cancelled at Google. |
  | `warming` | The database was waking; try again. |
- **Google shows its own error page.** Either the address is not a test user on the OAuth
  consent screen, or the redirect URI does not exactly match
  `<PUBLIC_URL>/auth/google/callback`.
- **Deploys stopped.** A commit with zero checks is never deployed
  (`docs/runbooks/hotfix.md`).
- **Keep-warm stopped running.** GitHub disables scheduled workflows after 60 days without
  repository activity. Re-enable it under Actions → Keep warm.
