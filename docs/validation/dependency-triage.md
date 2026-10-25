# Dependency security triage — October 23

Read-only GitHub Dependabot query returned 58 open Python repository alerts:
57 for Pillow 12.1.1 and one for pytest 9.0.2. Every reported affected range
includes the locked version; these are applicable dependency findings, not merely
an alert-count warning. Per-advisory ranges/fixes are in dependency-alerts.json.

Pillow is confined to the opt-in screenshots development group, used by
tools/generate_icon.py and tools/generate_screenshots.py. It is absent from runtime
dependencies, installed application imports and release build/test groups. The
current generators render configured internal content/fonts rather than accepting
arbitrary image uploads. This narrows exposure but does not invalidate the package
findings. Raised its floor and lock to 13.0.0, outside all 57 returned ranges.
Actual temporary ICO/PNG screenshots and animated GIF generation passed with 13.0.0.
No repository image assets were overwritten.

pytest is development-only. The upstream advisory affects shared Unix temporary
directory handling through 9.0.2; raised its floor to 9.0.3 and locked 9.1.1.
Rust had no open GitHub alerts, but manual lock review found pytest 8.4.2 for the
Python 3.9 development branch. Removed that vulnerable fallback from BOTH Rust
modernization and feature locks. Development now requires Python >=3.10 via uv's
group-specific requires-python; the distributable wrapper still supports Python
>=3.9 and has no pytest dependency. Wrapper unit tests pass with the patched lock.

No alert dismissals, repository settings or access changes were made. Alerts on
default main remain until the updated lock merges and GitHub rescans. This report
does not establish absence of all possible dependency or supply-chain issues.

Sources: GitHub repository Dependabot API (exact ranges recorded),
https://pillow.readthedocs.io/en/stable/releasenotes/13.0.0.html ,
https://github.com/advisories/GHSA-6w46-j5rx-g56g ,
https://docs.pytest.org/en/stable/changelog.html , and
https://docs.astral.sh/uv/concepts/projects/dependencies/#group-requires-python .
