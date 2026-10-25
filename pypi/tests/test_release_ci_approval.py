"""Never approve unknown PRs or changed CI capabilities with a write token."""

from __future__ import annotations

import base64
import copy
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml


def approval_module() -> object:
    """Import the production helper without invoking its CLI entry point."""
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "approve_release_ci", root / "scripts/approve_release_ci.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "scenario",
    [
        "approve",
        "active",
        "passed",
        "failed",
        "no-run",
        "approval-uncertain",
        "human",
        "spoofed-bot-id",
        "fork",
        "wrong-branch",
        "source-change",
        "immutable-source-change",
        "immutable-script-added",
        "symlink",
        "ci-capability-change",
        "cargo-dependency-change",
        "lock-checksum-change",
        "manifest-extra",
        "version-mismatch",
        "version-downgrade",
        "head-race",
        "run-race",
        "foreign-run-head",
        "foreign-run-base",
        "foreign-run-actor",
        "foreign-run-workflow",
        "foreign-run-pr",
    ],
)
def test_only_version_metadata_and_known_read_only_ci_can_be_approved(
    scenario: str,
) -> None:
    """Execute the real guard over API fixtures and capture every write/dispatch."""
    service = approval_module().ReleaseCI
    ci = b"reviewed read-only CI fixture"
    service.CI_SHA256 = hashlib.sha256(ci).hexdigest()
    repo = {"id": 7, "full_name": service.REPO, "fork": False}
    pr = {
        "number": 4,
        "state": "open",
        "user": copy.deepcopy(service.BOT),
        "changed_files": 4,
        "head": {"sha": "b" * 40, "ref": service.BRANCH, "repo": copy.deepcopy(repo)},
        "base": {"sha": "a" * 40, "ref": "main", "repo": copy.deepcopy(repo)},
    }
    if scenario == "human":
        pr["user"]["type"] = "User"
    if scenario == "spoofed-bot-id":
        pr["user"]["id"] = 99
    if scenario == "fork":
        pr["head"]["repo"]["full_name"] = "untrusted/fork"
        pr["head"]["repo"]["fork"] = True
    if scenario == "wrong-branch":
        pr["head"]["ref"] = "other"
    base_cargo = (
        '[package]\nname="launchline"\nversion="0.2.0"\n[dependencies]\nserde="1"\n'
    )
    base_lock = 'version=4\n[[package]]\nname="launchline"\nversion="0.2.0"\n[[package]]\nname="serde"\nversion="1.0.0"\nsource="registry"\nchecksum="known"\n'
    head_cargo = base_cargo.replace('version="0.2.0"', 'version="0.2.1"')
    head_lock = base_lock.replace('version="0.2.0"', 'version="0.2.1"')
    manifest = {".": "0.2.1"}
    if scenario == "cargo-dependency-change":
        head_cargo = head_cargo.replace('serde="1"', 'serde="2"')
    if scenario == "lock-checksum-change":
        head_lock = head_lock.replace('checksum="known"', 'checksum="changed"')
    if scenario == "manifest-extra":
        manifest["other"] = "1.0.0"
    if scenario == "version-mismatch":
        manifest["."] = "0.2.2"
    if scenario == "version-downgrade":
        head_cargo = head_cargo.replace('version="0.2.1"', 'version="0.1.0"')
    contents = {
        "a" * 40: {
            "Cargo.toml": base_cargo.encode(),
            "Cargo.lock": base_lock.encode(),
            ".release-please-manifest.json": b'{".":"0.2.0"}',
            ".github/workflows/ci.yml": ci,
        },
        "b" * 40: {
            "Cargo.toml": head_cargo.encode(),
            "Cargo.lock": head_lock.encode(),
            ".release-please-manifest.json": json.dumps(manifest).encode(),
            ".github/workflows/ci.yml": ci,
        },
    }
    if scenario == "ci-capability-change":
        contents["b" * 40][".github/workflows/ci.yml"] = b"id-token: write"
    run = {
        "id": 42,
        "workflow_id": 99,
        "event": "pull_request",
        "path": ".github/workflows/ci.yml",
        "head_sha": "b" * 40,
        "repository": {"full_name": service.REPO},
        "head_repository": {"full_name": service.REPO},
        "actor": copy.deepcopy(service.BOT),
        "pull_requests": [
            {
                "number": 4,
                "head": {"sha": "b" * 40, "repo": {"id": 7}},
                "base": {"sha": "a" * 40},
            }
        ],
        "status": "completed",
        "conclusion": "action_required",
    }
    if scenario == "active":
        run.update(status="in_progress", conclusion=None)
    if scenario in ("passed", "failed"):
        run["conclusion"] = "success" if scenario == "passed" else "failure"
    if scenario == "foreign-run-head":
        run["head_sha"] = "c" * 40
    if scenario == "foreign-run-base":
        run["pull_requests"][0]["base"]["sha"] = "c" * 40
    if scenario == "foreign-run-actor":
        run["actor"]["id"] = 99
    if scenario == "foreign-run-workflow":
        run["workflow_id"] = 88
    if scenario == "foreign-run-pr":
        run["pull_requests"][0]["number"] = 5
    identities = 0
    run_reads = 0
    writes = []

    def api(path: str) -> object:
        nonlocal identities, run_reads
        if path == "pulls/4":
            identities += 1
            result = copy.deepcopy(pr)
            if scenario == "head-race" and identities > 1:
                result["head"]["sha"] = "c" * 40
            return result
        if path.startswith("pulls/4/files"):
            files = sorted(service.FILES)
            if scenario == "source-change":
                files[0] = "src/main.rs"
            return [{"filename": name, "status": "modified"} for name in files]
        if path.startswith("git/trees/"):
            head = path.startswith("git/trees/" + "b" * 40)
            tree = [
                {
                    "path": "src/main.rs",
                    "mode": "100644",
                    "type": "blob",
                    "sha": "c" * 40
                    if scenario == "immutable-source-change" and head
                    else "d" * 40,
                },
            ]
            if scenario == "immutable-script-added" and head:
                tree.append(
                    {
                        "path": "build.rs",
                        "mode": "100644",
                        "type": "blob",
                        "sha": "e" * 40,
                    }
                )
            return {
                "truncated": False,
                "tree": tree
                + [
                    {
                        "path": name,
                        "type": "blob",
                        "sha": "f" * 40,
                        "mode": "120000"
                        if scenario == "symlink" and name == "Cargo.toml"
                        else "100644",
                    }
                    for name in service.FILES | {".github/workflows/ci.yml"}
                ],
            }
        if path.startswith("contents/"):
            name, ref = path.removeprefix("contents/").split("?ref=")
            return {
                "type": "file",
                "content": base64.b64encode(contents[ref][name]).decode(),
            }
        if path == "actions/workflows/ci.yml":
            return {"id": 99}
        if path.startswith("actions/workflows/ci.yml/runs?"):
            return {"workflow_runs": [] if scenario == "no-run" else [{"id": 42}]}
        if path == "actions/runs/42":
            run_reads += 1
            result = copy.deepcopy(run)
            if scenario == "run-race" and run_reads > 1:
                result["head_sha"] = "c" * 40
            return result
        raise AssertionError(path)

    def gh(*args: str) -> str:
        writes.append(args)
        if scenario == "approval-uncertain":
            raise subprocess.CalledProcessError(1, args)
        return ""

    positives = {
        "approve",
        "active",
        "passed",
        "no-run",
        "foreign-run-head",
        "foreign-run-base",
        "foreign-run-actor",
        "foreign-run-workflow",
        "foreign-run-pr",
    }
    with (
        patch.object(service, "api", side_effect=api),
        patch.object(service, "gh", side_effect=gh),
    ):
        if scenario in positives:
            service.ensure(4, attempts=1)
        else:
            with pytest.raises(
                (ValueError, RuntimeError, subprocess.CalledProcessError)
            ):
                service.ensure(4, attempts=1)
    approvals = [args for args in writes if args[:3] == ("api", "--method", "POST")]
    assert len(approvals) == (1 if scenario in ("approve", "approval-uncertain") else 0)
    if approvals:
        assert approvals[0][-1] == f"repos/{service.REPO}/actions/runs/42/approve"
    dispatch = [args for args in writes if args[:2] == ("workflow", "run")]
    assert len(dispatch) == (
        1
        if scenario
        in {
            "no-run",
            "foreign-run-head",
            "foreign-run-base",
            "foreign-run-actor",
            "foreign-run-workflow",
            "foreign-run-pr",
        }
        else 0
    )
    if dispatch:
        assert dispatch[0][dispatch[0].index("--ref") + 1] == "main"
        assert "expected-sha=" + "b" * 40 in dispatch[0]
        assert "expected-workflow-sha=" + "a" * 40 in dispatch[0]


