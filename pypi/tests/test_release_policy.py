"""Offline tests of exact crate upload bytes, retries and publisher boundaries."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import shutil
import struct
import subprocess
import sys
import urllib.error
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml


class TestCratePublisher:
    """Intercept every registry call while executing the production upload helper."""

    @staticmethod
    def _module() -> object:
        """Load the checked-in standard-library-only publisher."""
        root = Path(__file__).resolve().parents[2]
        spec = importlib.util.spec_from_file_location(
            "crate_upload", root / "scripts/crate_upload.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    @staticmethod
    def _bundle(path: Path) -> str:
        """Prepare harmless archive bytes and their exact release identity."""
        payload = b"tested crate bytes"
        digest = hashlib.sha256(payload).hexdigest()
        (path / "launchline-0.1.0.crate").write_bytes(payload)
        (path / "publish.json").write_text(
            json.dumps(
                {
                    "crate_file": "launchline-0.1.0.crate",
                    "source_sha": "a" * 40,
                    "sha256": digest,
                    "package": {
                        "name": "launchline",
                        "vers": "0.1.0",
                        "repository": "https://github.com/mikejhill/launchline-rust",
                    },
                }
            ),
            encoding="utf-8",
        )
        return digest

    @pytest.mark.parametrize(
        "scenario",
        [
            "new",
            "retry",
            "conflict",
            "tamper",
            "wrong-source",
            "inspection-denied",
            "upload-uncertain",
        ],
    )
    def test_real_upload_protocol_and_fail_closed_retry(
        self, scenario: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Only validated bytes can reach the fixed authenticated PUT endpoint."""
        module = self._module()
        digest = self._bundle(tmp_path)
        monkeypatch.setenv("VERSION", "0.1.0")
        monkeypatch.setenv(
            "GITHUB_SHA", "b" * 40 if scenario == "wrong-source" else "a" * 40
        )
        monkeypatch.setenv("CRATES_IO_TOKEN", "offline-fixture-token")
        if scenario == "tamper":
            (tmp_path / "launchline-0.1.0.crate").write_bytes(b"tampered")
        calls: list[object] = []

        class Registry:
            """A deterministic registry boundary, never a network server."""

            def open(self, request: object, timeout: int) -> io.BytesIO:
                """Capture the exact framed request and emulate registry states."""
                assert timeout in (30, 60), "Every request must be bounded"
                calls.append(request)
                if request.get_method() == "PUT":
                    assert request.full_url == "https://crates.io/api/v1/crates/new"
                    assert (
                        request.get_header("Authorization") == "offline-fixture-token"
                    )
                    data = request.data
                    length = struct.unpack("<I", data[:4])[0]
                    assert json.loads(data[4 : 4 + length])["vers"] == "0.1.0"
                    offset = 4 + length
                    size = struct.unpack("<I", data[offset : offset + 4])[0]
                    assert data[offset + 4 :] == b"tested crate bytes" and size == len(
                        b"tested crate bytes"
                    )
                    if scenario == "upload-uncertain":
                        raise urllib.error.URLError("fixture connection closed")
                    return io.BytesIO(b"{}")
                assert request.get_header("Authorization") is None, (
                    "Public inspection must not disclose the token"
                )
                if scenario == "inspection-denied":
                    raise urllib.error.HTTPError(
                        request.full_url, 403, "fixture", {}, None
                    )
                if scenario == "conflict":
                    return io.BytesIO(b'{"version":{"checksum":"different"}}')
                if scenario == "retry" or any(
                    call.get_method() == "PUT" for call in calls
                ):
                    return io.BytesIO(
                        json.dumps({"version": {"checksum": digest}}).encode()
                    )
                raise urllib.error.HTTPError(request.full_url, 404, "fixture", {}, None)

        registry = Registry()
        with patch.object(module.urllib.request, "build_opener", return_value=registry):
            if scenario in ("new", "retry"):
                module.CrateUpload.publish(tmp_path)
            else:
                with pytest.raises((ValueError, RuntimeError)):
                    module.CrateUpload.publish(tmp_path)
        puts = [call for call in calls if call.get_method() == "PUT"]
        assert len(puts) == (1 if scenario in ("new", "upload-uncertain") else 0), (
            "Never blindly retry uncertain uploads"
        )

    def test_authenticated_redirects_are_rejected(self) -> None:
        """A registry redirect cannot forward authorization to another origin."""
        module = self._module()
        assert (
            module.NoRedirect().redirect_request(
                None, None, 302, "redirect", {}, "https://example.invalid"
            )
            is None
        )

    def test_workflow_runs_only_pinned_isolated_publisher(self) -> None:
        """No wrapper/binary publisher or checked-out package code receives credentials."""
        root = Path(__file__).resolve().parents[2]
        workflow = yaml.safe_load(
            (root / ".github/workflows/release.yml").read_text(encoding="utf-8")
        )
        assert "pypi" not in workflow["jobs"], "Rust packages publish only to crates.io"
        publisher = workflow["jobs"]["crates"]
        assert "github.actor == 'mikejhill'" in publisher["if"]
        assert "github.triggering_actor == 'mikejhill'" in publisher["if"]
        assert publisher["environment"] == "crates-io"
        assert publisher["permissions"] == {"contents": "read", "id-token": "write"}
        assert not any(
            "checkout@" in step.get("uses", "") for step in publisher["steps"]
        )
        body = next(
            step["run"]
            for step in publisher["steps"]
            if step.get("name")
            == "Publish prebuilt archive without executing package code"
        )
        expected = (
            "python3 - <<'PY'\n"
            + (root / "scripts/crate_upload.py").read_text(encoding="utf-8")
            + "\nPY\n"
        )
        assert body == expected, (
            "Offline protocol tests must exercise the actual inline publisher"
        )
        assert "cargo publish" not in body and "subprocess" not in body, (
            "Publisher uploads already-compiled bytes only"
        )
        assert workflow["jobs"]["build"]["if"].endswith(
            "needs.target.outputs.version != ''"
        ), "Non-release commits must not publish"


