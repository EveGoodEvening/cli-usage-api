"""Opt-in, file-only JSON-lines debug log of provider responses and snapshots.

The logger is silent unless the live CLI configures a private file: it never
propagates to root logging (the TUI owns the terminal). Records hold raw response
bodies, which may contain personal data; values under secret-looking keys, JWT-like
strings and the request's own credential values are redacted best-effort. Request
headers and exception messages are never recorded.
"""

from __future__ import annotations

import json
import logging
import os
import re
import stat
from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from usage_tui.domain import ProviderId, Snapshot

LOGGER = logging.getLogger("usage_tui.debug")
LOGGER.propagate = False
LOGGER.addHandler(logging.NullHandler())
MAX_BODY_CHARS = 262_144
REDACTED = "[redacted]"
_SECRET_PARTS = (
    "secret",
    "password",
    "passwd",
    "cookie",
    "authorization",
    "apikey",
    "bearer",
    "credential",
    "privatekey",
    "session",
    "jwt",
    "refresh",
)
_JWT = re.compile(r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]*")
# Undecodable text: a quoted key's value (possibly unterminated) or key=value pairs.
# Keys are bounded and anchored so a long run of text cannot scan quadratically.
_QUOTED_PAIR = re.compile(
    r'"((?:[^"\\]|\\.){0,128})"(\s*:\s*)("(?:[^"\\]|\\.)*(?:"|$)|[^,{}\[\]\s]+)'
)
_PLAIN_PAIR = re.compile(r"(?<![A-Za-z0-9_.-])([A-Za-z0-9_.-]{1,128})(\s*=\s*)([^&;,\s\"'<>]+)")
_handler: logging.Handler | None = None
_providers: frozenset[ProviderId] | None = None


class DebugLogError(Exception):
    """The debug log file could not be opened privately."""


def provider_name(provider: ProviderId) -> str:
    return provider.value.replace("_", "-")


class _ProviderFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return _providers is None or getattr(record, "provider", None) in _providers


class _FileHandler(logging.StreamHandler):
    def handleError(self, record: logging.LogRecord) -> None:
        # Never print a traceback over the TUI; a failed debug write is dropped.
        pass

    def close(self) -> None:
        try:
            self.acquire()
            try:
                if self.stream is not None:
                    self.stream.close()
            finally:
                self.release()
        finally:
            super().close()


def configure(path: str | Path, providers: Iterable[ProviderId] | None = None) -> None:
    """Append to an owner-only regular file; the parent directory must already exist."""
    global _handler, _providers
    close()
    try:
        fd = os.open(
            os.path.abspath(path),
            os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
            0o600,
        )
    except OSError:
        raise DebugLogError from None
    info = os.fstat(fd)
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) & 0o077
        or info.st_nlink != 1
    ):
        os.close(fd)
        raise DebugLogError
    handler = _FileHandler(os.fdopen(fd, "a", encoding="utf-8"))
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.addFilter(_ProviderFilter())
    _providers = None if providers is None else frozenset(providers)
    _handler = handler
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.DEBUG)


def close() -> None:
    global _handler, _providers
    if _handler is not None:
        LOGGER.removeHandler(_handler)
        _handler.close()
        LOGGER.setLevel(logging.NOTSET)
    _handler = None
    _providers = None


def enabled(provider: ProviderId) -> bool:
    return _handler is not None and (_providers is None or provider in _providers)


def _secret_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", key.lower())
    return (
        any(part in normalized for part in _SECRET_PARTS)
        or normalized.endswith("token")
        or normalized == "auth"
    )


def _redact(value: object, decimals: dict[str, str], nonce: str) -> object:
    if isinstance(value, dict):
        return {
            str(key): REDACTED
            if isinstance(key, str) and _secret_key(key)
            else _redact(item, decimals, nonce)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(item, decimals, nonce) for item in value]
    if isinstance(value, str):
        return _JWT.sub(REDACTED, value)
    if isinstance(value, Decimal):
        # Emitted later as the exact wire numeral, never through float.
        placeholder = f"\x00{nonce}:{len(decimals)}\x00"
        decimals[json.dumps(placeholder)] = str(value)
        return placeholder
    return value


def _redact_text(text: str) -> str:
    def pair(match: re.Match[str]) -> str:
        if not _secret_key(match[1]):
            return match[0]
        return match[0][: match.start(3) - match.start(0)] + json.dumps(REDACTED)

    text = _QUOTED_PAIR.sub(pair, text)
    text = _PLAIN_PAIR.sub(lambda m: m[1] + m[2] + REDACTED if _secret_key(m[1]) else m[0], text)
    return _JWT.sub(REDACTED, text)


