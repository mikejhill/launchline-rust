"""Preload exact checksum-pinned semantic-release plugins without credentials."""

from __future__ import annotations

import hashlib
import json
import platform
import urllib.request
from pathlib import Path


class ReleasePlugins:
    """Verify executable bytes before placing them in the CLI plugin directory."""

    @staticmethod
    def main() -> None:
        """Resolve only reviewed lock entries for Linux/Windows x64 release targets."""
        root = Path(__file__).resolve().parents[1]
        target = {"Windows": "windows_amd64", "Linux": "linux_amd64"}[platform.system()]
        lock = json.loads(
            (root / "scripts/semantic-release-plugins.json").read_text(encoding="utf-8")
        )
        for entry in lock:
            if entry["platform"] != target:
                continue
            path = (
                Path.cwd()
                / ".semrel"
                / target
                / entry["plugin"]
                / entry["version"]
                / entry["file"]
            )
            if (
                path.exists()
                and hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"]
            ):
                continue
            with urllib.request.urlopen(entry["url"], timeout=60) as response:
                payload = response.read(64 * 1024 * 1024)
            if hashlib.sha256(payload).hexdigest() != entry["sha256"]:
                raise ValueError(f"Plugin checksum mismatch: {entry['plugin']}")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
            path.chmod(0o755)


if __name__ == "__main__":
    ReleasePlugins.main()
