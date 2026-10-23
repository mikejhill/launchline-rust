"""Extract the next version from semantic-release's dry-run changelog."""

from __future__ import annotations

import os
import re
from pathlib import Path


class ReleaseVersion:
    """Validate generated version text before writing a GitHub job output."""

    @staticmethod
    def main() -> None:
        """Emit no version when there are no releasable commits."""
        notes = Path("release-changelog.md")
        if not notes.exists():
            return
        header = notes.read_text(encoding="utf-8").splitlines()[0]
        match = re.fullmatch(r"## ([0-9]+\.[0-9]+\.[0-9]+) \(.*\)", header)
        if match is None:
            raise ValueError("Unexpected semantic-release changelog header")
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
            output.write(f"version={match[1]}\n")


if __name__ == "__main__":
    ReleaseVersion.main()
