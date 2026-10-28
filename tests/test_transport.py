"""Synthetic HTTP-only tests; no real provider, credential file or keyring access."""

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from email.utils import format_datetime

import httpx
import pytest

from usage_tui.domain import (
    CredentialKind,
    FetchState,
    ProviderId,
    ResolvedCredential,
    TransportError,
)
from usage_tui.transport import MAX_RESPONSE_BYTES, Transport

NOW = datetime(2026, 10, 28, 12, tzinfo=UTC)


def credential(provider=ProviderId.CLAUDE_SUBSCRIPTION, *, kind=None, user_id=None):
    if kind is None:
        kind = {
            ProviderId.CLAUDE_PLATFORM: CredentialKind.CONSOLE_SESSION,
            ProviderId.CODEX_SUBSCRIPTION: CredentialKind.CODEX_AUTH_FILE,
        }.get(provider, CredentialKind.MANUAL_BEARER)
    return ResolvedCredential(
        provider,
        kind,
        "synthetic-secret",
        "generation-1",
        user_id=user_id,
        codex_account_id="synthetic-selected-account"
        if provider == ProviderId.CODEX_SUBSCRIPTION
        else None,
    )


@pytest.mark.parametrize(
    ("provider", "path", "host", "expected_headers"),
    [
        (
            ProviderId.CLAUDE_SUBSCRIPTION,
            "/api/oauth/usage",
            "api.anthropic.com",
            {"authorization": "Bearer synthetic-secret", "anthropic-beta": "oauth-2025-04-20"},
        ),
        (
            ProviderId.CLAUDE_PLATFORM,
            "/api/organizations",
            "platform.claude.com",
            {"cookie": "sessionKey=synthetic-secret"},
        ),
        (
            ProviderId.CLAUDE_PLATFORM,
            "/api/organizations/org-1/prepaid/credits",
            "platform.claude.com",
            {"cookie": "sessionKey=synthetic-secret"},
        ),
        (
            ProviderId.CODEX_SUBSCRIPTION,
            "/backend-api/wham/usage",
            "chatgpt.com",
            {
                "authorization": "Bearer synthetic-secret",
                "chatgpt-account-id": "synthetic-selected-account",
            },
        ),
        (
            ProviderId.GROK_SUBSCRIPTION,
            "/v1/billing?format=credits",
            "cli-chat-proxy.grok.com",
            {
                "authorization": "Bearer synthetic-secret",
                "x-xai-token-auth": "xai-grok-cli",
                "x-userid": "synthetic-user",
            },
        ),
    ],
)
async def test_exact_routes_and_auth_headers(provider, path, host, expected_headers):
    requests = []

    def handler(request):
        requests.append(request)
        assert request.method == "GET"
        assert str(request.url) == f"https://{host}{path}"
        assert request.headers["accept"] == "application/json"
        assert request.headers["user-agent"].startswith("usage-tui/")
        for name, value in expected_headers.items():
            assert request.headers[name] == value
        for name in (
            "authorization",
            "cookie",
            "anthropic-beta",
            "x-xai-token-auth",
            "x-userid",
            "chatgpt-account-id",
        ):
            if name not in expected_headers:
                assert name not in request.headers
        assert request.extensions["timeout"]["connect"] == 5.0
        assert request.extensions["timeout"]["read"] == 10.0
        return httpx.Response(200, json={"synthetic": [1, 2]})

    source = credential(
        provider, user_id="synthetic-user" if provider == ProviderId.GROK_SUBSCRIPTION else None
    )
    transport = Transport(http_transport=httpx.MockTransport(handler))
    assert await transport.get_json(provider, path, credential=source) == {"synthetic": [1, 2]}
    assert len(requests) == 1


@pytest.mark.parametrize("payload", [{"a": 1}, [], [1, {"a": True}]])
async def test_json_container_roots(payload):
    transport = Transport(
        http_transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    )
    assert (
        await transport.get_json(
            ProviderId.CLAUDE_SUBSCRIPTION, "/api/oauth/usage", credential=credential()
        )
        == payload
    )


