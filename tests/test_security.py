"""Exercise credential confinement through the actual transport, with synthetic secrets."""

import gzip
import netrc
import traceback

import httpx
import pytest

from cli_usage_api.domain import (
    CredentialKind,
    Diagnostic,
    FetchState,
    ProviderId,
    ResolvedCredential,
    TransportError,
)
from cli_usage_api.transport import MAX_RESPONSE_BYTES, Transport

SECRET = "synthetic-never-real-secret"


def source(provider=ProviderId.CLAUDE_SUBSCRIPTION, kind=CredentialKind.MANUAL_BEARER, **kwargs):
    if provider == ProviderId.CODEX_SUBSCRIPTION:
        kwargs.setdefault("codex_account_id", "synthetic-selected-account")
        credential = ResolvedCredential(
            provider, CredentialKind.CODEX_AUTH_FILE, SECRET, "synthetic-generation", **kwargs
        )
        # Bypass the domain only to exercise Transport's independent kind guard.
        object.__setattr__(credential, "credential_kind", kind)
        return credential
    return ResolvedCredential(provider, kind, SECRET, "synthetic-generation", **kwargs)


@pytest.mark.parametrize(
    "path",
    [
        "https://attacker.invalid/api/oauth/usage",
        "http://api.anthropic.com/api/oauth/usage",
        "//attacker.invalid/api/oauth/usage",
        "/api/oauth/usage?token=synthetic-never-real-secret",
        "/api/oauth/usage#fragment",
        "/api/oauth/usage/",
        "/api/../api/oauth/usage",
        "/api/%6fauth/usage",
        "/api/oauth/usage\r\nX-Evil: yes",
        "/api/oauth/usage\\@attacker.invalid",
        " /api/oauth/usage",
        "",
    ],
)
async def test_forbidden_claude_paths_fail_before_http(path):
    def handler(_):
        pytest.fail("Forbidden request reached HTTP boundary")

    transport = Transport(http_transport=httpx.MockTransport(handler))
    with pytest.raises(TransportError) as caught:
        await transport.get_json(ProviderId.CLAUDE_SUBSCRIPTION, path, credential=source())
    assert caught.value.code == "forbidden_request"
    assert SECRET not in str(caught.value)


@pytest.mark.parametrize(
    ("provider", "path", "kind"),
    [
        (ProviderId.GROK_SUBSCRIPTION, "/v1/billing", CredentialKind.MANUAL_BEARER),
        (
            ProviderId.GROK_SUBSCRIPTION,
            "/v1/billing?format=credits&x=1",
            CredentialKind.MANUAL_BEARER,
        ),
        (
            ProviderId.GROK_SUBSCRIPTION,
            "/v1/billing?format=Credits",
            CredentialKind.MANUAL_BEARER,
        ),
        (
            ProviderId.CLAUDE_PLATFORM,
            "/api/organizations/../prepaid/credits",
            CredentialKind.CONSOLE_SESSION,
        ),
        (
            ProviderId.CLAUDE_PLATFORM,
            "/api/organizations/%2e/prepaid/credits",
            CredentialKind.CONSOLE_SESSION,
        ),
        (
            ProviderId.CLAUDE_PLATFORM,
            "/api/organizations/a_b/prepaid/credits",
            CredentialKind.CONSOLE_SESSION,
        ),
        (
            ProviderId.CLAUDE_PLATFORM,
            "/api/organizations/a/current_spend",
            CredentialKind.CONSOLE_SESSION,
        ),
        (
            ProviderId.CLAUDE_PLATFORM,
            "/api/organizations?all=true",
            CredentialKind.CONSOLE_SESSION,
        ),
        (
            ProviderId.CLAUDE_PLATFORM,
            f"/api/organizations/{'a' * 65}/prepaid/credits",
            CredentialKind.CONSOLE_SESSION,
        ),
    ],
)
async def test_other_provider_path_guards(provider, path, kind):
    def handler(_):
        pytest.fail("Forbidden request reached HTTP boundary")

    transport = Transport(http_transport=httpx.MockTransport(handler))
    with pytest.raises(TransportError) as caught:
        await transport.get_json(provider, path, credential=source(provider, kind))
    assert caught.value.code == "forbidden_request"


