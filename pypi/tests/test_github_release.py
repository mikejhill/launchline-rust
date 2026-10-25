"""Exercise registry/tag/provenance boundaries and partial GitHub release recovery."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import subprocess
import sys
import tarfile
import tomllib
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml


@pytest.fixture
def release_module() -> object:
    """Load the same standard-library helper inlined into both workflows."""
    path = Path(__file__).resolve().parents[2] / "scripts/github_release.py"
    spec = importlib.util.spec_from_file_location("github_release", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "scenario",
    [
        "new",
        "retry",
        "partial",
        "conflict",
        "uncertain-upload",
        "tag-conflict",
        "registry-conflict",
        "attestation-failure",
        "wrong-run",
        "wrong-source",
        "manifest-crlf",
        "manifest-conflict",
        "posix-bundle",
        "missing-bundle",
    ],
)
def test_verified_release_reconciliation(
    scenario: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    release_module: object,
) -> None:
    """Never publish a draft with missing/conflicting/unverified assets or source."""
    module = release_module
    if scenario == "posix-bundle" and sys.platform == "win32":
        pytest.skip(
            "The POSIX gh filename contains a colon, unsupported by Windows filesystems"
        )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VERSION", "0.2.0")
    monkeypatch.setenv("SOURCE_RUN_ID", "42")
    monkeypatch.setenv(
        "SOURCE_SHA", "b" * 40 if scenario == "wrong-source" else "a" * 40
    )
    directory = tmp_path / "release"
    directory.mkdir()
    archive = directory / "launchline-0.2.0.crate"
    with tarfile.open(archive, "w:gz") as stream:
        for name, content in {
            ".cargo_vcs_info.json": json.dumps({"git": {"sha1": "a" * 40}}),
            "release-changelog.md": "## 0.2.0\n\nNested menus.\n",
        }.items():
            data = content.encode()
            member = tarfile.TarInfo(f"launchline-0.2.0/{name}")
            member.size = len(data)
            stream.addfile(member, io.BytesIO(data))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (directory / "publish.json").write_text(
        json.dumps(
            {
                "crate_file": archive.name,
                "source_sha": "a" * 40,
                "sha256": digest,
                "package": {
                    "name": "launchline",
                    "vers": "0.2.0",
                    "repository": "https://github.com/mikejhill/launchline-rust",
                },
            }
        ),
        encoding="utf-8",
    )
    calls = []
    release = None
    uploaded = {}

    def gh(*args: str) -> str:
        nonlocal release
        calls.append(args)
        if args[:2] == ("attestation", "download"):
            if scenario != "missing-bundle":
                separator = ":" if scenario == "posix-bundle" else "-"
                Path(f"sha256{separator}{digest}.jsonl").write_bytes(b"signed-bundle\n")
        elif args[:2] == ("attestation", "verify"):
            assert "--source-digest" in args and "--source-ref" in args
            assert "--deny-self-hosted-runners" in args and "--signer-workflow" in args
            assert (
                Path(args[args.index("--bundle") + 1]).read_bytes()
                == b"signed-bundle\n"
            )
            if scenario == "attestation-failure":
                raise subprocess.CalledProcessError(1, args)
        elif args[0] == "api":
            path = args[1]
            if "/commits/" in path:
                return json.dumps(
                    {"sha": "b" * 40 if scenario == "tag-conflict" else "a" * 40}
                )
            if "/compare/" in path:
                return json.dumps({"merge_base_commit": {"sha": "a" * 40}})
            if "/actions/runs/" in path:
                return json.dumps(
                    {
                        "id": 42,
                        "head_sha": "a" * 40,
                        "head_branch": "main",
                        "event": "pull_request" if scenario == "wrong-run" else "push",
                        "path": ".github/workflows/release.yml",
                        "status": "completed",
                        "conclusion": "success",
                    }
                )
            if path.endswith("releases?per_page=100"):
                if release is None and scenario in (
                    "retry",
                    "partial",
                    "conflict",
                    "manifest-crlf",
                    "manifest-conflict",
                ):
                    release = {
                        "tag_name": "v0.2.0",
                        "draft": scenario == "partial",
                        "assets": [],
                    }
                    for asset in directory.iterdir():
                        if asset.name == "github-release-notes.md":
                            continue
                        if scenario == "partial" and asset.name != archive.name:
                            continue
                        uploaded[asset.name] = asset.read_bytes()
                        release["assets"].append({"name": asset.name})
                    if scenario == "conflict":
                        uploaded[archive.name] = b"different bytes"
                    if scenario == "manifest-crlf":
                        uploaded["SHA256SUMS"] = uploaded["SHA256SUMS"].replace(
                            b"\n", b"\r\n"
                        )
                    if scenario == "manifest-conflict":
                        uploaded["SHA256SUMS"] += b"different checksum record\n"
                return json.dumps([[release] if release else []])
            if "/releases/tags/" in path or path.endswith("releases/42"):
                return json.dumps(release)
            raise AssertionError(args)
        elif args[:2] == ("release", "create"):
            assert "--draft" in args and "--verify-tag" in args
            release = {"tag_name": "v0.2.0", "draft": True, "assets": []}
        elif args[:2] == ("release", "view"):
            return json.dumps({"databaseId": 42})
        elif args[:2] == ("release", "upload"):
            assert "--clobber" not in args
            if scenario == "uncertain-upload":
                raise subprocess.CalledProcessError(1, args)
            asset = Path(args[3])
            uploaded[asset.name] = asset.read_bytes()
            release["assets"].append({"name": asset.name})
        elif args[:2] == ("release", "download"):
            name = args[args.index("--pattern") + 1]
            target = Path(args[args.index("--dir") + 1]) / name
            target.write_bytes(uploaded[name])
        elif args[:2] == ("release", "edit"):
            assert len(uploaded) == 4, (
                "Never expose a partial draft as a published release"
            )
            release["draft"] = False
        else:
            raise AssertionError(args)
        return ""

    registry = io.BytesIO(
        json.dumps(
            {
                "version": {
                    "checksum": "different"
                    if scenario == "registry-conflict"
                    else digest,
                    "yanked": False,
                }
            }
        ).encode()
    )
    with (
        patch.object(module.GitHubRelease, "gh", side_effect=gh),
        patch.object(module.urllib.request, "urlopen", return_value=registry),
    ):
        if scenario in ("new", "retry", "partial", "manifest-crlf", "posix-bundle"):
            module.GitHubRelease.publish(directory)
            assert release is not None and not release["draft"]
            assert len(uploaded) == 4
        else:
            with pytest.raises((ValueError, subprocess.CalledProcessError)):
                module.GitHubRelease.publish(directory)
            assert not any(call[:2] == ("release", "edit") for call in calls)
    if scenario in ("retry", "manifest-crlf"):
        assert not any(
            call[:2] in (("release", "create"), ("release", "upload")) for call in calls
        )
    if scenario == "uncertain-upload":
        assert len([call for call in calls if call[:2] == ("release", "upload")]) == 1


def test_verifier_failure_reports_sanitized_diagnostic(release_module: object) -> None:
    """Keep the verification gate strict and make its public failure diagnosable."""
    error = subprocess.CalledProcessError(
        1,
        ["gh", "attestation", "verify"],
        stderr="bundle file not found\nAuthorization: Bearer fixture-secret\nghs_fixture_secret",
    )
    with patch.object(release_module.subprocess, "run", side_effect=error):
        with pytest.raises(RuntimeError) as result:
            release_module.GitHubRelease.gh("attestation", "verify", "fixture.crate")
    diagnostic = str(result.value)
    assert "bundle file not found" in diagnostic
    assert "fixture-secret" not in diagnostic and "ghs_fixture_secret" not in diagnostic
    assert "[redacted]" in diagnostic


def test_release_workflows_require_review_and_preserve_publisher_isolation() -> None:
    """New versions need reviewed release PRs; page repair cannot publish packages."""
    root = Path(__file__).resolve().parents[2]
    normal = yaml.safe_load(
        (root / ".github/workflows/release.yml").read_text(encoding="utf-8")
    )
    repair = yaml.safe_load(
        (root / ".github/workflows/repair-github-release.yml").read_text(
            encoding="utf-8"
        )
    )
    config = json.loads(
        (root / "release-please-config.json").read_text(encoding="utf-8")
    )
    manifest = json.loads(
        (root / ".release-please-manifest.json").read_text(encoding="utf-8")
    )
    assert config["release-type"] == "rust" and config["draft"]
    cargo = tomllib.loads((root / "Cargo.toml").read_text(encoding="utf-8"))
    assert config["force-tag-creation"]
    assert manifest["."] == cargo["package"]["version"], (
        "Release PRs must update Cargo and the manifest together, without freezing the bootstrap version"
    )
    assert normal["jobs"]["target"]["needs"] == ["release-please"]
    assert "release_created == 'true'" in normal["jobs"]["target"]["if"]
    planner = normal["jobs"]["release-please"]
    assert "pull-requests" in planner["permissions"]
    assert not any("checkout@" in step.get("uses", "") for step in planner["steps"])
    assert not any(
        "approve" in step.get("run", "") or "merge" in step.get("run", "")
        for step in planner["steps"]
    )
    assert set(repair["jobs"]) == {"github-release"}
    assert set(normal["jobs"]["github-release"]["needs"]) == {
        "target",
        "build",
        "crates",
        "source-tag",
    }
    expected = (
        "python3 - <<'PY'\n"
        + (root / "scripts/github_release.py").read_text(encoding="utf-8")
        + "\nPY\n"
    )
    for workflow in (normal, repair):
        writer = workflow["jobs"]["github-release"]
        assert "github.actor == 'mikejhill'" in writer["if"]
        assert "github.triggering_actor == 'mikejhill'" in writer["if"]
        assert writer["permissions"]["contents"] == "write"
        assert "id-token" not in writer["permissions"]
        assert not any("checkout@" in step.get("uses", "") for step in writer["steps"])
        assert writer["steps"][-1]["run"] == expected
        assert "--clobber" not in expected and "cargo publish" not in expected
