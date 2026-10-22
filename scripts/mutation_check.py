"""Seed explicit mutants across search, config, process, and keyboard behavior."""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path


class MutationCheck:
    """Transparent targeted campaign; results are not an exhaustive mutation score."""

    @staticmethod
    def main() -> None:
        """Classify genuine test kills, survivors, invalid mutants, and timeouts."""
        parser = argparse.ArgumentParser()
        parser.add_argument("language", choices=["python", "rust"])
        language = parser.parse_args().language
        root = Path(__file__).resolve().parents[1]
        suffix = "py" if language == "python" else "rs"
        prefix = "src/launchline/" if language == "python" else "src/"
        mutants = [
            ("fuzzy", "base-score", "score += 1", "score += 0"),
            ("fuzzy", "adjacency", "score += 2", "score += 0"),
            ("fuzzy", "word-boundary", "score += 3", "score += 0"),
        ]
        if language == "python":
            command = [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-o",
                "addopts=",
                "tests/test_contract.py",
                "tests/test_config.py",
                "tests/test_ui.py",
                "tests/test_runner.py",
            ]
            mutants += [
                ("fuzzy", "case-fold", "candidate.lower()", "candidate"),
                ("fuzzy", "no-match", "return None", "return 0"),
                ("config", "required-name", "if not name or not command:", "if False:"),
                (
                    "config",
                    "exit-policy",
                    "if on_exit not in ConfigLoader.VALID_ON_EXIT:",
                    "if False and on_exit not in ConfigLoader.VALID_ON_EXIT:",
                ),
                (
                    "config",
                    "scalar-types",
                    "if not isinstance(value, expected):",
                    "if False:",
                ),
                ("config", "directory-kind", "not wd.is_dir()", "not wd.exists()"),
                ("runner", "environment-overlay", "entry.env.items()", "{}.items()"),
                (
                    "runner",
                    "child-exit-code",
                    "return returncode if returncode >= 0 else 128 - returncode",
                    "return 0",
                ),
                (
                    "ui",
                    "numeric-setting",
                    "self._numeric_trigger = config.numeric_trigger",
                    "self._numeric_trigger = False",
                ),
            ]
        else:
            command = ["cargo", "test", "--locked", "--quiet"]
            mutants += [
                (
                    "fuzzy",
                    "case-fold",
                    "candidate.to_lowercase()",
                    "candidate.to_string()",
                ),
                (
                    "fuzzy",
                    "no-match",
                    ".find(character)?",
                    ".find(character).unwrap_or(0)",
                ),
                (
                    "config",
                    "required-name",
                    "if name.is_empty() || command.is_empty()",
                    "if false",
                ),
                (
                    "config",
                    "exit-policy",
                    "if !VALID_ON_EXIT.contains",
                    "if false && !VALID_ON_EXIT.contains",
                ),
                (
                    "config",
                    "exit-visible-default",
                    "let show_exit = settings.show_exit.unwrap_or(true);",
                    "let show_exit = settings.show_exit.unwrap_or(false);",
                ),
                ("config", "directory-kind", "expanded.is_dir()", "expanded.exists()"),
                ("runner", "environment-overlay", "proc.envs(env);", "drop(env);"),
                (
                    "ui",
                    "unicode-cursor",
                    "self.cursor_pos += ch.len_utf8();",
                    "self.cursor_pos += 1;",
                ),
                (
                    "ui",
                    "numeric-setting",
                    "numeric_trigger: config.numeric_trigger",
                    "numeric_trigger: false",
                ),
            ]
        baseline = subprocess.run(
            command, cwd=root, capture_output=True, text=True, check=False, timeout=180
        )
        assert baseline.returncode == 0, baseline.stdout + baseline.stderr
        originals = {
            module: (root / f"{prefix}{module}.{suffix}").read_text(encoding="utf-8")
            for module, *_ in mutants
        }
        records = []
        try:
            for module, name, old, new in mutants:
                path = root / f"{prefix}{module}.{suffix}"
                original = originals[module]
                assert old in original, (name, old)
                path.write_text(original.replace(old, new, 1), encoding="utf-8")
                if language == "python":
                    Path(importlib.util.cache_from_source(str(path))).unlink(
                        missing_ok=True
                    )
                try:
                    result = subprocess.run(
                        command,
                        cwd=root,
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=180,
                    )
                    invalid = (
                        "could not compile" in result.stderr
                        or "SyntaxError" in result.stdout
                    )
                    status = (
                        "invalid"
                        if invalid
                        else "survived"
                        if result.returncode == 0
                        else "killed"
                    )
                    diagnostic = (result.stdout + result.stderr)[-1500:]
                except subprocess.TimeoutExpired:
                    status, diagnostic = (
                        "timeout",
                        "Bounded mutation execution exceeded 180 seconds",
                    )
                records.append(
                    {
                        "source": f"{prefix}{module}.{suffix}",
                        "mutant": name,
                        "status": status,
                        "diagnostic": diagnostic,
                    }
                )
                sys.stdout.write(f"{name}: {status}\n")
                sys.stdout.flush()
                path.write_text(original, encoding="utf-8")
        finally:
            for module, original in originals.items():
                path = root / f"{prefix}{module}.{suffix}"
                path.write_text(original, encoding="utf-8")
                if language == "python":
                    Path(importlib.util.cache_from_source(str(path))).unlink(
                        missing_ok=True
                    )
        (root / "docs/validation/mutation.json").write_text(
            json.dumps(records, indent=2), encoding="utf-8"
        )
        assert all(record["status"] == "killed" for record in records), records


if __name__ == "__main__":
    MutationCheck.main()
