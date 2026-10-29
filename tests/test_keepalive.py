import asyncio
import base64
import json
import os
import stat
import threading
import time
from datetime import UTC, datetime, timedelta

import pytest

from cli_usage_api import keepalive
from cli_usage_api.domain import Account, CredentialKind, ProviderId
from cli_usage_api.keepalive import (
    BACKUP_SUFFIX,
    CLAUDE_MODEL,
    CLAUDE_STATUS,
    GROK_SESSIONS,
    RETRY_DELAYS,
    UNKNOWN_EXPIRY_INTERVAL,
    WINDOW_SECONDS,
    InstanceLock,
    Keepalive,
    KeepaliveError,
    Observation,
    Target,
    observe_claude,
    observe_codex,
    observe_grok,
    run_async,
)
from cli_usage_api.storage import AccountStore

NOW = datetime(2026, 10, 29, 12, tzinfo=UTC)


def _ms(value: datetime) -> int:
    return int(value.timestamp() * 1000)


def _claude(path, expires_at, token="access-placeholder"):
    content = {
        "claudeAiOauth": {
            "accessToken": token,
            "refreshToken": "refresh-placeholder",
            "expiresAt": expires_at if isinstance(expires_at, int) else _ms(expires_at),
        }
    }
    path.write_text(json.dumps(content))
    path.chmod(0o600)


def _jwt(exp: int) -> str:
    def part(value: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")

    return f"{part({'alg': 'none'})}.{part({'exp': exp})}.c2ln"


class Clock:
    def __init__(self) -> None:
        self.now = NOW
        self.mono = 1000.0

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)
        self.mono += seconds


def _runner(clock, path, results, calls):
    """Fake CLI: each call pops a behavior that may rewrite the credentials file."""

    def run(argv):
        calls.append(tuple(argv))
        behavior = results.pop(0)
        if behavior == "refresh":
            _claude(path, clock.now + timedelta(hours=8), token="new-access-placeholder")
        elif behavior == "blank":
            _claude(path, 0, token="")
        elif behavior == "delete":
            path.unlink()
        return 0

    return run


def _keepalive(tmp_path, results, mode=(CLAUDE_STATUS, CLAUDE_MODEL)):
    clock = Clock()
    path = tmp_path / ".credentials.json"
    calls, logs = [], []
    target = Target("claude", lambda: path, observe_claude, mode, backup=True)
    app = Keepalive(
        [target],
        log=logs.append,
        run=_runner(clock, path, results, calls),
        clock=lambda: clock.now,
        monotonic=lambda: clock.mono,
    )
    return app, target, path, clock, calls, logs


def test_observers_read_only_expiry_hints(tmp_path):
    claude = tmp_path / "claude.json"
    _claude(claude, NOW)
    assert observe_claude(claude) == Observation(True, NOW)
    _claude(claude, 0, token="")
    assert not observe_claude(claude).usable
    assert observe_claude(tmp_path / "missing.json") == Observation(False, None)

    codex = tmp_path / "codex.json"
    codex.write_text(json.dumps({"tokens": {"access_token": _jwt(int(NOW.timestamp()))}}))
    assert observe_codex(codex) == Observation(True, NOW)

    grok = tmp_path / "grok.json"
    later = NOW + timedelta(hours=1)
    grok.write_text(
        json.dumps(
            {
                "https://auth.x.ai::a": {"key": "k", "expires_at": later.isoformat()},
                "https://auth.x.ai::b": {"key": "k", "expires_at": NOW.isoformat()},
                "https://auth.x.ai::c": {"key": "", "expires_at": "2000-01-01T00:00:00Z"},
            }
        )
    )
    observed = observe_grok(grok)
    assert (observed.usable, observed.expires_at) == (True, NOW)
    assert dict(observed.scopes) == {"https://auth.x.ai::a": later, "https://auth.x.ai::b": NOW}

    deep = tmp_path / "deep.json"
    deep.write_text("[" * 100_000 + "]" * 100_000)
    for observe in (observe_claude, observe_codex, observe_grok):
        assert observe(deep) == Observation(False, None)


def test_not_due_outside_window_runs_nothing(tmp_path):
    app, _, path, _, calls, _ = _keepalive(tmp_path, [])
    _claude(path, NOW + timedelta(minutes=30))
    app.tick()
    assert calls == []


def test_status_refresh_skips_model_and_removes_backup(tmp_path):
    app, target, path, _, calls, logs = _keepalive(tmp_path, ["refresh"])
    _claude(path, NOW + timedelta(minutes=4))
    app.tick()
    assert calls == [CLAUDE_STATUS]
    assert not path.with_name(path.name + BACKUP_SUFFIX).exists()
    assert target.failures == 0
    assert any("refreshed via=auth" in line for line in logs)
    assert not any("placeholder" in line for line in logs)


