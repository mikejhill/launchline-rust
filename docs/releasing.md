# Reviewed releases to crates.io and GitHub

Every released version must have a public GitHub Release with useful notes and
the exact registry distribution, checksums and signed provenance. A registry
upload or source tag alone is not a complete release. Rust packages publish only
to crates.io; the separate Python implementation uses PyPI. GitHub assets here
are Cargo source distributions, not standalone native binaries.

## Normal process

1. Conventional commits update a release-please PR containing the proposed Cargo
   version, lockfile, changelog and release manifest. The bootstrap is the already
   published 0.2.0. Feature/fix merges propose release PRs; they do not immediately
   publish packages.
2. Review and merge that PR through normal CI and review rules. The pinned action
   creates its immutable tag and a draft GitHub Release. The workflow never
   approves PR reviews or merges PRs. GitHub can hold the release bot's PR-context
   CI because the bot is a first-time contributor. Using its existing Actions
   permission, the planner approves only that bot's same-repository generated PR
   after verifying the exact head/base, four version files, unchanged dependency
   records, immutable source trees and the pinned read-only CI definition. It executes no PR code with its
   write token. Changed source, workflows, authors or capabilities require review.
   The contributor approval policy and branch protections remain unchanged.
   If GitHub suppresses the PR event entirely, the planner dispatches the same
   read-only CI with an exact-SHA guard that rejects a branch race. Failed CI is
   never replaced by a dispatch; uncertain approval writes stop for inspection.
   All required checks and normal merge rules still apply.
3. Read-only jobs validate the exact source on Windows x64, Linux x64 and macOS
   ARM64. Build the versioned archive once, clean-install its extracted source and
   test real installed CLI/terminal behavior. Retain reviewed release notes inside
   the archive as release-changelog.md.
4. Attest the same-run .crate and publish.json. The isolated registry publisher
   checks source ancestry, tag identity, metadata and checksums before requesting
   an ephemeral crates.io OIDC token. It neither checks out nor executes package
   source. Exact-checksum registry retries succeed; different bytes fail.
5. After verified registry publication and tagging, a separate GitHub writer
   consumes that exact artifact. It checks the original run, embedded source and
   signed provenance, then attaches the .crate, publish.json, SHA256SUMS and
   .crate.intoto.jsonl bundle. Existing asset bytes are compared, missing assets
   are uploaded without clobbering, and downloaded again for hash readback before
   publishing a complete draft. Existing public notes and unrelated assets remain.
   Checksum text is generated with LF on every platform. Legacy CRLF manifests are
   accepted only when every checksum/name record is identical, preserving their
   remote bytes; crate, metadata and provenance comparisons remain byte-exact.

The trusted publisher remains mikejhill/launchline-rust, release.yml, environment
crates-io, restricted to main. OIDC, attestation, source-tag and GitHub writer
permissions stay isolated. Default Actions token permission remains read-only.
No Rust PyPI credentials, long-lived publishing token or new trust is required.

## Repair and retry

For uncertain registry uploads, inspect the exact version/checksum before retrying
the failed job. Never bump a version merely to repair a page. After successful
registry publication, run Repair GitHub release assets (repair-github-release.yml)
on main with the published version and original successful release.yml run ID.
This route cannot build, publish packages, create or move tags. It requires the
retained trusted-crate artifact and signed provenance, and rejects different
existing bytes rather than replacing them.

| Version | Original run | Immutable source |
| --- | --- | --- |
| 0.1.0 | 40013902606 | d5482ad782114ee7cfaa4b211e01c447a038b24a |
| 0.2.0 | 40216338286 | 75260f00a497a8ae3c79ba3eebd912a997cc0012 |

Run artifacts expire after seven days. After expiry, recover exact public crate
and metadata assets from the GitHub Release and verify provenance before repair;
do not rebuild existing versions. Uncertain writes stop without automatic retries:
inspect the specific draft/release and rerun reconciliation to reuse matching
bytes. A failed package publication leaves the GitHub Release draft.

## Validation

Run the focused offline tests under pypi/tests, Ruff, Rust format/Clippy/tests and
existing Cargo archive/clean-install CI. Fixtures cover first creation, complete
retry, partial drafts, conflicting assets, uncertain writes, registry/tag/source/
run conflicts and failed attestation. Both workflows inline the same tested
standard-library helper without source checkout under release-write credentials.

Independently verify a crate with gh attestation verify, the repository and exact
source digest; compare SHA256SUMS with crates.io. This follows VerdiClip's reviewed
release-PR and distribution pattern, retaining Rust's registry and failure order.
