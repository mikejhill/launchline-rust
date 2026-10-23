"""Transparent seeded mutation checks for menu state and provider resource limits."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


class MenuMutation:
    """Classify test kills independently from invalid compilation or timeouts."""

    @staticmethod
    def main() -> None:
        """Restore exact source bytes after every mutant and retain diagnostics."""
        parser = argparse.ArgumentParser()
        parser.add_argument("language", choices=["python", "rust"])
        language = parser.parse_args().language
        root = Path(__file__).resolve().parents[1]
        if language == "python":
            prefix, suffix = "src/launchline/", ".py"
            command = [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-o",
                "addopts=",
                "tests/test_menus.py",
                "tests/test_providers.py",
            ]
            mutants = [
                ("menus", "cache-reuse", "if not self.current.loaded:", "if True:"),
                (
                    "menus",
                    "return-refresh",
                    "self.current.declaration.refresh_on_return",
                    "not self.current.declaration.refresh_on_return",
                ),
                (
                    "menus",
                    "retain-snapshot",
                    "frame.error = str(error)",
                    "frame.entries = ()\n            frame.error = str(error)",
                ),
                ("menus", "changed-child", "child.declaration == entry.menu", "True"),
                (
                    "menus",
                    "cache-budget",
                    "MAX_CACHED_MENUS = 128",
                    "MAX_CACHED_MENUS = 256",
                ),
                ("config", "nesting-limit", "if depth >= 16:", "if depth >= 32:"),
                (
                    "config",
                    "unique-ids",
                    "if len(set(identities)) != len(identities):",
                    "if False:",
                ),
                (
                    "providers",
                    "output-limit",
                    "MAX_PROVIDER_BYTES = 1_048_576",
                    "MAX_PROVIDER_BYTES = 2_097_152",
                ),
                (
                    "providers",
                    "deadline",
                    "if time.monotonic() >= deadline:",
                    "if False:",
                ),
            ]
        else:
            prefix, suffix = "src/", ".rs"
            command = ["cargo", "test", "--locked", "--test", "menus", "--quiet"]
            mutants = [
                ("menus", "cache-reuse", "if !self.current().loaded {", "if true {"),
                (
                    "menus",
                    "return-refresh",
                    "frame.declaration.refresh_on_return &&",
                    "!frame.declaration.refresh_on_return &&",
                ),
                (
                    "menus",
                    "retain-snapshot",
                    "pointer.borrow_mut().error = Some(error.to_string());",
                    (
                        "pointer.borrow_mut().entries.clear();\n"
                        "                pointer.borrow_mut().error = "
                        "Some(error.to_string());"
                    ),
                ),
                (
                    "menus",
                    "changed-child",
                    "entry.menu.as_deref() == Some(&child.declaration)",
                    "true",
                ),
                (
                    "menus",
                    "cache-budget",
                    "MAX_CACHED_MENUS: usize = 128",
                    "MAX_CACHED_MENUS: usize = 256",
                ),
                ("config", "nesting-limit", "if depth >= 16 {", "if depth >= 32 {"),
                (
                    "config",
                    "unique-ids",
                    "!entry.id.is_empty() && !identities.insert(&entry.id)",
                    "false && !identities.insert(&entry.id)",
                ),
                (
                    "providers",
                    "output-limit",
                    "MAX_PROVIDER_BYTES: usize = 1_048_576",
                    "MAX_PROVIDER_BYTES: usize = 2_097_152",
                ),
                (
                    "providers",
                    "deadline",
                    "if Instant::now() >= deadline {",
                    "if false {",
                ),
            ]
        files = {module: root / (prefix + module + suffix) for module, *_ in mutants}
        originals = {module: path.read_bytes() for module, path in files.items()}
        for module, name, old, _new in mutants:
            assert originals[module].decode("utf-8").count(old) == 1, (
                name,
                "Mutation anchor must be unique",
            )
        baseline = subprocess.run(
            command,
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=180,
        )
        assert baseline.returncode == 0, baseline.stdout + baseline.stderr
        records = []
        try:
            for module, name, old, new in mutants:
                path = files[module]
                # Preserve checkout newlines: write_text on Windows would turn
                # decoded CRLF into CRCRLF and create invalid Rust mutants.
                path.write_bytes(
                    originals[module].replace(old.encode(), new.encode(), 1)
                )
                try:
                    result = subprocess.run(
                        command,
                        cwd=root,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        check=False,
                        timeout=180,
                    )
                    output = result.stdout + result.stderr
                    invalid = any(
                        marker in output
                        for marker in (
                            "SyntaxError",
                            "IndentationError",
                            "error[E",
                            "could not compile",
                        )
                    )
                    status = (
                        "invalid"
                        if invalid
                        else "survived"
                        if result.returncode == 0
                        else "killed"
                    )
                    diagnostic = output[-2000:]
                except subprocess.TimeoutExpired:
                    status, diagnostic = "timeout", "180-second mutation bound exceeded"
                finally:
                    path.write_bytes(originals[module])
                records.append(
                    {
                        "source": prefix + module + suffix,
                        "mutant": name,
                        "status": status,
                        "diagnostic": diagnostic,
                    }
                )
                sys.stdout.write(name + ": " + status + "\n")
                sys.stdout.flush()
        finally:
            for module, path in files.items():
                path.write_bytes(originals[module])
        (root / "docs/validation/menu-mutation.json").write_text(
            json.dumps(records, indent=2) + "\n", encoding="utf-8"
        )
        assert all(record["status"] == "killed" for record in records), records


if __name__ == "__main__":
    MenuMutation.main()