def test_status_without_progress_falls_back_to_haiku(tmp_path):
    app, _, path, _, calls, logs = _keepalive(tmp_path, ["noop", "refresh"])
    _claude(path, NOW + timedelta(minutes=4))
    app.tick()
    assert calls == [CLAUDE_STATUS, CLAUDE_MODEL]
    assert "--model" in CLAUDE_MODEL and "haiku" in CLAUDE_MODEL
    assert any("refreshed via=-p" in line for line in logs)


def test_blanked_file_is_restored_then_haiku_retried(tmp_path):
    app, _, path, _, calls, logs = _keepalive(tmp_path, ["blank", "refresh"])
    _claude(path, NOW + timedelta(minutes=4))
    app.tick()
    assert calls == [CLAUDE_STATUS, CLAUDE_MODEL]
    assert "claude restored_backup" in logs
    assert observe_claude(path).usable
    assert oct(path.stat().st_mode & 0o777) == "0o600"


def test_retries_back_off_then_alert_keeps_backup(tmp_path):
    attempts = len(RETRY_DELAYS) + 1
    app, target, path, clock, calls, logs = _keepalive(tmp_path, ["noop"] * (2 * attempts))
    _claude(path, NOW + timedelta(minutes=4))
    for delay in (0, *RETRY_DELAYS):
        clock.advance(delay)
        app.tick()
    assert len(calls) == 2 * attempts
    assert target.alerted
    assert path.with_name(path.name + BACKUP_SUFFIX).exists()
    assert any("ALERT manual login required" in line for line in logs)
    clock.advance(3600)
    app.tick()
    assert len(calls) == 2 * attempts  # Alerted: no further attempts until re-login.


def test_retry_waits_for_backoff(tmp_path):
    app, target, path, clock, calls, _ = _keepalive(tmp_path, ["noop", "noop", "refresh"])
    _claude(path, NOW + timedelta(minutes=4))
    app.tick()
    clock.advance(RETRY_DELAYS[0] - 1)
    app.tick()
    assert len(calls) == 2
    clock.advance(1)
    app.tick()
    assert len(calls) == 3 and target.failures == 0


def test_manual_relogin_clears_alert(tmp_path):
    app, target, path, _clock, calls, _ = _keepalive(tmp_path, ["refresh"])
    target.alerted = True
    _claude(path, NOW + timedelta(minutes=4))
    target.last_seen = observe_claude(path)
    _claude(path, NOW + timedelta(minutes=3))  # e.g. a fresh /login wrote new state
    app.tick()
    assert not target.alerted and calls == [CLAUDE_STATUS]


def test_run_command_times_out_and_discards_output():
    assert keepalive.run_command(["sh", "-c", "echo secret; exit 3"]) == 3
    assert keepalive.run_command(["sleep", "5"], timeout=0.2) is None
    assert keepalive.run_command(["/nonexistent/cli"]) is None


MODERN = "https://auth.x.ai::client"
LEGACY = "https://accounts.x.ai/sign-in"


def _grok_file(path, scopes):
    path.write_text(
        json.dumps(
            {key: {"key": "k", "expires_at": value.isoformat()} for key, value in scopes.items()}
        )
    )


def _grok_keepalive(tmp_path, scopes, refresh_modern, code=0, protected=frozenset()):
    """Fake grok CLI that renews only the modern scope, and only inside its window."""
    clock = Clock()
    path = tmp_path / "auth.json"
    _grok_file(path, scopes)
    calls, logs = [], []

    def run(argv):
        calls.append(tuple(argv))
        current = {
            key: datetime.fromisoformat(v["expires_at"])
            for key, v in json.loads(path.read_text()).items()
        }
        if refresh_modern and (current[MODERN] - clock.now).total_seconds() <= 300:
            current[MODERN] = clock.now + timedelta(hours=6)
            _grok_file(path, current)
        return code

    target = Target("grok", lambda: path, observe_grok, (GROK_SESSIONS,), protected=protected)
    app = Keepalive(
        [target], log=logs.append, run=run, clock=lambda: clock.now, monotonic=lambda: clock.mono
    )
    return app, target, path, clock, calls, logs


def test_grok_expired_legacy_scope_with_refreshing_modern_scope_succeeds(tmp_path):
    scopes = {LEGACY: NOW - timedelta(days=30), MODERN: NOW + timedelta(minutes=4)}
    app, target, _path, clock, calls, logs = _grok_keepalive(tmp_path, scopes, True)
    app.tick()
    assert calls == [GROK_SESSIONS]
    assert any(line.startswith("grok refreshed via=sessions") for line in logs)
    assert logs.count("grok stale_scope_ignored scope=legacy") == 1
    assert target.failures == 0 and not target.alerted
    # Six hours later the real scope is due again; the stale one never pins scheduling.
    for _ in range(3):
        clock.advance(6 * 3600 - 200)
        app.tick()
    assert len(calls) == 4
    assert not target.alerted and target.failures == 0
    assert not any("ALERT" in line or "retry_in" in line for line in logs)
    assert logs.count("grok stale_scope_ignored scope=legacy") == 1
    assert "https://" not in "".join(logs)


