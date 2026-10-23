"""Real pseudoterminal keyboard, cancellation, and child-interruption workflows."""

from __future__ import annotations

import json
import os
import queue
import re
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

    @property
    def plain_output(self) -> str:
        """Return collected text without ANSI CSI sequences for prompt readiness."""
        return re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", self.output)

    def wait_plain(self, text: str, count: int = 1) -> None:
        """Wait for a unique observable prompt rather than repeated row names."""
        deadline = time.monotonic() + 25
        while self.plain_output.count(text) < count:
            remaining = deadline - time.monotonic()
            assert remaining > 0, f"Missing visible {text!r}: {self.output}"
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
            try:
                self.output += self._messages.get(timeout=0.01)
            except queue.Empty:
                assert time.monotonic() < deadline, self.output
            assert time.monotonic() < deadline, self.output
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


class ProcessInspector:
    """Read fixture process liveness without sending termination signals."""

    @staticmethod
    def running(pid: int) -> bool:
        """Distinguish live children from terminated processes and Unix zombies."""
        if sys.platform == "win32":
            import ctypes

            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.argtypes = [
                ctypes.c_uint32,
                ctypes.c_int,
                ctypes.c_uint32,
            ]
            kernel.OpenProcess.restype = ctypes.c_void_p
            kernel.GetExitCodeProcess.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_uint32),
            ]
            kernel.GetExitCodeProcess.restype = ctypes.c_int
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel.CloseHandle.restype = ctypes.c_int
            handle = kernel.OpenProcess(0x1000, False, pid)
            if not handle:
                error = ctypes.get_last_error()
                if error in {87, 1168}:
                    return False
                raise OSError(error, "Cannot query fixture process")
            try:
                status = ctypes.c_uint32()
                if not kernel.GetExitCodeProcess(handle, ctypes.byref(status)):
                    raise OSError(ctypes.get_last_error(), "Cannot read fixture status")
                return status.value == 259
            finally:
                kernel.CloseHandle(handle)
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "stat="],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode in {0, 1}, "Cannot query fixture process status"
        return (
            result.returncode == 0
            and bool(result.stdout.strip())
            and not result.stdout.strip().startswith("Z")
        )

    @staticmethod
    def read_pids(path: Path) -> list[int]:
        """Wait for the provider readiness file with a diagnostic deadline."""
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if path.exists():
                try:
                    result = json.loads(path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    continue
                return [int(pid) for pid in result]
            time.sleep(0.01)
        raise AssertionError(f"Provider never wrote readiness file {path}")

    @staticmethod
    def assert_stopped(pids: list[int]) -> None:
        """Wait for OS job teardown and require every fixture process stopped."""
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if all(not ProcessInspector.running(pid) for pid in pids):
                return
            time.sleep(0.01)
        assert not any(ProcessInspector.running(pid) for pid in pids), (
            "Provider process tree must not survive cleanup"
        )


class TestMenuTerminalWorkflows:
    """Use identical actual terminal scenarios for Python and Rust menu contracts."""

    @staticmethod
    def _config(
        directory: Path,
        mode: str = "normal",
        *,
        refresh: bool = False,
        on_exit: str = "restart",
    ) -> tuple[Path, Path]:
        """Configure only an explicit harmless provider and disposable counters."""
        counter = directory / "calls"
        path = directory / "menus.toml"
        script = Path(__file__).parent / "fixtures/menu_provider.py"
        text = (
            '[settings]\ntitle="Dynamic root"\nclear_on_launch=false\n'
            + "refresh_on_return="
            + str(refresh).lower()
            + "\non_exit="
            + json.dumps(on_exit)
            + "\n[provider]\ncommand="
            + json.dumps(sys.executable)
            + "\nargs="
            + json.dumps([str(script), str(counter), mode])
            + "\ntimeout_seconds="
            + ("1" if mode == "timeout" else "20")
            + "\n"
        )
        path.write_text(text, encoding="utf-8")
        return path, counter

    def test_cached_back_reentry_and_explicit_refresh(self, tmp_path: Path) -> None:
        """Cache child providers and preserve selection after parent reorder."""
        config, counter = self._config(tmp_path)
        child = Path(str(counter) + ".child")
        with TerminalSession(TestTerminalWorkflows._command(config)) as session:
            session.wait("Projects1")
            session.write("1")
            session.wait("Tool child1")
            assert child.read_text(encoding="utf-8") == "1", (
                "Opening child must invoke its provider once"
            )
            root_count = session.output.count("Projects1")
            session.write("\x1b")
            session.wait("Projects1", count=root_count + 1)
            old_count = session.output.count("Tool child1")
            session.write("1")
            session.wait("Tool child1", count=old_count + 1)
            assert child.read_text(encoding="utf-8") == "1", (
                "Child cache must survive reentry"
            )
            root_count = session.output.count("Projects1")
            session.write("\x1b")
            session.wait("Projects1", count=root_count + 1)
            assert counter.read_text(encoding="utf-8") == "1", (
                "Default return must preserve parent snapshot"
            )
            session.write("\x12")
            session.wait("Projects2")
            old_count = session.output.count("Tool child1")
            session.write("\r")
            session.wait("Tool child1", count=old_count + 1)
            assert child.read_text(encoding="utf-8") == "1", (
                "Stable unchanged child declaration must keep its cache"
            )
            session.write("0")
            assert session.exited() == 0, session.output

    def test_return_regenerates_parent_and_restores_selection_after_reorder(
        self, tmp_path: Path
    ) -> None:
        """Parent policy regenerates once on Back and preserves selected stable id."""
        config, counter = self._config(tmp_path, refresh=True)
        with TerminalSession(TestTerminalWorkflows._command(config)) as session:
            session.wait("Projects1")
            session.write("1")
            session.wait("Tool child1")
            session.write("\x1b")
            session.wait("Projects2")
            assert counter.read_text(encoding="utf-8") == "2", (
                "Return policy must regenerate exactly once"
            )
            old_count = session.output.count("Tool child1")
            session.write("\r")
            session.wait("Tool child1", count=old_count + 1)
            session.write("0")
            assert session.exited() == 0, session.output

    def test_removed_parent_selection_falls_back_without_automatic_launch(
        self, tmp_path: Path
    ) -> None:
        """Require explicit launch after the selected submenu is removed."""
        config, _counter = self._config(
            tmp_path, "remove", refresh=True, on_exit="exit"
        )
        with TerminalSession(TestTerminalWorkflows._command(config)) as session:
            session.wait("Projects1")
            session.write("1")
            session.wait("Tool child1")
            session.write("\x1b")
            session.wait("Replacement")
            assert "REPLACEMENT_OK" not in session.output, (
                "Refresh must never auto-launch replacement entries"
            )
            session.write("\r")
            session.wait("REPLACEMENT_OK")
            assert session.exited() == 7, session.output

    def test_initial_failure_retries_without_running_child_providers(
        self, tmp_path: Path
    ) -> None:
        """Expose retry and discard stderr without starting child providers."""
        config, counter = self._config(tmp_path, "fail-first")
        with TerminalSession(TestTerminalWorkflows._command(config)) as session:
            session.wait("Retry provider")
            assert "DISCARDED_PROVIDER_SECRET" not in session.output, (
                "Provider stderr must not enter the terminal"
            )
            session.write("\x12")
            session.wait("Projects2")
            assert not Path(str(counter) + ".child").exists(), (
                "Rendering parent must never execute child providers"
            )
            session.write("0")
            assert session.exited() == 0, session.output

    def test_timed_out_provider_terminates_its_descendants(
        self, tmp_path: Path
    ) -> None:
        """Timeout must recover to retry with no surviving provider process tree."""
        config, counter = self._config(tmp_path, "timeout")
        with TerminalSession(TestTerminalWorkflows._command(config)) as session:
            pids = ProcessInspector.read_pids(Path(str(counter) + ".pids"))
            session.wait("Retry provider")
            ProcessInspector.assert_stopped(pids)
            session.write("0")
            assert session.exited() == 0, session.output

    def test_ctrl_c_during_provider_cleans_tree_and_returns_130(
        self, tmp_path: Path
    ) -> None:
        """Foreground cancellation must terminate providers and their descendants."""
        config, counter = self._config(tmp_path, "interrupt")
        with TerminalSession(TestTerminalWorkflows._command(config)) as session:
            pids = ProcessInspector.read_pids(Path(str(counter) + ".pids"))
            session.write("\x03")
            assert session.exited() == 130, session.output
            ProcessInspector.assert_stopped(pids)

    def test_parent_query_survives_child_back_and_escape_only_clears_it(
        self, tmp_path: Path
    ) -> None:
        """Back must restore the parent's query rather than silently dropping it."""
        config, _counter = self._config(tmp_path)
        with TerminalSession(TestTerminalWorkflows._command(config)) as session:
            session.wait("Projects1")
            session.write("Projects\r")
            session.wait("Tool child1")
            marker = "\u276f Projects ("
            count = session.plain_output.count(marker)
            session.write("\x1b")
            session.wait_plain(marker, count=count + 1)
            empty_marker = "\u276f  ("
            count = session.plain_output.count(empty_marker)
            session.write("\x1b")
            session.wait_plain(empty_marker, count=count + 1)
            session.write("0")
            assert session.exited() == 0, session.output

    def test_interrupted_nested_leaf_restarts_same_cached_submenu(
        self, tmp_path: Path
    ) -> None:
        """A foreground tool interruption must retain the current submenu and cache."""
        config, counter = self._config(tmp_path, "leaf-interrupt")
        with TerminalSession(TestTerminalWorkflows._command(config)) as session:
            session.wait("Projects1")
            session.write("1")
            session.wait("Tool child1")
            count = session.output.count("Tool child1")
            session.write("1")
            session.wait("LEAF_READY")
            session.write("\x03")
            session.wait("Tool child1", count=count + 1)
            assert Path(str(counter) + ".child").read_text(encoding="utf-8") == "1", (
                "Tool return must not regenerate the submenu"
            )
            session.write("0")
            assert session.exited() == 0, session.output

    def test_escape_then_numeric_exit_after_observable_redraw(
        self, tmp_path: Path
    ) -> None:
        """Separate Escape and digit events using the observable cleared prompt."""
        config, _counter = self._config(tmp_path)
        with TerminalSession(TestTerminalWorkflows._command(config)) as session:
            session.wait("Projects1")
            session.write("nomatch")
            session.wait_plain("\u276f nomatch")
            count = session.plain_output.count("\u276f  (")
            session.write("\x1b")
            session.wait_plain("\u276f  (", count=count + 1)
            session.write("0")
            assert session.exited() == 0, session.output

    def test_explicit_escape_event_then_numeric_exit(self, tmp_path: Path) -> None:
        """Bound unsupported Windows protocol input and verify a portable recovery."""
        config, _counter = self._config(tmp_path)
        with TerminalSession(TestTerminalWorkflows._command(config)) as session:
            session.wait("Projects1")
            session.write("nomatch")
            session.wait_plain("\u276f nomatch")
            session.write("\x1b[27u0")
            if sys.platform == "win32":
                # Crossterm uses native console events on Windows. ConPTY does not
                # negotiate Kitty here; the sequence becomes ordinary query text.
                session.wait_plain("\u276f nomatch[27u0")
                count = session.plain_output.count("\u276f  (")
                session.write("\x15")
                session.wait_plain("\u276f  (", count=count + 1)
                session.write("0")
            assert session.exited() == 0, session.output
