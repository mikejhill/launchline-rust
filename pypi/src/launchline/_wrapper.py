"""Binary wrapper that downloads, caches, and executes the native LaunchLine binary."""

from __future__ import annotations

import io
import os
import platform
import stat
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from importlib.metadata import version
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
}


def _get_cache_dir() -> Path:
    """Return the platform-appropriate cache directory for LaunchLine binaries."""
    base = Path(os.environ.get("XDG_CACHE_HOME", "")) if os.name != "nt" else Path("")
    if not base.is_absolute():
        if os.name == "nt":
            base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        else:
            base = Path.home() / ".cache"
    return base / "launchline" / "bin"


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

    pkg_version = version("launchline")
    ext = "zip" if system == "Windows" else "tar.gz"
    url = f"https://github.com/{_GITHUB_REPO}/releases/download/v{pkg_version}/{artifact}.{ext}"

    return artifact, url


def _binary_name() -> str:
    """Return the expected binary filename for this OS."""
    return "launchline.exe" if platform.system() == "Windows" else "launchline"


def _download_and_extract(url: str, dest: Path) -> Path:
    """Download a release archive and extract the binary to *dest*.

    Returns:
        Path to the extracted binary.
    """
    dest.mkdir(parents=True, exist_ok=True)
    binary_path = dest / _binary_name()

    print(f"Downloading LaunchLine from {url} ...", file=sys.stderr)

    with urllib.request.urlopen(url) as resp:  # noqa: S310
        data = resp.read()

    if url.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for member in zf.namelist():
                if member.endswith(_binary_name()):
                    binary_path.write_bytes(zf.read(member))
                    break
            else:
                raise RuntimeError(f"Binary '{_binary_name()}' not found in archive")
    else:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
            for member in tf.getmembers():
                if member.name.endswith(_binary_name()):
                    extracted = tf.extractfile(member)
                    if extracted is None:
                        raise RuntimeError(f"Cannot extract '{member.name}' from archive")
                    binary_path.write_bytes(extracted.read())
                    break
            else:
                raise RuntimeError(f"Binary '{_binary_name()}' not found in archive")

    if platform.system() != "Windows":
        binary_path.chmod(binary_path.stat().st_mode | stat.S_IEXEC)

    return binary_path


def _ensure_binary() -> Path:
    """Return the path to the cached binary, downloading if necessary."""
    pkg_version = version("launchline")
    cache_dir = _get_cache_dir() / pkg_version

    binary_path = cache_dir / _binary_name()
    if binary_path.is_file():
        return binary_path

    _artifact, url = _resolve_artifact()
    return _download_and_extract(url, cache_dir)


def main() -> None:
    """Download (if needed) and execute the native LaunchLine binary."""
    try:
        binary = _ensure_binary()
    except Exception as exc:
        print(f"launchline: failed to obtain binary: {exc}", file=sys.stderr)
        sys.exit(1)

    result = subprocess.run([str(binary), *sys.argv[1:]])
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
