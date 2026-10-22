"""Offline simulations of the actual publisher shell and credential boundaries."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


class TestPublisherPolicy:
    """Exercise actual workflow shell commands with every GitHub call replaced."""

    @pytest.mark.parametrize(
        ("scenario", "expected", "publishes"),
        [
            ("normal", 0, True),
            ("tag-conflict", 1, False),
            ("not-on-main", 1, False),
            ("retry", 0, True),
        ],
    )
    def test_publisher_refuses_conflicts_and_accepts_same_commit_retry(
        self, scenario: str, expected: int, publishes: bool, tmp_path: Path
    ) -> None:
        """Only a current main ancestor and matching tag can reach upload."""
        root = Path(__file__).resolve().parents[2]
        workflow = yaml.safe_load(
            (root / ".github/workflows/release.yml").read_text(encoding="utf-8")
        )
        publisher = workflow["jobs"]["github-release"]
        assert "github.actor == 'mikejhill'" in publisher["if"], (
            "Owner gate is required"
        )
        assert "github.triggering_actor == 'mikejhill'" in publisher["if"], (
            "Rerun owner gate is required"
        )
        assert not any(
            "checkout@" in step.get("uses", "") for step in publisher["steps"]
        ), "Publisher must not execute checked-out repository code"
        body = next(step["run"] for step in publisher["steps"] if "run" in step)
        release = tmp_path / "release"
        (release / "dist").mkdir(parents=True)
        (release / "release-notes.md").write_text(
            "Reviewed fixture notes", encoding="utf-8"
        )
        (release / "dist/fixture.whl").write_bytes(b"fixture")
        for extension in ["tar.gz", "zip", "whl"]:
            (release / f"fixture.{extension}").write_bytes(b"offline fixture")
        log = tmp_path / "github-calls"
        python_path = str(Path(sys.executable)).replace("\\", "/")
        fake = r"""
set -euo pipefail
python3() { "$FIXTURE_PYTHON" "$@"; }
gh() {
  printf '%s\n' "$*" >> "$FIXTURE_LOG"
  case "$*" in
    "api repos/fixture/launchline/compare/"*)
      if [ "$SCENARIO" = not-on-main ]; then
        echo bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
      else echo "$GITHUB_SHA"; fi ;;
    "api --method POST"*)
      if [ "$SCENARIO" = tag-conflict ] || [ "$SCENARIO" = retry ]; then return 1; fi ;;
    "api repos/fixture/launchline/commits/"*)
      if [ "$SCENARIO" = tag-conflict ]; then
        echo bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
      else echo "$GITHUB_SHA"; fi ;;
    "release view"*) [ "$SCENARIO" = retry ] ;;
    "release create"*) return 0 ;;
    "release upload"*) return 0 ;;
    *) echo "Unexpected offline GitHub call" >&2; return 99 ;;
  esac
}
"""
        if sys.platform == "win32":
            bash = str(Path(os.environ["PROGRAMFILES"]) / "Git/bin/bash.exe")
        else:
            bash = shutil.which("bash")
            assert bash is not None, "Publisher simulations require Bash"
        result = subprocess.run(
            [bash, "-c", fake + body],
            cwd=tmp_path,
            env={
                **os.environ,
                "FIXTURE_PYTHON": python_path,
                "FIXTURE_LOG": str(log).replace("\\", "/"),
                "SCENARIO": scenario,
                "GITHUB_SHA": "a" * 40,
                "GITHUB_REPOSITORY": "fixture/launchline",
                "TAG": "v0.1.0",
                "GH_TOKEN": "offline-fixture",
            },
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == expected, result.stderr
        calls = log.read_text(encoding="utf-8")
        assert ("release upload" in calls) == publishes, calls
        if scenario == "normal":
            assert "--generate-notes" in calls, (
                "Generated release notes must be retained"
            )
        if scenario == "retry":
            assert "release create" not in calls, (
                "Retry must reuse the matching existing release"
            )
