"""Binary wrapper that downloads, caches, and executes the native LaunchLine binary."""

from __future__ import annotations

import hashlib
import io
import os
import platform
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

_GITHUB_REPO = "mikejhill/launchline-rust"

_PLATFORM_MAP: dict[tuple[str, str], str] = {
    ("Linux", "x86_64"): "launchline-linux-x64",
    ("Linux", "aarch64"): "launchline-linux-arm64",
    ("Darwin", "x86_64"): "launchline-macos-x64",
    ("Darwin", "arm64"): "launchline-macos-arm64",
    ("Windows", "AMD64"): "launchline-windows-x64",
    ("Windows", "x86_64"): "launchline-windows-x64",
    ("Windows", "aarch64"): "launchline-windows-arm64",
    ("Windows", "ARM64"): "launchline-windows-arm64",
}


class NativeLauncher:
    """Resolve, verify, cache, and execute a native LaunchLine distribution."""

    @staticmethod
    def _get_cache_dir() -> Path:
        """Return the platform-appropriate cache directory for LaunchLine binaries."""
        base = (
            Path(os.environ.get("XDG_CACHE_HOME", "")) if os.name != "nt" else Path("")
        )
        if not base.is_absolute():
            if os.name == "nt":
                base = Path(
                    os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")
                )
            else:
                base = Path.home() / ".cache"
        return base / "launchline" / "bin"

    @staticmethod
    def _resolve_artifact() -> tuple[str, str]:
        """Determine the artifact name and download URL for the current platform.

        Returns:
            A (artifact_name, download_url) tuple.

        Raises:
            RuntimeError: If the current platform is unsupported.
        """
        system = platform.system()
        machine = platform.machine()
        key = (system, machine)

        artifact = _PLATFORM_MAP.get(key)
        if artifact is None:
            raise RuntimeError(
                f"Unsupported platform: {system} {machine}. "
                f"Supported: {', '.join(f'{s}/{m}' for s, m in sorted(_PLATFORM_MAP))}"
            )

        pkg_version = version("launchline-rust")
        ext = "zip" if system == "Windows" else "tar.gz"
        url = f"https://github.com/{_GITHUB_REPO}/releases/download/v{pkg_version}/{artifact}.{ext}"

        return artifact, url

    @staticmethod
    def _binary_name() -> str:
        """Return the expected binary filename for this OS."""
        return "launchline.exe" if platform.system() == "Windows" else "launchline"

    @staticmethod
    def _download_and_extract(url: str, dest: Path) -> Path:
        """Download a release archive and extract the binary to *dest*.

        Returns:
            Path to the extracted binary.
        """
        dest.mkdir(parents=True, exist_ok=True)
        binary_path = dest / _binary_name()

        sys.stderr.write(f"Downloading LaunchLine from {url} ...\n")

        with urllib.request.urlopen(url, timeout=30) as resp:
            data = resp.read(64 * 1024 * 1024 + 1)
        if len(data) > 64 * 1024 * 1024:
            raise RuntimeError("Release archive exceeds size limit")
        checksum_url = url.rsplit("/", 1)[0] + "/SHA256SUMS"
        with urllib.request.urlopen(checksum_url, timeout=30) as response:
            checksum_text = response.read(1024 * 1024).decode("ascii")
        expected_name = url.rsplit("/", 1)[1]
        matches = [
            line.split()
            for line in checksum_text.splitlines()
            if len(line.split()) == 2 and line.split()[1] == expected_name
        ]
        if len(matches) != 1 or hashlib.sha256(data).hexdigest() != matches[0][0]:
            raise RuntimeError(
                "Release archive checksum mismatch or missing manifest entry"
            )
        payload: bytes | None = None
        icon: bytes | None = None

        if url.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                for member in zf.namelist():
                    if member == _binary_name():
                        if zf.getinfo(member).file_size > 64 * 1024 * 1024:
                            raise RuntimeError("Release binary exceeds size limit")
                        payload = zf.read(member)
                if "assets/launchline.ico" in zf.namelist():
                    icon = zf.read("assets/launchline.ico")
                if payload is None:
                    raise RuntimeError(
                        f"Binary '{_binary_name()}' not found in archive"
                    )
        else:
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
                for member in tf.getmembers():
                    if member.name == _binary_name() and member.isfile():
                        extracted = tf.extractfile(member)
                        if extracted is None:
                            raise RuntimeError(
                                f"Cannot extract '{member.name}' from archive"
                            )
                        if member.size > 64 * 1024 * 1024:
                            raise RuntimeError("Release binary exceeds size limit")
                        payload = extracted.read()
                try:
                    icon_member = tf.getmember("assets/launchline.ico")
                except KeyError:
                    icon_member = None
                if icon_member is not None and icon_member.isfile():
                    icon_stream = tf.extractfile(icon_member)
                    if icon_stream is not None:
                        icon = icon_stream.read(1024 * 1024)
                if payload is None:
                    raise RuntimeError(
                        f"Binary '{_binary_name()}' not found in archive"
                    )

        if payload is None:
            raise RuntimeError(f"Binary '{_binary_name()}' not found in archive")
        if icon is not None:
            (dest / "assets").mkdir(exist_ok=True)
            (dest / "assets/launchline.ico").write_bytes(icon)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=dest, prefix=".download-", delete=False
            ) as stream:
                temporary_path = Path(stream.name)
                stream.write(payload)
            if platform.system() != "Windows":
                temporary_path.chmod(temporary_path.stat().st_mode | stat.S_IEXEC)
            os.replace(temporary_path, binary_path)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

        if platform.system() != "Windows":
            binary_path.chmod(binary_path.stat().st_mode | stat.S_IEXEC)

        return binary_path

    @staticmethod
    def _ensure_binary() -> Path:
        """Return the path to the cached binary, downloading if necessary."""
        pkg_version = version("launchline-rust")
        cache_dir = _get_cache_dir() / pkg_version

        binary_path = cache_dir / _binary_name()
        if binary_path.is_file():
            return binary_path

        _artifact, url = _resolve_artifact()
        return _download_and_extract(url, cache_dir)

    @staticmethod
    def main() -> None:
        """Download (if needed) and execute the native LaunchLine binary."""
        try:
            binary = _ensure_binary()
        except (
            OSError,
            RuntimeError,
            ValueError,
            tarfile.TarError,
            zipfile.BadZipFile,
            PackageNotFoundError,
        ) as exc:
            sys.stderr.write(f"launchline: failed to obtain binary: {exc}\n")
            sys.exit(1)

        try:
            result = subprocess.run([str(binary), *sys.argv[1:]], check=False)
        except OSError as exc:
            sys.stderr.write(f"launchline: cannot execute binary: {exc}\n")
            raise SystemExit(1) from exc
        except KeyboardInterrupt as exc:
            raise SystemExit(130) from exc
        sys.exit(result.returncode)


_get_cache_dir = NativeLauncher._get_cache_dir
_resolve_artifact = NativeLauncher._resolve_artifact
_binary_name = NativeLauncher._binary_name
_download_and_extract = NativeLauncher._download_and_extract
_ensure_binary = NativeLauncher._ensure_binary
main = NativeLauncher.main

if __name__ == "__main__":
    main()