@pytest.mark.parametrize(
    ("provider", "bound_provider"),
    [
        (provider, bound_provider)
        for provider in ProviderId
        for bound_provider in ProviderId
        if provider != bound_provider
    ],
)
async def test_cross_provider_credentials_never_reach_http(provider, bound_provider):
    kind = (
        CredentialKind.CONSOLE_SESSION
        if bound_provider == ProviderId.CLAUDE_PLATFORM
        else CredentialKind.MANUAL_BEARER
    )

    def handler(_):
        pytest.fail("Cross-provider credential reached HTTP boundary")

    transport = Transport(http_transport=httpx.MockTransport(handler))
    with pytest.raises(TransportError) as caught:
        await transport.get_json(
            provider, "/api/oauth/usage", credential=source(bound_provider, kind)
        )
    assert caught.value.code == "credential_mismatch"


@pytest.mark.parametrize("provider", list(ProviderId))
async def test_api_keys_enable_no_reads(provider):
    def handler(_):
        pytest.fail("API key reached HTTP boundary")

    transport = Transport(http_transport=httpx.MockTransport(handler))
    with pytest.raises(TransportError) as caught:
        await transport.get_json(
            provider, "/api/oauth/usage", credential=source(provider, CredentialKind.API_KEY)
        )
    assert caught.value.code == "credential_mismatch"


async def test_codex_manual_bearer_cannot_enable_a_request():
    def handler(_):
        pytest.fail("Non-file Codex credential reached HTTP boundary")

    transport = Transport(http_transport=httpx.MockTransport(handler))
    with pytest.raises(TransportError) as caught:
        await transport.get_json(
            ProviderId.CODEX_SUBSCRIPTION,
            "/backend-api/wham/usage",
            credential=source(ProviderId.CODEX_SUBSCRIPTION),
        )
    assert caught.value.code == "credential_mismatch"


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
async def test_redirects_cannot_exfiltrate_credentials(status):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(
            status, headers={"Location": f"https://attacker.invalid/?key={SECRET}"}
        )

    transport = Transport(http_transport=httpx.MockTransport(handler))
    with pytest.raises(TransportError) as caught:
        await transport.get_json(
            ProviderId.CLAUDE_SUBSCRIPTION, "/api/oauth/usage", credential=source()
        )
    assert len(seen) == 1
    assert seen[0].url.host == "api.anthropic.com"
    assert caught.value.status == status
    assert SECRET not in "".join(traceback.format_exception(caught.value))


async def test_cookies_never_persist_between_calls_or_accounts():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={}, headers={"Set-Cookie": "server-secret=hidden; Path=/"})

    transport = Transport(http_transport=httpx.MockTransport(handler))
    for _ in range(2):
        await transport.get_json(
            ProviderId.CLAUDE_SUBSCRIPTION, "/api/oauth/usage", credential=source()
        )
    await transport.get_json(
        ProviderId.CLAUDE_PLATFORM,
        "/api/organizations",
        credential=source(ProviderId.CLAUDE_PLATFORM, CredentialKind.CONSOLE_SESSION),
    )
    assert "cookie" not in seen[0].headers
    assert "cookie" not in seen[1].headers
    assert seen[2].headers["cookie"] == f"sessionKey={SECRET}"


async def test_client_disables_environment_redirects_and_verification_overrides(monkeypatch):
    actual_client = httpx.AsyncClient
    options = []

    def client_factory(**kwargs):
        options.append(kwargs)
        return actual_client(**kwargs)

    def forbidden_netrc(*args, **kwargs):
        pytest.fail("Transport consulted netrc")

    monkeypatch.setenv("HTTPS_PROXY", "http://attacker.invalid:8888")
    monkeypatch.setenv("ALL_PROXY", "http://attacker.invalid:8888")
    monkeypatch.setenv("SSL_CERT_FILE", "/nonexistent/synthetic-ca")
    monkeypatch.setenv("NETRC", "/nonexistent/synthetic-netrc")
    monkeypatch.setattr(netrc, "netrc", forbidden_netrc)
    monkeypatch.setattr(httpx, "AsyncClient", client_factory)
    transport = Transport(
        http_transport=httpx.MockTransport(lambda _: httpx.Response(200, json={}))
    )
    await transport.get_json(
        ProviderId.CLAUDE_SUBSCRIPTION, "/api/oauth/usage", credential=source()
    )
    assert options[0]["trust_env"] is False
    assert options[0]["follow_redirects"] is False
    assert options[0]["verify"] is True
    assert "auth" not in options[0]
    assert "cookies" not in options[0]


