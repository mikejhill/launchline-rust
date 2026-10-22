"""Tests for the LaunchLine PyPI binary wrapper."""

from __future__ import annotations

import hashlib
import io
import os
import stat
import tarfile
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from launchline._wrapper import (
    _PLATFORM_MAP,
    _binary_name,
    _download_and_extract,
    _ensure_binary,
    _get_cache_dir,
    _resolve_artifact,
    main,
)

# ---------------------------------------------------------------------------
# _get_cache_dir
# ---------------------------------------------------------------------------


class TestGetCacheDir:
    """Tests for cache directory resolution."""

    @patch("launchline._wrapper.os.name", "nt")
    @patch.dict(
        "os.environ", {"LOCALAPPDATA": r"C:\Users\Test\AppData\Local"}, clear=False
    )
    def test_windows_uses_localappdata(self) -> None:
        result = _get_cache_dir()
        assert result == Path(r"C:\Users\Test\AppData\Local") / "launchline" / "bin", (
            f"Expected LOCALAPPDATA-based path on Windows, got {result}"
        )

    @pytest.mark.skipif(os.name == "nt", reason="PosixPath unavailable on Windows")
    @patch("launchline._wrapper.os.name", "posix")
    @patch.dict("os.environ", {"XDG_CACHE_HOME": "/custom/cache"}, clear=False)
    def test_posix_respects_xdg_cache_home(self) -> None:
        result = _get_cache_dir()
        assert str(result) == str(Path("/custom/cache/launchline/bin")), (
            f"Expected XDG_CACHE_HOME-based path, got {result}"
        )

    @pytest.mark.skipif(os.name == "nt", reason="PosixPath unavailable on Windows")
    @patch("launchline._wrapper.os.name", "posix")
    @patch.dict("os.environ", {}, clear=True)
    @patch("launchline._wrapper.Path.home", return_value=Path("/home/testuser"))
    def test_posix_falls_back_to_dot_cache(self, _mock_home: MagicMock) -> None:
        result = _get_cache_dir()
        assert str(result) == str(Path("/home/testuser/.cache/launchline/bin")), (
            f"Expected ~/.cache fallback, got {result}"
        )


# ---------------------------------------------------------------------------
# _binary_name
# ---------------------------------------------------------------------------


class TestBinaryName:
    """Tests for platform-specific binary naming."""

    @patch("launchline._wrapper.platform.system", return_value="Windows")
    def test_windows_returns_exe(self, _mock: MagicMock) -> None:
        assert _binary_name() == "launchline.exe", "Expected .exe extension on Windows"

    @patch("launchline._wrapper.platform.system", return_value="Linux")
    def test_linux_returns_no_extension(self, _mock: MagicMock) -> None:
        assert _binary_name() == "launchline", "Expected no extension on Linux"

    @patch("launchline._wrapper.platform.system", return_value="Darwin")
    def test_macos_returns_no_extension(self, _mock: MagicMock) -> None:
        assert _binary_name() == "launchline", "Expected no extension on macOS"


# ---------------------------------------------------------------------------
# _resolve_artifact
# ---------------------------------------------------------------------------


class TestResolveArtifact:
    """Tests for platform-to-artifact resolution."""

    @patch("launchline._wrapper.version", return_value="0.3.0")
    @patch("launchline._wrapper.platform.machine", return_value="x86_64")
    @patch("launchline._wrapper.platform.system", return_value="Linux")
    def test_linux_x64_resolves_correctly(self, *_mocks: MagicMock) -> None:
        artifact, url = _resolve_artifact()
        assert artifact == "launchline-linux-x64", (
            f"Expected linux-x64 artifact, got {artifact}"
        )
        assert url.endswith("launchline-linux-x64.tar.gz"), (
            f"Expected .tar.gz URL for Linux, got {url}"
        )
        assert "v0.3.0" in url, f"Expected version in URL, got {url}"

    @patch("launchline._wrapper.version", return_value="0.3.0")
    @patch("launchline._wrapper.platform.machine", return_value="AMD64")
    @patch("launchline._wrapper.platform.system", return_value="Windows")
    def test_windows_amd64_resolves_to_zip(self, *_mocks: MagicMock) -> None:
        artifact, url = _resolve_artifact()
        assert artifact == "launchline-windows-x64", (
            f"Expected windows-x64 artifact, got {artifact}"
        )
        assert url.endswith(".zip"), f"Expected .zip URL for Windows, got {url}"

    @patch("launchline._wrapper.version", return_value="1.2.3")
    @patch("launchline._wrapper.platform.machine", return_value="arm64")
    @patch("launchline._wrapper.platform.system", return_value="Darwin")
    def test_macos_arm64_uses_correct_version(self, *_mocks: MagicMock) -> None:
        artifact, url = _resolve_artifact()
        assert artifact == "launchline-macos-arm64", (
            f"Expected macos-arm64 artifact, got {artifact}"
        )
        assert "/v1.2.3/" in url, f"Expected version 1.2.3 in URL, got {url}"

    @patch("launchline._wrapper.platform.machine", return_value="mips64")
    @patch("launchline._wrapper.platform.system", return_value="Linux")
    def test_unsupported_platform_raises_runtime_error(
        self, *_mocks: MagicMock
    ) -> None:
        with pytest.raises(RuntimeError, match="Unsupported platform"):
            _resolve_artifact()

    def test_platform_map_covers_all_major_platforms(self) -> None:
        expected_systems = {"Linux", "Darwin", "Windows"}
        actual_systems = {k[0] for k in _PLATFORM_MAP}
        assert expected_systems == actual_systems, (
            f"Platform map missing systems: {expected_systems - actual_systems}"
        )

    def test_platform_map_has_eight_entries(self) -> None:
        # Linux x64/arm64, Darwin x64/arm64, Windows AMD64/x86_64/arm64
        assert len(_PLATFORM_MAP) == 8, (
            f"Expected 8 platform mappings, got {len(_PLATFORM_MAP)}"
        )


