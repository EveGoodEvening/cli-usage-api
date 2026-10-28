#!/usr/bin/env python3
"""Offline installed-entry smoke: uv run python scripts/tui_smoke.py [--scenario errors].

Captures stay in bounded memory, never on disk or in diagnostics. No browser,
credentials, live account state, or third-party terminal emulator is needed.
"""

from __future__ import annotations

import argparse
import errno
import fcntl
import json
import os
import pty
import re
import select
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import time
from pathlib import Path
from typing import Self

CSI = re.compile(rb"\x1b\[[0-?]*[ -/]*[@-~]")
OSC = re.compile(rb"\x1b\].*?(?:\x07|\x1b\\)", re.DOTALL)
MAX_CAPTURE = 4 * 1024 * 1024
SECRET_SENTINEL = "NEVER_RENDER_USAGE_SMOKE_SECRET_987654321"


class SmokeFailure(RuntimeError):
    """A curated failure that never includes captured terminal contents."""


def installed_command(scenario: str) -> list[str]:
    """Select the console script beside this interpreter, not another PATH install."""
    entry = Path(sys.executable).parent / "usage"
    if not entry.is_file() or not os.access(entry, os.X_OK):
        raise SmokeFailure("Installed usage entry point missing; run uv sync first.")
    command = [str(entry), "--demo"]
    if scenario == "errors":
        command.extend(("--scenario", "errors"))
    elif scenario != "healthy":
        raise ValueError("Unknown demo scenario.")
    return command


def isolated_environment(home: str) -> dict[str, str]:
    # Do not pass through credentials, alternate config locations, or driver hooks.
    environment = {
        "HOME": home,
        "XDG_CONFIG_HOME": home + "/config",
        "XDG_DATA_HOME": home + "/data",
        "XDG_CACHE_HOME": home + "/cache",
        "XDG_STATE_HOME": home + "/state",
        "TERM": "xterm-256color",
        "COLORTERM": "truecolor",
        "LANG": "C.UTF-8",
        "PYTHONUNBUFFERED": "1",
        "USAGE_SMOKE_SYNTHETIC_SECRET": SECRET_SENTINEL,
    }
    for name in ("PATH", "VIRTUAL_ENV", "SYSTEMROOT"):
        if name in os.environ:
            environment[name] = os.environ[name]
    return environment