def test_grok_lone_due_scope_without_proof_is_retried_not_stale(tmp_path):
    # Exit 0 but nothing advanced: no proof the CLI renews another scope, so retry.
    scopes = {LEGACY: NOW - timedelta(days=30), MODERN: NOW + timedelta(hours=2)}
    app, target, _path, clock, calls, logs = _grok_keepalive(tmp_path, scopes, True)
    app.tick()
    assert calls == [GROK_SESSIONS]
    assert target.stale == {} and target.failures == 1
    assert f"retry_in={RETRY_DELAYS[0]}s attempt=1" in " ".join(logs)
    for delay in RETRY_DELAYS:
        clock.advance(delay)
        app.tick()
    assert target.alerted and len(calls) == len(RETRY_DELAYS) + 1
    clock.advance(600)
    app.tick()
    assert len(calls) == len(RETRY_DELAYS) + 1  # The failed scope alone stays alerted.
    # The modern scope entering its own window is still renewed, which proves the
    # legacy scope is not the CLI's active one: it becomes stale and the alert clears.
    clock.advance(2 * 3600 - sum(RETRY_DELAYS) - 600 - 200)
    app.tick()
    assert len(calls) == len(RETRY_DELAYS) + 2
    assert any(line.startswith("grok refreshed via=sessions") for line in logs)
    assert logs.count("grok stale_scope_ignored scope=legacy") == 1
    assert not target.alerted and target.failures == 0
    assert "https://" not in "".join(logs)


def test_grok_failed_refresh_never_marks_active_scope_stale(tmp_path):
    # The active modern scope is due but the CLI fails (exit 1); a second live scope
    # is not due. The due scope must be retried, never silently ignored.
    other = "https://auth.x.ai::other"
    scopes = {MODERN: NOW + timedelta(minutes=4), other: NOW + timedelta(hours=5)}
    app, target, _path, clock, calls, logs = _grok_keepalive(tmp_path, scopes, False, code=1)
    app.tick()
    assert target.stale == {} and target.failures == 1
    assert "grok not_advanced via=sessions exit=1" in " ".join(logs)
    assert not any("stale_scope_ignored" in line for line in logs)
    clock.advance(RETRY_DELAYS[0])
    app.tick()
    assert len(calls) == 2 and target.failures == 2 and target.stale == {}


def test_grok_nonzero_exit_with_advance_does_not_mark_stale(tmp_path):
    scopes = {LEGACY: NOW - timedelta(days=30), MODERN: NOW + timedelta(minutes=4)}
    app, target, _path, _clock, _calls, logs = _grok_keepalive(tmp_path, scopes, True, code=1)
    app.tick()
    assert any(line.startswith("grok refreshed") for line in logs)
    assert target.stale == {} and target.failures == 0


def test_grok_protected_scope_never_marked_stale(tmp_path):
    scopes = {LEGACY: NOW - timedelta(days=30), MODERN: NOW + timedelta(minutes=4)}
    app, target, _path, clock, calls, logs = _grok_keepalive(
        tmp_path, scopes, True, protected=frozenset({LEGACY})
    )
    app.tick()
    assert any(line.startswith("grok refreshed") for line in logs)
    assert target.stale == {}
    assert not any("stale_scope_ignored" in line for line in logs)
    # The protected scope still schedules, so its continued failure is surfaced.
    clock.advance(5)
    app.tick()
    assert len(calls) == 2 and target.failures == 1


def test_grok_preferred_scope_never_marked_stale(tmp_path):
    # Only a legacy scope: it is the reader's selection, so failures still alert.
    app, target, _path, _clock, _calls, _logs = _grok_keepalive(
        tmp_path, {LEGACY: NOW + timedelta(minutes=4)}, False
    )
    app.tick()
    assert target.stale == {} and target.failures == 1


def test_grok_stale_scope_revives_when_its_expiry_changes(tmp_path):
    scopes = {LEGACY: NOW - timedelta(days=30), MODERN: NOW + timedelta(minutes=4)}
    app, target, path, clock, calls, logs = _grok_keepalive(tmp_path, scopes, True)
    app.tick()
    assert LEGACY in target.stale
    modern = clock.now + timedelta(hours=6)
    _grok_file(path, {LEGACY: NOW + timedelta(minutes=3), MODERN: modern})
    app.tick()
    # Revived and scheduled again; without proof it is a retried failure, not stale.
    assert len(calls) == 2
    assert target.stale == {} and target.failures == 1
    assert logs.count("grok stale_scope_ignored scope=legacy") == 1