# ---------------------------------------------------------------------------
# _download_and_extract
# ---------------------------------------------------------------------------


class TestDownloadAndExtract:
    """Tests for archive download and binary extraction."""

    def _make_tar_gz(self, binary_name: str, content: bytes) -> bytes:
        """Create an in-memory .tar.gz archive containing a single binary."""
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            info = tarfile.TarInfo(name=binary_name)
            info.size = len(content)
            tf.addfile(info, io.BytesIO(content))
        return buf.getvalue()

    def _make_zip(self, binary_name: str, content: bytes) -> bytes:
        """Create an in-memory .zip archive containing a single binary."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(binary_name, content)
        return buf.getvalue()

    @patch("launchline._wrapper.platform.system", return_value="Linux")
    def test_extracts_binary_from_tar_gz(
        self, _mock: MagicMock, tmp_path: Path
    ) -> None:
        archive_data = self._make_tar_gz("launchline", b"FAKE_BINARY")
        url = "https://example.com/launchline.tar.gz"

        mock_resp = MagicMock()
        mock_resp.read.side_effect = [
            archive_data,
            (
                hashlib.sha256(archive_data).hexdigest() + "  " + url.rsplit("/", 1)[1]
            ).encode("ascii"),
        ]
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch(
            "launchline._wrapper.urllib.request.urlopen", return_value=mock_resp
        ):
            result = _download_and_extract(url, tmp_path)

        assert result.exists(), f"Binary not found at {result}"
        assert result.read_bytes() == b"FAKE_BINARY", (
            "Extracted binary content mismatch"
        )
        if os.name != "nt":
            assert result.stat().st_mode & stat.S_IEXEC, (
                "Binary should be executable on Unix"
            )

    @patch("launchline._wrapper.platform.system", return_value="Windows")
    def test_extracts_binary_from_zip(self, _mock: MagicMock, tmp_path: Path) -> None:
        archive_data = self._make_zip("launchline.exe", b"FAKE_BINARY_WIN")
        url = "https://example.com/launchline.zip"

        mock_resp = MagicMock()
        mock_resp.read.side_effect = [
            archive_data,
            (
                hashlib.sha256(archive_data).hexdigest() + "  " + url.rsplit("/", 1)[1]
            ).encode("ascii"),
        ]
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch(
            "launchline._wrapper.urllib.request.urlopen", return_value=mock_resp
        ):
            result = _download_and_extract(url, tmp_path)

        assert result.exists(), f"Binary not found at {result}"
        assert result.read_bytes() == b"FAKE_BINARY_WIN", (
            "Extracted binary content mismatch"
        )

    @patch("launchline._wrapper.platform.system", return_value="Linux")
    def test_tar_gz_missing_binary_raises_error(
        self, _mock: MagicMock, tmp_path: Path
    ) -> None:
        archive_data = self._make_tar_gz("wrong_name", b"IRRELEVANT")
        url = "https://example.com/launchline.tar.gz"

        mock_resp = MagicMock()
        mock_resp.read.side_effect = [
            archive_data,
            (
                hashlib.sha256(archive_data).hexdigest() + "  " + url.rsplit("/", 1)[1]
            ).encode("ascii"),
        ]
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with (
            patch("launchline._wrapper.urllib.request.urlopen", return_value=mock_resp),
            pytest.raises(RuntimeError, match="not found in archive"),
        ):
            _download_and_extract(url, tmp_path)

    @patch("launchline._wrapper.platform.system", return_value="Windows")
    def test_zip_missing_binary_raises_error(
        self, _mock: MagicMock, tmp_path: Path
    ) -> None:
        archive_data = self._make_zip("wrong_name.exe", b"IRRELEVANT")
        url = "https://example.com/launchline.zip"

        mock_resp = MagicMock()
        mock_resp.read.side_effect = [
            archive_data,
            (
                hashlib.sha256(archive_data).hexdigest() + "  " + url.rsplit("/", 1)[1]
            ).encode("ascii"),
        ]
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with (
            patch("launchline._wrapper.urllib.request.urlopen", return_value=mock_resp),
            pytest.raises(RuntimeError, match="not found in archive"),
        ):
            _download_and_extract(url, tmp_path)

    @patch("launchline._wrapper.platform.system", return_value="Linux")
    def test_creates_destination_directory(
        self, _mock: MagicMock, tmp_path: Path
    ) -> None:
        dest = tmp_path / "nested" / "dir"
        archive_data = self._make_tar_gz("launchline", b"BIN")
        url = "https://example.com/launchline.tar.gz"

        mock_resp = MagicMock()
        mock_resp.read.side_effect = [
            archive_data,
            (
                hashlib.sha256(archive_data).hexdigest() + "  " + url.rsplit("/", 1)[1]
            ).encode("ascii"),
        ]
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch(
            "launchline._wrapper.urllib.request.urlopen", return_value=mock_resp
        ):
            result = _download_and_extract(url, dest)

        assert dest.is_dir(), "Should have created nested directories"
        assert result.exists(), "Binary should exist in created directory"


# ---------------------------------------------------------------------------
# _ensure_binary
# ---------------------------------------------------------------------------


class TestEnsureBinary:
    """Tests for binary caching logic."""

    @patch("launchline._wrapper.version", return_value="0.3.0")
    @patch("launchline._wrapper._get_cache_dir")
    def test_returns_cached_binary_without_downloading(
        self, mock_cache_dir: MagicMock, _mock_ver: MagicMock, tmp_path: Path
    ) -> None:
        mock_cache_dir.return_value = tmp_path
        versioned_dir = tmp_path / "0.3.0"
        versioned_dir.mkdir()
        binary = versioned_dir / _binary_name()
        binary.write_bytes(b"CACHED")

        result = _ensure_binary()
        assert result == binary, f"Expected cached path {binary}, got {result}"

    @patch("launchline._wrapper._download_and_extract")
    @patch(
        "launchline._wrapper._resolve_artifact",
        return_value=("launchline-linux-x64", "https://example.com/bin.tar.gz"),
    )
    @patch("launchline._wrapper.version", return_value="0.3.0")
    @patch("launchline._wrapper._get_cache_dir")
    def test_downloads_when_not_cached(
        self,
        mock_cache_dir: MagicMock,
        _mock_ver: MagicMock,
        _mock_resolve: MagicMock,
        mock_download: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_cache_dir.return_value = tmp_path
        expected_binary = tmp_path / "0.3.0" / _binary_name()
        mock_download.return_value = expected_binary

        result = _ensure_binary()
        mock_download.assert_called_once()
        assert result == expected_binary, (
            f"Expected downloaded path {expected_binary}, got {result}"
        )


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


class TestMain:
    """Tests for the main entry point."""

    @patch("launchline._wrapper.subprocess.run")
    @patch("launchline._wrapper._ensure_binary")
    def test_main_passes_argv_to_binary(
        self, mock_ensure: MagicMock, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        binary = tmp_path / "launchline"
        binary.write_bytes(b"BIN")
        mock_ensure.return_value = binary
        mock_run.return_value = MagicMock(returncode=0)

        with (
            patch("sys.argv", ["launchline", "--config", "my.toml"]),
            pytest.raises(SystemExit) as exc_info,
        ):
            main()

        assert exc_info.value.code == 0, (
            f"Expected exit code 0, got {exc_info.value.code}"
        )
        call_args = mock_run.call_args[0][0]
        assert call_args == [str(binary), "--config", "my.toml"], (
            f"Expected binary + forwarded args, got {call_args}"
        )

    @patch("launchline._wrapper.subprocess.run")
    @patch("launchline._wrapper._ensure_binary")
    def test_main_forwards_nonzero_exit_code(
        self, mock_ensure: MagicMock, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        binary = tmp_path / "launchline"
        binary.write_bytes(b"BIN")
        mock_ensure.return_value = binary
        mock_run.return_value = MagicMock(returncode=42)

        with patch("sys.argv", ["launchline"]), pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 42, (
            f"Expected exit code 42, got {exc_info.value.code}"
        )

    @patch(
        "launchline._wrapper._ensure_binary",
        side_effect=RuntimeError("download failed"),
    )
    def test_main_handles_binary_download_failure(self, _mock: MagicMock) -> None:
        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1, (
            f"Expected exit code 1 on failure, got {exc_info.value.code}"
        )
