"""Set validated release metadata in an ephemeral CI checkout, without tags or pushes."""

from __future__ import annotations

import os
import re
from pathlib import Path


class VersionMetadata:
    """Update only local project version fields."""

    @staticmethod
    def main() -> None:
        """Require a semantic version and update Rust and wrapper metadata."""
        version = os.environ["VERSION"]
        if re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version) is None:
            raise ValueError("Expected a numeric semantic version")
        root = Path(__file__).resolve().parents[1]
        for relative in ["Cargo.toml", "pypi/pyproject.toml"]:
            path = root / relative
            source = path.read_text(encoding="utf-8")
            updated, count = re.subn(
                r'(?m)^version = "[^"]+"', f'version = "{version}"', source, count=1
            )
            assert count == 1, relative
            path.write_text(updated, encoding="utf-8")
        path = root / "Cargo.lock"
        source = path.read_text(encoding="utf-8")
        updated, count = re.subn(
            r'(name = "launchline"\nversion = )"[^"]+"',
            lambda match: match[1] + f'"{version}"',
            source,
        )
        assert count == 1, "Cargo.lock must identify exactly one local package"
        path.write_text(updated, encoding="utf-8")


if __name__ == "__main__":
    VersionMetadata.main()