def test_restore_skips_logout_deleted_file(tmp_path):
    app, _, path, _, _calls, logs = _keepalive(tmp_path, ["delete"], mode=(CLAUDE_STATUS,))
    _claude(path, NOW + timedelta(minutes=4))
    app.tick()
    assert not path.exists()
    assert "claude restore_skipped_file_missing" in logs
    assert "claude restored_backup" not in logs


def test_restore_skips_file_changed_after_command(tmp_path):
    app, target, path, _, _calls, logs = _keepalive(tmp_path, ["blank"], mode=(CLAUDE_STATUS,))
    _claude(path, NOW + timedelta(minutes=4))
    observe = target.observe
    seen = []

    def concurrent(p):
        result = observe(p)
        if not seen and not result.usable:
            seen.append(1)
            p.write_text('{"claudeAiOauth": {"accessToken": ""}}')  # a different writer
        return result

    target.observe = concurrent
    app.tick()
    assert "claude restore_skipped_file_changed" in logs
    assert path.read_text() == '{"claudeAiOauth": {"accessToken": ""}}'


def test_restore_and_backup_use_private_unique_temp_files(tmp_path):
    app, _, path, _, _calls, logs = _keepalive(tmp_path, ["blank", "noop"])
    outside = tmp_path / "outside"
    outside.write_text("untouched")
    backup = path.with_name(path.name + BACKUP_SUFFIX)
    backup.symlink_to(outside)  # A planted link must be replaced, not followed.
    _claude(path, NOW + timedelta(minutes=4))
    app.tick()
    assert "claude restored_backup" in logs and observe_claude(path).usable
    assert outside.read_text() == "untouched"
    assert not backup.is_symlink() and oct(backup.stat().st_mode & 0o777) == "0o600"
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert not list(tmp_path.glob("*keepalive-tmp*"))


def test_alert_recovery_by_relogin_deletes_stale_backup(tmp_path):
    attempts = len(RETRY_DELAYS) + 1
    app, target, path, clock, _calls, logs = _keepalive(tmp_path, ["noop"] * (2 * attempts))
    _claude(path, NOW + timedelta(minutes=4))
    for delay in (0, *RETRY_DELAYS):
        clock.advance(delay)
        app.tick()
    backup = path.with_name(path.name + BACKUP_SUFFIX)
    assert target.alerted and backup.exists()
    _claude(path, clock.now + timedelta(hours=8))  # manual /login
    app.tick()
    assert not target.alerted and not backup.exists()
    assert "claude recovered" in " ".join(logs)


def test_codex_alert_does_not_mention_backup(tmp_path):
    clock = Clock()
    path = tmp_path / "auth.json"
    path.write_text(json.dumps({"tokens": {"access_token": _jwt(int(NOW.timestamp()) + 200)}}))
    logs = []
    target = Target("codex", lambda: path, observe_codex, (("codex", "doctor", "--json"),))
    app = Keepalive(
        [target],
        log=logs.append,
        run=lambda argv: 0,
        clock=lambda: clock.now,
        monotonic=lambda: clock.mono,
    )
    for delay in (0, *RETRY_DELAYS):
        clock.advance(delay)
        app.tick()
    alerts = [line for line in logs if "ALERT manual login required" in line]
    assert alerts and not any("backup" in line for line in alerts)


def test_unknown_expiry_run_is_not_reported_as_refreshed(tmp_path):
    clock = Clock()
    path = tmp_path / "auth.json"
    path.write_text(json.dumps({LEGACY: {"key": "k"}}))
    logs, calls = [], []
    target = Target("grok", lambda: path, observe_grok, (GROK_SESSIONS,))
    app = Keepalive(
        [target],
        log=logs.append,
        run=calls.append,
        clock=lambda: clock.now,
        monotonic=lambda: clock.mono,
    )
    app.tick()
    assert logs == [f"grok ran_unknown_expiry via=sessions next_in={UNKNOWN_EXPIRY_INTERVAL}s"]
    clock.advance(UNKNOWN_EXPIRY_INTERVAL - 1)
    app.tick()
    assert len(calls) == 1


def test_tick_error_is_logged_by_type_and_loop_continues(tmp_path):
    clock = Clock()
    logs, calls = [], []

    def broken(path):
        raise TypeError("secret-looking message")

    codex = tmp_path / "auth.json"
    codex.write_text(json.dumps({"tokens": {"access_token": _jwt(int(NOW.timestamp()) + 60)}}))
    targets = [
        Target("claude", lambda: tmp_path / "x", broken, (CLAUDE_STATUS,), backup=True),
        Target("codex", lambda: codex, observe_codex, (("codex", "doctor", "--json"),)),
    ]
    app = Keepalive(
        targets,
        log=logs.append,
        run=calls.append,
        clock=lambda: clock.now,
        monotonic=lambda: clock.mono,
    )
    app.tick()
    assert "claude tick_error type=TypeError" in logs
    assert not any("secret-looking" in line for line in logs)
    assert calls == [("codex", "doctor", "--json")]