def test_approval_pin_and_workflow_permissions_remain_read_only_at_execution() -> None:
    """The privileged planner never checks out or runs arbitrary PR code."""
    root = Path(__file__).resolve().parents[2]
    service = approval_module().ReleaseCI
    ci_bytes = (root / ".github/workflows/ci.yml").read_bytes()
    # API blobs use committed LF; Windows checkouts may translate working copies.
    assert (
        hashlib.sha256(ci_bytes.replace(b"\r\n", b"\n")).hexdigest()
        == service.CI_SHA256
    )
    ci = yaml.safe_load(ci_bytes)
    assert ci["permissions"] == {"contents": "read"}
    assert b"secrets." not in ci_bytes
    assert all(
        not job.get("permissions") and not job.get("environment")
        for job in ci["jobs"].values()
    )
    workflow = yaml.safe_load(
        (root / ".github/workflows/release.yml").read_text(encoding="utf-8")
    )
    planner = workflow["jobs"]["release-please"]
    assert planner["permissions"] == {
        "contents": "write",
        "pull-requests": "write",
        "actions": "write",
    }
    assert not any("checkout@" in step.get("uses", "") for step in planner["steps"])
    expected = (
        "python3 - <<'PY'\n"
        + (root / "scripts/approve_release_ci.py").read_text(encoding="utf-8")
        + "\nPY\n"
    )
    assert planner["steps"][1]["run"] == expected
    assert "merge" not in expected and "/reviews" not in expected


