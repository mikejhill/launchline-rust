# Retained Rust wrapper source and test tooling

This historical wrapper is not published. Rust LaunchLine is distributed only as
crate `launchline` on crates.io: `cargo install launchline --locked`.
Its native executable has no Python runtime dependency. This directory retains
development dependencies, terminal tests and old wrapper compatibility tests.
The Python implementation remains a separate PyPI `launchline` project.
See [the Rust repository](https://github.com/mikejhill/launchline-rust) and
[release process](../docs/releasing.md).
