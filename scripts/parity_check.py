"""Differential CLI contract tests; all fixtures and tools remain isolated."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


class ParityCheck:
    """Compare actual installed Python runtime and compiled Rust binary."""

    @staticmethod
    def main() -> None:
        """Run accepted and rejected config cases against both implementations."""
        native = os.environ["LAUNCHLINE_RUST"]
        valid = '\n[[entries]]\nname="猫 tool"\ncommand="unused"\n'
        cases = [
            ("defaults", valid, 0),
            ("settings", '[settings]\non_exit="exit"\nshow_exit=false\n' + valid, 0),
            ("boolean-string", '[settings]\nshow_exit="yes"\n' + valid, 1),
            ("title-number", "[settings]\ntitle=12\n" + valid, 1),
            ("array-command", '[[entries]]\nname="x"\ncommand=["unused"]', 1),
            ("argument-number", valid + "args=[1]", 1),
            ("environment-number", valid + "env={A=12}", 1),
            ("control-name", '[[entries]]\nname="x\\u001b]0;bad"\ncommand="unused"', 1),
            ("bad-env-key", valid + 'env={"A=B"="value"}', 1),
            ("empty-entries", "entries=[]", 1),
            ("wrong-settings-table", "settings=[]" + valid, 1),
            ("valid-argv", valid + 'args=["a b", "&literal", "猫"]', 0),
            ("bad-on-exit", '[settings]\non_exit="retry"' + valid, 1),
            ("missing-name", '[[entries]]\ncommand="unused"', 1),
            ("unicode-name", valid + 'description="café"', 0),
        ]
        evidence = []
        with tempfile.TemporaryDirectory(prefix="launchline-parity-") as temp:
            directory = Path(temp)
            for name, content, expected in cases:
                config = directory / f"{name}.toml"
                config.write_text(content, encoding="utf-8")
                results = []
                for command in [[sys.executable, "-m", "launchline"], [native]]:
                    result = subprocess.run(
                        [*command, "--check-config", "--config", str(config)],
                        cwd=directory,
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=15,
                    )
                    assert result.returncode == expected, (name, command, result.stderr)
                    if expected == 0:
                        assert (
                            result.stdout.strip() == "Configuration valid: 1 entries"
                        ), result.stdout
                    results.append(result.returncode)
                evidence.append(
                    {"case": name, "python": results[0], "rust": results[1]}
                )
        root = Path(__file__).resolve().parents[1]
        (root / "docs/validation/parity.json").write_text(
            json.dumps(evidence, indent=2), encoding="utf-8"
        )


if __name__ == "__main__":
    ParityCheck.main()
