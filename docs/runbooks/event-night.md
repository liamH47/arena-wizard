# Event night: building FRA decks before the public file exists

For the Reality Fracture Arena Direct, 2026-10-02 to 10-11. There is no 17Lands public
Sealed file for weeks, and 17Lands asks tools not to show FRA data before 2026-10-10.
Decks are built from data you paste in by hand, kept private on your machine (decisions
0005 and 0007).

Once the web app is deployed (milestone 3), paste on its Pastes page instead. It is the
group's store of record, and every friend's build reads it. The CLI's store below stays on
your machine (decision 0008).

## What to paste, and when

Paste in this order of value. The sealed-analyst measured the draft data as worth about one
win-rate point per deck over grades alone.

1. **17Lands Premier Draft card data, daily from 2026-10-01.**
   1. Sign in to 17Lands and open the FRA card data page.
   2. Choose **Premier Draft**.
   3. Switch to the **Table** view and clear the Color and Rarity filters.
   4. Tick **Ever in Hand** and **Not Seen**.
   5. Export with **Download as CSV**, then run:

   ```
   uv run arena-wizard paste --set FRA --dataset card-data --event-type PremierDraft --source 17lands-card-data --file card-ratings-2026-10-01.csv
   ```
2. **17Lands Arena Direct Sealed card data**, once the event has games. Same page, format
   Arena Direct Sealed, and `--event-type ArenaDirect_Sealed`. It stacks on top of the
   draft data and never replaces it.
3. **Grades, one reviewer per paste.**
   - For Limited Level-Ups, use their tier list's "Download CSV" and paste with
     `--source llu-marc` or `--source llu-alex`.
   - For TCGplayer, type `Name,Grade` lines into a file by hand and paste with
     `--source tcgplayer-lsv` or `--source tcgplayer-juza`.
   - Add `--published-on` with the review's date.

   A grade list must cover at least 80% of FRA's spells.
4. **The group's bomb list:** write `backend/src/arena_wizard/config/bombs/FRA.yaml` before
   pasting any FRA win rates, in your own words, with `provenance: own`.

The bomb list's shape:

```yaml
provenance: own
curated:
  - name: Exact Card Name
    action: add            # add, remove, or annotate
    source: group vote     # who in the group decided
    note: in our own words, no reviewer quotes
```

On Windows, save the export to a file and pass `--file`. PowerShell 5.1 turns accented
names into `?` when piping.

Pasting again on the same UTC day replaces that day's paste. An identical paste changes
nothing. To see or retract what is stored:

```
uv run arena-wizard pastes --set FRA
uv run arena-wizard pastes --set FRA --delete card-data/PremierDraft/17lands-card-data/2026-10-01
```

## Building

```
uv run arena-wizard build --set FRA --pool pool.txt
```

The Data block at the top says what each value rests on and what is missing, with the
command to add it.

On grades alone, most close decks read as toss-ups. The grade error is assumed, not
measured, and the text says so. Draft data narrows that.

## Where the data lives

The data lives in `~/.local/share/arena-wizard`, or in `ARENA_WIZARD_DATA_DIR`. The app
refuses a data directory inside any git repository. Do not put it in a cloud-synced
folder, and share copies only with the allow-listed friends.