@pytest.mark.parametrize(
    "case",
    [
        "match",
        "source-moved",
        "workflow-moved",
        "malformed-source",
        "malformed-workflow",
        "ordinary",
    ],
)
def test_dispatch_guard_rejects_branch_races_before_package_execution(
    case: str,
) -> None:
    """Execute the actual workflow guard, including an optional ordinary dispatch."""
    bash = (
        str(Path(os.environ["PROGRAMFILES"]) / "Git/bin/bash.exe")
        if os.name == "nt"
        else shutil.which("bash")
    )
    if not bash:
        pytest.skip("Bash is unavailable")
    root = Path(__file__).resolve().parents[2]
    workflow = yaml.safe_load((root / ".github/workflows/ci.yml").read_text())
    script = workflow["jobs"]["check"]["steps"][1]["run"]
    source = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    expected = {
        "source-moved": "b" * 40,
        "malformed-source": "not-a-sha",
        "ordinary": "",
    }.get(case, source)
    expected_workflow = {
        "workflow-moved": "c" * 40,
        "malformed-workflow": "not-a-sha",
    }.get(case, "a" * 40)
    result = subprocess.run(
        [bash, "-c", script],
        env={
            **os.environ,
            "EXPECTED_SHA": expected,
            "EXPECTED_WORKFLOW_SHA": expected_workflow,
            "GITHUB_SHA": "a" * 40,
        },
        cwd=root,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert (result.returncode == 0) == (case in {"match", "ordinary"})
