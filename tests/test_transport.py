"""Synthetic HTTP-only tests; no real provider, credential file or keyring access."""

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from email.utils import format_datetime

import httpx
import pytest

from cli_usage_api.domain import (
    CredentialKind,
    FetchState,
    ProviderId,
    ResolvedCredential,
    TransportError,
)
from cli_usage_api.transport import MAX_RESPONSE_BYTES, Transport, claude_credits_path

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
                "x-grok-client-version": "1.0.70",
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
        assert request.headers["user-agent"].startswith("cli-usage-api/")
        for name, value in expected_headers.items():
            assert request.headers[name] == value
        for name in (
            "authorization",
            "cookie",
            "anthropic-beta",
            "x-xai-token-auth",
            "x-userid",
            "x-grok-client-version",
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
    import cli_usage_api.transport as module

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


# --- Claude profile/prepaid credits and OpenAI Platform credit grants ----------------

CLAUDE_ORG = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
OTHER_ORG = "ffffffff-bbbb-4ccc-8ddd-eeeeeeeeeeee"
OPENAI_ORG = "org-Synthetic0123"
OPENAI_SESSION = "synthetic-openai-session-0000"


def claude_credential(organization_id=CLAUDE_ORG, kind=CredentialKind.MANUAL_BEARER):
    return ResolvedCredential(
        ProviderId.CLAUDE_SUBSCRIPTION,
        kind,
        "synthetic-secret",
        "generation-1",
        organization_id=organization_id,
    )


def openai_credential(secret=OPENAI_SESSION, organization_id=OPENAI_ORG):
    return ResolvedCredential(
        ProviderId.OPENAI_PLATFORM,
        CredentialKind.OPENAI_PLATFORM_SESSION,
        secret,
        "generation-1",
        organization_id=organization_id,
    )


def capture(status=200, **response):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status, **response)

    return requests, Transport(http_transport=httpx.MockTransport(handler), clock=lambda: NOW)


_OPTIONAL_HEADERS = (
    "anthropic-beta",
    "anthropic-version",
    "anthropic-client-platform",
    "x-organization-uuid",
    "openai-organization",
    "cache-control",
    "content-type",
    "cookie",
    "chatgpt-account-id",
)


def assert_only(request, expected):
    assert request.method == "GET"
    assert request.headers["accept"] == "application/json"
    assert request.headers["user-agent"].startswith("cli-usage-api/")
    for name, value in expected.items():
        assert request.headers[name] == value
    for name in _OPTIONAL_HEADERS:
        if name not in expected:
            assert name not in request.headers


async def test_claude_profile_uses_no_beta_header():
    requests, transport = capture(json={"organization": {"uuid": CLAUDE_ORG}})
    await transport.get_json(
        ProviderId.CLAUDE_SUBSCRIPTION, "/api/oauth/profile", credential=claude_credential(None)
    )
    assert str(requests[0].url) == "https://api.anthropic.com/api/oauth/profile"
    assert_only(
        requests[0], {"authorization": "Bearer synthetic-secret", "cache-control": "no-cache"}
    )


@pytest.mark.parametrize("kind", [CredentialKind.MANUAL_BEARER, CredentialKind.CLAUDE_CODE_FILE])
async def test_claude_prepaid_credits_bind_the_saved_organization(kind):
    requests, transport = capture(json={"amount": 1234, "currency": "usd"})
    path = claude_credits_path(CLAUDE_ORG)
    assert await transport.get_json(
        ProviderId.CLAUDE_SUBSCRIPTION, path, credential=claude_credential(kind=kind)
    ) == {"amount": 1234, "currency": "usd"}
    assert str(requests[0].url) == (
        f"https://api.anthropic.com/api/oauth/organizations/{CLAUDE_ORG}/prepaid/credits"
    )
    assert_only(
        requests[0],
        {
            "authorization": "Bearer synthetic-secret",
            "anthropic-version": "2023-06-01",
            "x-organization-uuid": CLAUDE_ORG,
        },
    )


