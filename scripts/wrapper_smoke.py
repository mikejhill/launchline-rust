"""Test an installed wrapper wheel against an actual locally built release archive."""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path
from unittest.mock import patch

from launchline._wrapper import NativeLauncher


class WrapperSmoke:
    """Use isolated cache state and an offline archive response, never production."""

    @staticmethod
    def main() -> None:
        """Verify metadata resolution, archive integrity, icon lookup, and CLI forwarding."""
        root = Path(__file__).resolve().parents[1]
        wheel = next((root / "pypi/dist").glob("*.whl"))
        metadata = tomllib.loads(
            (root / "pypi/pyproject.toml").read_text(encoding="utf-8")
        )
        version = metadata["project"]["version"]
        artifact = os.environ.get(
            "ARTIFACT",
            "launchline-windows-x64"
            if sys.platform == "win32"
            else "launchline-linux-x64",
        )
        pattern = artifact + (".zip" if sys.platform == "win32" else ".tar.gz")
        archive = root / "release" / pattern
        payload = archive.read_bytes()
        checksum = f"{hashlib.sha256(payload).hexdigest()}  {pattern}\n".encode("ascii")
        records = []
        with tempfile.TemporaryDirectory(prefix="launchline-wrapper-") as temporary:
            directory = Path(temporary)
            cache = directory / "launchline/bin" / version
            url = f"https://github.com/mikejhill/launchline-rust/releases/download/v{version}/{pattern}"
            with patch(
                "urllib.request.urlopen",
                side_effect=[io.BytesIO(payload), io.BytesIO(checksum)],
            ):
                NativeLauncher._download_and_extract(url, cache)
            environment = {
                **os.environ,
                "LOCALAPPDATA": str(directory),
                "XDG_CACHE_HOME": str(directory),
                "UV_OFFLINE": "1",
            }
            for arguments, expected in [
                (["--help"], 0),
                (["--icon-path"], 0),
                (["--log-level", "INVALID"], 2),
            ]:
                result = subprocess.run(
                    [
                        "uv",
                        "tool",
                        "run",
                        "--isolated",
                        "--from",
                        str(wheel),
                        "launchline",
                        *arguments,
                    ],
                    cwd=directory,
                    env=environment,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                assert result.returncode == expected, (arguments, result.stderr)
                assert "Downloading" not in result.stderr, (
                    "Installed wrapper must use the isolated verified cache"
                )
                if arguments == ["--icon-path"]:
                    assert Path(result.stdout.strip()).is_file(), result.stdout
                records.append({"args": arguments, "exit": result.returncode})
        (root / "docs/validation/wrapper-smoke.json").write_text(
            json.dumps(records, indent=2), encoding="utf-8"
        )


if __name__ == "__main__":
    WrapperSmoke.main()