class PtySession:
    """One bounded, drained subprocess lifetime with unconditional kill/reap."""

    def __init__(self, command: list[str], *, total_timeout: float = 45) -> None:
        self.command = command
        self.deadline = time.monotonic() + total_timeout
        self.capture = bytearray()
        self.process: subprocess.Popen | None = None
        self.master = self.slave = -1
        self.original = None
        self.home = None
        self.eof = False

    def __enter__(self) -> Self:
        try:
            self.home = tempfile.TemporaryDirectory(prefix="usage-pty-")
            self.master, self.slave = pty.openpty()
            self.original = termios.tcgetattr(self.slave)
            self.resize(80, 24)
            self.process = subprocess.Popen(
                self.command,
                stdin=self.slave,
                stdout=self.slave,
                stderr=self.slave,
                env=isolated_environment(self.home.name),
                cwd=self.home.name,
                start_new_session=True,
            )
            return self
        except BaseException:
            self.close()
            raise

    def __exit__(self, *_exc) -> None:
        self.close()

    def close(self) -> None:
        try:
            if self.process is not None:
                if self.process.poll() is None:
                    try:
                        os.killpg(self.process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                self.process.wait(timeout=3)
        finally:
            try:
                if self.original is not None and self.slave >= 0:
                    termios.tcsetattr(self.slave, termios.TCSANOW, self.original)
            finally:
                for name in ("master", "slave"):
                    descriptor = getattr(self, name)
                    if descriptor >= 0:
                        os.close(descriptor)
                        setattr(self, name, -1)
                if self.home is not None:
                    self.home.cleanup()
                    self.home = None

    def resize(self, width: int, height: int) -> None:
        fcntl.ioctl(self.slave, termios.TIOCSWINSZ, struct.pack("HHHH", height, width, 0, 0))
        if self.process is not None and self.process.poll() is None:
            self.process.send_signal(signal.SIGWINCH)

    def text(self) -> str:
        return CSI.sub(b"", OSC.sub(b"", bytes(self.capture))).decode("utf-8", "replace")

    def check_capture(self) -> None:
        if SECRET_SENTINEL.encode() in self.capture:
            raise SmokeFailure("Synthetic secret appeared in terminal output.")
        if b"Traceback (most recent call last)" in self.capture:
            raise SmokeFailure("Child rendered a Python traceback.")

    def drain(self, seconds: float = 0.15) -> None:
        until = min(time.monotonic() + seconds, self.deadline)
        while not self.eof and time.monotonic() < until:
            ready, _, _ = select.select([self.master], [], [], max(0, until - time.monotonic()))
            if not ready:
                break
            try:
                chunk = os.read(self.master, 65536)
            except OSError as error:
                if error.errno != errno.EIO:
                    raise
                chunk = b""
            if not chunk:
                self.eof = True
                break
            if len(self.capture) + len(chunk) > MAX_CAPTURE:
                raise SmokeFailure("Terminal capture exceeded its bounded memory allowance.")
            self.capture.extend(chunk)
            self.check_capture()

    def expect(self, token: str, *, timeout: float = 5) -> None:
        until = min(time.monotonic() + timeout, self.deadline)
        while token not in self.text():
            if time.monotonic() >= until or self.eof:
                raise SmokeFailure("Timed out waiting for a required rendered UI token.")
            self.drain(min(0.1, max(0, until - time.monotonic())))
            if self.process.poll() is not None and token not in self.text():
                raise SmokeFailure("Child exited before rendering a required UI token.")

    def send(self, value: bytes) -> None:
        if time.monotonic() >= self.deadline:
            raise SmokeFailure("PTY scenario exceeded its total timeout.")
        os.write(self.master, value)
        self.drain()

    def wait_exit(self, *, timeout: float = 8) -> None:
        until = min(time.monotonic() + timeout, self.deadline)
        while self.process.poll() is None:
            if time.monotonic() >= until:
                raise SmokeFailure("Child did not exit within its drained shutdown deadline.")
            self.drain(min(0.1, max(0, until - time.monotonic())))
        self.process.wait(timeout=1)
        self.drain(0.2)
        if self.process.returncode != 0:
            raise SmokeFailure("Installed usage child exited unsuccessfully.")
        self.check_capture()

    def assert_restored(self) -> None:
        sequences = (
            (b"\x1b[?1049l", b"\x1b[?1049h"),
            (b"\x1b[?25h", b"\x1b[?25l"),
        )
        for restored, hidden in sequences:
            if self.capture.rfind(restored) <= self.capture.rfind(hidden):
                raise SmokeFailure("Terminal screen or cursor was not restored.")
        if termios.tcgetattr(self.slave) != self.original:
            raise SmokeFailure("Terminal input modes, including echo, were not restored.")


def scenario_run(scenario: str, quit_key: str = "q") -> dict[str, str | bool | int]:
    if quit_key not in {"q", "ctrl+c"}:
        raise ValueError("Unknown quit key.")
    with PtySession(installed_command(scenario)) as terminal:
        terminal.expect("DEMO")
        terminal.expect("Claude")
        # Navigation makes every row visible; a headless model assertion is not enough.
        for _ in range(35):
            terminal.send(b"\x1b[B")
        for token in (
            "Claude 5h",
            "Claude 每周",
            "Fable",
            "Claude Platform",
            "购买余额",
            "赠送余额",
            "总余额",
            "ChatGPT",
            "Grok 共享池",
            "GrokBuild",
            "GrokChat",
            "已用",
            "剩余",
        ):
            terminal.expect(token)
        if scenario == "healthy":
            terminal.expect("USD")
        if scenario == "errors":
            for token in ("STALE", "LAST KNOWN", "retry"):
                terminal.expect(token)
        terminal.send(b"\r")
        terminal.expect("Details")
        terminal.expect("provenance")
        terminal.send(b"\x1b")
        terminal.send(b"?")
        terminal.expect("Help")
        terminal.send(b"\x1b")
        terminal.send(b"a")
        terminal.expect("read only")
        terminal.send(b"\x1b")
        terminal.send(b"r")
        terminal.expect("refresh pending")
        terminal.resize(40, 12)
        terminal.expect("窗口较小")
        terminal.send(b"\x1b[B")
        if quit_key == "ctrl+c":
            terminal.send(b"?")
            terminal.send(b"\x03")
        else:
            terminal.send(b"q")
        terminal.wait_exit()
        terminal.assert_restored()
        return {
            "scenario": scenario,
            "quit": quit_key,
            "bytes": len(terminal.capture),
            "rendered_metrics": True,
            "terminal_restored": True,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=("healthy", "errors", "all"), default="all")
    arguments = parser.parse_args(argv)
    scenarios = ("healthy", "errors") if arguments.scenario == "all" else (arguments.scenario,)
    try:
        for scenario in scenarios:
            for quit_key in ("q", "ctrl+c"):
                print(json.dumps(scenario_run(scenario, quit_key)), flush=True)
    except (SmokeFailure, OSError, subprocess.SubprocessError):
        # Neither exception strings nor terminal transcripts are safe diagnostics.
        print(
            "PTY smoke failed (capture withheld); check installation and terminal lifecycle.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
