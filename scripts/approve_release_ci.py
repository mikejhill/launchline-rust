"""Approve only the trusted bot's version-only PR against known read-only CI."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import re
import subprocess
import time
import tomllib
from typing import ClassVar


class ReleaseCI:
    """Keep unknown authors, source changes and workflow capabilities manual."""

    REPO = "mikejhill/launchline-rust"
    BRANCH = "release-please--branches--main--components--launchline"
    BOT: ClassVar[dict[str, str | int]] = {
        "login": "github-actions[bot]",
        "id": 41898282,
        "type": "Bot",
    }
    CI_SHA256 = "1537005f266d2111e4368bc8c03597ed8a48095f12615972d07b463e1e457c7e"
    FILES: ClassVar[set[str]] = {
        "Cargo.toml",
        "Cargo.lock",
        "CHANGELOG.md",
        ".release-please-manifest.json",
    }

    @staticmethod
    def gh(*args: str) -> str:
        """Use fixed CLI arguments without executing checked-out PR code."""
        return subprocess.run(
            ["gh", *args],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
        ).stdout

    @classmethod
    def api(cls, path: str) -> object:
        """Read only the fixed repository; writes use a separate explicit call."""
        return json.loads(cls.gh("api", f"repos/{cls.REPO}/{path}"))

    @classmethod
    def content(cls, path: str, ref: str) -> bytes:
        """Read immutable blobs via the API, never through a credentialed checkout."""
        record = cls.api(f"contents/{path}?ref={ref}")
        if record["type"] != "file":
            raise ValueError("Expected a regular metadata file")
        return base64.b64decode(record["content"], validate=False)

    @classmethod
    def identity(cls, number: int) -> dict:
        """Bind the known bot, repository, generated branch and main base."""
        pr = cls.api(f"pulls/{number}")
        if (
            pr["state"] != "open"
            or pr["number"] != number
            or any(pr["user"].get(key) != value for key, value in cls.BOT.items())
            or pr["head"]["repo"]["full_name"] != cls.REPO
            or pr["base"]["repo"]["full_name"] != cls.REPO
            or pr["head"]["repo"]["id"] != pr["base"]["repo"]["id"]
            or pr["head"]["repo"]["fork"]
            or pr["head"]["ref"] != cls.BRANCH
            or pr["base"]["ref"] != "main"
            or any(
                re.fullmatch(r"[0-9a-f]{40}", pr[side]["sha"]) is None
                for side in ("head", "base")
            )
        ):
            raise ValueError("Not the trusted same-repository bot release PR")
        return pr

    @classmethod
    def validate(cls, number: int) -> dict:
        """Allow version records only, with unchanged dependencies and pinned CI."""
        pr = cls.identity(number)
        changes = cls.api(f"pulls/{number}/files?per_page=100")
        if (
            pr["changed_files"] != 4
            or len(changes) != 4
            or {item["filename"] for item in changes} != cls.FILES
            or any(item["status"] != "modified" for item in changes)
        ):
            raise ValueError("Release PR changes more than the four version files")
        snapshots = {}
        for side in ("base", "head"):
            ref = pr[side]["sha"]
            tree = cls.api(f"git/trees/{ref}?recursive=1")
            if tree.get("truncated"):
                raise ValueError("Cannot validate a truncated source tree")
            modes = {item["path"]: item for item in tree["tree"]}
            for path in cls.FILES | {".github/workflows/ci.yml"}:
                if modes[path]["type"] != "blob" or modes[path]["mode"] != "100644":
                    raise ValueError("Release metadata/CI must remain regular files")
            ci = cls.content(".github/workflows/ci.yml", ref)
            if hashlib.sha256(ci).hexdigest() != cls.CI_SHA256:
                raise ValueError("CI capabilities changed; review the read-only CI pin")
            snapshots[side] = {
                "cargo": tomllib.loads(cls.content("Cargo.toml", ref).decode("utf-8")),
                "lock": tomllib.loads(cls.content("Cargo.lock", ref).decode("utf-8")),
                "manifest": json.loads(
                    cls.content(".release-please-manifest.json", ref)
                ),
            }
        before, after = snapshots["base"], snapshots["head"]
        old = before["cargo"]["package"]["version"]
        new = after["cargo"]["package"]["version"]
        if (
            not isinstance(new, str)
            or re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", new) is None
            or tuple(map(int, new.split("."))) <= tuple(map(int, old.split(".")))
            or after["manifest"].get(".") != new
            or before["manifest"].get(".") != old
        ):
            raise ValueError("Inconsistent or non-increasing release version")
        normalized = copy.deepcopy(after)
        normalized["cargo"]["package"]["version"] = old
        normalized["manifest"]["."] = old
        roots = [
            item
            for item in normalized["lock"]["package"]
            if item["name"] == "launchline" and "source" not in item
        ]
        if len(roots) != 1 or roots[0]["version"] != new:
            raise ValueError("Cargo lock root version differs")
        roots[0]["version"] = old
        if normalized != before:
            raise ValueError("Release PR changes dependencies or non-version metadata")
        return pr

    @classmethod
    def unchanged(cls, number: int, expected: dict) -> None:
        """Reject a head/base race instead of approving a stale validation."""
        current = cls.identity(number)
        if any(
            current[side]["sha"] != expected[side]["sha"] for side in ("head", "base")
        ):
            raise ValueError("Release PR source changed during approval")

    @classmethod
    def run_matches(cls, run: dict, pr: dict, workflow_id: int) -> bool:
        """Associate only the known CI's PR-context run with the exact source."""
        return (
            run["event"] == "pull_request"
            and run["path"] == ".github/workflows/ci.yml"
            and run["workflow_id"] == workflow_id
            and run["head_sha"] == pr["head"]["sha"]
            and run["repository"]["full_name"] == cls.REPO
            and run["head_repository"]["full_name"] == cls.REPO
            and any(
                item["number"] == pr["number"]
                and item["head"]["sha"] == pr["head"]["sha"]
                and item["base"]["sha"] == pr["base"]["sha"]
                and item["head"]["repo"]["id"] == pr["head"]["repo"]["id"]
                for item in run["pull_requests"]
            )
            and all(run["actor"].get(key) == value for key, value in cls.BOT.items())
        )

    @classmethod
    def ensure(cls, number: int, attempts: int = 8) -> None:
        """Approve eligible held runs once; otherwise validate the exact known head."""
        pr = cls.validate(number)
        workflow = cls.api("actions/workflows/ci.yml")
        for attempt in range(attempts):
            runs = cls.api(
                f"actions/workflows/ci.yml/runs?event=pull_request&head_sha={pr['head']['sha']}&per_page=100"
            )["workflow_runs"]
            for candidate in runs:
                run = cls.api(f"actions/runs/{candidate['id']}")
                if not cls.run_matches(run, pr, workflow["id"]):
                    continue
                if run["conclusion"] == "action_required":
                    cls.unchanged(number, pr)
                    fresh = cls.api(f"actions/runs/{run['id']}")
                    if (
                        not cls.run_matches(fresh, pr, workflow["id"])
                        or fresh["conclusion"] != "action_required"
                    ):
                        raise ValueError("Held run changed before approval")
                    cls.gh(
                        "api",
                        "--method",
                        "POST",
                        f"repos/{cls.REPO}/actions/runs/{run['id']}/approve",
                    )
                    print(
                        f"Approved trusted version-only release PR CI run {run['id']} at {pr['head']['sha']}."
                    )
                    return
                if run["status"] != "completed" or run["conclusion"] == "success":
                    print(
                        f"Exact-head release PR CI run {run['id']} is already active or passed."
                    )
                    return
                raise RuntimeError(
                    "The exact-head PR-context CI failed; fix it rather than bypassing it"
                )
            if attempt + 1 < attempts:
                time.sleep(5)
        cls.unchanged(number, pr)
        cls.gh(
            "workflow",
            "run",
            "ci.yml",
            "--repo",
            cls.REPO,
            "--ref",
            cls.BRANCH,
            "--field",
            f"expected-sha={pr['head']['sha']}",
        )
        print(
            "No PR-context run appeared; dispatched unchanged read-only CI with an exact-SHA guard."
        )


if __name__ == "__main__":
    if os.environ.get("GITHUB_REPOSITORY") != ReleaseCI.REPO:
        raise ValueError("Unexpected repository")
    proposal = json.loads(os.environ["PR_JSON"])
    number = proposal["number"]
    if (
        not isinstance(number, int)
        or number <= 0
        or proposal["headBranchName"] != ReleaseCI.BRANCH
    ):
        raise ValueError("Unexpected release-please PR output")
    ReleaseCI.ensure(number)
