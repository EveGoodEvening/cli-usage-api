"""Read-only, fixed-origin HTTP with a deliberately small safe error boundary."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from importlib.metadata import PackageNotFoundError, version

import httpx

from usage_tui.domain import (
    DomainError,
    FetchState,
    ProviderId,
    ResolvedCredential,
    TransportError,
    validate_credential_binding,
)

MAX_RESPONSE_BYTES = 1_048_576
TOTAL_TIMEOUT_SECONDS = 10.0
CONNECT_TIMEOUT_SECONDS = 5.0
_ORGANIZATION_PATH = re.compile(r"/api/organizations/[A-Za-z0-9-]{1,64}/prepaid/credits")
_ORIGINS = {
    ProviderId.CLAUDE_SUBSCRIPTION: "https://api.anthropic.com",
    ProviderId.CLAUDE_PLATFORM: "https://platform.claude.com",
    ProviderId.GROK_SUBSCRIPTION: "https://cli-chat-proxy.grok.com",
    ProviderId.CODEX_SUBSCRIPTION: "https://chatgpt.com",
}


def _user_agent() -> str:
    try:
        installed_version = version("usage-tui")
    except PackageNotFoundError:
        installed_version = "0.1.0"
    return f"usage-tui/{installed_version}"


def _allowed_path(provider: ProviderId, path: str) -> bool:
    if not isinstance(path, str):
        return False
    if provider == ProviderId.CLAUDE_SUBSCRIPTION:
        return path == "/api/oauth/usage"
    if provider == ProviderId.CODEX_SUBSCRIPTION:
        return path == "/backend-api/wham/usage"
    if provider == ProviderId.GROK_SUBSCRIPTION:
        return path == "/v1/billing?format=credits"
    if provider == ProviderId.CLAUDE_PLATFORM:
        return path == "/api/organizations" or _ORGANIZATION_PATH.fullmatch(path) is not None
    return False


def _header_token(value: str) -> bool:
    return bool(value) and all(0x21 <= ord(character) <= 0x7E for character in value)


def _cookie_value(value: str) -> bool:
    # RFC 6265 cookie-octet: no whitespace, quote, comma, semicolon or backslash.
    return bool(value) and all(
        ord(character) == 0x21
        or 0x23 <= ord(character) <= 0x2B
        or 0x2D <= ord(character) <= 0x3A
        or 0x3C <= ord(character) <= 0x5B
        or 0x5D <= ord(character) <= 0x7E
        for character in value
    )


def _retry_at(value: str | None, now: datetime) -> datetime | None:
    if value is None:
        return None
    value = value.strip()
    minimum = now + timedelta(seconds=60)
    if value and value.isascii() and value.isdecimal():
        # Avoid parsing arbitrarily large integers supplied by a hostile server.
        if len(value.lstrip("0")) > 12:
            return datetime.max.replace(tzinfo=UTC)
        seconds = int(value.lstrip("0") or "0")
        try:
            return max(minimum, now + timedelta(seconds=seconds))
        except OverflowError:
            return datetime.max.replace(tzinfo=UTC)
    try:
        deadline = parsedate_to_datetime(value)
        if deadline.tzinfo is not None:
            return max(minimum, deadline.astimezone(UTC))
    except (ValueError, TypeError, OverflowError):
        pass
    return None


def _reject_json_constant(value: str) -> None:
    raise ValueError("Non-JSON numeric constant.")


class Transport:
    """Inject only the HTTP I/O boundary, never a configurable URL or client.

    Each read owns a fresh client, so upstream Set-Cookie values cannot influence
    later requests or another account. Construction performs no I/O.
    """

    def __init__(
        self,
        *,
        http_transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._http_transport = http_transport
        self._clock = clock or (lambda: datetime.now(UTC))

    async def get_json(
        self, provider: ProviderId, path: str, *, credential: ResolvedCredential
    ) -> dict | list:
        binding_valid = True
        try:
            validate_credential_binding(provider, credential)
        except (DomainError, TypeError, ValueError):
            binding_valid = False
        if not binding_valid:
            raise TransportError(FetchState.AUTH_REQUIRED, "credential_mismatch")
        if not _allowed_path(provider, path):
            raise TransportError(FetchState.PERMISSION_DENIED, "forbidden_request")
        if not _header_token(credential.secret) or (
            provider == ProviderId.CLAUDE_PLATFORM and not _cookie_value(credential.secret)
        ):
            raise TransportError(FetchState.AUTH_REQUIRED, "credential_mismatch")
        if credential.user_id is not None and not _header_token(credential.user_id):
            raise TransportError(FetchState.AUTH_REQUIRED, "credential_mismatch")
        if provider == ProviderId.CODEX_SUBSCRIPTION:
            selected = credential.codex_account_id
            if not isinstance(selected, str) or len(selected) > 256 or not _header_token(selected):
                raise TransportError(FetchState.AUTH_REQUIRED, "credential_mismatch")
            if credential.expires_at is not None and credential.expires_at <= self._clock():
                raise TransportError(FetchState.AUTH_REQUIRED, "credential_expired")

        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "User-Agent": _user_agent(),
        }
        if provider == ProviderId.CLAUDE_PLATFORM:
            headers["Cookie"] = f"sessionKey={credential.secret}"
        elif provider == ProviderId.CODEX_SUBSCRIPTION:
            headers["Authorization"] = f"Bearer {credential.secret}"
            headers["ChatGPT-Account-Id"] = credential.codex_account_id
        elif provider == ProviderId.CLAUDE_SUBSCRIPTION:
            headers["Authorization"] = f"Bearer {credential.secret}"
            headers["anthropic-beta"] = "oauth-2025-04-20"
        elif provider == ProviderId.GROK_SUBSCRIPTION:
            headers["Authorization"] = f"Bearer {credential.secret}"
            headers["x-xai-token-auth"] = "xai-grok-cli"
            if credential.user_id is not None:
                headers["x-userid"] = credential.user_id

        # Raise outside exception handlers: even __context__ must not retain the
        # original upstream exception (which may contain credentials or bodies).
        error = None
        try:
            async with (
                asyncio.timeout(TOTAL_TIMEOUT_SECONDS),
                httpx.AsyncClient(
                    transport=self._http_transport,
                    trust_env=False,
                    follow_redirects=False,
                    verify=True,
                    timeout=httpx.Timeout(TOTAL_TIMEOUT_SECONDS, connect=CONNECT_TIMEOUT_SECONDS),
                ) as client,
                client.stream("GET", _ORIGINS[provider] + path, headers=headers) as response,
            ):
                self._check_status(provider, path, response)
                # Do not allow a compressed chunk to expand without a
                # bound inside httpx's automatic content decoder.
                encoding = response.headers.get("Content-Encoding", "identity")
                if encoding.strip().lower() != "identity":
                    raise TransportError(
                        FetchState.SCHEMA_ERROR,
                        "schema_error",
                        status=response.status_code,
                    )
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                        raise TransportError(
                            FetchState.SCHEMA_ERROR,
                            "response_too_large",
                            status=response.status_code,
                        )
                    body.extend(chunk)
                return self._decode(body, response.status_code)
        except TransportError as failure:
            error = failure
        except Exception:  # noqa: BLE001 - Redact arbitrary third-party transport failures.
            error = TransportError(FetchState.NETWORK_ERROR, "network_error")
        raise error from None

    def _check_status(self, provider: ProviderId, path: str, response: httpx.Response) -> None:
        status = response.status_code
        if 200 <= status < 300:
            return
        if status == 401 or (
            status == 403
            and provider == ProviderId.CLAUDE_PLATFORM
            and path == "/api/organizations"
        ):
            raise TransportError(FetchState.AUTH_REQUIRED, "auth_required", status=status)
        if status == 403:
            raise TransportError(FetchState.PERMISSION_DENIED, "permission_denied", status=status)
        if status == 429:
            raise TransportError(
                FetchState.RATE_LIMITED,
                "rate_limited",
                status=status,
                retry_at=_retry_at(response.headers.get("Retry-After"), self._clock()),
            )
        raise TransportError(FetchState.PROVIDER_ERROR, "provider_error", status=status)

    @staticmethod
    def _decode(body: bytearray, status: int) -> dict | list:
        result = None
        try:
            result = json.loads(body, parse_float=Decimal, parse_constant=_reject_json_constant)
        except (ValueError, UnicodeError, RecursionError, InvalidOperation):
            pass
        if not isinstance(result, (dict, list)):
            raise TransportError(FetchState.SCHEMA_ERROR, "schema_error", status=status)
        return result
