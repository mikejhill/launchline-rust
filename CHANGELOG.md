# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Menus

- Add nested menus with Back navigation, lazy JSON providers, explicit refresh/retry,
  configurable parent refresh, and stable selection restoration.
- Bound generated output, provider timeouts and process cleanup; cache up to 128 menu
  snapshots with inactive least-recently-used eviction. Existing static configs remain valid.
- Add shared declaration fixtures, actual provider/terminal tests and seeded menu mutations.
  See [menu lifecycle and provider contract](docs/menus.md) for examples and limits.

### Changed

- **Rewritten from Python to Rust** for near-instant startup (~14ms vs ~150ms).
  The TOML config format is fully compatible — existing config files work unchanged.
- Pre-built binaries for 6 platforms: Windows (x64, ARM64), macOS (x64, ARM64),
  Linux (x64, ARM64)
- Release workflow now produces GitHub Release binaries instead of PyPI packages

### Added

- PyPI binary wrapper — `pip install launchline` downloads the correct native
  binary for your platform

### Removed

- Python runtime dependency — LaunchLine is now a single static binary
- Reverted array syntax for `command` config key; `command` is string-only,
  use `args` for arguments

## [0.2.0] - 2026-03-30

### Added

- `--config-path` CLI flag to print the active configuration file path

### Fixed

- PyPI package page now renders README images correctly (paths are rewritten
  to absolute URLs during the release build)
- Release artifacts no longer accidentally include non-distribution files
- Release workflow now produces correct version numbers (fixed dirty-tree
  version detection via `SETUPTOOLS_SCM_PRETEND_VERSION`)

## [0.1.0] - 2026-03-30

### Added

- Interactive TUI launcher with numbered shortcuts and fuzzy search
- TOML configuration with `[settings]` and `[[entries]]` tables
- Per-entry environment variables and working directory support
- Configurable on-exit behavior: restart loop or exit
- Auto-generated starter config on first run
- Configurable `show_exit` setting to show/hide Exit entry
- Windows Terminal integration support
- Cross-platform keyboard handling via crossterm
- `ghost_text` feature flag for autocomplete hints on the prompt line
- `numeric_trigger` feature flag for immediate digit-key launching
- Bundled icon accessible via `launchline --icon-path` for Windows Terminal profiles
- Cross-platform support (Windows, macOS, Linux)
- LaunchLine icon (SVG, ICO, PNG) in `assets/`
- PyPI publishing via GitHub Actions
