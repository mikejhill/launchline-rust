"""Dry-run release versioning against a disposable Git fixture without a remote."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


class ReleaseFixture:
    """Verify plugin execution, version extraction, and zero publication side effects."""

    @staticmethod
    def main() -> None:
        """Require an explicitly selected checksum-verified SEMREL_BIN executable."""
        root = Path(__file__).resolve().parents[1]
        cli = Path(os.environ["SEMREL_BIN"]).resolve()
        environment = {
            key: value
            for key, value in os.environ.items()
            if key
            not in {"GITHUB_TOKEN", "GH_TOKEN", "GITLAB_TOKEN", "CI", "GITHUB_ACTIONS"}
        }
        with tempfile.TemporaryDirectory(
            prefix="launchline-semrel-fixture-"
        ) as temporary:
            fixture = Path(temporary)
            subprocess.run(
                ["git", "init", "--initial-branch=main"],
                cwd=fixture,
                env=environment,
                capture_output=True,
                check=True,
            )
            (fixture / "README.md").write_text(
                "Local release fixture.\n", encoding="utf-8"
            )
            subprocess.run(
                ["git", "add", "README.md"], cwd=fixture, env=environment, check=True
            )
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Fixture",
                    "-c",
                    "user.email=fixture@example.invalid",
                    "commit",
                    "-m",
                    "feat: initial fixture",
                ],
                cwd=fixture,
                env=environment,
                capture_output=True,
                check=True,
            )
            config = json.loads((root / ".semrelrc").read_text(encoding="utf-8"))
            config["plugins"]["provider"] = {
                "name": "git@1.13.0",
                "options": {"default_branch": "main"},
            }
            (fixture / ".semrelrc").write_text(json.dumps(config), encoding="utf-8")
            subprocess.run(
                [sys.executable, str(root / "scripts/prepare_semrel.py")],
                cwd=fixture,
                env=environment,
                check=True,
                timeout=180,
            )
            arguments = [
                "--dry",
                "--no-ci",
                "--allow-initial-development-versions",
                "--plugin-resolver-disable-batch-prefetch",
                "--changelog",
                "release-changelog.md",
            ]
            result = subprocess.run(
                [str(cli), *arguments],
                cwd=fixture,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
                timeout=120,
            )
            tags = subprocess.run(
                ["git", "tag", "--list"],
                cwd=fixture,
                env=environment,
                capture_output=True,
                text=True,
                check=True,
            ).stdout
            output = fixture / "github-output"
            subprocess.run(
                [sys.executable, str(root / "scripts/release_version.py")],
                cwd=fixture,
                env={**environment, "GITHUB_OUTPUT": str(output)},
                check=True,
            )
            evidence = {
                "command": arguments,
                "fixture": "disposable local Git repository; no remote or tokens",
                "returncode": result.returncode,
                "stderr": result.stderr,
                "tags_after": tags,
                "version_output": output.read_text(encoding="utf-8"),
                "notes": (fixture / "release-changelog.md").read_text(encoding="utf-8"),
            }
            (root / "docs/validation/semantic-release-dry-run.json").write_text(
                json.dumps(evidence, indent=2), encoding="utf-8"
            )
            assert (
                result.returncode == 0
                and tags == ""
                and evidence["version_output"] == "version=0.1.0\n"
            ), evidence


if __name__ == "__main__":
    ReleaseFixture.main()