def test_backup_unlink_failure_does_not_crash(tmp_path, monkeypatch):
    app, target, path, _, _calls, logs = _keepalive(tmp_path, ["refresh"])
    _claude(path, NOW + timedelta(minutes=4))
    original = type(path).unlink

    def unlink(self, missing_ok=False):
        if self.name.endswith(BACKUP_SUFFIX):
            raise PermissionError
        return original(self, missing_ok=missing_ok)

    monkeypatch.setattr(type(path), "unlink", unlink)
    app.tick()
    assert "claude backup_delete_failed" in logs and target.failures == 0
    assert not any("tick_error" in line for line in logs)


def test_external_renewal_resets_backoff_without_keepalive_success(tmp_path):
    app, target, path, clock, _calls, _logs = _keepalive(tmp_path, ["noop", "noop"])
    _claude(path, NOW + timedelta(minutes=4))
    app.tick()
    assert target.failures == 1 and target.next_attempt > clock.mono
    _claude(path, NOW + timedelta(hours=8))  # an interactive session renewed it
    clock.advance(5)
    app.tick()
    assert target.failures == 0 and target.next_attempt == 0.0
    assert not path.with_name(path.name + BACKUP_SUFFIX).exists()


def test_sleep_tracks_window_start_and_backoff(tmp_path):
    app, _target, path, clock, calls, _logs = _keepalive(tmp_path, ["noop", "noop"])
    _claude(path, NOW + timedelta(seconds=WINDOW_SECONDS + 100))
    app.tick()
    assert calls == []
    assert app.sleep_seconds(240) == 100  # wake at the window start, not after 240 s
    assert app.sleep_seconds(60) == 60
    clock.advance(100)
    app.tick()
    assert len(calls) == 2
    assert app.sleep_seconds(240) == RETRY_DELAYS[0]  # backoff is not rounded up
    clock.advance(RETRY_DELAYS[0] + 1)
    assert app.sleep_seconds(240) == 1.0


def test_interval_capped_below_window(capsys):
    assert keepalive.main(["--interval", "241", "--once"]) == 2
    assert "between 10 and 240" in capsys.readouterr().err
    assert keepalive.MAX_INTERVAL < WINDOW_SECONDS


def test_logout_during_attempt_alerts_at_once_and_drops_backup(tmp_path):
    app, target, path, clock, calls, logs = _keepalive(tmp_path, ["delete"])
    _claude(path, NOW + timedelta(minutes=4))
    app.tick()
    assert calls == [CLAUDE_STATUS]  # No Haiku request against a deleted login.
    assert logs.count("claude ALERT login file missing or unusable; log in again") == 1
    assert not any("retry_in" in line for line in logs)
    assert not path.with_name(path.name + BACKUP_SUFFIX).exists()
    for _ in range(3):
        clock.advance(600)
        app.tick()
    assert calls == [CLAUDE_STATUS]
    assert logs.count("claude ALERT login file missing or unusable; log in again") == 1
    _claude(path, clock.now + timedelta(hours=8))  # a new login
    app.tick()
    assert not target.alerted and "claude recovered" in " ".join(logs)


def test_unusable_file_left_by_attempt_alerts_and_keeps_backup(tmp_path):
    app, target, path, clock, calls, logs = _keepalive(tmp_path, ["blank"], mode=(CLAUDE_STATUS,))
    _claude(path, NOW + timedelta(minutes=4))
    observe = target.observe

    def concurrent(p):
        result = observe(p)
        if not result.usable and "writer" not in p.read_text():
            p.write_text('{"claudeAiOauth": {"accessToken": "", "writer": 1}}')
        return result

    target.observe = concurrent
    app.tick()
    assert "claude restore_skipped_file_changed" in logs
    assert logs[-1] == "claude ALERT login file missing or unusable; log in again"
    assert not any("retry_in" in line for line in logs)
    assert path.with_name(path.name + BACKUP_SUFFIX).exists()
    clock.advance(3600)
    app.tick()
    assert calls == [CLAUDE_STATUS]


def _homes(tmp_path, monkeypatch, *present):
    for variable in ("CLAUDE_CONFIG_DIR", "CODEX_HOME", "GROK_HOME"):
        directory = tmp_path / variable
        directory.mkdir()
        monkeypatch.setenv(variable, str(directory))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    files = {
        "claude": tmp_path / "CLAUDE_CONFIG_DIR" / ".credentials.json",
        "codex": tmp_path / "CODEX_HOME" / "auth.json",
        "grok": tmp_path / "GROK_HOME" / "auth.json",
    }
    for name in present:
        files[name].write_text("{}")


