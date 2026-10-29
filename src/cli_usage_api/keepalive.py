"""Opt-in keepalive that lets official CLIs renew their own file-backed logins.

The usage reader never refreshes credentials or reads refresh tokens. On a
headless host nobody runs the official CLIs, so their access tokens lapse. This
separate loop invokes each official CLI shortly before its stored access token
expires, so that CLI performs its own refresh and rewrites its own file.

Each CLI only refreshes inside a short pre-expiry window (five minutes for all
three at the inspected source revisions), so the loop schedules from the stored
expiry instead of a fixed timer, and success is judged solely by re-reading the
file and observing that the expiry advanced.

Token fields are read only to check that they are present and to decode expiry
hints (Codex: the access-token JWT ``exp``, decoded without verification). Command
output is discarded; no token value is ever logged or printed.

Grok: every selectable keyed scope is observed separately. An attempt succeeds when
any scope's expiry advanced. A due scope that stays put is marked stale (logged once
and ignored for scheduling) only when the command exited 0 and another scope
advanced in the same attempt, which proves the CLI refreshed its active scope. The
scope a no-selector reader would select (the only modern scope, else legacy) is
never marked stale, nor is an explicit selector of an enabled saved Grok account
reading the default login file (see :func:`grok_protected_scopes`). Any other outcome is
an ordinary failure with retry; after an alert, a different live scope entering
its own window still gets an attempt so it does not lapse with the failed one.

When an attempt leaves the login file missing or unusable, the loop alerts at once
and waits for a new login instead of retrying; a deleted file (logout) also
discards the refresh-token backup.

Claude Code: ``claude auth status`` first (no model call). Its refresh can be
lost when the CLI exits before persisting it, so the credentials file is backed
up (owner-only, same directory) before the attempt and restored only when the
file is left blank or unreadable. A restored backup cannot revive a refresh
token already consumed upstream; that case ends in a manual ``/login`` alert.
If ``auth status`` did not advance the expiry, a minimal Haiku print-mode
request follows, which costs a small amount of subscription quota.

Stopping is cooperative (:meth:`Keepalive.request_stop`): no target or command
starts afterwards, and the in-flight command's process group is killed. A stopped
attempt counts as neither success nor failure.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import fcntl
import json
import os
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Self

from cli_usage_api.credentials import (
    _LEGACY_SCOPE,
    _MODERN_SCOPE,
    CredentialResolutionError,
    _codex_expiry,
    _expiry,
    _grok_expiry,
    _jwt_payload,
)
from cli_usage_api.domain import Account, CredentialKind, ProviderId

WINDOW_SECONDS = 290  # Each CLI refreshes within 300 s of expiry; keep a margin.
UNKNOWN_EXPIRY_INTERVAL = 24 * 3600
RETRY_DELAYS = (30, 60, 120, 300, 600)
COMMAND_TIMEOUT = 90
MAX_INTERVAL = 240  # Below WINDOW_SECONDS, so a check always lands inside the window.
DEFAULT_INTERVAL = 60
BACKUP_SUFFIX = ".keepalive-backup"
_UNREADABLE = (
    OSError,
    ValueError,
    AttributeError,
    TypeError,
    RecursionError,
    CredentialResolutionError,
)

CLI_ENV = {
    "DISABLE_AUTOUPDATER": "1",
    "DISABLE_TELEMETRY": "1",
    "DISABLE_ERROR_REPORTING": "1",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    "GROK_DISABLE_AUTOUPDATER": "1",
    "GROK_TELEMETRY_ENABLED": "0",
}

CLAUDE_STATUS = ("claude", "auth", "status")
CLAUDE_MODEL = (
    "claude",
    "-p",
    "Reply with the single word OK.",
    "--model",
    "haiku",
    "--effort",
    "low",
    "--tools",
    "",
    "--max-turns",
    "1",
    "--output-format",
    "json",
)
CODEX_DOCTOR = ("codex", "doctor", "--json")
GROK_SESSIONS = ("grok", "sessions", "list", "-n", "1")

Scopes = tuple[tuple[str, datetime | None], ...]
FileState = tuple[int, int, int]


class KeepaliveError(Exception):
    """Curated, secret-free setup error (invalid names, no logins, lock held)."""


@dataclass(frozen=True, slots=True)
class Observation:
    """Nonsecret file state: whether usable, and its access-token expiry.

    ``scopes`` holds per-scope expiries (Grok only); ``preferred`` is the scope the
    usage reader would select without an explicit selector, when unambiguous.
    """

    usable: bool
    expires_at: datetime | None
    scopes: Scopes = ()
    preferred: str | None = None


def state_dir() -> Path:
    return Path.home() / ".local" / "state" / "usage-keepalive"


def _home(variable: str, default: str) -> Path:
    root = os.environ.get(variable)
    return Path(root) if root else Path.home() / default


def claude_path() -> Path:
    return _home("CLAUDE_CONFIG_DIR", ".claude") / ".credentials.json"


def codex_path() -> Path:
    return _home("CODEX_HOME", ".codex") / "auth.json"


def grok_path() -> Path:
    return _home("GROK_HOME", ".grok") / "auth.json"


def _load(path: Path) -> object:
    with open(path, "rb") as handle:
        content = handle.read(1_048_577)
    if len(content) > 1_048_576:
        raise ValueError
    return json.loads(content)


def _file_state(path: Path) -> FileState | None:
    try:
        status = os.stat(path)
    except OSError:
        return None
    return (status.st_ino, status.st_mtime_ns, status.st_size)


def observe_claude(path: Path) -> Observation:
    try:
        entry = _load(path).get("claudeAiOauth")
        token = entry.get("accessToken")
        expires_at = _expiry(entry.get("expiresAt"), milliseconds=True)
    except _UNREADABLE:
        return Observation(False, None)
    return Observation(isinstance(token, str) and bool(token), expires_at)


def observe_codex(path: Path) -> Observation:
    try:
        token = _load(path).get("tokens").get("access_token")
        expires_at = _codex_expiry(_jwt_payload(token))
    except _UNREADABLE:
        return Observation(False, None)
    return Observation(True, expires_at)


def _grok_selectable(key: str) -> bool:
    return key == _LEGACY_SCOPE or (key.startswith(_MODERN_SCOPE) and key != _MODERN_SCOPE)


def _scope_label(key: str) -> str:
    return "legacy" if key == _LEGACY_SCOPE else "modern"


def observe_grok(path: Path) -> Observation:
    """Per-scope expiries of the keyed scopes the usage reader can select."""
    try:
        data = _load(path)
        scopes: list[tuple[str, datetime | None]] = []
        for key, entry in data.items():
            if not (_grok_selectable(key) and isinstance(entry, dict)):
                continue
            if not (isinstance(entry.get("key"), str) and entry["key"]):
                continue
            try:
                expires_at = _grok_expiry(entry.get("expires_at"))
            except CredentialResolutionError:
                expires_at = None  # One malformed scope must not hide the others.
            scopes.append((key, expires_at))
        modern = [key for key in data if _grok_selectable(key) and key != _LEGACY_SCOPE]
    except _UNREADABLE:
        return Observation(False, None)
    scopes.sort(key=lambda scope: scope[0])
    keyed = dict(scopes)
    # Mirror the reader's default selection: the only modern scope, else legacy.
    preferred = modern[0] if len(modern) == 1 else None if modern else _LEGACY_SCOPE
    known = [value for value in keyed.values() if value is not None]
    return Observation(
        bool(scopes),
        min(known) if known else None,
        tuple(scopes),
        preferred if preferred in keyed else None,
    )


def grok_default_forms() -> frozenset[str]:
    """The default Grok login path as written and as resolved; computed once by callers.

    Custom references are compared lexically against these forms, so an account
    reference (possibly token-supplied over HTTP) never triggers filesystem lookups.
    """
    default = grok_path()
    return frozenset({str(default), os.path.normpath(default), os.path.realpath(default)})


def _selected_grok_file(account: Account) -> bool:
    return bool(
        account.enabled
        and account.provider == ProviderId.GROK_SUBSCRIPTION
        and account.credential_kind == CredentialKind.GROK_AUTH_FILE
        and account.credential_ref is not None
        and account.credential_selector
    )


def resolve_grok_references(accounts: Collection[Account]) -> dict[str, str]:
    """Resolve saved custom Grok references once, off the event loop, at startup.

    Saved references may predate normalization or reach the default login file
    through a symlinked directory, which a lexical comparison cannot see. Only
    references already saved when a process starts are resolved here; references
    supplied later (over HTTP) stay lexical so they never cause filesystem lookups.
    """
    resolved = {}
    for account in accounts:
        ref = account.credential_ref
        if not _selected_grok_file(account) or ref == "default" or ref in resolved:
            continue
        try:
            resolved[ref] = os.path.realpath(ref)
        except (OSError, ValueError):
            continue
    return resolved


def grok_protected_scopes(
    accounts: Collection[Account],
    *,
    default_forms: Collection[str] | None = None,
    resolved: Mapping[str, str] | None = None,
) -> frozenset[str]:
    """Explicit selectors that enabled saved Grok accounts read from ``grok_path()``.

    A no-selector account adds nothing: the reader then uses the only modern scope,
    else legacy, which ``Observation.preferred`` already mirrors and never marks
    stale. Accounts reading another file cannot be affected by this loop. A custom
    reference matches lexically (as written or ``normpath``-normalized, never a
    filesystem lookup) or through ``resolved``, the startup realpaths from
    :func:`resolve_grok_references`; ``default_forms`` defaults to
    :func:`grok_default_forms`.
    """
    forms = grok_default_forms() if default_forms is None else frozenset(default_forms)
    known = resolved or {}
    scopes = set()
    for account in accounts:
        if not _selected_grok_file(account):
            continue
        ref = account.credential_ref
        if (
            ref == "default"
            or ref in forms
            or os.path.normpath(ref) in forms
            or known.get(ref) in forms
        ):
            scopes.add(account.credential_selector)
    return frozenset(scopes)


def _advanced_scopes(before: Observation, after: Observation) -> set[str]:
    prior = dict(before.scopes)
    return {
        key
        for key, value in after.scopes
        if value is not None and (prior.get(key) is None or value > prior[key])
    }


def _kill_group(process: subprocess.Popen) -> None:
    """SIGKILL a child's whole process group (it leads its own session)."""
    if process.returncode is not None:
        return  # Already reaped: its pid (and group id) may have been reused.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except OSError:
        pass


