# Known broken or incomplete — do not paper over

Each entry names the gap, where it lives, and what would close it. Remove an entry in the
same change that fixes it.

- **FRA's card table is not checked against a 17Lands header.** No FRA file exists yet.
  Closes when `arena-wizard sync-cards --set FRA` runs after 17Lands publishes one and the
  golden test starts covering FRA's header.
- **FRA 35 Plan for All Outcomes is missing from FRA's card table.** On 2026-09-28
  Scryfall listed it for paper and MTGO but not Arena, so the `game:arena` query skips it.
  If it is in Arena packs, its export line will not resolve. Closes when Scryfall tags it or
  the FRA header proves it absent; `sync-cards` exits 1 on it once a header exists.
- **FRA's non-basic pool range is a guess** (78 to 86 in `config/sets/FRA.yaml`). Closes
  when a FRA Sealed file can be measured.
- **The FastAPI test client emits a Starlette deprecation warning** asking for `httpx2`.
  Harmless today; revisit when upgrading Starlette.
