"""Real pseudoterminal keyboard, cancellation, and child-interruption workflows."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Self

import pytest


class TerminalSession:
    """Own a single disposable terminal and collect its real runtime output."""

    def __init__(self, command: list[str]) -> None:
        self.output = ""
        self._messages: queue.Queue[str] = queue.Queue()
        if sys.platform == "win32":
            from winpty import PtyProcess

            self._closed_errors = (EOFError, OSError)
            self._process = PtyProcess.spawn(subprocess.list2cmdline(command))
        else:
            import pexpect

            self._closed_errors = (pexpect.EOF, OSError)
            self._read_timeouts = (pexpect.TIMEOUT,)
            self._process = pexpect.spawn(
                command[0], command[1:], encoding="utf-8", timeout=20
            )
        self._reader = threading.Thread(target=self._collect, daemon=True)
        self._reader.start()

    def __enter__(self) -> Self:
        """Return this owned session."""
        return self

    def __exit__(self, *_error: object) -> None:
        """Terminate only the fixture process and close its terminal."""
        self._process.close(force=True)
        self._reader.join(timeout=2)

    def _collect(self) -> None:
        """Drain the terminal until its process closes the stream."""
        try:
            while True:
                if sys.platform == "win32":
                    chunk = self._process.read(1024)
                else:
                    try:
                        chunk = self._process.read_nonblocking(size=1024, timeout=1)
                    except self._read_timeouts:
                        continue
                self._messages.put(chunk)
        except self._closed_errors:
            return

    def write(self, text: str) -> None:
        """Send keyboard input through the actual terminal driver."""
        self._process.write(text)

    def wait(self, text: str, count: int = 1) -> None:
        """Wait for observable readiness, with a bounded diagnostic timeout."""
        deadline = time.monotonic() + 25
        while self.output.count(text) < count:
            remaining = deadline - time.monotonic()
            assert remaining > 0, f"Missing {text!r} (count={count}): {self.output}"
            try:
                self.output += self._messages.get(timeout=min(remaining, 0.2))
            except queue.Empty:
                continue

    def resize(self, rows: int, columns: int) -> None:
        """Resize the owned terminal through its actual platform API."""
        self._process.setwinsize(rows, columns)

    def exited(self) -> int:
        """Wait for process completion and return its actual exit status."""
        deadline = time.monotonic() + 25
        while self._process.isalive():
            assert time.monotonic() < deadline, self.output
            time.sleep(0.01)
        self._process.close()
        return self._process.exitstatus


class TestTerminalWorkflows:
    """Exercise the installed runtime rather than replacing keyboard or process APIs."""

    @staticmethod
    def _command(config: Path) -> list[str]:
        """Select the runtime under test without contacting any external service."""
        native = os.environ.get("LAUNCHLINE_RUST") or str(
            Path(__file__).resolve().parents[2]
            / "target"
            / "release"
            / ("launchline.exe" if sys.platform == "win32" else "launchline")
        )
        command = [native] if native else [sys.executable, "-m", "launchline"]
        return [*command, "--config", str(config)]

    @staticmethod
    def _config(directory: Path, *, interrupt: bool = False) -> Path:
        """Create a harmless child and an isolated launcher configuration."""
        child = directory / "child.py"
        script = "import sys; print('CHILD_OK', flush=True); sys.exit(7)"
        if interrupt:
            script = "import time; print('CHILD_READY', flush=True); time.sleep(60)"
        child.write_text(script, encoding="utf-8")
        config = directory / "config.toml"
        config.write_text(
            '[settings]\non_exit="'
            + ("restart" if interrupt else "exit")
            + '"\nclear_on_launch=false\n[[entries]]\nname="Safe fixture"\ncommand='
            + json.dumps(sys.executable)
            + "\nargs="
            + json.dumps([str(child)])
            + "\n",
            encoding="utf-8",
        )
        return config

    def test_search_escape_numeric_launch_and_exit(self, tmp_path: Path) -> None:
        """Search, clear with Escape, and launch a real child using its number."""
        config = self._config(tmp_path)
        with TerminalSession(self._command(config)) as session:
            session.wait("Safe fixture")
            session.write("nomatch")
            session.wait("nomatch")
            count = session.output.count("Safe fixture")
            session.write("\x1b")
            session.wait("Safe fixture", count=count + 1)
            session.write("1")
            session.wait("CHILD_OK")
            assert session.exited() == 7, session.output
            assert "\x1b[?1049l" in session.output, (
                "Child must run after alternate-screen restoration"
            )

    def test_ctrl_c_cancels_menu_and_restores_screen(self, tmp_path: Path) -> None:
        """Ctrl+C in the menu must quit cleanly and restore the terminal."""
        with TerminalSession(self._command(self._config(tmp_path))) as session:
            session.wait("Ctrl+C=quit")
            session.write("\x03")
            assert session.exited() == 0, session.output

    def test_interrupted_child_returns_to_menu(self, tmp_path: Path) -> None:
        """Interrupt a real child, then cancel the restarted launcher."""
        config = self._config(tmp_path, interrupt=True)
        with TerminalSession(self._command(config)) as session:
            session.wait("Safe fixture")
            session.write("1")
            session.wait("CHILD_READY")
            count = session.output.count("Safe fixture")
            session.write("\x03")
            session.wait("Safe fixture", count=count + 1)
            session.write("\x1b")
            assert session.exited() == 0, session.output

    def test_no_color_retains_noncolor_selection_marker(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """NO_COLOR removes styling while preserving the selection marker."""
        monkeypatch.setenv("NO_COLOR", "1")
        with TerminalSession(self._command(self._config(tmp_path))) as session:
            session.wait("Safe fixture")
            session.wait("Ctrl+C=quit")
            assert "▸" in session.output, "Selection must have a noncolor marker"
            assert "\x1b[38;" not in session.output, (
                "NO_COLOR must remove accent styling"
            )
            assert "\x1b[92m" not in session.output, (
                "NO_COLOR must remove selection color"
            )
            session.write("0")
            assert session.exited() == 0, session.output

    def test_resize_preserves_arrow_navigation_and_exit(self, tmp_path: Path) -> None:
        """A resize redraw must preserve keyboard selection and cleanup."""
        with TerminalSession(self._command(self._config(tmp_path))) as session:
            session.wait("Ctrl+C=quit")
            count = session.output.count("Ctrl+C=quit")
            session.resize(14, 80)
            session.wait("Ctrl+C=quit", count=count + 1)
            session.write("\x1b[B")
            session.write("\r")
            assert session.exited() == 0, session.output

    @pytest.mark.skipif(
        sys.platform != "win32", reason="Windows inherited console attribute"
    )
    def test_inherited_ctrl_c_ignore_is_repaired(self, tmp_path: Path) -> None:
        """A launcher must recover Ctrl+C handling inherited from a process group."""
        parent = tmp_path / "ignored_parent.py"
        parent.write_text(
            "import ctypes, subprocess, sys; "
            "ctypes.WinDLL('kernel32').SetConsoleCtrlHandler(None, True); "
            "sys.exit(subprocess.call(sys.argv[1:]))",
            encoding="utf-8",
        )
        config = self._config(tmp_path, interrupt=True)
        with TerminalSession(
            [sys.executable, str(parent), *self._command(config)]
        ) as session:
            session.wait("Ctrl+C=quit")
            session.write("1")
            session.wait("CHILD_READY")
            count = session.output.count("Safe fixture")
            session.write("\x03")
            session.wait("Safe fixture", count=count + 1)
            session.write("\x1b")
            assert session.exited() == 0, session.output
