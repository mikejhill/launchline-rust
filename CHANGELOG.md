# Changelog

Rust registry versions use reviewed version/changelog PRs. Earlier development
snapshots remain in Git history; they were not the crates.io releases below.

## [Unreleased]

### Release process

- Create reviewed release PRs and complete GitHub Release pages with the exact
  Cargo archive, checksums, metadata and signed provenance after verified registry
  publication. Repair pages without republishing packages or moving source tags.

## [0.2.0] - 2026-10-25

### Features

- Recursive static menus with Back navigation and optional dynamic JSON providers
  at the root and submenu levels.
- Retained parent queries, stable selections and cached snapshots; explicit
  refresh/retry and configurable parent refresh on return.
- Last-good snapshots after provider errors and bounded output, timeout, nesting,
  process cleanup and inactive menu caches.
- Shared configuration/lifecycle fixtures with the separate Python implementation.

## [0.1.0] - 2026-10-25

### Features

- Publish the native Rust launcher as the crates.io package launchline.
- Validate configuration and Unicode search/editing, preserve inherited
  interruption behavior and embed the icon for clean Cargo installations.
- Verify actual Cargo archives and installed terminal behavior on Windows x64,
  Linux x64 and macOS ARM64, with signed provenance and scoped OIDC releases.

[0.2.0]: https://github.com/mikejhill/launchline-rust/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/mikejhill/launchline-rust/tree/v0.1.0
