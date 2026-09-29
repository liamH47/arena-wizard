# Hotfix during an event

Realistic time from a bug report to a fix live: about 25 minutes. That is roughly 10 to
write and test the fix, 5 for CI, and 5 to 10 for Render to build and swap. A rollback
takes about 5.

## Roll back first if the last deploy broke something

In Render's dashboard, open the service, go to **Events**, find the last good deploy, and
choose **Rollback**. The rolled-back build starts as normal.

If the bad deploy included a migration, the database is now ahead of the rolled-back
build. The entrypoint detects this and serves without migrating, logging `database at
revision X, ahead of this build's head Y` (decision 0008). This works only because every
migration keeps the previous release working: nullable or defaulted additions, and no drops
or renames in the same release. Never merge a migration that breaks that rule during an
event.

## Ship a fix

1. Branch from `main`, fix, and run the verify skill locally.
2. Open a PR. Merge it when CI is green.
3. Render deploys the merge commit once every check on it passes
   (`autoDeployTrigger: checksPass`).
4. Confirm the new commit is live: `curl -s $APP_URL/readyz` shows its `commit`.

Cached builds never hide a fix. A build's key includes a digest of every file in the
deployed package, so the next Build after the deploy recomputes (decision 0008).

## When a commit produced zero checks

Render treats zero checks as "do not deploy", silently. This happens if CI did not
trigger. Re-run CI on `main`'s head:

```
gh workflow run ci.yml --ref main
```

If it is urgent and the commit is known good, use **Manual Deploy → Deploy latest commit**
in Render.

## A scoring or config change

Any edit to `config/scoring/*.yaml`, the builder, or the eval code changes the public
report. Regenerate and commit it with the change, or CI's evaluation gate fails:

```
cd backend
uv run arena-wizard eval run
```

That takes about four minutes. A change to `config/sets/*.yaml` or the card tables needs
the same.