class TestSourceTagPolicy:
    """Execute the actual source-tag shell against an offline GitHub boundary."""

    @pytest.mark.parametrize(
        ("scenario", "expected"),
        [("normal", 0), ("retry", 0), ("tag-conflict", 1), ("not-on-main", 1)],
    )
    def test_source_tags_require_matching_ancestry(
        self, scenario: str, expected: int, tmp_path: Path
    ) -> None:
        """Conflicting refs fail and source-only retries preserve immutable tags."""
        root = Path(__file__).resolve().parents[2]
        workflow = yaml.safe_load(
            (root / ".github/workflows/release.yml").read_text(encoding="utf-8")
        )
        job = workflow["jobs"]["source-tag"]
        assert job["permissions"] == {"contents": "write"}
        body = job["steps"][0]["run"]
        fake = r"""
set -euo pipefail
python3() { "$FIXTURE_PYTHON" "$@"; }
gh() {
  case "$*" in
    "api repos/fixture/launchline/compare/"*)
      if [ "$SCENARIO" = not-on-main ]; then echo bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb; else echo "$GITHUB_SHA"; fi ;;
    "api --method POST"*)
      if [ "$SCENARIO" = retry ] || [ "$SCENARIO" = tag-conflict ]; then return 1; fi ;;
    "api repos/fixture/launchline/commits/"*)
      if [ "$SCENARIO" = tag-conflict ]; then echo bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb; else echo "$GITHUB_SHA"; fi ;;
    *) echo 'Unexpected offline GitHub call' >&2; return 99 ;;
  esac
}
"""
        bash = (
            str(Path(os.environ["PROGRAMFILES"]) / "Git/bin/bash.exe")
            if sys.platform == "win32"
            else shutil.which("bash")
        )
        assert bash is not None
        result = subprocess.run(
            [bash, "-c", fake + body],
            cwd=tmp_path,
            env={
                **os.environ,
                "FIXTURE_PYTHON": str(Path(sys.executable)).replace("\\", "/"),
                "SCENARIO": scenario,
                "GITHUB_SHA": "a" * 40,
                "GITHUB_REPOSITORY": "fixture/launchline",
                "TAG": "v0.1.0",
            },
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        assert result.returncode == expected, result.stderr
        assert "release create" not in body and "release upload" not in body, (
            "Source tagging must stay separate from verified GitHub release assets"
        )


class TestReleaseCheckParity:
    """Prevent the inline release matrix from losing normal CI checks."""

    def test_release_and_pr_checks_match_except_checkout_ref(self) -> None:
        root = Path(__file__).resolve().parents[2]
        ci = yaml.safe_load(
            (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        )
        release = yaml.safe_load(
            (root / ".github/workflows/release.yml").read_text(encoding="utf-8")
        )
        expected = ci["jobs"]["check"]
        expected["steps"][0]["with"]["ref"] = "${{ github.sha }}"
        expected["steps"][1]["env"]["EXPECTED_SHA"] = "${{ github.sha }}"
        expected["steps"][1]["env"]["EXPECTED_WORKFLOW_SHA"] = "${{ github.sha }}"
        assert release["jobs"]["ci"] == expected, (
            "Release must retain the complete exact-head test matrix"
        )


class TestPreUploadSourcePolicy:
    """Run the actual pre-authentication main/tag boundary without network calls."""

    @pytest.mark.parametrize(
        ("scenario", "expected"),
        [("normal", 0), ("tag-conflict", 1), ("not-on-main", 1)],
    )
    def test_preflight_rejects_conflicting_source_before_oidc(
        self, scenario: str, expected: int, tmp_path: Path
    ) -> None:
        root = Path(__file__).resolve().parents[2]
        workflow = yaml.safe_load(
            (root / ".github/workflows/release.yml").read_text(encoding="utf-8")
        )
        steps = workflow["jobs"]["crates"]["steps"]
        body = next(
            step["run"]
            for step in steps
            if step.get("name") == "Validate source ancestry and immutable tag boundary"
        )
        auth = next(
            index for index, step in enumerate(steps) if step.get("id") == "auth"
        )
        validation = next(
            index
            for index, step in enumerate(steps)
            if step.get("name") == "Validate artifact before requesting credentials"
        )
        assert validation < auth, (
            "Validate untrusted artifact bytes before acquiring a publishing credential"
        )
        fake = r"""
set -euo pipefail
gh() {
  case "$*" in
    "api repos/fixture/launchline/compare/"*)
      if [ "$SCENARIO" = not-on-main ]; then echo bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb; else echo "$GITHUB_SHA"; fi ;;
    "api repos/fixture/launchline/git/matching-refs/"*)
      if [ "$SCENARIO" = tag-conflict ]; then echo bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb; else echo ''; fi ;;
    *) echo 'Unexpected offline GitHub call' >&2; return 99 ;;
  esac
}
"""
        bash = (
            str(Path(os.environ["PROGRAMFILES"]) / "Git/bin/bash.exe")
            if sys.platform == "win32"
            else shutil.which("bash")
        )
        assert bash is not None
        result = subprocess.run(
            [bash, "-c", fake + body],
            cwd=tmp_path,
            env={
                **os.environ,
                "SCENARIO": scenario,
                "GITHUB_SHA": "a" * 40,
                "GITHUB_REPOSITORY": "fixture/launchline",
                "TAG": "v0.1.0",
                "VERSION": "0.1.0",
            },
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        assert result.returncode == expected, result.stderr
