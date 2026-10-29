"""Capture actual Python/Rust terminal output using the original CGA renderer.

The owned ConPTY receives all keys; no desktop input or window capture is used.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pyte
from terminal_render import TerminalRenderer, capture_cells
from winpty import PtyProcess


def main() -> None:
    """Run the real executable and render its decoded cells without adding UI text."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", choices=["Python", "Rust"], required=True)
    parser.add_argument("--executable", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    subprocess.run(
        ["git", "diff", "--exit-code", "HEAD", "--", "src"], cwd=root, check=True
    )
    executable = args.executable.resolve()
    images = root / "docs/images"
    evidence = images / "captures"
    evidence.mkdir(parents=True, exist_ok=True)
    source = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    renderer = TerminalRenderer()
    grids = {}
    input_events = []
    cols, rows = 80, 22
    raw = ""
    with tempfile.TemporaryDirectory(
        prefix=f"LL-{args.runtime[0]}-"
    ) as fixture:
        home = Path(fixture)
        project = home / "projects/my-app"
        project.mkdir(parents=True)
        shutil.copytree(root / "examples", project / "examples")
        command = [str(executable)]
        if args.runtime == "Python":
            command += ["-m", "launchline"]
        command += ["--config", "examples/menu-demo.toml"]
        env = dict(os.environ)
        env.pop("NO_COLOR", None)
        env["TERM"] = "xterm-256color"
        env["COLORTERM"] = "truecolor"
        env["USERPROFILE"] = str(home)
        env["HOME"] = str(home)
        env["PYTHONPATH"] = str(root / "src")
        env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env["PATH"]
        process = PtyProcess.spawn(
            command, cwd=str(project), env=env, dimensions=(rows, cols)
        )
        messages = queue.Queue()

        def collect():
            try:
                while True:
                    messages.put(process.read(4096))
            except (EOFError, OSError):
                return

        reader = threading.Thread(target=collect, daemon=True)
        reader.start()
        screen = pyte.Screen(cols, rows)
        stream = pyte.Stream(screen)

        def frame(name, ready):
            nonlocal raw
            deadline = time.monotonic() + 20
            while True:
                assert time.monotonic() < deadline, (
                    f"Missing {ready!r}: {screen.display}"
                )
                try:
                    chunk = messages.get(timeout=0.3)
                except queue.Empty:
                    if ready in "\n".join(screen.display):
                        break
                    continue
                raw += chunk
                stream.feed(chunk)
            text = "\n".join(screen.display)
            (evidence / f"{name}.txt").write_text(
                "\n".join(line.rstrip() for line in screen.display) + "\n",
                encoding="utf-8",
            )
            (evidence / f"{name}.ansi").write_bytes(raw.encode("utf-8"))
            grid = capture_cells(screen)
            assert any(cell.fg == (85, 255, 85) for row in grid for cell in row), (
                "Missing actual active ANSI green"
            )
            assert any(cell.bold for row in grid for cell in row), (
                "Missing actual ANSI bold"
            )
            grids[name] = grid
            renderer.render_png(grid, images / f"{name}.png")

        def key(value, label):
            input_events.append(label)
            process.write(value)

        try:
            frame("root", "Generated on first visit")
            key("p", "type p")
            frame("search-p", "❯ p")
            key("o", "type o")
            frame("search-po", "❯ po")
            key("w", "type w")
            frame("search-pow", "❯ pow")
            key("\x7f" * 3, "Backspace x3")
            frame("cleared", "Generated on first visit")
            key("\x1b[B" * 3, "Down x3")
            frame("navigation", "(Node.js)")
            key("7", "7 (Development submenu)")
            frame("nested", "Project test suite")
            key("\x1b", "Escape (Back)")
            frame("returned", "Generated on first visit")
            key("8", "8 (Projects provider)")
            frame("dynamic", "Recent commits")
            key("\x12", "Ctrl+R (Refresh provider)")
            frame("refreshed", "Recent commits")
            key("0", "0 (Exit)")
            deadline = time.monotonic() + 10
            while process.isalive() and time.monotonic() < deadline:
                time.sleep(0.05)
            assert not process.isalive(), "Exit shortcut failed"
        finally:
            process.close(force=True)
            reader.join(timeout=2)
        assert process.exitstatus == 0, f"Application exited with {process.exitstatus}"
    renderer.render_gif(
        [
            grids[n]
            for n in [
                "root",
                "search-p",
                "search-po",
                "search-pow",
                "cleared",
                "navigation",
            ]
        ],
        images / "launcher.gif",
        durations=[1600, 350, 350, 1200, 650, 1600],
    )
    renderer.render_gif(
        [grids[n] for n in ["root", "nested", "returned", "dynamic", "refreshed"]],
        images / "menus.gif",
        durations=[1600, 2200, 800, 2200, 1200],
    )
    manifest = {
        "runtime": args.runtime,
        "exit_status": process.exitstatus,
        "source_commit": source,
        "command": command,
        "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
        "terminal": "Windows ConPTY via pywinpty",
        "dimensions": [cols, rows],
        "fixture": "Disposable home/projects/my-app with committed example config/provider copied unchanged",
        "input": input_events,
        "capture_python": sys.version,
        "dependencies": {
            p: importlib.metadata.version(p) for p in ["pywinpty", "pyte", "Pillow"]
        },
        "rendering": "Original generate_screenshots.py CGA palette, Cascadia Mono 15px, ANSI foreground/background/reverse/bold and terminal chrome; all terminal content from this runtime",
        "capture_sources": {
            name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in [
                "examples/menu-demo.toml",
                "examples/menu_provider.py",
                "tools/capture_menus.py",
                "tools/terminal_render.py",
            ]
        },
        "files": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(evidence.iterdir())
            if p.suffix in {".ansi", ".txt"}
        },
        "assets": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(images.iterdir())
            if p.stem in {*grids, "launcher", "menus"} and p.suffix in {".png", ".gif"}
        },
    }
    (evidence / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