def run_command(
    argv: Sequence[str],
    timeout: float = COMMAND_TIMEOUT,
    *,
    track: Callable[[subprocess.Popen | None], None] | None = None,
) -> int | None:
    """Run a CLI without a TTY; discard output; kill its process group on timeout.

    ``track`` receives the live child right after it starts and ``None`` once it
    has been reaped, so a stop request can kill the command in flight.
    """
    try:
        process = subprocess.Popen(
            list(argv),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={**os.environ, **CLI_ENV},
            start_new_session=True,
        )
    except OSError:
        return None
    if track is not None:
        track(process)
    try:
        return process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_group(process)
        process.wait()
        return None
    except BaseException:
        # e.g. Ctrl-C in standalone mode: the child is in its own session and
        # would otherwise outlive this process and the instance lock.
        _kill_group(process)
        process.wait()
        raise
    finally:
        if track is not None:
            track(None)


def _write_private(path: Path, content: bytes) -> None:
    """Atomically write ``0600`` content through a unique same-directory temp file.

    ``mkstemp`` creates the temp with ``O_CREAT | O_EXCL`` (and ``O_NOFOLLOW``), so
    it can neither collide with nor follow a planted name; ``os.replace`` swaps the
    directory entry itself and never writes through a symlink at ``path``.
    """
    fd, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".keepalive-tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


