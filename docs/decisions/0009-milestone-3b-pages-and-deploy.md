# 0009: Pages and deploy (milestone 3b)

Status: accepted 2026-09-29. The pages, the Docker image, Render, the end-to-end tests,
keep-warm, and the runbooks, on top of the 3a backend (decision 0008).

## Consulted

The following reviewed the slice read-only:

- **event-night-ux:** a Pixel 7 between Arena Direct matches.
- **edge-case-hunter:** probes included the real API client under Node with a mock fetch,
  and browser decoding of Excel exports.

The first CI run built the image, confirmed it refuses to boot on Render without
production settings, and ran the Playwright specs against the container: 5 passed, and
the phone-only spec was skipped on desktop.

## Decisions

### The deck page is for clicking a list into Arena

1. **The deck page leads with the list** (event-night-ux M1). Each deck shows its label
   and one-line trade-off, then the Arena list, then Record result:
   - The list is grouped rows (creatures, other spells, lands, with counts and a 40-card
     total). It is large enough to tap and can be struck through as cards are clicked in.
   - The reasons, breakdown, card values, and images sit in one closed "Why this deck"
     section.
   - Decks after the first start collapsed.
   - The Data block is first on the page, closed behind a one-line status, and open when
     the build was refused. That keeps decision 0007's "opens every build".
2. **Record result edits one run** (event-night-ux and edge-case-hunter converged). After
   the first save, the form updates that run with absolute wins and losses. "Record
   another event" starts a new one. The old form created a second run for the same event
   on every tap, double-counting the results the eval will use. The deck page drops the
   notes and event-name inputs, which opened the keyboard for fields nobody edits.
3. **The review page leads with what needs action:**
   - the count;
   - unrecognised lines, with one-tap fixes (apply a suggestion, or drop the line);
   - Build.

   The card list and the export text are behind closed sections. Build saves unsaved
   edits before building, because it had silently built from the old text.
4. **A deck page with no build offers Build,** and stale decks are dimmed with their lists
   hidden. The stale message names the app too, since a deploy changes every build's key.

### Cold starts

5. **A failed identity check is not "signed out".** The app shows "The server is still
   waking up" with Try again, and never sends a friend to sign-in over a 503. Retries run
   for 90 s. Load failures offer Try again.
6. **The waking banner is sticky and appears only when a request is actually retrying.**
   It had stayed on forever after one kind of retry (reproduced); that is fixed.
7. **Keep-warm never blocks a deploy** (edge-case-hunter). A scheduled run's check lands
   on main's newest commit, and Render deploys only when every check passes. So a
   failing ping during an outage would have stopped the hotfix from deploying. The ping
   now retries, never fails the job, and writes its result to the run summary. Alerting
   comes from an external uptime monitor, an owner step in the deploy runbook.

### Pasting

8. **Uploads decode like the server:**
   - UTF-16 with a byte-order mark;
   - UTF-8;
   - Windows-1252 as a fallback, for Excel's exports.

   The garbled-names refusal no longer gives CLI advice on the web.
9. **Replace resets after every paste,** so the "much smaller than today's paste" guard
   applies again.
10. **Deleting a paste asks first,** naming it, its size, and who pasted it. The Delete
    button shows only for the person who pasted it, or the owner; `/api/me` now says
    whether you are the owner.

## Rejected

- **Deleting the card images** (event-night-ux, optional): they stay, inside "Why this
  deck", where they cost nothing on the way to the list.

## Owner actions (docs/runbooks/deploy.md)

Neon, the Google consent screen and OAuth client, the Render Blueprint and its secrets,
the GitHub variables `APP_URL` and `KEEP_WARM`, an external uptime monitor on `/healthz`,
and "E2E (Docker image)" as a required check.
