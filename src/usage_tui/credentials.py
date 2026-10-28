"""Read-only first-party imports and explicit local secret references.

An imported reference is a local path, or ``default`` for the documented provider
location. Defaults are looked up only by resolve(), never during construction.
No login commands, refreshes, credential writes, or permission repairs occur.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import secrets
import stat
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from usage_tui.domain import (
    Account,
    CredentialKind,
    Diagnostic,
    DomainError,
    FetchState,
    ResolvedCredential,
    parse_timestamp,
    utc_datetime,
    validate_credential_kind,
)
from usage_tui.storage import CredentialError, CredentialStore

MAX_FILE_BYTES = 1_048_576
_MODERN_SCOPE = "https://auth.x.ai::"
_LEGACY_SCOPE = "https://accounts.x.ai/sign-in"


class CredentialResolutionError(Exception):
    """Curated failure boundary; never includes paths, identities, or secrets."""

    def __init__(self, fetch_state: FetchState, code: str) -> None:
        self.fetch_state = fetch_state
        self.diagnostic = Diagnostic(code)
        self.code = self.diagnostic.code
        super().__init__(self.diagnostic.message)


def _error(code: str, state: FetchState = FetchState.AUTH_REQUIRED) -> CredentialResolutionError:
    return CredentialResolutionError(state, code)


def _schema() -> CredentialResolutionError:
    return _error("schema_error", FetchState.SCHEMA_ERROR)


def _text(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > MAX_FILE_BYTES
        or any(ord(char) < 33 or ord(char) > 126 for char in value)
    ):
        raise _schema()
    return value


def _expiry(value: object, *, milliseconds: bool = False) -> datetime | None:
    if value is None:
        return None
    try:
        if isinstance(value, str) and not milliseconds:
            return parse_timestamp(value)
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise _schema()
        divisor = 1000 if milliseconds or value >= 100_000_000_000 else 1
        return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(seconds=value / divisor)
    except (DomainError, OverflowError, ValueError, TypeError):
        raise _schema() from None


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise _schema()
        result[key] = value
    return result


def _read_file(path: Path) -> bytes:
    if os.name != "posix":
        raise _error("unsafe_credential_file")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except FileNotFoundError:
        raise _error("credential_unavailable") from None
    except (OSError, ValueError):
        raise _error("unsafe_credential_file") from None
    try:
        before = os.fstat(fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_size > MAX_FILE_BYTES
        ):
            raise _error("unsafe_credential_file")
        chunks = []
        size = 0
        while size <= MAX_FILE_BYTES:
            chunk = os.read(fd, min(65_536, MAX_FILE_BYTES + 1 - size))
            if not chunk:
                break
            size += len(chunk)
            chunks.append(chunk)
        after = os.fstat(fd)
        if size > MAX_FILE_BYTES or (
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
            before.st_mode,
            before.st_uid,
        ) != (
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
            after.st_mode,
            after.st_uid,
        ):
            raise _error("unsafe_credential_file")
        return b"".join(chunks)
    except OSError:
        raise _error("unsafe_credential_file") from None
    finally:
        os.close(fd)


class CredentialResolver:
    """Capture one immutable credential generation per fetch attempt.

    A fingerprint is a per-resolver keyed opaque identifier, not a public token
    digest. It changes with source contents or account binding, and is not logged.
    An API key can be resolved for local management but never authorizes reads;
    provider and transport read-kind validation enforce that separate boundary.
    """

    def __init__(
        self,
        credential_store: CredentialStore | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = credential_store if credential_store is not None else CredentialStore()
        self._clock = clock if clock is not None else lambda: datetime.now(UTC)
        self._generation_key = secrets.token_bytes(32)

    def _path(self, account: Account) -> Path:
        ref = account.credential_ref
        if ref != "default":
            return Path(ref)
        if account.credential_kind == CredentialKind.CLAUDE_CODE_FILE:
            root = os.environ.get("CLAUDE_CONFIG_DIR")
            return (Path(root) if root else Path.home() / ".claude") / ".credentials.json"
        root = os.environ.get("GROK_HOME")
        return (Path(root) if root else Path.home() / ".grok") / "auth.json"

    def resolve(self, account: Account) -> ResolvedCredential:
        if not isinstance(account, Account):
            raise _error("credential_mismatch")
        if account.credential_kind is None or account.credential_ref is None:
            raise _error("credential_unavailable", FetchState.UNCONFIGURED)
        try:
            validate_credential_kind(account.provider, account.credential_kind)
        except DomainError:
            raise _error("credential_mismatch") from None
        user_id = None
        expires_at = None
        if account.credential_kind in (
            CredentialKind.CLAUDE_CODE_FILE,
            CredentialKind.GROK_AUTH_FILE,
        ):
            raw = _read_file(self._path(account))
            try:
                data = json.loads(raw, object_pairs_hook=_unique_object)
            except (ValueError, UnicodeError, RecursionError):
                raise _schema() from None
            if not isinstance(data, dict):
                raise _schema()
            if account.credential_kind == CredentialKind.CLAUDE_CODE_FILE:
                entry = data.get("claudeAiOauth")
                if not isinstance(entry, dict):
                    raise _schema()
                secret = _text(entry.get("accessToken"))
                expires_at = _expiry(entry.get("expiresAt"), milliseconds=True)
                if "scopes" in entry:
                    scopes = entry["scopes"]
                    if not isinstance(scopes, list) or any(
                        not isinstance(scope, str) for scope in scopes
                    ):
                        raise _schema()
                    if "user:profile" not in scopes:
                        raise _error("permission_denied", FetchState.PERMISSION_DENIED)
            else:
                selector = account.credential_selector
                modern = [
                    key for key in data if key.startswith(_MODERN_SCOPE) and key != _MODERN_SCOPE
                ]
                if selector is None:
                    if len(modern) > 1:
                        raise _error("credential_selection_required")
                    selector = modern[0] if modern else _LEGACY_SCOPE
                if (
                    not (
                        selector == _LEGACY_SCOPE
                        or (selector.startswith(_MODERN_SCOPE) and selector != _MODERN_SCOPE)
                    )
                    or selector not in data
                ):
                    raise _error("credential_selection_required")
                entry = data[selector]
                if not isinstance(entry, dict):
                    raise _schema()
                secret = _text(entry.get("key"))
                expires_at = _expiry(entry.get("expires_at"))
                if entry.get("user_id") is not None:
                    user_id = _text(entry["user_id"])
        else:
            try:
                secret = self._store.get(account.credential_ref)
            except CredentialError:
                raise _error("credential_unavailable") from None
            secret = _text(secret)
            raw = secret.encode("utf-8")
        if expires_at is not None and expires_at <= utc_datetime(self._clock()):
            raise _error("credential_expired")
        binding = json.dumps(
            [
                account.id,
                account.provider,
                account.credential_kind,
                account.credential_ref,
                account.credential_selector,
                account.organization_id,
            ],
            separators=(",", ":"),
        ).encode("utf-8")
        fingerprint = hmac.new(self._generation_key, digestmod=hashlib.sha256)
        fingerprint.update(binding)
        fingerprint.update(b"\0")
        fingerprint.update(raw)
        try:
            return ResolvedCredential(
                provider=account.provider,
                credential_kind=account.credential_kind,
                secret=secret,
                generation_fingerprint=fingerprint.hexdigest(),
                user_id=user_id,
                expires_at=expires_at,
                organization_id=account.organization_id,
            )
        except DomainError:
            raise _schema() from None