@dataclass(slots=True)
class Target:
    """One official CLI login, scheduled from its own stored expiry."""

    name: str
    path: Callable[[], Path]
    observe: Callable[[Path], Observation]
    commands: tuple[tuple[str, ...], ...]
    backup: bool = False
    # Grok scopes that must never be marked stale (e.g. a saved account's selector).
    protected: frozenset[str] = frozenset()
    failures: int = 0
    next_attempt: float = 0.0
    alerted: bool = False
    last_seen: Observation | None = field(default=None)
    # Grok scopes that did not advance after a completed attempt, with the expiry
    # they were stuck at; a later change to that scope's expiry revives it.
    stale: dict[str, datetime | None] = field(default_factory=dict)
    # Scopes due in the latest attempt, and those that were due when it alerted.
    attempted: frozenset[str] = frozenset()
    failed_scopes: frozenset[str] = frozenset()

    def prune_stale(self, observation: Observation) -> None:
        current = dict(observation.scopes)
        for key in [key for key, value in self.stale.items() if current.get(key, 0) != value]:
            del self.stale[key]

    def live_scopes(self, observation: Observation) -> Scopes:
        # A scope protected or chosen by the reader after it went stale is live
        # again; filter here rather than mutate ``stale`` from the event loop.
        keep = self.protected | {observation.preferred}
        return tuple(
            (key, value)
            for key, value in observation.scopes
            if key not in self.stale or key in keep
        )

    def expiry(self, observation: Observation) -> datetime | None:
        """Scheduling expiry: earliest known expiry among non-stale scopes."""
        if not observation.scopes:
            return observation.expires_at
        known = [value for _, value in self.live_scopes(observation) if value is not None]
        return min(known) if known else None

    def other_due(self, observation: Observation, now: datetime) -> datetime | None:
        """Earliest known expiry among live scopes that were not part of the alert."""
        known = [
            value
            for key, value in self.live_scopes(observation)
            if key not in self.failed_scopes and value is not None
        ]
        return min(known) if known else None

    def in_window(self, observation: Observation, now: datetime) -> bool:
        expires_at = self.expiry(observation)
        return expires_at is None or (expires_at - now).total_seconds() <= WINDOW_SECONDS

    def advanced(self, before: Observation, after: Observation) -> bool:
        if not after.usable:
            return False
        if before.scopes or after.scopes:
            if _advanced_scopes(before, after):
                return True
            return self.expiry(before) is None and self.expiry(after) is None
        if after.expires_at is None:
            return before.expires_at is None
        return before.expires_at is None or after.expires_at > before.expires_at


