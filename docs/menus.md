# Nested and generated menus

Existing static configurations retain their behavior. This feature adds optional
`id` and `menu` fields to entries, `[provider]` for a dynamic root, and
`[entries.menu.provider]` for a dynamic submenu. A menu declares **either** static
`entries` **or** a `provider`, never both. A leaf has `command`; a submenu has
`menu`, without command/args/env/working_directory on that submenu entry itself.

```toml
[settings]
title = "Tools"
refresh_on_return = false

[[entries]]
id = "projects"
name = "Projects"
[entries.menu]
title = "Projects"
refresh_on_return = true
[entries.menu.provider]
command = "python"
args = ["tools/projects.py"]
timeout_seconds = 10

[[entries]]
name = "Static submenu"
[entries.menu]
[[entries.menu.entries]]
name = "Shell"
command = "pwsh"
args = ["-NoProfile"]
```

For a dynamic root, omit root `[[entries]]` and declare `[provider]` with the same
fields. `refresh_on_return` in `[settings]` controls root return behavior; the
field in each submenu controls that submenu. The default is **false**. It applies
when returning from a child menu, not when a launched tool returns to its menu.

## Lifecycle and keyboard contract

- Entering a menu loads its provider on first visit. Child providers do not run
  while parsing configuration, rendering parents or running `--check-config`.
- Snapshots and child menu instances use a session LRU cache of at most 128
  menu frames, including root. Active ancestors are never evicted. Back/reentry
  uses the cache unless an inactive snapshot was evicted or invalidated. `Ctrl+R` or the visible Refresh/Retry row explicitly regenerates the
  current provider. Static menus do not launch a provider on refresh.
- `Escape` clears a nonempty query first; at an empty query it returns to parent,
  or exits at root. Each submenu also has an accessible Back row. `Ctrl+C`, empty
  `Ctrl+D`, and the `0`/Exit row exit the whole launcher. Providers interrupted by
  Ctrl+C terminate with status 130. Leaf exit/restart policy remains global.
- Query, cursor and viewport survive Back. Selection is restored by a unique
  per-menu `id`, or exact entry declaration when no id is supplied. Removed
  selections fall back to the first matching row. Stable ids are recommended for
  generated entries that can reorder or rename. Restoration never launches a row.
- A successful refresh atomically replaces the snapshot, including an empty one.
  Removed or changed submenu declarations discard their child caches. Provider
  failure retains the last good snapshot, marks the view failed and exposes Retry;
  initial failure exposes Retry and Exit/Back without pretending it is empty.
- Empty menus remain navigable. An empty static root is still rejected, preserving
  existing validation; empty submenus and empty generated snapshots are valid.

## Provider contract and trust

Providers are explicitly configured trusted executables, like launch commands;
this is process supervision, not a security sandbox for malicious code. A provider
can describe more submenus/providers, but those run only when opened by the user.
Ordinary returned commands run only when explicitly selected.

The provider receives argv literally without a shell, inherits the launcher's
environment plus its configured `env`, and uses configured `working_directory`
(otherwise the original launcher cwd). Paths/environment follow existing home
expansion rules. Stdin is closed; stderr is discarded, avoiding accidental terminal
control or secret output. Explicitly invoke `cmd.exe` for Windows batch providers;
implicit `.bat`/`.cmd` provider execution is rejected.

Successful stdout must be UTF-8 JSON of this form:

```json
{"entries":[{"id":"shell","name":"Shell","command":"pwsh","args":["-NoProfile"]}]}
```

Entries use the same schema as TOML, including nested `menu` objects. Only the
`entries` value is consumed; provider output cannot change global launcher settings.
Nonzero exit, malformed JSON/UTF-8/schema, oversized output, timeout and excessive
nesting all fail without replacing the previous snapshot. Display control
characters and invalid environment keys are rejected by the shared parser.

Limits: cache 128 menu frames, JSON 64 container levels, stdout 1 MiB, at most 1,000 entries per generated menu (including nested declarations; static TOML menus retain their existing capacity), at most 16 active/static menu
levels including root; integer `timeout_seconds` is 1–300, default 10. Each process
uses an owned POSIX process group or Windows kill-on-close job. Cleanup runs after
success, failure, cancellation and timeout, including descendants holding stdout.
Windows assignment occurs immediately after spawning; trusted providers must not
try to evade or daemonize outside the cleanup boundary. No credential or persistent
access is provisioned by this feature.

## Validation status

This is the shared design contract. Runtime coverage, benchmarks, mutation evidence
and artifact verification must be recorded separately for each final feature head;
the modernization's green checks do not establish this feature's parity or release.


## Terminal protocol limit

Legacy pseudoterminals can interpret raw Escape followed immediately by a digit
as a single Alt-modified key sequence. An exploratory `ESC+0` byte-burst test did
not exit either runtime under Windows ConPTY; the query was retained instead.
This byte stream cannot reliably encode both a physical Alt key and two separate
keypresses. Tests therefore observe the cleared prompt between Escape and numeric
selection, and separately verify queued-character handling at the decoder boundary.
No universal fast-Escape behavior is claimed across terminal protocols. Real parent
query restoration, Back, numeric selection, refresh and interrupted flows remain
covered through actual terminals; physical keyboards/screen readers need separate
validation.


The Windows boundary probe confirmed a narrower cause for Python: in an owned
ConPTY, `msvcrt.getwch()` received `[27]` for bare Escape, `[48]` for a raw
`ESC+0` burst, and `[27,91,50,55,117,48]` for `CSI 27u` followed by `0`.
The terminal discarded the burst's Escape before application input decoding;
the application cannot reconstruct that missing event. The Rust burst also failed,
but its native event boundary was not instrumented, so the same cause is an inference.
Use separate Escape then digit events, or the explicit Back/Exit rows; the tested
query-clear flow waits for its redraw before sending the next key. Kitty event
encoding survives the Python console boundary; end-to-end support still depends
on the terminal's negotiated keyboard protocol. See `menu-protocol-limit.json`.


Windows protocol difference: Python decodes an explicit `CSI 27u` Escape followed
by a queued digit (verified in the installed wheel). Rust uses Crossterm native
Windows console events and does not negotiate Kitty input there; injecting that
sequence produced literal `[27u0` query text. Its test verifies that no command
runs and that Ctrl+U followed by numeric Exit recovers cleanly. On Unix the same
test exercises Crossterm's escape-sequence decoder. Separate Escape events, Ctrl+U,
Back/Exit rows and ordinary keyboard navigation are the portable contract.
