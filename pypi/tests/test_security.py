"""Archive integrity and interrupted cache-write regressions."""

from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from launchline._wrapper import _download_and_extract, _resolve_artifact


class TestArchiveSecurity:
    """Reject unverified bytes before exposing an executable cache entry."""

    def test_checksum_mismatch_leaves_no_binary(self, tmp_path: Path) -> None:
        """Tampered downloads must not create an executable."""
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as archive:
            archive.writestr("launchline.exe", b"tampered")
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.side_effect = [data.getvalue(), b"0" * 64 + b"  launchline.zip"]
        with (
            patch("launchline._wrapper.urllib.request.urlopen", return_value=response),
            patch("launchline._wrapper.platform.system", return_value="Windows"),
            pytest.raises(RuntimeError, match="checksum"),
        ):
            _download_and_extract("https://example.com/launchline.zip", tmp_path)
        assert not (tmp_path / "launchline.exe").exists(), (
            "Tampered archive must not enter cache"
        )

    def test_resolves_wrapper_distribution_version(self) -> None:
        """Resolve launchline-rust metadata rather than unrelated Python distribution."""
        with patch("launchline._wrapper.version", return_value="0.3.0") as metadata:
            _resolve_artifact()
        metadata.assert_called_once_with("launchline-rust")

    @staticmethod
    def _response(member: str) -> MagicMock:
        """Create a checksum-valid archive response at the network boundary."""
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, "w") as archive:
            archive.writestr(member, b"binary")
        data = payload.getvalue()
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.side_effect = [
            data,
            (hashlib.sha256(data).hexdigest() + "  launchline.zip").encode("ascii"),
        ]
        return response

    def test_interrupted_replace_leaves_no_partial_cache(self, tmp_path: Path) -> None:
        """An interrupted atomic replacement must not expose a partial binary."""
        with (
            patch(
                "launchline._wrapper.urllib.request.urlopen",
                return_value=self._response("launchline.exe"),
            ),
            patch("launchline._wrapper.platform.system", return_value="Windows"),
            patch("launchline._wrapper.os.replace", side_effect=OSError("interrupted")),
            pytest.raises(OSError, match="interrupted"),
        ):
            _download_and_extract("https://example.com/launchline.zip", tmp_path)
        assert not (tmp_path / "launchline.exe").exists(), (
            "Partial binaries must not be executable cache entries"
        )
        assert not list(tmp_path.glob(".download-*")), (
            "Temporary files must be cleaned after interruption"
        )

    def test_nested_suffix_impostor_is_rejected(self, tmp_path: Path) -> None:
        """Only the exact root binary member may enter the executable cache."""
        with (
            patch(
                "launchline._wrapper.urllib.request.urlopen",
                return_value=self._response("evil/launchline.exe"),
            ),
            patch("launchline._wrapper.platform.system", return_value="Windows"),
            pytest.raises(RuntimeError, match="not found"),
        ):
            _download_and_extract("https://example.com/launchline.zip", tmp_path)
        assert not (tmp_path / "launchline.exe").exists(), (
            "Suffix matches must not be accepted as binaries"
        )
