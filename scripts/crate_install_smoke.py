"""Clean-install the packaged Cargo source and exercise the actual installed CLI."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import tomllib
from pathlib import Path


class CrateInstall:
    """Keep the installed prefix independent of the editable checkout and wrappers."""

    @staticmethod
    def main() -> None:
        """Compile extracted crate source, check its icon, and run terminal workflows."""
        parser = argparse.ArgumentParser()
        parser.add_argument("--terminal-only", action="store_true")
        args = parser.parse_args()
        root = Path(__file__).resolve().parents[1]
        version = tomllib.loads((root / "Cargo.toml").read_text(encoding="utf-8"))[
            "package"
        ]["version"]
        archive = root / "target/package" / f"launchline-{version}.crate"
        with tempfile.TemporaryDirectory(
            prefix="launchline-cargo-install-"
        ) as temporary:
            directory = Path(temporary)
            with tarfile.open(archive) as packaged:
                packaged.extractall(directory, filter="data")
            source = directory / f"launchline-{version}"
            prefix = directory / "installed"
            subprocess.run(
                [
                    "cargo",
                    "install",
                    "--path",
                    str(source),
                    "--root",
                    str(prefix),
                    "--locked",
                    "--offline",
                    "--target-dir",
                    str(root / "target/crate-install"),
                ],
                check=True,
            )
            executable = (
                prefix
                / "bin"
                / ("launchline.exe" if sys.platform == "win32" else "launchline")
            )
            result = subprocess.run(
                [str(executable), "--icon-path"],
                capture_output=True,
                text=True,
                check=True,
            )
            icon = Path(result.stdout.strip())
            assert icon.read_bytes() == (root / "assets/launchline.ico").read_bytes(), (
                "Cargo-installed icon must match bundled asset"
            )
            subprocess.run([str(executable), "--help"], capture_output=True, check=True)
            if not args.terminal_only:
                subprocess.run([
                    "cargo", "test", "--manifest-path", str(source / "Cargo.toml"),
                    "--locked", "--offline", "--target-dir", str(root / "target/crate-tests"),
                ], check=True)
            test = root / "pypi/tests"
            if args.terminal_only:
                test /= "test_terminal_e2e.py"
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    str(test),
                    "-o",
                    "addopts=",
                    "-q",
                    "--junitxml=" + str(root / "junit.xml"),
                ],
                cwd=Path(tempfile.gettempdir()),
                env={**os.environ, "LAUNCHLINE_RUST": str(executable)},
                check=True,
                timeout=240,
            )
        (root / "docs/validation/crate-install.json").write_text(
            json.dumps(
                {
                    "version": version,
                    "source": "extracted .crate",
                    "offline_install": True,
                    "installed_terminal_suite": "passed",
                    "icon": "embedded resource verified",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    CrateInstall.main()