def test_build_selects_present_logins_and_validates(tmp_path, monkeypatch):
    _homes(tmp_path, monkeypatch)
    with pytest.raises(KeepaliveError, match="No official CLI login files found"):
        keepalive.build(None, log=print)
    _homes_present = tmp_path / "GROK_HOME" / "auth.json"
    _homes_present.write_text("{}")
    (tmp_path / "CODEX_HOME" / "auth.json").write_text("{}")
    built = keepalive.build(None, log=print, grok_protected_scopes=[MODERN])
    assert [t.name for t in built.targets] == ["codex", "grok"]
    assert built.targets[1].protected == frozenset({MODERN})
    status = keepalive.build(["claude", "grok", "claude"], "status", log=print)
    assert [t.name for t in status.targets] == ["claude", "grok"]
    assert status.targets[0].commands == (CLAUDE_STATUS,)
    for names, mode in ((["nope"], "hybrid"), ([], "hybrid"), (["grok"], "turbo")):
        with pytest.raises(KeepaliveError):
            keepalive.build(names, mode, log=print)
    with pytest.raises(KeepaliveError, match="No official CLI login files found"):
        keepalive.build(["claude"], log=print)


def test_instance_lock_is_exclusive_and_private(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    state = tmp_path / "home" / ".local" / "state" / "usage-keepalive"
    with InstanceLock():
        assert stat.S_IMODE(state.stat().st_mode) == 0o700
        assert stat.S_IMODE((state / "keepalive.lock").stat().st_mode) == 0o600
        with pytest.raises(KeepaliveError, match="Another usage-keepalive is already running"):
            InstanceLock().__enter__()
    with InstanceLock():  # Released on exit.
        pass


def test_instance_lock_refuses_symlink(tmp_path):
    outside = tmp_path / "outside"
    outside.write_text("untouched")
    lock = tmp_path / "state" / "keepalive.lock"
    lock.parent.mkdir()
    lock.symlink_to(outside)
    with pytest.raises(KeepaliveError):
        InstanceLock(lock).__enter__()
    assert outside.read_text() == "untouched"


def test_main_refuses_second_instance(tmp_path, monkeypatch, capsys):
    _homes(tmp_path, monkeypatch, "codex")
    with InstanceLock():
        assert keepalive.main(["--once"]) == 2
    assert "Another usage-keepalive is already running." in capsys.readouterr().err


class _CountingKeepalive:
    """Fake with the surface run_async uses; its third tick raises."""

    def __init__(self):
        self.ticks = 0
        self.logs = []

    def tick(self):
        self.ticks += 1
        if self.ticks == 3:
            raise RuntimeError("unguarded secret-looking message")

    def sleep_seconds(self):
        return 0.0

    def log(self, message):
        self.logs.append(message)


def test_run_async_returns_promptly_when_stopped(tmp_path):
    async def scenario():
        stop = asyncio.Event()
        clock = Clock()
        path = tmp_path / "auth.json"
        path.write_text(json.dumps({"tokens": {"access_token": _jwt(int(NOW.timestamp()) + 60)}}))
        calls = []
        target = Target("codex", lambda: path, observe_codex, (("codex", "doctor", "--json"),))
        app = Keepalive(
            [target],
            log=[].append,
            run=calls.append,
            clock=lambda: clock.now,
            monotonic=lambda: clock.mono,
        )
        task = asyncio.create_task(run_async(app, stop))
        for _ in range(100):
            await asyncio.sleep(0.01)
            if calls:
                break
        assert calls == [("codex", "doctor", "--json")]
        stop.set()
        await asyncio.wait_for(task, timeout=1.0)  # sleep_seconds is ~30 s: stop wins.

        # A raising tick is logged by type only; the loop then backs off, not exits.
        stop = asyncio.Event()
        fake = _CountingKeepalive()
        task = asyncio.create_task(run_async(fake, stop))
        for _ in range(200):
            await asyncio.sleep(0.01)
            if fake.logs:
                break
        await asyncio.sleep(0.05)
        assert fake.ticks == 3 and fake.logs == ["keepalive loop_error type=RuntimeError"]
        assert not task.done()
        stop.set()
        await asyncio.wait_for(task, timeout=1.0)

        # Cancellation propagates cleanly.
        task = asyncio.create_task(run_async(_CountingKeepalive(), asyncio.Event()))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())


def test_run_async_skips_work_when_already_stopped():
    stop = asyncio.Event()
    stop.set()
    fake = _CountingKeepalive()
    asyncio.run(run_async(fake, stop))
    assert fake.ticks == 0


def test_file_logger_appends_private_lines_and_never_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    log = keepalive.file_logger()
    log("grok refreshed via=sessions")
    log("codex retry_in=30s")
    path = tmp_path / "home" / ".local" / "state" / "usage-keepalive" / "keepalive.log"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    lines = path.read_text().splitlines()
    assert [line.split(" ", 1)[1] for line in lines] == [
        "grok refreshed via=sessions",
        "codex retry_in=30s",
    ]
    assert all(datetime.strptime(line.split()[0], "%Y-%m-%dT%H:%M:%SZ") for line in lines)

    outside = tmp_path / "outside"
    outside.write_text("untouched")
    link = tmp_path / "link.log"
    link.symlink_to(outside)
    keepalive.file_logger(link)("dropped")  # O_NOFOLLOW: dropped, not raised.
    assert outside.read_text() == "untouched"
    fifo = tmp_path / "fifo.log"
    os.mkfifo(fifo)
    keepalive.file_logger(fifo)("dropped")  # Non-regular file: no hang, no raise.
    keepalive.file_logger(tmp_path / "missing-dir" / "x.log")("dropped")


