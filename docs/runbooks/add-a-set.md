# Adding a set

Adding a set is configuration plus a reviewed data commit, never code.

1. **Find the set's Scryfall codes.** List sets released the same day
   (`https://api.scryfall.com/sets`) and note the main set, any bonus sheet, and the
   Special Guests date. Ask card-data-verifier to confirm which of them ship in Arena play
   boosters.
2. **Write `backend/src/arena_wizard/config/sets/{CODE}.yaml`.** Copy an existing file. Use
   the Arena release date (the first game in the 17Lands file once one exists, otherwise
   the MTG Arena announcement), not the paper date. Leave `nonbasic_pool_range` wide until
   it can be measured.
3. **Generate the card table.**

   ```
   cd backend
   uv run arena-wizard sync-cards --set CODE
   ```

   It exits 1 and names every card the 17Lands header lists that did not resolve. Fix the
   Scryfall queries until it exits 0.
4. **Run verify.** The golden tests check the new table: every header name resolves, every
   printing carries one of the set's export codes, and the file matches what the
   serializer writes.
5. **Open a PR** with the config, the table, and a note of what was checked. After 17Lands
   publishes the set's Sealed file, re-run step 3 so the table is checked against the
   header, and measure the pool-size range.