@pytest.mark.parametrize("failure_type", [httpx.ConnectError, httpx.ReadError, ValueError])
async def test_raw_exception_body_and_request_never_escape(failure_type, caplog):
    def handler(request):
        raise failure_type(f"{SECRET} https://attacker.invalid/?token={SECRET}")

    transport = Transport(http_transport=httpx.MockTransport(handler))
    with pytest.raises(TransportError) as caught:
        await transport.get_json(
            ProviderId.CLAUDE_SUBSCRIPTION, "/api/oauth/usage", credential=source()
        )
    error = caught.value
    assert error.fetch_state == FetchState.NETWORK_ERROR
    assert str(error) == Diagnostic("network_error").message
    assert error.__context__ is None
    assert error.__cause__ is None
    assert SECRET not in repr(error)
    assert SECRET not in "".join(traceback.format_exception(error))
    assert SECRET not in caplog.text
    assert set(vars(error)) == {"fetch_state", "code", "status", "retry_at"}


@pytest.mark.parametrize("status", [200, 401, 403, 429, 500])
async def test_upstream_body_never_enters_error(status, caplog):
    transport = Transport(
        http_transport=httpx.MockTransport(
            lambda _: httpx.Response(status, text=f"invalid {SECRET}")
        )
    )
    with pytest.raises(TransportError) as caught:
        await transport.get_json(
            ProviderId.CLAUDE_SUBSCRIPTION, "/api/oauth/usage", credential=source()
        )
    assert SECRET not in "".join(traceback.format_exception(caught.value))
    assert SECRET not in caplog.text
    assert caught.value.__context__ is None


@pytest.mark.parametrize(
    "value", ["has;extra=cookie", "has,comma", 'has"quote', "has\\slash", "has space"]
)
async def test_invalid_cookie_octets_are_rejected_before_http(value):
    def handler(_):
        pytest.fail("Invalid cookie reached HTTP boundary")

    credential = ResolvedCredential(
        ProviderId.CLAUDE_PLATFORM, CredentialKind.CONSOLE_SESSION, value, "synthetic-generation"
    )
    transport = Transport(http_transport=httpx.MockTransport(handler))
    with pytest.raises(TransportError) as caught:
        await transport.get_json(
            ProviderId.CLAUDE_PLATFORM, "/api/organizations", credential=credential
        )
    assert caught.value.code == "credential_mismatch"


async def test_non_ascii_bearer_fails_safely_before_header_encoding():
    def handler(_):
        pytest.fail("Invalid bearer reached HTTP boundary")

    credential = ResolvedCredential(
        ProviderId.CLAUDE_SUBSCRIPTION, CredentialKind.MANUAL_BEARER, "synthetic-é", "generation-1"
    )
    transport = Transport(http_transport=httpx.MockTransport(handler))
    with pytest.raises(TransportError) as caught:
        await transport.get_json(
            ProviderId.CLAUDE_SUBSCRIPTION, "/api/oauth/usage", credential=credential
        )
    assert caught.value.code == "credential_mismatch"


async def test_compression_is_refused_before_unbounded_decoder_expansion():
    compressed = gzip.compress(b" " * (MAX_RESPONSE_BYTES + 1))

    class Compressed(httpx.AsyncByteStream):
        read = False
        closed = False

        async def __aiter__(self):
            self.read = True
            yield compressed

        async def aclose(self):
            self.closed = True

    stream = Compressed()

    def handler(request):
        assert request.headers["accept-encoding"] == "identity"
        return httpx.Response(200, stream=stream, headers={"Content-Encoding": "gzip"})

    transport = Transport(http_transport=httpx.MockTransport(handler))
    with pytest.raises(TransportError) as caught:
        await transport.get_json(
            ProviderId.CLAUDE_SUBSCRIPTION, "/api/oauth/usage", credential=source()
        )
    assert caught.value.code == "schema_error"
    assert not stream.read
    assert stream.closed


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("secret", "synthetic\r\nX-Injected: yes"),
        ("secret", "synthetic\x00secret"),
        ("secret", "synthetic\tsecret"),
        ("user_id", "synthetic\r\nX-Injected: yes"),
    ],
)
async def test_header_controls_are_rejected_independently_of_resolver(field, value):
    def handler(_):
        pytest.fail("Unsafe header reached HTTP boundary")

    credential = source(ProviderId.GROK_SUBSCRIPTION)
    # Simulate an invalid result from an injected resolver, bypassing the domain
    # constructor to exercise the transport's own final header defense.
    object.__setattr__(credential, field, value)
    transport = Transport(http_transport=httpx.MockTransport(handler))
    with pytest.raises(TransportError) as caught:
        await transport.get_json(
            ProviderId.GROK_SUBSCRIPTION, "/v1/billing?format=credits", credential=credential
        )
    assert caught.value.code == "credential_mismatch"


