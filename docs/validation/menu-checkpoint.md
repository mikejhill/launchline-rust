# Nested and dynamic menu validation

This feature is implemented locally and awaits exact-head hosted CI and release
ordering. Python modernization v0.3.0 is already published; Rust modernization
remains unmerged pending the main-only `pypi` environment approval. No settings or
publisher trust registrations were changed. Python feature release follows its completed modernization; Rust feature release follows Rust modernization.

| Contract | Evidence in both implementations |
| --- | --- |
| Existing static configs, no new entry-count cap | 1,001-entry real TOML regression; old CLI/scoring corpus retained |
| Recursive static/provider menus, no provider execution during config check | Shared 31-case declaration/provider corpus and real CLI checks |
| Lazy generation, cached reentry, explicit retry/refresh | State-boundary tests plus actual provider subprocesses and terminal flows |
| Configurable parent refresh, default false | Actual root provider calls 1 cached versus 8 refreshed over seven Back/Enter cycles |
| Stable selection, restored parent query, changed-child invalidation | State tests and real terminal Back/query assertions |
| Empty/error snapshots, retained last-good data | Real malformed/non-UTF8/nonzero/empty/timeout providers and recovery flows |
| Resource bounds | Generated 1,000-entry limit recursively; 1 MiB output; 64 JSON containers; 16 menu levels; 128-frame inactive LRU |
| Interruption and cleanup | Windows job/process probes, Linux Python process groups; interrupted provider exits 130; leaf return preserves current submenu |
| Packaged runtime | Both installed wheels run the terminal suite; Rust wheel forwards to the actual verified local native archive |

Local gates on final production sources (October 23, MHILL-LAPTOP):
- Python Windows: 347 passed, 2 skipped, 94.12% branch-inclusive coverage; strict
  Ruff and ty pass. Linux/WSL: 347 passed, 2 skipped, 92.32% coverage.
- Python installed wheel: all 16 real terminal scenarios pass. `package_smoke.py`
  now enforces those scenarios in CI and release gates, in an isolated wheel environment.
- Rust strict Clippy and rustfmt pass; 85 native unit tests, 6 baseline integration
  tests and 9 menu integration tests pass. Wrapper suite: 47 passed, 2 skipped after the wrapper signal correction.
- Rust installed wrapper/archive: all 16 terminal scenarios pass after correcting
  wrapper SIGINT ownership. `wrapper_smoke.py` now enforces these installed tests.
  The same fix is applied to the pending modernization branch, whose installed suite
  has 6 scenarios and passes. The download response is local/verified; runtime is offline.
- Both seeded campaigns: 9/9 menu mutants killed plus 12/12 existing mutants killed.
  Corrected Rust unique-id mutant compiles and is killed. Earlier invalid mutation
  is not counted as a kill. These 21 chosen faults are not an exhaustive mutation score.
- actionlint 1.7.12 and zizmor 1.31.1 auditor pass for both workflow sets.
- Both exact pinned semantic-release/plugin fixtures pass with no remote, no tokens,
  no tags and extracted version 0.1.0; actual publishing remains a separate operation.

Reproduce with `uv run poe check`, `uv run poe mutation`, `uv run poe mutation-menus`,
`uv build`, `uv run python scripts/package_smoke.py` for Python. For Rust use
`cargo fmt --check`, `cargo clippy --locked --all-targets -- -D warnings`,
`cargo test --locked`, `uv run --locked --project pypi pytest pypi/tests`,
`uv run --locked --project pypi python scripts/mutate_menus.py rust`, and
`scripts/mutation_check.py rust`. Build native target/archive and wrapper wheel
before `scripts/wrapper_smoke.py`; see CI's exact TARGET/ARTIFACT values.

Seven-sample warm Back+Enter medians, same CPython 3.12.13 provider interpreter:
Python cache/refresh 21.5749/171.2463 ms; Rust 9.9860/154.9770 ms. Raw samples and
provider counts are in `menu-performance.json`; `scripts/benchmark_menus.py`
reproduces them. These host-specific warm navigation measurements exclude startup,
have no timing gate, and support no universal performance or maximum-speed claim.

Windows raw ESC+0 loses Escape before Python msvcrt receives it; the standalone
boundary probe observed [48] instead of [27,48]. Bare Escape survives. Explicit
Kitty Escape works in Python's installed wheel; Rust's native Windows console
path treats the injected protocol as query text. Its test verifies harmless query
input and Ctrl+U then numeric Exit recovery. Separate Escape events and Back/Exit
rows are the portable contract. See `menu-protocol-limit.json` and `../menus.md`.

Not claimed: exhaustive keyboard/Alt protocol parity, physical screen-reader
certification, grapheme/display-width equivalence, macOS/ARM physical runtime
coverage, or Rust Unix feature execution before hosted CI. WSL runs only Python;
prior modernization hosted CI is not feature-head proof. Published feature artifacts
cannot be verified until the ordered releases actually happen.

Exact pending security approval: create GitHub environment `pypi` in
`mikejhill/launchline-rust`, main-only custom branch policy, no reviewers. No mutation
was attempted. PyPI pending trusted publisher cannot be inspected through this
connection. If absent, separate trust-creation approval is needed for PyPI project
`launchline-rust`, GitHub owner `mikejhill`, repository `launchline-rust`, workflow
`release.yml`, environment `pypi`, under maintainer account `mike12489`. Project JSON
404 does not prove a private pending publisher is absent. Existing Python environment
reviewer gate remains unchanged; release approval applies to individual runs.


## Hosted follow-up

First Python feature run 39998061639 passed 7/9 jobs; macOS 3.13/3.14 exposed a
Ctrl+R timing race between first render and per-key raw mode. The corrected Python
UI owns Unix raw input for its entire interactive session and restores settings
before providers/tools; an actual PTY regression verifies restoration after an
exception. Full Windows/Linux gates and 16 scenarios through the exact fresh wheel
pass after this fix. All 21 Python seeded mutants were rerun and killed.

Rust modernization run 39997787065 passed all three OS jobs at 81fb411, including
the installed-wrapper interruption fix. Feature run 39998072302 passed Linux and
macOS and was superseded during Windows mutations by the patched dependency lock.
Final-head hosted results are tracked on the PRs, not inferred from those old runs.

All 58 reported Python dependency findings apply to the old lock; Pillow 13.0.0
and pytest 9.1.1 are outside the reported ranges. Rust's latent pytest 8.4.2 lock
fallback was also removed without raising its packaged Python >=3.9 requirement.
See dependency-triage.md and per-advisory dependency-alerts.json for exact exposure.
