# Known broken or incomplete — do not paper over

Each entry names the gap, where it lives, and what would close it. Remove an entry in the
same change that fixes it.

- **FRA's card table is not checked against a 17Lands header.** No FRA file exists yet.
  Closes when `arena-wizard sync-cards --set FRA` runs after 17Lands publishes one and the
  golden test starts covering FRA's header.
- **FRA's non-basic pool range is a guess** (78 to 86 in `config/sets/FRA.yaml`). Closes
  when a FRA Sealed file can be measured.
- **The FastAPI test client emits a Starlette deprecation warning** asking for `httpx2`.
  Harmless today; revisit when upgrading Starlette.
