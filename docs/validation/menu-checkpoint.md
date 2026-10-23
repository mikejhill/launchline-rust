# Menu implementation coordination checkpoint

This is unfinished feature work, not a release-readiness claim. Publishing approval
for Rust remains pending; no GitHub environment/publisher identity has been created.

Implemented in both runtimes: recursive menu/provider declarations; lazy generated
snapshots; Back/refresh/retry intents; query/identity restoration; atomic last-good
refresh; process-group/job cleanup; JSON/UTF-8/size/deadline boundaries; bounded
128-frame inactive LRU caching; shared JSON/TOML fixture contract.

Completed validation checkpoints (before the latest small refinements):
- Python full Windows gate: 339 passed, 1 skipped; 94.59% branch-inclusive coverage.
- Python full Linux/WSL gate: 340 passed, 2 skipped; 92.23% coverage.
- Rust: strict Clippy passes; 85 unit tests and 6 existing Windows integration tests
  passed. Latest targeted menus integration suite: 8 passed.
- Both runtimes passed 14 ordinary Windows terminal scenarios. An exploratory raw
  ESC+0 byte burst failed in both ConPTY runtimes (documented separately); the test
  now models distinct key events by waiting for an observable cleared prompt. The
  complete updated suite still needs rerunning.
- Python latest selected menu/provider suite: 32 passed; cache/controller suite:
  30 passed.
- Seeded menu mutation: Python 9 killed. Rust first sweep: 8 killed, 1 invalid due
  to type inference after replacing the only HashSet insertion. The mutant has
  been corrected to retain type inference and must be rerun; it is not a test kill.
- Real seven-sample warm Back+Enter benchmarks, same provider interpreter 3.12.13:
  Python cache/refresh medians 22.2027/167.1772 ms; Rust 9.5067/161.0139 ms. Root
  provider invocations 1 versus 8; child provider 1 in both policies. These are
  preliminary host-specific measurements, not startup/general performance claims.

Important remaining code correction: the initial shared parser's 1000-entry limit
also affects static TOML. Preserve legacy large static menus by applying this limit
only to generated snapshots (including their nested declarations), with regression
tests in both implementations before merge. No legacy limit should be introduced.

Remaining validation/work: corrected Rust mutation sweep; updated legacy mutation
anchors/campaigns; full final Windows/Linux gates; Rust hosted Unix validation;
packaged/installed feature artifacts; performance rerun for final heads; CI wiring
for new campaigns; changelog/README review; feature PRs and exact-head hosted CI;
then feature releases only after both modernization releases complete.

No owned validation command remains running at this checkpoint. Separate feature
worktrees preserve existing user checkouts. Python modernization v0.3.0 is already
published and verified; Rust modernization PR1 remains unmerged pending the exact
main-only pypi environment approval. PyPI account mike12489 is public maintainer of
launchline; its private pending publisher registrations are inaccessible here.
