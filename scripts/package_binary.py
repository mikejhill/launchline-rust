"""Package a locally built native binary and icon without publishing."""

from __future__ import annotations

import os
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path


class BinaryPackage:
    """Build and smoke-test the exact archive layout consumed by the wrapper."""

    @staticmethod
    def main() -> None:
        """Archive the target binary and validate help and icon after extraction."""
        root = Path(__file__).resolve().parents[1]
        target = os.environ["TARGET"]
        artifact = os.environ["ARTIFACT"]
        binary = "launchline.exe" if "windows" in target else "launchline"
        source = root / "target" / target / "release" / binary
        release = root / "release"
        release.mkdir(exist_ok=True)
        members = [
            (source, binary),
            (root / "assets/launchline.ico", "assets/launchline.ico"),
        ]
        if "windows" in target:
            archive_path = release / f"{artifact}.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                for path, name in members:
                    archive.write(path, name)
        else:
            archive_path = release / f"{artifact}.tar.gz"
            with tarfile.open(archive_path, "w:gz") as archive:
                for path, name in members:
                    archive.add(path, arcname=name)
        with tempfile.TemporaryDirectory(prefix="launchline-native-") as temp:
            destination = Path(temp)
            if "windows" in target:
                with zipfile.ZipFile(archive_path) as archive:
                    archive.extractall(destination)
            else:
                with tarfile.open(archive_path) as archive:
                    archive.extractall(destination, filter="data")
            executable = destination / binary
            subprocess.run(
                [str(executable), "--help"],
                cwd=destination,
                check=True,
                capture_output=True,
            )
            icon = subprocess.run(
                [str(executable), "--icon-path"],
                cwd=destination,
                check=True,
                capture_output=True,
                text=True,
            )
            assert Path(icon.stdout.strip()).is_file(), icon.stdout


if __name__ == "__main__":
    BinaryPackage.main()
