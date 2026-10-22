# Release readiness

Trusted owner merges to main trigger conventional-commit version calculation.
Read-only jobs test/build the exact merge SHA before separate publishers consume
same-run artifacts. Both actor and rerun initiator must be mikejhill. Publisher
jobs do not check out repository code; write/OIDC permissions are job-scoped.
Artifacts receive provenance. Conflicting tags fail; generated GitHub notes are
retained. Release publication remains a production action and was not invoked.

The go-semantic-release CLI is pinned to 2.31.0 with a verified checksum; exact
runtime plugin versions and Linux/Windows checksums are in
scripts/semantic-release-plugins.json. prepare_semrel.py verifies/preloads them.
release_version.py validates the generated changelog header (the CLI dry-run does
not produce its version-file output). The disposable fixture script removes token
variables, has no remote and verifies no tags; its evidence is in validation/.
It exercises the Git provider, not the production GitHub provider or PyPI upload.
Publisher policy tests execute the real workflow shell body with an intercepting
gh shell function; no requests reach GitHub.

Current VerdiClip workflow was read as the reference; Python PR #1 at
96d72c1e157e57e1b1aa9c5ad1dfbf51aaa606ab was inspected and its CLI pin,
immutable tag conflict check, owner/rerun gates and generated notes preserved
selectively. Neither PR nor production settings were merged or modified.

## Remaining setup (owner action required)

Read-only inspection found Python's existing pypi environment still has a required
reviewer and no deployment branch policy. Rust's pypi environment returned 404
(absent). PyPI trusted-publisher identities could not be verified. Thus production
approval-free PyPI delivery is NOT ready. Before rollout, establish/verify main-only
environment restrictions and the PyPI identity for the corresponding repository,
release.yml and pypi environment. Any removal of the existing reviewer requires
separate authorization; this task deliberately leaves the gate unchanged. Verify
version-tag protection and GitHub attestation availability as well. No credentials
were created and no repository security setting was changed.

To reproduce a safe version fixture, explicitly set SEMREL_BIN to the verified CLI
and run scripts/release_dryrun.py through the repository's uv environment. Do not
substitute a production provider or run publication commands as a dry run. A failed
production upload should be retried on its original run; never move an existing tag.