@pytest.mark.parametrize(
    ("path", "organization_id"),
    [
        (f"/api/oauth/organizations/{OTHER_ORG}/prepaid/credits", CLAUDE_ORG),
        (f"/api/oauth/organizations/{CLAUDE_ORG}/prepaid/credits", None),
        (f"/api/oauth/organizations/{CLAUDE_ORG.upper()}/prepaid/credits", CLAUDE_ORG),
        (f"/api/oauth/organizations/{CLAUDE_ORG}/prepaid/credits/", CLAUDE_ORG),
        (f"/api/oauth/organizations/{CLAUDE_ORG}/prepaid/credits?x=1", CLAUDE_ORG),
        (f"/api/oauth/organizations/{CLAUDE_ORG}/contracts/prepaid/credits", CLAUDE_ORG),
        (f"/api/oauth/organizations/{CLAUDE_ORG}/setup_overage_billing", CLAUDE_ORG),
        (f"/api/oauth/organizations/{CLAUDE_ORG}/overage_spend_limit", CLAUDE_ORG),
        (f"/api/oauth/organizations/{CLAUDE_ORG}/contracts/auto_reload_settings", CLAUDE_ORG),
        (f"/api/oauth/organizations/{CLAUDE_ORG}/prepaid/bundles", CLAUDE_ORG),
        (f"/api/oauth/organizations/{CLAUDE_ORG}/payment_method", CLAUDE_ORG),
        ("/api/oauth/organizations/../prepaid/credits", CLAUDE_ORG),
        ("/api/oauth/profile/", None),
    ],
)
async def test_claude_credit_paths_outside_the_exact_read_never_reach_http(path, organization_id):
    requests, transport = capture()
    with pytest.raises(TransportError) as caught:
        await transport.get_json(
            ProviderId.CLAUDE_SUBSCRIPTION, path, credential=claude_credential(organization_id)
        )
    assert (caught.value.fetch_state, caught.value.code) == (
        FetchState.PERMISSION_DENIED,
        "forbidden_request",
    )
    assert requests == []


async def test_openai_credit_grants_route_and_headers():
    requests, transport = capture(json={"total_available": 4.9})
    result = await transport.get_json(
        ProviderId.OPENAI_PLATFORM,
        "/v1/dashboard/billing/credit_grants",
        credential=openai_credential(),
    )
    assert result == {"total_available": Decimal("4.9")}
    assert str(requests[0].url) == "https://api.openai.com/v1/dashboard/billing/credit_grants"
    assert_only(
        requests[0],
        {"authorization": f"Bearer {OPENAI_SESSION}", "openai-organization": OPENAI_ORG},
    )


@pytest.mark.parametrize(
    "path",
    [
        "/v1/dashboard/billing/credit_grants/",
        "/v1/dashboard/billing/credit_grants?x=1",
        "/dashboard/billing/credit_grants",
        "/v1/dashboard/onboarding/login",
        "/v1/dashboard/billing/subscription",
        "/v1/dashboard/billing/subscription/setup",
        "/v1/organizations",
        "/v1/me",
        "/api/oauth/usage",
    ],
)
async def test_openai_paths_outside_the_exact_read_never_reach_http(path):
    requests, transport = capture()
    with pytest.raises(TransportError) as caught:
        await transport.get_json(ProviderId.OPENAI_PLATFORM, path, credential=openai_credential())
    assert caught.value.code == "forbidden_request"
    assert requests == []


async def test_transport_has_no_write_method_for_purchase_neighbours():
    # The only request surface is GET; the same credit_grants path's POST buys credits.
    methods = []

    def handler(request):
        methods.append(request.method)
        return httpx.Response(200, json={})

    transport = Transport(http_transport=httpx.MockTransport(handler))
    await transport.get_json(
        ProviderId.OPENAI_PLATFORM,
        "/v1/dashboard/billing/credit_grants",
        credential=openai_credential(),
    )
    await transport.get_json(
        ProviderId.CLAUDE_SUBSCRIPTION,
        claude_credits_path(CLAUDE_ORG),
        credential=claude_credential(),
    )
    assert methods == ["GET", "GET"]
    assert not any(hasattr(transport, name) for name in ("post", "put", "delete", "request"))


@pytest.mark.parametrize(
    "secret",
    ["short-session", "Bearer" + "x" * 30, "x" * 4097, "a" * 20 + ";b", '{"k":"' + "v" * 30 + '"}'],
)
async def test_openai_non_bare_session_values_never_reach_http(secret):
    requests, transport = capture()
    with pytest.raises(TransportError) as caught:
        await transport.get_json(
            ProviderId.OPENAI_PLATFORM,
            "/v1/dashboard/billing/credit_grants",
            credential=openai_credential(secret),
        )
    assert caught.value.code == "credential_mismatch"
    assert requests == []