async def test_json_numbers_preserve_wire_precision_and_integer_types():
    body = (
        b'{"fraction":43.500000000000000000000000000001,'
        b'"tiny":1e-1001,"large":1e1001,"integer":42,"boolean":true}'
    )
    transport = Transport(
        http_transport=httpx.MockTransport(lambda _: httpx.Response(200, content=body))
    )
    result = await transport.get_json(
        ProviderId.CLAUDE_SUBSCRIPTION, "/api/oauth/usage", credential=credential()
    )
    assert type(result["fraction"]) is Decimal
    assert result["fraction"] == Decimal("43.500000000000000000000000000001")
    assert result["tiny"] == Decimal("1e-1001")
    assert result["large"] == Decimal("1e1001")
    assert type(result["integer"]) is int
    assert result["integer"] == 42
    assert result["boolean"] is True


@pytest.mark.parametrize(
    ("status", "state", "code"),
    [
        (301, FetchState.PROVIDER_ERROR, "provider_error"),
        (400, FetchState.PROVIDER_ERROR, "provider_error"),
        (401, FetchState.AUTH_REQUIRED, "auth_required"),
        (403, FetchState.PERMISSION_DENIED, "permission_denied"),
        (404, FetchState.PROVIDER_ERROR, "provider_error"),
        (429, FetchState.RATE_LIMITED, "rate_limited"),
        (500, FetchState.PROVIDER_ERROR, "provider_error"),
        (503, FetchState.PROVIDER_ERROR, "provider_error"),
    ],
)
async def test_status_mapping(status, state, code):
    transport = Transport(http_transport=httpx.MockTransport(lambda _: httpx.Response(status)))
    with pytest.raises(TransportError) as caught:
        await transport.get_json(
            ProviderId.CLAUDE_SUBSCRIPTION, "/api/oauth/usage", credential=credential()
        )
    assert (caught.value.fetch_state, caught.value.code, caught.value.status) == (
        state,
        code,
        status,
    )


@pytest.mark.parametrize(
    ("path", "state"),
    [
        ("/api/organizations", FetchState.AUTH_REQUIRED),
        ("/api/organizations/org-1/prepaid/credits", FetchState.PERMISSION_DENIED),
    ],
)
async def test_console_discovery_and_selected_org_permission(path, state):
    transport = Transport(http_transport=httpx.MockTransport(lambda _: httpx.Response(403)))
    with pytest.raises(TransportError) as caught:
        await transport.get_json(
            ProviderId.CLAUDE_PLATFORM, path, credential=credential(ProviderId.CLAUDE_PLATFORM)
        )
    assert caught.value.fetch_state == state


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, None),
        ("not-a-date", None),
        ("-1", None),
        ("1.5", None),
        ("0", NOW + timedelta(seconds=60)),
        ("59", NOW + timedelta(seconds=60)),
        ("3600", NOW + timedelta(hours=1)),
        (format_datetime(NOW + timedelta(days=365), usegmt=True), NOW + timedelta(days=365)),
        (format_datetime(NOW - timedelta(days=1), usegmt=True), NOW + timedelta(seconds=60)),
        ("9" * 5000, datetime.max.replace(tzinfo=UTC)),
        ("0" * 5000, NOW + timedelta(seconds=60)),
    ],
)
async def test_retry_after_preserves_long_server_deadlines(header, expected):
    headers = {} if header is None else {"Retry-After": header}
    transport = Transport(
        http_transport=httpx.MockTransport(lambda _: httpx.Response(429, headers=headers)),
        clock=lambda: NOW,
    )
    with pytest.raises(TransportError) as caught:
        await transport.get_json(
            ProviderId.CLAUDE_SUBSCRIPTION, "/api/oauth/usage", credential=credential()
        )
    assert caught.value.retry_at == expected


@pytest.mark.parametrize(
    "body",
    [
        b"not JSON",
        b"<html>synthetic-secret</html>",
        b"null",
        b"1",
        b"true",
        b'"a"',
        b'{"a":NaN}',
        b'{"a":Infinity}',
        b'{"a":-Infinity}',
        b'{"a":1e9999999999999999999999999999999999999999}',
        b"\xff",
        b"[" * 2000,
    ],
)
async def test_invalid_json_is_safe_schema_failure(body):
    transport = Transport(
        http_transport=httpx.MockTransport(lambda _: httpx.Response(200, content=body))
    )
    with pytest.raises(TransportError) as caught:
        await transport.get_json(
            ProviderId.CLAUDE_SUBSCRIPTION, "/api/oauth/usage", credential=credential()
        )
    assert caught.value.code == "schema_error"
    assert caught.value.status == 200
    assert caught.value.__context__ is None


