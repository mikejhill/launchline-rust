# Validation evidence - 2026-10-22

Host: MHILL-LAPTOP, Windows x64; CPython 3.12.13, Rust 1.99.1. Linux checks used
Ubuntu WSL CPython 3.12.3 and a separate venv/cache/coverage file. Work proceeded
Python contract/optimization first, then Rust and packaging/release equivalents.

## Executed checks

- Python Windows: 292 passed, 1 POSIX-only skip; branch-inclusive coverage 95.49%.
- Python Ubuntu WSL: 291 passed, 2 Windows-only skips; 94.14% branch-inclusive
  coverage, including entry point and Unix reader. Ruff and strict ty pass.
- Rust Windows: 83 unit + 6 integration tests pass; rustfmt and all-target strict
  Clippy pass. The additional Unix-only SIGTERM integration is unexecuted locally.
- Rust wrapper: 37 passed, 2 POSIX-only skips; strict ty and Ruff pass. Real PTY
  tests exercise both launchers, including inherited ignored Ctrl+C, menu exit,
  interrupted child restart, search/Escape/numeric selection, NO_COLOR and resize.
- Python built wheel installed in isolation: five actual console-entry-point cases.
  Rust release archive extracted and executed; wrapper wheel installed with the
  actual locally-built archive through a mocked HTTP boundary, isolated cache and
  offline execution. Native child probe checks argv/env/cwd/exit without shell mocks.
- Shared 405-score corpus and 15 differential CLI config cases pass. Evidence JSON
  is retained; the Rust repository also contains the shared differential script.
- Targeted mutation campaigns: 12/12 killed in each implementation, zero survivors,
  invalid mutants or timeouts. Source restored in finally. This is a transparent
  seeded campaign, not exhaustive mutation coverage or a universal mutation score.
- Offline release tests exercise actual publisher shell under gh interception.
  Checksum-verified CLI/plugins dry fixture resolves 0.1.0 with generated notes,
  exit 0 and no tags. Production GitHub/PyPI provider execution remains untested.
- Workflow static audits: actionlint 1.7.12 and zizmor 1.31.1 auditor persona.

## Measured search performance

Reproduce with `uv run python scripts/benchmark_compare.py` (Rust: add
`--project pypi`). Baseline sources come from the recorded Git commits; both versions
use identical warmed workloads, seven samples of 1,000 calls. Rust compiles both
standalone harnesses with rustc -O. Compilation is excluded. Raw samples are in
search-comparison.json. These measurements describe scorer calls only; they do
not establish application startup, UI latency or cross-runtime superiority.

| Workload | Python baseline/current ns median | Rust baseline/current ns median |
| --- | ---: | ---: |
| exact | 958.7 / 167.1 | 235 / 106 |
| prefix + 4K tail | 106687.4 / 953.9 | 3072 / 202 |
| sparse | 4737.6 / 362.3 | 278 / 70 |
| miss + 4K tail | 162117.8 / 1096.4 | 3433 / 340 |
| Unicode | 526.2 / 410.1 | 176 / 116 |

No wall-clock threshold is used as a flaky correctness assertion. Allocation/runtime
models and Unicode library versions differ; absolute numbers are host-specific.

## Limits and rollout risks

No hosted CI was dispatched and macOS/ARM runtime validation remains pending.
Rust Linux signal/TTY code is compiled/tested only when its CI OS runs; Windows
tests cannot establish Unix parity. Screen readers, physical keyboard layouts,
wide/combining glyph column widths and all escape protocols are not exhaustively
validated. No analogous Rust skill was found; Cargo/rustfmt/Clippy and the shared
test standard were used. See ../compatibility.md for bounded parity claims.

Production remains blocked on the environment/trusted-publisher checks described
in ../releasing.md. No main commits, merges, tags, releases, deployments or settings
changes were performed. The main checkouts were preserved.

One automatic approval review rejected adding a Ruff exclusion for generated
src/launchline/_version.py because it would weaken tool configuration; that action
did not execute. The generated version template was formatted instead, preserving
the lint rules. No denied operation was bypassed; no tool approval remains pending.
