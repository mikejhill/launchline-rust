# crates.io-only release process

Rust LaunchLine is distributed as crate `launchline` on crates.io. `cargo install
launchline --locked` builds the native executable; Python is not a runtime requirement.
The separate Python implementation remains the `launchline` PyPI project.
No Rust PyPI wrapper or standalone GitHub binary releases are published.

Owner merges to main calculate conventional-commit versions from immutable source
tags using pinned semantic-release 2.31.0 and checksum-pinned Git provider/plugins.
Read-only jobs check the exact merge, build/compile its `.crate`, clean-install its
extracted source, and run actual installed CLI/terminal behavior. The icon is embedded
so Cargo installs retain `--icon-path` without adjacent archive assets.

The publisher consumes only same-run `.crate` and registry metadata artifacts. It
does not check out source or execute package/build scripts. It validates name,
version, source commit, checksum, main ancestry and tag conflicts before requesting
an ephemeral token through the immutable official crates.io OIDC action. Upload uses
Cargo's documented fixed crates.io API protocol; authenticated redirects are rejected.
An exact-checksum existing version is a safe retry; a conflicting version fails.
Uncertain upload outcomes fail for readback before any retry. Provenance covers
the tested crate and metadata. A source-only `v*` tag is created after registry
checksum verification; no GitHub Release or binary asset upload occurs.

Both actor and rerun initiator must be mikejhill on main. OIDC, attestation and
source-tag permissions are isolated to their jobs. Non-release commits skip build
and publication. Modernization publishes before the nested/dynamic menu feature.

## Registry setup pending explicit approval

The launchline crates.io lookup returned 404; a name is not reserved until first
publication. The logged-in account's token page shows no existing API tokens, and
Cargo has no token environment variable, credential file or configured provider.
No credential or registry trust has been created. Official crates.io guidance
requires a first manual release before configuring Trusted Publishing.

The concrete setup proposal is a short-lived, crate-restricted bootstrap publish
credential (initial release only, then revoke), followed by Trusted Publishing for
crate `launchline`, GitHub repository `mikejhill/launchline-rust`, workflow `release.yml`,
environment `crates-io`. A separate main-only `crates-io` GitHub environment with no
reviewers is required before merging; it is not created implicitly by this task.
Exact token scope/expiry and account identity must be approved before credential
creation. The old unused `pypi` environment remains inert and unchanged.

## Validation

Run `cargo fmt --check`, `cargo clippy --locked --all-targets -- -D warnings`,
`cargo test --locked`, `cargo publish --dry-run --locked --allow-dirty`, then
`uv run --locked --project pypi python scripts/build_crate.py` and
`uv run --locked --project pypi python scripts/crate_install_smoke.py`.
The historical pypi directory supplies retained Python test tooling only; its
wrapper source is preserved but excluded from the Cargo payload and publishing.
Offline policy tests intercept every registry/GitHub request; no test publishes.

Sources: https://doc.rust-lang.org/cargo/reference/registry-web-api.html#publish ,
https://doc.rust-lang.org/cargo/reference/publishing.html , and
https://blog.rust-lang.org/2025/07/11/crates-io-development-update-2025-07/ .
