# LaunchLine (Rust)

[![CI](https://github.com/mikejhill/launchline-rust/actions/workflows/ci.yml/badge.svg)](https://github.com/mikejhill/launchline-rust/actions/workflows/ci.yml)
[![Release](https://github.com/mikejhill/launchline-rust/actions/workflows/release.yml/badge.svg)](https://github.com/mikejhill/launchline-rust/actions/workflows/release.yml)

> **Rust rewrite of [LaunchLine](https://github.com/mikejhill/launchline)** —
> shared configuration and keyboard contract. See the
> [Python version](https://github.com/mikejhill/launchline) for the original.

A lightweight terminal launcher for interactive CLI tools. Define your frequently
used commands in a TOML config file, then pick them from a fuzzy-searchable menu
instead of remembering flags and paths.

![LaunchLine demo](docs/images/demo.gif)

## Why

Switching between CLI tools — AI assistants, shells, dev utilities — means
remembering commands, flags, working directories, and environment variables.
LaunchLine puts them all in one menu so you press a number or type a few letters
instead.

## Features

- **Fuzzy search** — type any substring to narrow the list instantly
- **Numbered shortcuts** — press a digit to launch directly
- **Per-entry environment and working directory** — set once, forget forever
- **Auto-restart or exit** — configurable behavior after a tool exits
- **Near-instant startup** — native binary, ~14ms cold start
- **Single binary** — no runtime dependencies, nothing extra to install
- **Auto-generated starter config** — creates `~/.config/launchline/config.toml`
  on first run if no config exists
- **Cross-platform** — pre-built binaries for Windows, macOS, and Linux (x64 & ARM64)

|           Fuzzy search            |         Arrow-key navigation          |
| :-------------------------------: | :-----------------------------------: |
| ![Search](docs/images/search.png) | ![Navigate](docs/images/navigate.png) |

## Installation

### Install the native Rust application

Rust releases are published only to crates.io as crate `launchline`:

```sh
cargo install launchline --locked
```

Cargo builds the native executable. The CI-validated build toolchain is Rust 1.99.1;
the installed application does not require Python. Source version tags identify
published crates. GitHub Releases provide release notes, the exact Cargo archive,
checksums and signed provenance; standalone native binary bundles are not produced.

### Build a checkout

```sh
git clone https://github.com/mikejhill/launchline-rust.git
cd launchline-rust
cargo build --release --locked
# Binary: target/release/launchline (launchline.exe on Windows)
```

The separate [Python implementation](https://github.com/mikejhill/launchline) is
installed from PyPI with `pip install launchline`. The former Rust Python-download
wrapper is retained as historical source/test tooling and is not published.
See [release process and registry setup](docs/releasing.md).

## Quick Start

1. Run `launchline`. If no config exists, a starter config is created at
   `~/.config/launchline/config.toml`.
2. Edit the config to add your tools.
3. Run `launchline` again.

Override the config path:

```sh
# CLI flag (highest priority)
launchline --config ~/my-config.toml

# Environment variable
export LAUNCHLINE_CONFIG=~/my-config.toml
launchline
```

Resolution order: `--config` flag > `LAUNCHLINE_CONFIG` env var > default path.

## Configuration Reference

Config file format is [TOML](https://toml.io). The file has an optional
`[settings]` table and one or more `[[entries]]` tables.

### `[settings]`

| Key               | Type   | Default        | Description                                                       |
| ----------------- | ------ | -------------- | ----------------------------------------------------------------- |
| `title`           | string | `"LaunchLine"` | Window/tab title shown while the launcher is active               |
| `on_exit`         | string | `"restart"`    | Behavior after a launched tool exits: `restart` or `exit`         |
| `show_exit`       | bool   | `true`         | Show the **Exit** entry (shortcut `0`) in the menu                |
| `clear_on_launch` | bool   | `true`         | Clear terminal before launching an entry                          |
| `ghost_text`      | bool   | `true`         | Show the highlighted entry name as an autocomplete hint on prompt |
| `numeric_trigger` | bool   | `true`         | Pressing a digit immediately launches the matching entry          |

### `[[entries]]`

Each `[[entries]]` table defines one launchable tool:

| Key                 | Type            | Required | Default | Description                                                    |
| ------------------- | --------------- | -------- | ------- | -------------------------------------------------------------- |
| `name`              | string          | yes      | —       | Display name shown in the menu                                 |
| `command`           | string          | yes      | —       | Executable to run                                              |
| `args`              | list of strings | no       | `[]`    | Arguments passed to the command                                |
| `description`       | string          | no       | `""`    | Short description shown next to the name                       |
| `working_directory` | string          | no       | —       | Working directory for the subprocess                           |
| `env`               | table           | no       | `{}`    | Extra environment variables (`KEY = "value"`)                  |

### Validation Rules

- At least one `[[entries]]` table is required.
- Every entry must have both `name` and `command`.
- `on_exit` must be `"restart"` or `"exit"`.
- `args` must be a list (not a bare string).
- `env` must be a TOML table (not a string or list).
- If `working_directory` does not exist at load time, it is silently reset to
  `None` (a warning is logged).

### Example Config

```toml
[settings]
title = "My Tools"
on_exit = "restart"
show_exit = true
clear_on_launch = true
ghost_text = true
numeric_trigger = true

[[entries]]
name = "GitHub Copilot CLI"
command = "copilot"

[[entries]]
name = "Claude Code"
command = "claude"
description = "Anthropic coding agent"
working_directory = "~/projects"

[[entries]]
name = "PowerShell"
command = "pwsh"
args = ["-NoProfile"]
env = { TERM = "xterm-256color" }
```

## Usage

| Key           | Action                                    |
| ------------- | ----------------------------------------- |
| `1`–`9`       | Launch entry by number                    |
| `0`           | Exit (when `show_exit` is enabled)        |
| Type any text | Fuzzy-filter the entry list               |
| `Up` / `Down` | Move highlight                            |
| `Enter`       | Launch highlighted entry                  |
| `Escape`      | Clear filter (or exit if filter is empty) |
| `Backspace`   | Delete last character from filter         |
| `Ctrl+U`      | Clear filter                              |

## Windows Terminal Integration

Add LaunchLine as a Windows Terminal profile to use it as your default launcher.
The `--icon-path` flag prints the path to the bundled icon (place the `assets/`
directory next to the `launchline` binary):

```jsonc
// In your Windows Terminal settings.json → profiles.list
{
  "name": "LaunchLine",
  "commandline": "launchline",
  "startingDirectory": "%USERPROFILE%",
  // Run: launchline --icon-path
  "icon": "C:/path/to/launchline/assets/launchline.ico"
}
```

Set it as the default profile to see the launcher every time you open a terminal.

## Development

Requires [Rust](https://rustup.rs/) 1.85 or later.

```sh
cargo build            # debug build
cargo test             # run tests
cargo fmt --check      # formatting check
cargo clippy -- -D warnings  # lint
```

### Release build (optimized)

```sh
cargo build --release
```

The release profile enables LTO, single codegen unit, and symbol stripping for
optimized native execution. Measured scorer results are recorded below.

## License

MIT

## See Also

- **[LaunchLine (Python)](https://github.com/mikejhill/launchline)** — the
  original Python version. Installable via `pip install launchline`.
  See the compatibility matrix for verified behavior and runtime differences.

## Compatibility and validation

Use `launchline --check-config` to validate configuration without opening the menu.
Set `NO_COLOR` for a selection marker without ANSI color. See the
[compatibility matrix](docs/compatibility.md), [reproducible test and performance
results](docs/validation/report.md), and [release readiness](docs/releasing.md).

Nested menus and optional dynamic providers are described in the
[menu lifecycle and provider contract](docs/menus.md), including Back navigation,
refresh policies, caching, limits and error/retry behavior.