async def test_openai_requires_a_bound_organization_before_http():
    credential = openai_credential()
    object.__setattr__(credential, "organization_id", None)
    requests, transport = capture()
    with pytest.raises(TransportError) as caught:
        await transport.get_json(
            ProviderId.OPENAI_PLATFORM, "/v1/dashboard/billing/credit_grants", credential=credential
        )
    assert caught.value.code == "credential_mismatch"
    assert requests == []


@pytest.mark.parametrize(
    ("status", "body", "state", "code"),
    [
        (401, None, FetchState.AUTH_REQUIRED, "auth_required"),
        (
            401,
            {"error": {"code": "expired_session_key"}},
            FetchState.AUTH_REQUIRED,
            "credential_expired",
        ),
        (
            400,
            {"error": {"code": "expired_session_key"}},
            FetchState.AUTH_REQUIRED,
            "credential_expired",
        ),
        (
            403,
            {"error": {"code": "expired_session_key"}},
            FetchState.AUTH_REQUIRED,
            "credential_expired",
        ),
        (
            403,
            {"error": {"code": "personal_organization_access_blocked", "message": "x"}},
            FetchState.PERMISSION_DENIED,
            "permission_denied",
        ),
        (
            403,
            {
                "error": {
                    "message": "Your request ... must be made with a session key (that is ...)"
                }
            },
            FetchState.AUTH_REQUIRED,
            "credential_mismatch",
        ),
        (403, None, FetchState.PERMISSION_DENIED, "permission_denied"),
        (403, {"error": "expired_session_key"}, FetchState.PERMISSION_DENIED, "permission_denied"),
        (404, {"error": {"code": "other"}}, FetchState.PROVIDER_ERROR, "provider_error"),
        (
            500,
            {"error": {"code": "expired_session_key"}},
            FetchState.PROVIDER_ERROR,
            "provider_error",
        ),
    ],
)
async def test_openai_error_classification_uses_curated_codes(status, body, state, code):
    response = {} if body is None else {"json": body}
    _, transport = capture(status, **response)
    with pytest.raises(TransportError) as caught:
        await transport.get_json(
            ProviderId.OPENAI_PLATFORM,
            "/v1/dashboard/billing/credit_grants",
            credential=openai_credential(),
        )
    assert (caught.value.fetch_state, caught.value.code, caught.value.status) == (
        state,
        code,
        status,
    )
    assert "expired_session_key" not in str(caught.value)
    assert OPENAI_SESSION not in str(caught.value)


async def test_openai_rate_limit_keeps_the_retry_deadline_without_reading_the_body():
    stream = Chunks([b'{"error":{"code":"expired_session_key"}}'])
    _, transport = capture(429, headers={"Retry-After": "600"}, stream=stream)
    with pytest.raises(TransportError) as caught:
        await transport.get_json(
            ProviderId.OPENAI_PLATFORM,
            "/v1/dashboard/billing/credit_grants",
            credential=openai_credential(),
        )
    assert caught.value.fetch_state == FetchState.RATE_LIMITED
    assert caught.value.retry_at == NOW + timedelta(seconds=600)
    assert stream.read_count == 0


async def test_openai_oversized_or_invalid_error_body_keeps_the_status_mapping():
    for stream in (
        Chunks([b"x" * MAX_RESPONSE_BYTES, b'{"error":{"code":"expired_session_key"}}']),
        Chunks([b"not json"]),
    ):
        _, transport = capture(403, stream=stream)
        with pytest.raises(TransportError) as caught:
            await transport.get_json(
                ProviderId.OPENAI_PLATFORM,
                "/v1/dashboard/billing/credit_grants",
                credential=openai_credential(),
            )
        assert caught.value.code == "permission_denied"
        assert stream.closed


async def test_openai_slow_error_body_cannot_turn_into_a_network_error(monkeypatch):
    import cli_usage_api.transport as module

    monkeypatch.setattr(module, "DEBUG_BODY_TIMEOUT_SECONDS", 0.05)

    class Slow(httpx.AsyncByteStream):
        async def __aiter__(self):
            await asyncio.sleep(5)
            yield b"{}"

    _, transport = capture(401, stream=Slow())
    with pytest.raises(TransportError) as caught:
        await transport.get_json(
            ProviderId.OPENAI_PLATFORM,
            "/v1/dashboard/billing/credit_grants",
            credential=openai_credential(),
        )
    assert caught.value.code == "auth_required"
