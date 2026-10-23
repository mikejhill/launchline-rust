"""Measure real warm menu navigation with cached versus regenerated parents."""

from __future__ import annotations

import json
import platform
import runpy
import statistics
import sys
import tempfile
import time
from pathlib import Path


class MenuBenchmark:
    """Record provider calls and seven PTY roundtrips without thresholds."""

    @staticmethod
    def main() -> None:
        """Use identical providers and interpreters for paired measurements."""
        root = Path(__file__).resolve().parents[1]
        python_test = root / "tests/test_terminal_e2e.py"
        test = (
            python_test
            if python_test.exists()
            else root / "pypi/tests/test_terminal_e2e.py"
        )
        namespace = runpy.run_path(str(test))
        terminal = namespace["TerminalSession"]
        fixture = namespace["TestMenuTerminalWorkflows"]
        runtime = namespace["TestTerminalWorkflows"]
        records = []
        for regenerate in (False, True):
            with tempfile.TemporaryDirectory(
                prefix="launchline-menu-benchmark-"
            ) as directory:
                config, counter = fixture._config(Path(directory), refresh=regenerate)
                with terminal(runtime._command(config)) as session:
                    session.wait("Projects1")
                    session.write("1")
                    session.wait_plain("\u276f  (Tool child1)")
                    samples = []
                    for _ in range(7):
                        parent = session.plain_output.count("\u276f  (Projects")
                        child = session.plain_output.count("\u276f  (Tool child1)")
                        started = time.perf_counter_ns()
                        session.write("\x1b")
                        session.wait_plain("\u276f  (Projects", count=parent + 1)
                        session.write("\r")
                        session.wait_plain("\u276f  (Tool child1)", count=child + 1)
                        samples.append((time.perf_counter_ns() - started) / 1_000_000)
                    session.write("0")
                    assert session.exited() == 0, session.output
                calls = int(counter.read_text(encoding="utf-8"))
                child_calls = int(
                    Path(str(counter) + ".child").read_text(encoding="utf-8")
                )
                assert calls == (8 if regenerate else 1), (
                    "Return policy must explain provider invocations"
                )
                assert child_calls == 1, "Unchanged selected child should remain cached"
                records.append(
                    {
                        "refresh_on_return": regenerate,
                        "roundtrip_ms": samples,
                        "median_ms": statistics.median(samples),
                        "root_provider_calls": calls,
                        "child_provider_calls": child_calls,
                    }
                )
        result = {
            "host": platform.node(),
            "platform": platform.platform(),
            "provider_interpreter": sys.version,
            "scope": (
                "Warm Back+Enter PTY roundtrip, including configured parent refresh. "
                "Excludes initial app startup; seven samples; no timing threshold "
                "or universal runtime claim."
            ),
            "cases": records,
        }
        (root / "docs/validation/menu-performance.json").write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    MenuBenchmark.main()