def _dumps(value: object) -> str:
    decimals: dict[str, str] = {}
    text = json.dumps(_redact(value, decimals, uuid4().hex), ensure_ascii=False)
    for placeholder, numeral in decimals.items():
        text = text.replace(placeholder, numeral, 1)
    return text


def _scrub(text: str, values: Iterable[str | None]) -> str:
    for value in values:
        if value and len(value) >= 4:
            for form in (value, json.dumps(value, ensure_ascii=False)[1:-1]):
                text = text.replace(form, REDACTED)
    return text


def _emit(provider: ProviderId, event: str, scrub: Iterable[str | None] = (), **fields) -> None:
    record = {
        "ts": datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "provider": provider_name(provider),
        "event": event,
        **fields,
    }
    try:
        line = _scrub(_dumps(record), tuple(scrub))
    except (TypeError, ValueError, RecursionError):
        line = _dumps(
            {**{k: record[k] for k in ("ts", "provider", "event")}, "error": "unloggable"}
        )
    LOGGER.debug(line, extra={"provider": provider})


def http_response(
    provider: ProviderId,
    path: str,
    status: int,
    body: bytes | bytearray | None,
    *,
    decoded: object = None,
    scrub: Iterable[str | None] = (),
) -> None:
    """Log one response: decoded JSON when available, otherwise bounded text.

    Never raises: a body that cannot be serialized (for example nesting deeper
    than the recursion limit) is recorded as unloggable rather than changing
    the fetch result.
    """
    if not enabled(provider):
        return
    scrub = tuple(scrub)
    fields: dict[str, object] = {"path": path, "status": status}
    if body is not None:
        fields["bytes"] = len(body)
    try:
        if body is None:
            fields["body_unread"] = True
        elif isinstance(decoded, (dict, list)):
            # Redact and scrub before cutting, so no secret survives as a prefix.
            text = _scrub(_dumps(decoded), scrub)
            if len(text) <= MAX_BODY_CHARS:
                fields["body"] = decoded
            else:
                fields["body_truncated"] = text[:MAX_BODY_CHARS]
        else:
            text = bytes(body).decode("utf-8", errors="replace")
            fields["body_text"] = _scrub(_redact_text(text), scrub)[:MAX_BODY_CHARS]
    except (TypeError, ValueError, RecursionError):
        fields.pop("body", None)
        fields["body_unloggable"] = True
    _emit(provider, "http_response", scrub, **fields)


def http_error(
    provider: ProviderId,
    path: str,
    *,
    code: str | None = None,
    fetch_state: str | None = None,
    status: int | None = None,
    exception: str | None = None,
) -> None:
    if enabled(provider):
        fields = {"code": code, "fetch_state": fetch_state, "status": status}
        if exception is not None:
            fields["exception"] = exception
        _emit(provider, "http_error", path=path, **fields)


def _time(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def snapshot(provider: ProviderId, result: Snapshot) -> None:
    """Summarize what an adapter (or a failed attempt) produced before merging."""
    if not enabled(provider):
        return
    metrics = []
    for metric in result.metrics:
        quota = metric.quota
        balance = metric.balance
        metrics.append(
            {
                "id": metric.id,
                "label": metric.label,
                "state": metric.state.value,
                "detail": metric.detail,
                "quota": None
                if quota is None
                else {
                    name: getattr(quota, name)
                    for name in (
                        "used_percent",
                        "remaining_percent",
                        "used_count",
                        "limit_count",
                        "remaining_count",
                    )
                    if getattr(quota, name) is not None
                },
                "reset_at": _time(metric.reset_at),
                "balance": None
                if balance is None
                else {
                    "minor": balance.minor,
                    "currency": balance.currency,
                    "exponent": balance.exponent,
                },
                "share_percent": metric.share_percent,
                "shared_pool_id": metric.shared_pool_id,
            }
        )
    _emit(
        provider,
        "snapshot",
        account_id=result.account_id,
        fetch_state=result.fetch_state.value,
        diagnostic=None if result.diagnostic is None else result.diagnostic.code,
        attempted_at=_time(result.attempted_at),
        retry_at=_time(result.retry_at),
        grants=len(result.grants),
        metrics=metrics,
    )