class Keepalive:
    """The scheduling loop body. ``tick`` runs in a worker thread.

    ``request_stop`` is thread-safe and cooperative: no new target or command starts
    after it, and the official CLI command in flight (when run through the default
    runner) has its process group killed. ``wait_idle`` returns once no tick runs.
    """

    def __init__(
        self,
        targets: Sequence[Target],
        *,
        log: Callable[[str], None],
        run: Callable[[Sequence[str]], int | None] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.targets = list(targets)
        self._log = log
        self._run = run if run is not None else self._run_tracked
        self._clock = clock
        self._monotonic = monotonic
        self._state = threading.Lock()
        self._stop = threading.Event()
        self._idle = threading.Event()
        self._idle.set()
        self._process: subprocess.Popen | None = None

    def log(self, message: str) -> None:
        self._log(message)

    @property
    def stopping(self) -> bool:
        return self._stop.is_set()

    def request_stop(self) -> None:
        """Stop starting work and kill the in-flight official CLI command, if any."""
        with self._state:
            self._stop.set()
            if self._process is not None:
                _kill_group(self._process)

    def wait_idle(self, timeout: float | None = None) -> bool:
        """Wait until no tick is running; ``True`` when idle."""
        return self._idle.wait(timeout)

    def _track(self, process: subprocess.Popen | None) -> None:
        with self._state:
            self._process = process
            if process is not None and self._stop.is_set():
                _kill_group(process)  # Started just as the stop arrived.

    def _run_tracked(self, argv: Sequence[str]) -> int | None:
        return run_command(argv, track=self._track)

    def set_protected(self, name: str, scopes: Collection[str]) -> None:
        """Atomically replace a target's protected Grok scopes."""
        protected = frozenset(scope for scope in scopes if isinstance(scope, str) and scope)
        for target in self.targets:
            if target.name == name:
                target.protected = protected

    def _event(self, target: Target, event: str, observation: Observation | None = None) -> None:
        detail = ""
        expires_at = None if observation is None else target.expiry(observation)
        if expires_at is not None:
            remaining = int((expires_at - self._clock()).total_seconds())
            detail = f" expires_in={remaining}s"
        self._log(f"{target.name} {event}{detail}")

    def tick(self) -> None:
        with self._state:
            if self._stop.is_set():
                return
            self._idle.clear()
        try:
            for target in self.targets:
                if self._stop.is_set():
                    return
                try:
                    self._tick(target)
                except Exception as error:  # noqa: BLE001 - one target must not stop the loop
                    # Only the type name: messages could quote file content.
                    self._log(f"{target.name} tick_error type={type(error).__name__}")
                    target.next_attempt = max(
                        target.next_attempt, self._monotonic() + RETRY_DELAYS[0]
                    )
        finally:
            self._idle.set()

    def _tick(self, target: Target) -> None:
        path = target.path()
        observation = target.observe(path)
        target.prune_stale(observation)
        previous = target.last_seen
        now, monotonic = self._clock(), self._monotonic()
        if not observation.usable and (previous is None or previous.usable):
            self._event(target, "ALERT login file missing or unusable; log in again")
        if target.alerted:
            # Wait for a manual re-login: a changed, usable file state resets.
            if not observation.usable or observation == previous:
                target.last_seen = observation
                other = target.other_due(observation, now) if observation.usable else None
                if (
                    other is not None
                    and (other - now).total_seconds() <= WINDOW_SECONDS
                    and monotonic >= target.next_attempt
                ):
                    # A different live scope is due: give the CLI a chance to renew it.
                    self._attempt(target, path, observation)
                return
            target.alerted = False
            target.failed_scopes = frozenset()
            self._recovered(target, path, observation)
        elif (
            observation.usable
            and previous is not None
            and target.failures
            and (
                not target.in_window(observation, now) or self._later(target, observation, previous)
            )
        ):
            # Renewed without us (e.g. an interactive CLI session or /login).
            self._recovered(target, path, observation)
        target.last_seen = observation
        if monotonic < target.next_attempt or not observation.usable:
            return
        if not target.in_window(observation, now):
            return
        self._attempt(target, path, observation)

    @staticmethod
    def _later(target: Target, observation: Observation, previous: Observation) -> bool:
        current, prior = target.expiry(observation), target.expiry(previous)
        return current is not None and prior is not None and current > prior

    def _recovered(self, target: Target, path: Path, observation: Observation) -> None:
        target.failures, target.next_attempt = 0, 0.0
        self._discard_backup(target, path)
        self._event(target, "recovered", observation)

    def _backup_path(self, target: Target, path: Path) -> Path | None:
        return path.with_name(path.name + BACKUP_SUFFIX) if target.backup else None

    def _discard_backup(self, target: Target, path: Path) -> None:
        backup = self._backup_path(target, path)
        if backup is None:
            return
        try:
            backup.unlink(missing_ok=True)
        except OSError:
            self._event(target, "backup_delete_failed")

    def _attempt(self, target: Target, path: Path, before: Observation) -> None:
        if self._stop.is_set():
            return
        backup = self._backup_path(target, path)
        if backup is not None:
            try:
                _write_private(backup, path.read_bytes())
            except OSError:
                self._event(target, "backup_failed_skipping")
                self._schedule_retry(target, before)
                return
        start = self._clock()
        due_scopes = {
            key
            for key, value in target.live_scopes(before)
            if value is not None and (value - start).total_seconds() <= WINDOW_SECONDS
        }
        target.attempted = frozenset(due_scopes)
        after = before
        for argv in target.commands:
            if self._stop.is_set():
                self._event(target, "attempt_stopped")
                return
            code = self._run(argv)
            state = _file_state(path)
            after = target.observe(path)
            if (
                backup is not None
                and not after.usable
                and self._restore(target, path, backup, state)
            ):
                after = target.observe(path)
            if self._stop.is_set():
                # Killed or interrupted by a stop: neither success nor failure. The
                # restore rules above already kept the file safe; the backup stays.
                self._event(target, f"attempt_stopped via={argv[1]}")
                return
            if not after.usable:
                self._unusable(target, path, after)
                return
            if target.advanced(before, after):
                if code == 0:
                    self._mark_stale(target, before, after, due_scopes)
                target.failures, target.next_attempt = 0, 0.0
                target.alerted, target.failed_scopes = False, frozenset()
                target.last_seen = after
                self._discard_backup(target, path)
                if target.expiry(after) is None:
                    # Unknown expiry: renew on a slow fixed cadence instead.
                    target.next_attempt = self._monotonic() + UNKNOWN_EXPIRY_INTERVAL
                    self._event(
                        target,
                        f"ran_unknown_expiry via={argv[1]} next_in={UNKNOWN_EXPIRY_INTERVAL}s",
                    )
                else:
                    self._event(target, f"refreshed via={argv[1]}", after)
                return
            outcome = "timeout_or_missing" if code is None else f"exit={code}"
            self._event(target, f"not_advanced via={argv[1]} {outcome}", after)
        self._schedule_retry(target, after)

    def _unusable(self, target: Target, path: Path, after: Observation) -> None:
        """The attempt left no usable login: alert now and wait for a new login."""
        target.last_seen = after
        target.alerted = True
        target.failed_scopes = frozenset()
        try:
            os.lstat(path)
        except FileNotFoundError:
            # Logged out: the refresh-token backup must not outlive the login.
            self._discard_backup(target, path)
        except OSError:
            pass
        self._event(target, "ALERT login file missing or unusable; log in again")

    def _mark_stale(
        self, target: Target, before: Observation, after: Observation, due_scopes: set[str]
    ) -> None:
        """Mark due scopes that stayed put while another advanced (exit 0 only).

        Never the reader's own selection or an explicitly protected scope.
        """
        advanced = _advanced_scopes(before, after)
        if not after.usable or not advanced:
            return
        current = dict(after.scopes)
        candidates = {
            key
            for key in due_scopes - advanced - target.protected - {after.preferred}
            if key in current
        }
        for key in sorted(candidates):
            target.stale[key] = current[key]
            self._log(f"{target.name} stale_scope_ignored scope={_scope_label(key)}")

    def _restore(self, target: Target, path: Path, backup: Path, state: FileState | None) -> bool:
        """Restore only an unchanged, still-unusable file; never undo a logout or login."""
        if state is None:
            self._event(target, "restore_skipped_file_missing")
            return False
        if target.observe(path).usable:
            return False
        if _file_state(path) != state:
            self._event(target, "restore_skipped_file_changed")
            return False
        try:
            _write_private(path, backup.read_bytes())
        except OSError:
            self._event(target, "restore_failed")
            return False
        self._event(target, "restored_backup")
        return True

    def _schedule_retry(self, target: Target, observation: Observation) -> None:
        target.last_seen = observation
        if target.failures >= len(RETRY_DELAYS):
            target.alerted = True
            target.failed_scopes = target.failed_scopes | target.attempted
            target.next_attempt = self._monotonic() + RETRY_DELAYS[-1]
            kept = "; backup kept" if target.backup else ""
            self._event(target, f"ALERT manual login required{kept}", observation)
            return
        delay = RETRY_DELAYS[target.failures]
        target.failures += 1
        target.next_attempt = self._monotonic() + delay
        self._event(target, f"retry_in={delay}s attempt={target.failures}", observation)

    def sleep_seconds(self, interval: float = DEFAULT_INTERVAL) -> float:
        """Sleep until the next window start or backoff expiry, at most ``interval``."""
        now, monotonic = self._clock(), self._monotonic()
        wait = float(interval)
        for target in self.targets:
            seen = target.last_seen
            if seen is None or not seen.usable:
                continue
            expires_at = target.other_due(seen, now) if target.alerted else target.expiry(seen)
            if target.alerted and expires_at is None:
                continue
            if target.next_attempt > monotonic:
                wait = min(wait, target.next_attempt - monotonic)
                continue
            if expires_at is not None:
                wait = min(wait, (expires_at - now).total_seconds() - WINDOW_SECONDS)
        return max(1.0, wait)


CLAUDE_MODES = {
    "hybrid": (CLAUDE_STATUS, CLAUDE_MODEL),
    "status": (CLAUDE_STATUS,),
    "model": (CLAUDE_MODEL,),
}
LOGIN_PATHS: dict[str, Callable[[], Path]] = {
    "claude": claude_path,
    "codex": codex_path,
    "grok": grok_path,
}


def _target(name: str, claude_mode: str, grok_protected: frozenset[str]) -> Target:
    if name == "claude":
        return Target("claude", claude_path, observe_claude, CLAUDE_MODES[claude_mode], backup=True)
    if name == "codex":
        return Target("codex", codex_path, observe_codex, (CODEX_DOCTOR,))
    return Target("grok", grok_path, observe_grok, (GROK_SESSIONS,), protected=grok_protected)


def build(
    names: Sequence[str] | None,
    claude_mode: str = "hybrid",
    *,
    log: Callable[[str], None],
    grok_protected_scopes: Collection[str] = (),
) -> Keepalive:
    """Build a keepalive for ``names`` (``None``: every CLI whose login file exists).

    Does not take the single-instance lock; see :class:`InstanceLock`.
    """
    if claude_mode not in CLAUDE_MODES:
        raise KeepaliveError(f"Unknown Claude mode; choose one of {', '.join(CLAUDE_MODES)}.")
    if names is None:
        selected = list(LOGIN_PATHS)
    else:
        if isinstance(names, str) or not names:
            raise KeepaliveError("Name at least one CLI to keep alive.")
        if not all(isinstance(name, str) and name in LOGIN_PATHS for name in names):
            raise KeepaliveError(f"Unknown CLI; choose from {', '.join(LOGIN_PATHS)}.")
        selected = list(dict.fromkeys(names))
    present = [name for name in selected if _exists(LOGIN_PATHS[name]())]
    if not present:
        raise KeepaliveError("No official CLI login files found; log in first.")
    if names is None:
        selected = present
    protected = frozenset(
        scope for scope in grok_protected_scopes if isinstance(scope, str) and scope
    )
    return Keepalive([_target(name, claude_mode, protected) for name in selected], log=log)


def _exists(path: Path) -> bool:
    try:
        os.stat(path)
    except OSError:
        return False
    return True


def _private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)


