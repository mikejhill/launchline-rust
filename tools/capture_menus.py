"""Capture a real LaunchLine process in an owned Windows ConPTY.

Requires pywinpty, pyte and Pillow. No desktop input or window capture is used.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

import pyte
from PIL import Image, ImageDraw, ImageFont
from winpty import PtyProcess


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", choices=["Python", "Rust"], required=True)
    parser.add_argument("--executable", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    executable = args.executable.resolve()
    command = [str(executable)]
    if args.runtime == "Python":
        command += ["-m", "launchline"]
    command += ["--config", "examples/menu-demo.toml"]
    env = dict(os.environ)
    env.pop("NO_COLOR", None)
    env["PYTHONPATH"] = str(root / "src")
    # The provider uses this same Python interpreter, independent of shell setup.
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env["PATH"]
    process = PtyProcess.spawn(
        subprocess.list2cmdline(command),
        cwd=str(root),
        env=env,
        dimensions=(24, 100),
    )
    messages: queue.Queue[str] = queue.Queue()

    def collect() -> None:
        try:
            while True:
                messages.put(process.read(4096))
        except (EOFError, OSError):
            return

    reader = threading.Thread(target=collect, daemon=True)
    reader.start()
    screen = pyte.Screen(100, 24)
    stream = pyte.Stream(screen)
    raw = ""
    images = root / "docs/images"
    evidence = images / "captures"
    evidence.mkdir(parents=True, exist_ok=True)
    font = ImageFont.truetype("C:/Windows/Fonts/CascadiaMono.ttf", 16)
    frames: list[Image.Image] = []

    def frame(name: str, ready: str) -> None:
        nonlocal raw
        deadline = time.monotonic() + 20
        # Drain until readiness and a short quiet period after the last redraw.
        while True:
            assert time.monotonic() < deadline, f"Missing {ready!r}: {screen.display}"
            try:
                chunk = messages.get(timeout=0.3)
            except queue.Empty:
                if ready in "\n".join(screen.display):
                    break
                continue
            raw += chunk
            stream.feed(chunk)
        text = "\n".join(screen.display)
        (evidence / f"{name}.txt").write_text(text + "\n", encoding="utf-8")
        (evidence / f"{name}.ansi").write_bytes(raw.encode("utf-8"))
        # Paint the cells returned by the terminal emulator; do not invent UI text.
        image = Image.new("RGB", (920, 500), "#10151e")
        draw = ImageDraw.Draw(image)
        for y, line in enumerate(screen.display):
            draw.text((10, 8 + 20 * y), line, font=font, fill="#d8e3ef")
        image.save(images / f"{name}.png")
        frames.append(image)

    try:
        frame("root", "Generated on first visit")
        process.write("1")
        frame("nested", "Git version")
        process.write("\x1b")
        frame("returned", "Generated on first visit")
        process.write("2")
        frame("dynamic", "Recent commits")
        process.write("0")
        deadline = time.monotonic() + 10
        while process.isalive() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not process.isalive(), "Exit shortcut failed"
    finally:
        process.close(force=True)
        reader.join(timeout=2)
    frames[0].save(
        images / "menus.gif",
        save_all=True,
        append_images=frames[1:],
        duration=[1600] * len(frames),
        loop=0,
    )
    source = subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        text=True,
    ).strip()
    manifest = {
        "runtime": args.runtime,
        "source_commit": source,
        "command": [str(executable), *command[1:]],
        "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
        "terminal": "Windows ConPTY via pywinpty",
        "dimensions": [100, 24],
        "input": ["1 (static submenu)", "Escape (Back)", "2 (provider)", "0 (Exit)"],
        "capture_python": sys.version,
        "dependencies": {
            p: importlib.metadata.version(p) for p in ["pywinpty", "pyte", "Pillow"]
        },
        "rendering": "Actual terminal text cells, monochrome; ANSI colors omitted",
        "files": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(evidence.iterdir())
            if p.suffix in {".ansi", ".txt"}
        },
    }
    (evidence / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
