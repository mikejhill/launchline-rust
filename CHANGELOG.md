# Changelog

Rust registry versions use reviewed version/changelog PRs. Earlier development
snapshots remain in Git history; they were not the crates.io releases below.

## [0.2.2](https://github.com/mikejhill/launchline-rust/compare/v0.2.1...v0.2.2) (2026-10-29)


### Bug Fixes

* reserve zero for Back in every submenu ([#10](https://github.com/mikejhill/launchline-rust/issues/10)) ([86dd4ca](https://github.com/mikejhill/launchline-rust/commit/86dd4cad21f299ad044aaf344460e45be470c977))

## [0.2.1](https://github.com/mikejhill/launchline-rust/compare/v0.2.0...v0.2.1) (2026-10-29)


### Bug Fixes

* bind release approval to immutable source trees ([75a3dc7](https://github.com/mikejhill/launchline-rust/commit/75a3dc7809837c87ac3eecbe051c2ebf79ebd30c))
* complete reviewed GitHub releases with verified assets ([8dfdd3b](https://github.com/mikejhill/launchline-rust/commit/8dfdd3b8916be8fb9c4d1ecc294d6341af9031fd))
* dispatch fallback CI only from trusted main ([ee01752](https://github.com/mikejhill/launchline-rust/commit/ee01752a6d7f24746eac36c4111f4026c5a50d0d))
* make release recovery portable across Windows and Linux ([929d8dc](https://github.com/mikejhill/launchline-rust/commit/929d8dceee467c537498d8d5d0f16ed8a24e282a))
* validate trusted bot release CI before approving runs ([fc9b1b7](https://github.com/mikejhill/launchline-rust/commit/fc9b1b78aeee61f3de4fdc6f66bcbca601e33333))
* validate trusted release PRs before approving CI runs ([1af6377](https://github.com/mikejhill/launchline-rust/commit/1af63776d44b69d35d3c32bbc25d624e123c742a))

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