class InstanceLock:
    """Single-instance advisory lock on ``~/.local/state/usage-keepalive/keepalive.lock``."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self._fd: int | None = None

    def __enter__(self) -> Self:
        path = self._path or state_dir() / "keepalive.lock"
        try:
            _private_dir(path.parent)
            fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        except OSError as error:
            raise KeepaliveError("Cannot open the usage-keepalive lock file.") from error
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            os.close(fd)
            raise KeepaliveError("Another usage-keepalive is already running.") from error
        self._fd = fd
        return self

    def __exit__(self, *_exc: object) -> None:
        if self._fd is not None:
            fd, self._fd = self._fd, None
            os.close(fd)  # Closing the descriptor releases the flock.


async def run_async(keepalive: Keepalive, stop: asyncio.Event) -> None:
    """Tick in a worker thread until ``stop`` is set or a stop was requested.

    Cancelling an ``asyncio.to_thread`` await does not stop its thread: callers must
    call ``keepalive.request_stop()`` (which kills the in-flight CLI command and
    prevents new ones) and then wait for this coroutine or ``wait_idle``. A stop
    during the sleep returns immediately. Cancellation propagates normally.
    """

    def stopped() -> bool:
        return stop.is_set() or bool(getattr(keepalive, "stopping", False))

    while not stopped():
        try:
            await asyncio.to_thread(keepalive.tick)
            delay = keepalive.sleep_seconds()
        except Exception as error:  # noqa: BLE001 - the loop must outlive one bad tick
            keepalive.log(f"keepalive loop_error type={type(error).__name__}")
            delay = RETRY_DELAYS[0]
        if stopped():
            return
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=delay)


def _stamp(message: str) -> str:
    return f"{datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')} {message}"


def file_logger(path: Path | None = None) -> Callable[[str], None]:
    """Return a logger appending timestamped lines to an owner-only log file.

    Defaults to ``~/.local/state/usage-keepalive/keepalive.log``. The file is opened
    per line with ``O_NOFOLLOW``, created ``0600``, and must be a regular file; any
    ``OSError`` drops the line instead of raising.
    """
    target = path or state_dir() / "keepalive.log"

    def log(message: str) -> None:
        data = (_stamp(message) + "\n").encode("utf-8", "replace")
        try:
            if path is None:
                _private_dir(target.parent)
            fd = os.open(
                target,
                os.O_WRONLY
                | os.O_APPEND
                | os.O_CREAT
                | os.O_NOFOLLOW
                | os.O_NONBLOCK
                | os.O_CLOEXEC,
                0o600,
            )
            try:
                if stat.S_ISREG(os.fstat(fd).st_mode):
                    os.write(fd, data)
            finally:
                os.close(fd)
        except OSError:
            return

    return log


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="usage-keepalive",
        description="Invoke official CLIs shortly before their stored logins expire so "
        "they renew their own credential files. Output contains no secrets.",
    )
    parser.add_argument(
        "--cli",
        action="append",
        choices=tuple(LOGIN_PATHS),
        default=None,
        help="Login to keep alive (repeatable; default: every CLI with a login file).",
    )
    parser.add_argument(
        "--claude-mode",
        choices=tuple(CLAUDE_MODES),
        default="hybrid",
        help="hybrid: 'claude auth status', then a minimal Haiku request only if the "
        "expiry did not advance (uses a little quota). Default: hybrid.",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=DEFAULT_INTERVAL,
        help=f"Maximum seconds between checks (10-{MAX_INTERVAL}; default "
        f"{DEFAULT_INTERVAL}). The loop also wakes at each window start and backoff expiry.",
    )
    parser.add_argument("--once", action="store_true", help="Check once and exit.")
    return parser


def _log(message: str) -> None:
    print(_stamp(message), flush=True)


def _saved_grok_scopes(log: Callable[[str], None]) -> frozenset[str]:
    """Read saved accounts once (never written); fail soft without protection."""
    from cli_usage_api.storage import AccountStore, ConfigError

    try:
        accounts = AccountStore().load()
        return grok_protected_scopes(accounts, resolved=resolve_grok_references(accounts))
    except ConfigError:
        log("accounts unavailable; no protected Grok scopes")
        return frozenset()


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not 10 <= args.interval <= MAX_INTERVAL:
        print(f"--interval must be between 10 and {MAX_INTERVAL} seconds.", file=sys.stderr)
        return 2
    try:
        keepalive = build(
            args.cli,
            args.claude_mode,
            log=_log,
            grok_protected_scopes=_saved_grok_scopes(_log),
        )
        with InstanceLock():
            _log("keepalive started for " + ", ".join(t.name for t in keepalive.targets))
            while True:
                keepalive.tick()
                if args.once:
                    return 0
                time.sleep(keepalive.sleep_seconds(args.interval))
    except KeepaliveError as error:
        print(str(error), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 0
