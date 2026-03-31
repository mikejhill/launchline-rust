"""LaunchLine — a lightweight launcher for interactive CLI tools.

This Python package is a thin wrapper that downloads and runs the pre-built
native binary from GitHub Releases. The actual application is written in Rust
for near-instant startup.
"""

from launchline._wrapper import main

__all__ = ["main"]
