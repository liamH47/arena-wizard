# Arena Wizard

Card statistics and color-pair data from
[17Lands](https://www.17lands.com/public_datasets) public game files, licensed
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) and aggregated per day by Arena
Wizard. Card data and images from [Scryfall](https://scryfall.com). Arena
Wizard is not affiliated with or endorsed by 17Lands or Scryfall.

Arena Wizard recommends decks for Magic: The Gathering Arena Best-of-One sealed. Paste your
pool's Arena export and it returns the strongest 40-card builds, each with a scored
breakdown that names the source and sample size behind every number and says what you
trade away by choosing one deck over another. It is calibrated against thousands of real
sealed pools, the decks their owners built, and how those decks did.

## Status

Under construction. `docs/roadmap.md` tracks milestones; `docs/plan.md` is the full design.

## Private instance, public code

The code is public and the app is free. The deployed instance is a private one for a group
of friends, behind Google sign-in. No license has been chosen yet, so the code is not yet
open source in the legal sense.

## Development

Requires [uv](https://docs.astral.sh/uv/) and Node 24.

```
cd backend
uv sync
uv run pytest
```

```
cd frontend
npm ci
npm run dev
```

The full check suite, identical to CI, is in `.claude/skills/verify/SKILL.md`.

Regenerating a set's card table from Scryfall (developer-run, never in production):

```
cd backend
uv run arena-wizard sync-cards --set SOS
```

## Fan Content notice

Arena Wizard is unofficial Fan Content permitted under the
[Fan Content Policy](https://company.wizards.com/en/legal/fancontentpolicy). Not
approved/endorsed by Wizards. Portions of the materials used are property of Wizards of the
Coast. ©Wizards of the Coast LLC.
