"""Stdlib harness contracts; these tests never launch a live usage session."""

import importlib.util
import os
import sys
import termios
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "usage_smoke_harness", Path(__file__).parents[1] / "scripts" / "tui_smoke.py"
)
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


def child(code):
    return [sys.executable, "-u", "-c", code]


def test_installed_entry_uses_current_environment(tmp_path, monkeypatch):
    interpreter = tmp_path / "python"
    entry = tmp_path / "usage"
    entry.write_text("#!/bin/sh\nexit 0\n")
    entry.chmod(0o700)
    monkeypatch.setattr(smoke.sys, "executable", str(interpreter))
    assert smoke.installed_command("healthy") == [str(entry), "--demo"]
    assert smoke.installed_command("errors") == [str(entry), "--demo", "--scenario", "errors"]
    with pytest.raises(ValueError):
        smoke.installed_command("other")
    entry.unlink()
    with pytest.raises(smoke.SmokeFailure, match="entry point missing"):
        smoke.installed_command("healthy")


def test_isolation_does_not_forward_credentials_or_driver(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-not-for-child")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/unwanted/config")
    monkeypatch.setenv("CODEX_HOME", "/unwanted/codex")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-not-for-child")
    monkeypatch.setenv("TEXTUAL_DRIVER", "unwanted.driver")
    environment = smoke.isolated_environment(str(tmp_path))
    assert environment["HOME"] == str(tmp_path)
    assert environment["XDG_CONFIG_HOME"] == str(tmp_path / "config")
    assert environment["CODEX_HOME"] == str(tmp_path / "codex")
    assert environment["USAGE_SMOKE_SYNTHETIC_SECRET"] == smoke.SECRET_SENTINEL
    assert "ANTHROPIC_API_KEY" not in environment
    assert "CLAUDE_CONFIG_DIR" not in environment
    assert "OPENAI_API_KEY" not in environment
    assert "TEXTUAL_DRIVER" not in environment


def test_terminal_escape_stripping_and_fragmented_utf8():
    terminal = smoke.PtySession([])
    terminal.capture.extend(b"\x1b]0;window title\x07\x1b[31m")
    encoded = "赠送余额".encode()
    terminal.capture.extend(encoded[:2])
    terminal.capture.extend(encoded[2:] + b"\x1b[0m")
    assert terminal.text() == "赠送余额"


@pytest.mark.parametrize("content", [smoke.SECRET_SENTINEL, "Traceback (most recent call last)"])
def test_capture_failures_never_include_transcript(content):
    terminal = smoke.PtySession([])
    terminal.capture.extend(content.encode())
    with pytest.raises(smoke.SmokeFailure) as caught:
        terminal.check_capture()
    assert content not in str(caught.value)


def test_drained_shutdown_handles_output_larger_than_pty_buffer():
    with smoke.PtySession(child("import os; os.write(1, b'x' * 262144)")) as terminal:
        terminal.wait_exit()
        assert len(terminal.capture) == 262144
    assert terminal.process.returncode == 0
    assert terminal.master == terminal.slave == -1


def test_failed_wait_kills_reaps_and_restores_in_finally():
    terminal = smoke.PtySession(child("import time; print('READY'); time.sleep(60)"))
    with pytest.raises(smoke.SmokeFailure, match="shutdown deadline"), terminal:
        terminal.expect("READY")
        terminal.wait_exit(timeout=0.05)
    assert terminal.process.returncode is not None
    assert terminal.master == terminal.slave == -1
    assert terminal.home is None
    with pytest.raises(ChildProcessError):
        os.waitpid(terminal.process.pid, os.WNOHANG)


def test_missing_token_wait_is_bounded_and_does_not_disclose_output():
    terminal = smoke.PtySession(child("import time; print('PRIVATE'); time.sleep(60)"))
    with pytest.raises(smoke.SmokeFailure) as caught, terminal:
        terminal.expect("never-rendered", timeout=0.05)
    assert "PRIVATE" not in str(caught.value)
    assert terminal.process.returncode is not None


def test_capture_limit_is_enforced(monkeypatch):
    monkeypatch.setattr(smoke, "MAX_CAPTURE", 64)
    with (
        pytest.raises(smoke.SmokeFailure, match="bounded memory"),
        smoke.PtySession(child("print('x' * 1024)")) as terminal,
    ):
        terminal.wait_exit()
    assert len(terminal.capture) <= 64
    assert terminal.process.returncode is not None


def test_total_deadline_bounds_send_and_wait():
    with smoke.PtySession(child("import time; time.sleep(60)"), total_timeout=0) as terminal:
        with pytest.raises(smoke.SmokeFailure, match="total timeout"):
            terminal.send(b"q")
        with pytest.raises(smoke.SmokeFailure, match="shutdown deadline"):
            terminal.wait_exit()


def test_restoration_requires_final_cursor_screen_and_original_termios():
    with smoke.PtySession(child("import time; time.sleep(60)")) as terminal:
        terminal.capture.extend(b"\x1b[?1049h\x1b[?25l\x1b[?1049l\x1b[?25h")
        terminal.assert_restored()
        changed = termios.tcgetattr(terminal.slave)
        changed[3] ^= termios.ECHO
        termios.tcsetattr(terminal.slave, termios.TCSANOW, changed)
        with pytest.raises(smoke.SmokeFailure, match="echo"):
            terminal.assert_restored()
        termios.tcsetattr(terminal.slave, termios.TCSANOW, terminal.original)
        terminal.capture.extend(b"\x1b[?25l")
        with pytest.raises(smoke.SmokeFailure, match="cursor"):
            terminal.assert_restored()


def test_main_failure_suppresses_exception_and_capture(monkeypatch, capsys):
    def fail(*_args):
        raise smoke.SmokeFailure("PRIVATE TRANSCRIPT")

    monkeypatch.setattr(smoke, "scenario_run", fail)
    assert smoke.main([]) == 1
    output = capsys.readouterr()
    assert "PRIVATE" not in output.out + output.err
    assert "capture withheld" in output.err