class Chunks(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks
        self.read_count = 0
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            self.read_count += 1
            yield chunk

    async def aclose(self):
        self.closed = True


async def test_stream_size_is_bounded_without_trusting_content_length():
    stream = Chunks([b" " * MAX_RESPONSE_BYTES, b"x", b"must-not-be-read"])
    transport = Transport(
        http_transport=httpx.MockTransport(
            lambda _: httpx.Response(200, headers={"Content-Length": "1"}, stream=stream)
        )
    )
    with pytest.raises(TransportError) as caught:
        await transport.get_json(
            ProviderId.CLAUDE_SUBSCRIPTION, "/api/oauth/usage", credential=credential()
        )
    assert caught.value.code == "response_too_large"
    assert stream.read_count == 2
    assert stream.closed


async def test_exact_size_limit_is_allowed():
    body = b"{}" + b" " * (MAX_RESPONSE_BYTES - 2)
    transport = Transport(
        http_transport=httpx.MockTransport(lambda _: httpx.Response(200, content=body))
    )
    assert (
        await transport.get_json(
            ProviderId.CLAUDE_SUBSCRIPTION, "/api/oauth/usage", credential=credential()
        )
        == {}
    )


async def test_error_body_is_not_read():
    stream = Chunks([b"synthetic-secret" * MAX_RESPONSE_BYTES])
    transport = Transport(
        http_transport=httpx.MockTransport(lambda _: httpx.Response(500, stream=stream))
    )
    with pytest.raises(TransportError):
        await transport.get_json(
            ProviderId.CLAUDE_SUBSCRIPTION, "/api/oauth/usage", credential=credential()
        )
    assert stream.read_count == 0
    assert stream.closed


async def test_total_deadline_covers_the_stream(monkeypatch):
    import usage_tui.transport as module

    monkeypatch.setattr(module, "TOTAL_TIMEOUT_SECONDS", 0.01)

    class NeverEnds(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            yield b"{"
            await asyncio.Event().wait()

        async def aclose(self):
            self.closed = True

    stream = NeverEnds()
    transport = Transport(
        http_transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=stream))
    )
    with pytest.raises(TransportError) as caught:
        await transport.get_json(
            ProviderId.CLAUDE_SUBSCRIPTION, "/api/oauth/usage", credential=credential()
        )
    assert caught.value.code == "network_error"
    assert caught.value.__context__ is None
    assert stream.closed


async def test_cancellation_propagates_and_closes_response():
    entered = asyncio.Event()

    class Waiting(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            entered.set()
            await asyncio.Event().wait()
            yield b"{}"

        async def aclose(self):
            self.closed = True

    stream = Waiting()
    transport = Transport(
        http_transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=stream))
    )
    task = asyncio.create_task(
        transport.get_json(
            ProviderId.CLAUDE_SUBSCRIPTION, "/api/oauth/usage", credential=credential()
        )
    )
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert stream.closed


@pytest.mark.parametrize(
    ("provider", "kind", "path"),
    [
        (
            ProviderId.CLAUDE_SUBSCRIPTION,
            CredentialKind.CLAUDE_CODE_FILE,
            "/api/oauth/usage",
        ),
        (
            ProviderId.GROK_SUBSCRIPTION,
            CredentialKind.GROK_AUTH_FILE,
            "/v1/billing?format=credits",
        ),
        (
            ProviderId.CODEX_SUBSCRIPTION,
            CredentialKind.CODEX_AUTH_FILE,
            "/backend-api/wham/usage",
        ),
    ],
)
async def test_first_party_file_credentials_are_supported(provider, kind, path):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={})

    transport = Transport(http_transport=httpx.MockTransport(handler))
    assert (
        await transport.get_json(provider, path, credential=credential(provider, kind=kind)) == {}
    )
    assert seen[0].headers["authorization"] == "Bearer synthetic-secret"
    assert "x-userid" not in seen[0].headers
