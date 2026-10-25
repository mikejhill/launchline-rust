"""Harmless real provider with observable invocations for both terminal runtimes."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path


class MenuFixture:
    """Produce controlled snapshots without executing any returned leaf."""

    @staticmethod
    def main() -> None:
        """Count actual provider starts and emit a requested success/failure case."""
        counter = Path(sys.argv[1])
        mode = sys.argv[2]
        count = int(counter.read_text(encoding="utf-8")) + 1 if counter.exists() else 1
        counter.write_text(str(count), encoding="utf-8")
        if mode in {"timeout", "interrupt"}:
            child = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(60)"]
            )
            Path(str(counter) + ".pids").write_text(
                json.dumps([__import__("os").getpid(), child.pid]), encoding="utf-8"
            )
            time.sleep(60)
        if mode == "fail-first" and count == 1:
            sys.stderr.write("DISCARDED_PROVIDER_SECRET")
            raise SystemExit(7)
        if mode in {"child", "child-interrupt"}:
            entries = [
                {
                    "id": "tool",
                    "name": "Tool child" + str(count),
                    "command": sys.executable,
                    "args": [
                        "-c",
                        "import sys;sys.stdout.write('LEAF_OK\\n'); sys.exit(7)",
                    ],
                }
            ]
            if mode == "child-interrupt":
                entries[0]["args"] = [
                    "-c",
                    "import time; print('LEAF_READY', flush=True); time.sleep(60)",
                ]
        elif mode == "remove" and count > 1:
            entries = [
                {
                    "id": "replacement",
                    "name": "Replacement",
                    "command": sys.executable,
                    "args": [
                        "-c",
                        "import sys;sys.stdout.write('REPLACEMENT_OK\\n'); sys.exit(7)",
                    ],
                }
            ]
        else:
            child_counter = str(counter) + ".child"
            entries = [
                {
                    "id": "projects",
                    "name": "Projects" + str(count),
                    "menu": {
                        "title": "Child menu",
                        "provider": {
                            "command": sys.executable,
                            "args": [
                                str(Path(__file__).resolve()),
                                child_counter,
                                "child-interrupt"
                                if mode == "leaf-interrupt"
                                else "child",
                            ],
                        },
                    },
                }
            ]
            if count > 1:
                entries.insert(
                    0,
                    {
                        "id": "other",
                        "name": "Other",
                        "command": sys.executable,
                        "args": ["-c", "raise SystemExit(99)"],
                    },
                )
        sys.stdout.write(json.dumps({"entries": entries}))


if __name__ == "__main__":
    MenuFixture.main()
