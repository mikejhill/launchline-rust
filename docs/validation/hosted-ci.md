# Hosted CI follow-up

Draft PR: https://github.com/mikejhill/launchline-rust/pull/1

Mike authorized non-force pushes and draft PRs after the local validation snapshot.
Python's initial hosted run 39871242844 passed all nine Windows/Linux/macOS and
Python 3.12/3.13/3.14 combinations. That run checked GitHub's generated merge SHA;
CI now explicitly checks out pull_request.head.sha so subsequent PR runs execute
the exact proposed source commit. Main/release checkout semantics are unchanged.

Rust's initial run 39871247740 exposed two portable-test issues: macOS temp-directory
aliases (/var versus /private/var), and a Windows test that mocked global os.name
on Unix, thereby changing pathlib behavior. The child cwd assertion now compares
canonical directory identities while still asserting literal argv/environment.
Wrapper platform mocks affect only the wrapper's os reference, and LOCALAPPDATA
no longer eagerly evaluates an unused home fallback. No test was disabled.

The PR checks provide final run status and commit identities; the accompanying
report.md and summary.json retain the earlier local validation snapshot. Native
Linux x64, Windows x64 and macOS ARM64 are in Rust PR CI. Release-only Linux ARM64,
Windows ARM64 and macOS x64 targets are not exercised by this PR matrix. Production
publishing, repository security settings and credentials remain untouched.