# --- Cooperative stop -------------------------------------------------------------


def test_stop_during_first_hybrid_command_never_runs_model(tmp_path):
    app, target, path, _clock, calls, logs = _keepalive(tmp_path, [])
    _claude(path, NOW + timedelta(minutes=3))

    def run(argv):
        calls.append(tuple(argv))
        app.request_stop()  # The stop arrives while auth status is running.
        return -9  # As if killed by SIGKILL.

    app._run = run
    app.tick()
    assert calls == [CLAUDE_STATUS]
    assert "claude attempt_stopped via=auth" in " ".join(logs)
    # A stopped attempt is neither a success nor a failure.
    assert target.failures == 0 and not target.alerted and target.next_attempt == 0.0
    assert not any("retry_in" in line or "ALERT" in line for line in logs)
    app.tick()  # No new work after a stop.
    assert calls == [CLAUDE_STATUS]


def test_stop_between_targets_starts_no_later_target(tmp_path):
    clock = Clock()
    calls = []
    paths = []
    for name in ("first", "second"):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps({"tokens": {"access_token": _jwt(int(NOW.timestamp()) + 60)}}))
        paths.append(path)
    targets = [
        Target(name, (lambda p=p: p), observe_codex, ((name, "doctor"),))
        for name, p in zip(("first", "second"), paths, strict=True)
    ]

    def run(argv):
        calls.append(tuple(argv))
        app.request_stop()
        return 0

    app = Keepalive(
        targets, log=[].append, run=run, clock=lambda: clock.now, monotonic=lambda: clock.mono
    )
    app.tick()
    assert calls == [("first", "doctor")]
    assert app.wait_idle(0)


def _alive(pid: int) -> bool:
    try:
        with open(f"/proc/{pid}/stat") as handle:
            return handle.read().rsplit(")", 1)[1].split()[0] not in {"Z", "X"}
    except (FileNotFoundError, ProcessLookupError):
        return False


def _wait_for(predicate, seconds=10.0):
    deadline = time.monotonic() + seconds
    while not predicate():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.02)


def test_stop_kills_long_running_cli_process_group(tmp_path):
    """Real child processes: the in-flight command and its grandchild die on stop."""
    path = tmp_path / ".credentials.json"
    _claude(path, datetime.now(UTC) + timedelta(minutes=3))
    record, pid_file = tmp_path / "calls", tmp_path / "sleep.pid"
    script = tmp_path / "fake-claude"
    script.write_text(
        f'#!/bin/sh\necho "$1" >> "{record}"\nsleep 60 &\necho $! > "{pid_file}"\nwait\n'
    )
    script.chmod(0o700)
    commands = ((str(script), "status"), (str(script), "model"))
    logs = []
    target = Target("claude", lambda: path, observe_claude, commands, backup=True)
    app = Keepalive([target], log=logs.append)  # Default, tracked runner.
    worker = threading.Thread(target=app.tick)
    worker.start()
    try:
        _wait_for(lambda: pid_file.exists() and pid_file.read_text().strip())
        grandchild = int(pid_file.read_text())
        assert not app.wait_idle(0)
        started = time.monotonic()
        app.request_stop()
        worker.join(5)
        assert not worker.is_alive()
        assert time.monotonic() - started < 5
    finally:
        app.request_stop()
        worker.join(100)
    assert app.wait_idle(0)
    _wait_for(lambda: not _alive(grandchild), 5)
    assert record.read_text().splitlines() == ["status"]  # The model request never ran.
    assert target.failures == 0 and not target.alerted
    assert "claude attempt_stopped via=status" in " ".join(logs)
    assert observe_claude(path).usable


def test_run_async_honors_request_stop():
    fake = _CountingKeepalive()
    fake.stopping = True
    asyncio.run(run_async(fake, asyncio.Event()))
    assert fake.ticks == 0


# --- Protected Grok scopes --------------------------------------------------------


def _grok_account(number, selector=None, *, ref="default", enabled=True):
    return Account(
        id=f"{number:08d}-1111-4111-8111-111111111111",
        provider=ProviderId.GROK_SUBSCRIPTION,
        label=f"grok {number}",
        credential_ref=ref,
        credential_kind=None if ref is None else CredentialKind.GROK_AUTH_FILE,
        credential_selector=selector,
        enabled=enabled,
    )


