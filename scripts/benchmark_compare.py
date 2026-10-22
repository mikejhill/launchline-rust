"""Compile baseline/current Rust fuzzy search with the identical benchmark harness."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path


class BenchmarkComparison:
    """Measure both versions with rustc -O, excluding compilation from timings."""

    @staticmethod
    def main() -> None:
        """Record paired source revisions and raw timing samples."""
        root = Path(__file__).resolve().parents[1]
        harness = (root / "examples/benchmark.rs").read_text(encoding="utf-8")
        baseline = subprocess.check_output(
            ["git", "show", "109a68b:src/fuzzy.rs"],
            cwd=root,
            text=True,
            encoding="utf-8",
        )
        records = {}
        with tempfile.TemporaryDirectory(prefix="launchline-benchmark-") as temporary:
            directory = Path(temporary)
            for label, source in [
                ("baseline", baseline),
                ("current", (root / "src/fuzzy.rs").read_text(encoding="utf-8")),
            ]:
                (directory / "fuzzy.rs").write_text(source, encoding="utf-8")
                (directory / "bench.rs").write_text(
                    harness.replace("../src/fuzzy.rs", "fuzzy.rs"), encoding="utf-8"
                )
                executable = directory / f"{label}.exe"
                subprocess.run(
                    [
                        "rustc",
                        "--edition=2024",
                        "-O",
                        str(directory / "bench.rs"),
                        "-o",
                        str(executable),
                    ],
                    cwd=root,
                    check=True,
                )
                result = subprocess.run(
                    [str(executable)],
                    cwd=directory,
                    capture_output=True,
                    text=True,
                    check=True,
                )
                records[label] = result.stdout
        (root / "docs/validation/search-comparison.json").write_text(
            json.dumps(records, indent=2), encoding="utf-8"
        )


if __name__ == "__main__":
    BenchmarkComparison.main()
