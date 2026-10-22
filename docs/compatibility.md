# Shared compatibility contract

Baseline: Python `904ace1`, Rust `109a68b`. Modernized together on MHILL-LAPTOP.
This matrix records the supported contract and evidence, not universal parity.

| Surface | Baseline gap | Implemented contract | Evidence |
| --- | --- | --- | --- |
| Configuration | Python coerced types; Rust discarded invalid args/env | Strict strings, booleans, string arrays/maps; reject controls/NUL and illegal environment keys | Both unit suites; 15 differential real CLI cases in validation/parity.json |
| Resolution | Same CLI > LAUNCHLINE_CONFIG > default precedence | Explicit missing paths fail; exclusive default creation; missing/file cwd warns and inherits | Config tests; actual CLI and child processes |
| Search | Equivalent greedy subsequence scoring | Identical score bonuses and stable ties; monotonic search avoids tail scans | Shared 405-case ASCII/Unicode score corpus; paired benchmarks |
| Numeric selection | Python non-ASCII digit crash | ASCII digits only, existing prefix and shortcut semantics | Keyboard and mutation tests |
| Editing | Rust UTF-8 byte cursor could panic | Character boundary editing; Emacs keys, arrows, Escape clear/quit | Rust unit UX; Python decoder/UI tests; real PTY flows |
| CLI | Rust accepted arbitrary log levels; Python config-path tracebacks | Same five uppercase levels; friendly failures; --check-config validates without opening TUI; non-TTY guard | Actual subprocess and wheel smoke tests |
| Launch | Rust cloned entire environment; POSIX status representation differed | Literal argv, inherited env plus overlay, cwd, child exit code; interrupted child 130; POSIX signal 128+signal | Actual child probe; Python Linux SIGTERM test; Rust Unix test added but not run locally |
| Terminal | Windows inherited ignore flag; Unix queued input loss | Enable own Ctrl+C; restore terminal; preserve queued UTF-8 input; stop on EOF/read error | Windows PTY both; Linux PTY Python; faithful OS-boundary simulations |
| Accessibility | Color-only emphasis | NO_COLOR suppresses SGR with visible selection marker; keyboard navigation and resize | PTY output/assertions both; no screen-reader certification |
| Distribution | Rust archives lacked icons; wrapper used wrong version metadata | Bundle icons; wrapper uses launchline-rust version, verifies SHA256SUMS before atomic cache install | Built native archive and isolated installed wheel; tamper/interruption tests |
| Release | Python #1 pending; Rust broad permissions | Preserve #1 pin/generated notes; owner + rerun owner gates, exact SHA, read-only build, isolated publishers, provenance | actionlint, zizmor auditor, mocked actual publisher body, no-remote semantic-release fixture |

Unknown TOML keys remain ignored for compatibility. Shell expansion is not supported.
Portable home expansion is `~`/`~/...`; Python also recognizes OS-supported named-user
forms. Diagnostic wording, argparse/clap help formatting, platform process lookup,
batch execution, Unicode database versions, terminal escape timing and font widths
can differ. Cursor accounting uses code points rather than grapheme/display columns;
wide/combining glyph layout is not claimed equivalent. Python needs CPython >=3.12;
Rust is native, with a separate Python >=3.9 download wrapper. Binary and interpreter
startup/memory costs therefore differ. No maximum-performance claim is made.

Executed: Windows x64 both; Ubuntu/WSL Python. macOS, ARM targets, Rust Linux/macOS,
physical terminal/screen-reader combinations and hosted CI have not been executed
here. See [validation report](validation/report.md) and [release readiness](releasing.md).