def test_grok_protected_scopes_only_from_explicit_default_file_selectors(tmp_path, monkeypatch):
    monkeypatch.setenv("GROK_HOME", str(tmp_path / "grok"))
    default = tmp_path / "grok" / "auth.json"
    accounts = (
        _grok_account(1, MODERN),
        _grok_account(2),  # No selector: the reader's default, mirrored by preferred.
        _grok_account(3, "https://auth.x.ai::disabled", enabled=False),
        _grok_account(4, "https://auth.x.ai::other-file", ref=str(tmp_path / "other.json")),
        _grok_account(5, "https://auth.x.ai::same-file", ref=str(default)),
        _grok_account(6, "https://auth.x.ai::no-ref", ref=None),
        Account(
            id="77777777-1111-4111-8111-111111111111",
            provider=ProviderId.CLAUDE_SUBSCRIPTION,
            label="claude",
        ),
    )
    assert keepalive.grok_protected_scopes(accounts) == frozenset(
        {MODERN, "https://auth.x.ai::same-file"}
    )
    assert keepalive.grok_protected_scopes([_grok_account(2)]) == frozenset()


def test_no_selector_account_lets_expired_legacy_go_stale_without_alerts(tmp_path, monkeypatch):
    # Legacy expired, one modern scope: a no-selector account reads the modern one,
    # so legacy must not be protected (it would fail and alert every token lifetime).
    monkeypatch.setenv("GROK_HOME", str(tmp_path))
    protected = keepalive.grok_protected_scopes([_grok_account(1)])
    scopes = {LEGACY: NOW - timedelta(days=30), MODERN: NOW + timedelta(minutes=4)}
    app, target, _path, clock, calls, logs = _grok_keepalive(
        tmp_path, scopes, True, protected=protected
    )
    app.tick()
    assert LEGACY in target.stale
    for _ in range(4):
        clock.advance(6 * 3600 - 200)
        app.tick()
    assert len(calls) == 5
    assert not any("ALERT" in line or "retry_in" in line for line in logs)
    assert logs.count("grok stale_scope_ignored scope=legacy") == 1


def test_set_protected_swaps_grok_scopes(tmp_path):
    scopes = {LEGACY: NOW - timedelta(days=30), MODERN: NOW + timedelta(minutes=4)}
    app, target, _path, _clock, _calls, _logs = _grok_keepalive(tmp_path, scopes, True)
    app.set_protected("grok", [LEGACY, "", MODERN])
    assert target.protected == frozenset({LEGACY, MODERN})
    app.tick()
    assert target.stale == {}
    app.set_protected("grok", ())
    assert target.protected == frozenset()


def test_scope_protected_after_going_stale_is_scheduled_again(tmp_path):
    scopes = {LEGACY: NOW - timedelta(days=30), MODERN: NOW + timedelta(minutes=4)}
    app, target, path, clock, calls, _logs = _grok_keepalive(tmp_path, scopes, True)
    app.tick()
    assert LEGACY in target.stale
    observation = observe_grok(path)
    assert LEGACY not in dict(target.live_scopes(observation))
    # The user now saves an account selecting the legacy scope: it schedules again.
    app.set_protected("grok", [LEGACY])
    assert dict(target.live_scopes(observation))[LEGACY] == scopes[LEGACY]
    assert target.expiry(observation) == scopes[LEGACY]
    clock.advance(60)
    app.tick()
    assert len(calls) == 2


def test_stale_scope_that_becomes_preferred_is_live(tmp_path):
    other = "https://auth.x.ai::other"
    scopes = {MODERN: NOW + timedelta(minutes=4), other: NOW - timedelta(days=1)}
    _app, target, path, _clock, _calls, _logs = _grok_keepalive(tmp_path, scopes, True)
    target.stale[other] = scopes[other]
    _grok_file(path, {other: scopes[other]})  # The other login is now the only one.
    observation = observe_grok(path)
    assert observation.preferred == other
    assert target.expiry(observation) == scopes[other]


def test_standalone_main_protects_saved_selectors(tmp_path, monkeypatch, capsys):
    _homes(tmp_path, monkeypatch)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("GROK_HOME", str(tmp_path / "GROK_HOME"))
    seen = {}

    def build(names, mode, *, log, grok_protected_scopes=()):
        seen["protected"] = frozenset(grok_protected_scopes)
        return Keepalive([], log=log)

    monkeypatch.setattr(keepalive, "build", build)
    AccountStore().save((_grok_account(1, MODERN), _grok_account(2)))
    assert keepalive.main(["--once"]) == 0
    assert seen["protected"] == frozenset({MODERN})

    # Unreadable config: fail soft, log it, and run without protection.
    config = AccountStore().path
    assert config.exists()
    config.write_text("{not json")
    assert keepalive.main(["--once"]) == 0
    assert seen["protected"] == frozenset()
    out = capsys.readouterr().out
    assert "accounts unavailable; no protected Grok scopes" in out
