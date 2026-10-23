"""Exercise release-version extraction without credentials or publication."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


class TestReleaseVersion:
    """Test the actual dry-run parser as a subprocess in an isolated directory."""

    @pytest.mark.parametrize(
        ("header", "expected"),
        [("## 0.1.0 (2026-10-22)", 0), ("## injected", 1), ("## 1.2.3-beta (date)", 1)],
    )
    def test_version_header_is_validated(
        self, header: str, expected: int, tmp_path: Path
    ) -> None:
        """Only numeric semantic versions can enter publisher job outputs."""
        script = Path(__file__).resolve().parents[2] / "scripts/release_version.py"
        (tmp_path / "release-changelog.md").write_text(header, encoding="utf-8")
        output = tmp_path / "output"
        result = subprocess.run(
            [sys.executable, str(script)],
            cwd=tmp_path,
            env={**os.environ, "GITHUB_OUTPUT": str(output)},
            capture_output=True,
            check=False,
        )
        assert result.returncode == expected, result.stderr
        if expected == 0:
            assert output.read_text(encoding="utf-8") == "version=0.1.0\n", (
                "Expected exact job output"
            )
        else:
            assert not output.exists(), "Invalid versions must not reach publisher jobs"