async def test_unsupported_kind_is_independently_rejected_before_http():
    def handler(_):
        pytest.fail("Unsupported credential kind reached HTTP boundary")

    credential = source()
    object.__setattr__(credential, "credential_kind", CredentialKind.CONSOLE_SESSION)
    transport = Transport(http_transport=httpx.MockTransport(handler))
    with pytest.raises(TransportError) as caught:
        await transport.get_json(
            ProviderId.CLAUDE_SUBSCRIPTION, "/api/oauth/usage", credential=credential
        )
    assert caught.value.code == "credential_mismatch"


@pytest.mark.parametrize(
    "path",
    [
        "https://attacker.invalid/backend-api/wham/usage",
        "https://chatgpt.com/backend-api/wham/usage",
        "http://chatgpt.com/backend-api/wham/usage",
        "//chatgpt.com/backend-api/wham/usage",
        "/backend-api/wham/usage?account=synthetic-selected-account",
        "/backend-api/wham/usage#fragment",
        "/backend-api/wham/usage/",
        "/backend-api/wham/../wham/usage",
        "/backend-api/%77ham/usage",
        "/backend-api/wham/usage\r\nX-Evil: yes",
        "/backend-api/wham/usage\\@attacker.invalid",
        "/backend-api/conversations",
        "/auth/refresh",
        "",
    ],
)
async def test_codex_fixed_route_refuses_alternatives_before_http(path):
    def handler(_):
        pytest.fail("Forbidden Codex request reached HTTP boundary")

    transport = Transport(http_transport=httpx.MockTransport(handler))
    with pytest.raises(TransportError) as caught:
        await transport.get_json(
            ProviderId.CODEX_SUBSCRIPTION,
            path,
            credential=source(ProviderId.CODEX_SUBSCRIPTION, CredentialKind.CODEX_AUTH_FILE),
        )
    assert caught.value.code == "forbidden_request"
    assert SECRET not in str(caught.value)
    assert "synthetic-selected-account" not in repr(caught.value)


@pytest.mark.parametrize(
    "value", [None, "", "has space", "has\tcontrol", "has\r\nheader", "非ASCII", "x" * 257]
)
async def test_codex_selected_account_header_revalidated_before_http(value):
    def handler(_):
        pytest.fail("Unsafe Codex account header reached HTTP boundary")

    credential = source(ProviderId.CODEX_SUBSCRIPTION, CredentialKind.CODEX_AUTH_FILE)
    object.__setattr__(credential, "codex_account_id", value)
    transport = Transport(http_transport=httpx.MockTransport(handler))
    with pytest.raises(TransportError) as caught:
        await transport.get_json(
            ProviderId.CODEX_SUBSCRIPTION, "/backend-api/wham/usage", credential=credential
        )
    assert caught.value.code == "credential_mismatch"
    assert SECRET not in "".join(traceback.format_exception(caught.value))


@pytest.mark.parametrize("status", [200, 401, 403, 429, 500])
async def test_codex_body_and_identity_never_enter_diagnostics(status, caplog):
    identity = "synthetic-selected-account"
    transport = Transport(
        http_transport=httpx.MockTransport(
            lambda _: httpx.Response(status, content=f"{SECRET} {identity}".encode())
        )
    )
    with pytest.raises(TransportError) as caught:
        await transport.get_json(
            ProviderId.CODEX_SUBSCRIPTION,
            "/backend-api/wham/usage",
            credential=source(ProviderId.CODEX_SUBSCRIPTION, CredentialKind.CODEX_AUTH_FILE),
        )
    rendered = "".join(traceback.format_exception(caught.value)) + caplog.text
    assert SECRET not in rendered
    assert identity not in rendered
    assert caught.value.__cause__ is caught.value.__context__ is None
