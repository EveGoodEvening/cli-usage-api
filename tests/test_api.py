"""Read-only HTTP API contracts: authentication, limiting, CORS, headers and payloads."""

from __future__ import annotations

import asyncio
import json
import os
import stat
import uuid
from datetime import UTC, datetime

import httpx
import pytest

from cli_usage_api import api, storage
from cli_usage_api.credentials import CredentialResolver
from cli_usage_api.domain import (
    Account,
    CredentialKind,
    FetchState,
    Metric,
    MetricId,
    MetricState,
    ProviderId,
    QuotaValue,
    Snapshot,
    SourceKind,
    SourceRef,
)
from cli_usage_api.operations import AccountOperations
from cli_usage_api.providers.console import OrganizationChoice
from cli_usage_api.storage import (
    AccountStore,
    ApiTokenStore,
    ConfigError,
    CredentialStore,
    api_token_digest,
)

SECURITY_HEADERS = {
    "cache-control": "no-store",
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "x-frame-options": "DENY",
    "content-security-policy": "default-src 'none'; frame-ancestors 'none'",
}
ORIGIN = "https://usage.example.com"
CLAUDE_ID = "11111111-1111-4111-8111-111111111111"
PLATFORM_ID = "22222222-2222-4222-8222-222222222222"
DISABLED_ID = "33333333-3333-4333-8333-333333333333"
SECRET_REF = "keyring:22222222-2222-4222-8222-222222222222:44444444-4444-4444-8444-444444444444"
NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)


class FakeClock:
    def __init__(self) -> None:
        self.value = 1000.0

    def __call__(self) -> float:
        return self.value


@pytest.fixture
def config_dir(tmp_path):
    directory = tmp_path / "config"
    directory.mkdir(mode=0o700)
    return directory


@pytest.fixture
def token_store(config_dir):
    return ApiTokenStore(config_dir / "api_tokens.json")


@pytest.fixture
def token(token_store):
    value, _ = token_store.create("test")
    return value


def live_accounts():
    return (
        Account(
            id=CLAUDE_ID,
            provider=ProviderId.CLAUDE_SUBSCRIPTION,
            label="Claude main",
            credential_kind=CredentialKind.CLAUDE_CODE_FILE,
            credential_ref="/home/someone/.claude/.credentials.json",
            poll_interval_seconds=60,
        ),
        Account(
            id=PLATFORM_ID,
            provider=ProviderId.CLAUDE_PLATFORM,
            label="Console",
            credential_kind=CredentialKind.CONSOLE_SESSION,
            credential_ref=SECRET_REF,
            organization_id="org-secretish-123",
        ),
        Account(
            id=DISABLED_ID,
            provider=ProviderId.GROK_SUBSCRIPTION,
            label="Grok off",
            credential_kind=CredentialKind.GROK_AUTH_FILE,
            credential_ref="default",
            credential_selector="https://auth.x.ai::selector-value",
            enabled=False,
        ),
    )


class StaticSource:
    def __init__(self, publish, snapshots):
        self.publish = publish
        self.snapshots = snapshots
        self.started = False
        self.stopped = False

    async def start(self):
        self.started = True
        for snapshot in self.snapshots:
            self.publish(snapshot)

    async def stop(self):
        self.stopped = True


def snapshot(account_id, **kwargs):
    metric = Metric(
        id=MetricId.CLAUDE_FIVE_HOUR,
        label="Claude 5h",
        state=MetricState.READY,
        source=SourceRef(SourceKind.OFFLINE_DEMO, "test"),
        quota=QuotaValue(used_percent="12.5"),
    )
    values = {
        "account_id": account_id,
        "metrics": (metric,),
        "grants": (),
        "fetch_state": FetchState.OK,
        "attempted_at": NOW,
        "fetched_at": NOW,
    }
    values.update(kwargs)
    return Snapshot(**values)


def static_hub(snapshots=()):
    holder = {}

    def factory(publish):
        holder["source"] = StaticSource(publish, snapshots)
        return holder["source"]

    hub = api.SnapshotHub(
        mode="live", accounts=live_accounts(), source_factory=factory, now=lambda: NOW
    )
    return hub, holder


def client_for(app, peer="203.0.113.7"):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=(peer, 50000)), base_url="http://api.test"
    )


def auth(value):
    return {"Authorization": f"Bearer {value}"}


class Lifespan:
    """Drive the ASGI lifespan protocol directly, as uvicorn does."""

    def __init__(self, app):
        self.app = app
        self.inbox = asyncio.Queue()
        self.outbox = asyncio.Queue()
        self.task = None

    async def _send(self, message):
        await self.outbox.put(message)

    async def startup(self):
        self.task = asyncio.create_task(self.app({"type": "lifespan"}, self.inbox.get, self._send))
        await self.inbox.put({"type": "lifespan.startup"})
        return (await asyncio.wait_for(self.outbox.get(), 5))["type"]

    async def shutdown(self):
        await self.inbox.put({"type": "lifespan.shutdown"})
        message = await asyncio.wait_for(self.outbox.get(), 5)
        await asyncio.wait_for(self.task, 5)
        return message["type"]


def assert_security(response):
    for key, value in SECURITY_HEADERS.items():
        assert response.headers[key] == value
    assert "access-control-allow-credentials" not in response.headers
    assert response.headers.get("access-control-allow-origin") != "*"


async def test_healthz_is_the_only_public_path(token_store, token):
    hub, _ = static_hub()
    app = api.create_app(hub, token_store)
    async with client_for(app) as client:
        response = await client.get("/healthz")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        assert_security(response)
        for path in (
            "/api/v1/session",
            "/api/v1/dashboard",
            f"/api/v1/accounts/{CLAUDE_ID}",
            "/api/v1/unknown",
            "/api/v2/anything",
            "/",
            "/other",
        ):
            response = await client.get(path)
            assert response.status_code == 401, path
            assert response.json() == {"error": "unauthorized"}
            assert response.headers["www-authenticate"] == "Bearer"
            assert_security(response)


async def test_valid_token_reads_and_unknown_paths_404_after_auth(token_store, token):
    hub, holder = static_hub()
    app = api.create_app(hub, token_store)
    await hub.start()
    async with client_for(app) as client:
        session = await client.get("/api/v1/session", headers=auth(token))
        assert session.status_code == 200
        assert session.json() == {
            "mode": "live",
            "version": api.package_version(),
            "server_time": "2026-10-28T12:00:00Z",
            "auth": "token",
            # Read-only app (no operations): never writable.
            "capabilities": {"writable": False, "secure_store_available": False},
        }
        assert_security(session)
        assert session.headers["content-type"] == "application/json; charset=utf-8"
        missing = await client.get("/api/v1/nope", headers=auth(token))
        assert missing.status_code == 404
        assert missing.json() == {"error": "not_found"}
        assert_security(missing)
        unknown_account = await client.get(
            "/api/v1/accounts/99999999-9999-4999-8999-999999999999", headers=auth(token)
        )
        assert unknown_account.status_code == 404
        trailing = await client.get("/api/v1/session/", headers=auth(token))
        assert trailing.status_code == 404
    await hub.stop()
    assert holder["source"].stopped


@pytest.mark.parametrize(
    "header",
    [
        None,
        "Bearer",
        "Bearer ",
        "Basic dXNlcjpwYXNz",
        "Bearer usk_wrong",
        "Token usk_x",
    ],
)
async def test_bad_or_missing_credentials_are_unauthorized(token_store, token, header):
    hub, _ = static_hub()
    app = api.create_app(hub, token_store)
    headers = {} if header is None else {"Authorization": header}
    async with client_for(app) as client:
        response = await client.get("/api/v1/dashboard", headers=headers)
    assert response.status_code == 401
    assert response.json() == {"error": "unauthorized"}
    assert "usk_" not in response.text


async def test_query_string_and_cookie_tokens_are_not_accepted(token_store, token):
    hub, _ = static_hub()
    app = api.create_app(hub, token_store)
    async with client_for(app) as client:
        query = await client.get("/api/v1/session", params={"token": token})
        cookie = await client.get("/api/v1/session", headers={"Cookie": f"token={token}"})
        lower = await client.get("/api/v1/session", headers={"authorization": f"bearer {token}"})
    assert query.status_code == 401
    assert cookie.status_code == 401
    assert lower.status_code == 200
    assert token not in query.text


async def test_duplicate_authorization_headers_are_rejected(token_store, token):
    hub, _ = static_hub()
    app = api.create_app(hub, token_store)
    async with client_for(app) as client:
        response = await client.get(
            "/api/v1/session",
            headers=[("Authorization", f"Bearer {token}"), ("Authorization", f"Bearer {token}")],
        )
    assert response.status_code == 401


def test_verifier_compares_every_digest_constant_time(token_store, monkeypatch):
    tokens = [token_store.create(f"t{index}")[0] for index in range(3)]
    verifier = api.TokenVerifier(token_store)
    calls = []
    real = api.hmac.compare_digest

    def spy(left, right):
        calls.append((left, right))
        return real(left, right)

    monkeypatch.setattr(api.hmac, "compare_digest", spy)
    assert verifier.verify(tokens[0])
    # No early exit on the first match: every stored digest is compared.
    assert len(calls) == 3
    calls.clear()
    assert not verifier.verify("usk_not-a-token")
    assert len(calls) == 3
    assert all(isinstance(left, bytes) and len(left) == 32 for left, _ in calls)


def test_verifier_requires_token_shape_even_if_digest_matches(token_store, config_dir):
    # A digest of a malformed value written by hand is never accepted.
    path = config_dir / "api_tokens.json"
    record = {
        "id": "a" * 32,
        "label": "weird",
        "sha256": api_token_digest("not a usk token"),
        "created_at": "2026-10-28T12:00:00Z",
    }
    fd = os.open(path, os.O_WRONLY | os.O_CREAT, 0o600)
    os.write(fd, json.dumps({"schema_version": 1, "tokens": [record]}).encode())
    os.close(fd)
    verifier = api.TokenVerifier(token_store)
    assert verifier.count == 1
    assert not verifier.verify("not a usk token")


async def test_failed_auth_limit_per_client_with_retry_after(token_store, token):
    clock = FakeClock()
    hub, _ = static_hub()
    app = api.create_app(hub, token_store, monotonic=clock)
    async with client_for(app) as client:
        for _ in range(10):
            assert (await client.get("/api/v1/session", headers=auth("usk_bad"))).status_code == 401
            clock.value += 1
        limited = await client.get("/api/v1/session", headers=auth("usk_bad"))
        assert limited.status_code == 429
        assert limited.json() == {"error": "rate_limited"}
        assert limited.headers["retry-after"] == "50"
        assert_security(limited)
        assert (await client.get("/api/v1/session")).status_code == 429
        # A valid token from the limited client still passes; it never touches the limiter.
        assert (await client.get("/api/v1/session", headers=auth(token))).status_code == 200
        # Health checks are never limited.
        assert (await client.get("/healthz")).status_code == 200
        clock.value += 50
        # First failure (t=1000) left the window; one slot opens.
        assert (await client.get("/api/v1/session", headers=auth("usk_bad"))).status_code == 401
        assert (await client.get("/api/v1/session", headers=auth("usk_bad"))).status_code == 429
    async with client_for(app, peer="198.51.100.9") as other:
        assert (await other.get("/api/v1/session", headers=auth("usk_bad"))).status_code == 401


async def test_global_failure_cap(token_store, token):
    clock = FakeClock()
    hub, _ = static_hub()
    app = api.create_app(hub, token_store, monotonic=clock)
    for index in range(100):
        async with client_for(app, peer=f"10.0.{index // 250}.{index % 250}") as client:
            assert (await client.get("/api/v1/session")).status_code == 401
    async with client_for(app, peer="192.0.2.200") as fresh:
        response = await fresh.get("/api/v1/session", headers=auth("usk_bad"))
        assert response.status_code == 429
        assert int(response.headers["retry-after"]) == 60
        # Saturating the global limit never locks out a valid token, from any client.
        assert (await fresh.get("/api/v1/session", headers=auth(token))).status_code == 200
        clock.value += 60
        assert (await fresh.get("/api/v1/session", headers=auth("usk_bad"))).status_code == 401
    async with client_for(app, peer="10.0.0.0") as attacker:
        assert (await attacker.get("/api/v1/session", headers=auth(token))).status_code == 200


async def test_valid_tokens_do_not_consume_failure_budget(token_store, token):
    clock = FakeClock()
    hub, _ = static_hub()
    limiter = api.FailureLimiter(monotonic=clock)
    app = api.create_app(hub, token_store, limiter=limiter, monotonic=clock)
    async with client_for(app) as client:
        for _ in range(150):
            assert (await client.get("/api/v1/session", headers=auth(token))).status_code == 200
    assert limiter.tracked_clients == 0
    assert limiter.retry_after("203.0.113.7") is None


def test_limiter_bounds_tracked_clients():
    clock = FakeClock()
    limiter = api.FailureLimiter(monotonic=clock, global_limit=10**9, max_clients=5)
    for index in range(20):
        limiter.record(f"client-{index}")
    assert limiter.tracked_clients == 5
    assert limiter.retry_after("client-0") is None
    for _ in range(10):
        limiter.record("client-19")
    assert limiter.retry_after("client-19") == 60
    clock.value += 61
    assert limiter.retry_after("client-19") is None


async def test_trust_proxy_uses_rightmost_forwarded_entry(token_store, token):
    clock = FakeClock()
    hub, _ = static_hub()
    app = api.create_app(hub, token_store, trust_proxy=True, monotonic=clock)
    async with client_for(app, peer="10.0.0.1") as client:
        for index in range(10):
            # Spoofed left-most values vary; the proxy-appended right-most stays constant.
            headers = {"X-Forwarded-For": f"1.1.1.{index}, 203.0.113.50"}
            assert (await client.get("/api/v1/session", headers=headers)).status_code == 401
        blocked = await client.get(
            "/api/v1/session",
            headers={**auth("usk_bad"), "X-Forwarded-For": "9.9.9.9, 203.0.113.50"},
        )
        assert blocked.status_code == 429
        other = await client.get(
            "/api/v1/session",
            headers={**auth("usk_bad"), "X-Forwarded-For": "203.0.113.50, 203.0.113.51"},
        )
        assert other.status_code == 401


async def test_without_trust_proxy_forwarded_header_is_ignored(token_store, token):
    hub, _ = static_hub()
    app = api.create_app(hub, token_store)
    async with client_for(app, peer="10.0.0.1") as client:
        for index in range(10):
            headers = {"X-Forwarded-For": f"203.0.113.{index}"}
            assert (await client.get("/api/v1/session", headers=headers)).status_code == 401
        response = await client.get(
            "/api/v1/session", headers={**auth("usk_bad"), "X-Forwarded-For": "198.51.100.1"}
        )
        assert response.status_code == 429


def test_client_key_falls_back_on_invalid_forwarded_value():
    headers = api.Headers(raw=[(b"x-forwarded-for", b"1.2.3.4, not-an-ip")])
    assert api._client_key({"client": ("10.0.0.2", 1)}, headers, True) == "10.0.0.2"
    headers = api.Headers(raw=[(b"x-forwarded-for", b"1.2.3.4"), (b"x-forwarded-for", b"5.6.7.8")])
    assert api._client_key({"client": ("10.0.0.2", 1)}, headers, True) == "5.6.7.8"


async def test_cors_allowed_denied_and_preflight(token_store, token):
    hub, _ = static_hub()
    app = api.create_app(hub, token_store, [ORIGIN, "HTTP://LOCALHOST:5173"])
    async with client_for(app) as client:
        preflight = await client.options(
            "/api/v1/dashboard",
            headers={
                "Origin": ORIGIN,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )
        assert preflight.status_code == 204
        assert preflight.content == b""
        assert preflight.headers["access-control-allow-origin"] == ORIGIN
        assert (
            preflight.headers["access-control-allow-headers"]
            == "Authorization, Content-Type, If-Match"
        )
        # The full set even read-only, so browsers see a readable 403 read_only.
        assert (
            preflight.headers["access-control-allow-methods"]
            == "GET, HEAD, OPTIONS, POST, PUT, PATCH, DELETE"
        )
        assert preflight.headers["access-control-max-age"] == "600"
        assert preflight.headers["vary"] == "Origin"
        assert_security(preflight)
        local = await client.options(
            "/api/v1/dashboard",
            headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
        )
        assert local.headers["access-control-allow-origin"] == "http://localhost:5173"
        denied = await client.options(
            "/api/v1/dashboard",
            headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
        )
        assert denied.status_code == 403
        assert denied.json() == {"error": "forbidden_origin"}
        assert "access-control-allow-origin" not in denied.headers
        assert_security(denied)
        allowed = await client.get("/api/v1/session", headers={**auth(token), "Origin": ORIGIN})
        assert allowed.headers["access-control-allow-origin"] == ORIGIN
        assert allowed.headers["access-control-expose-headers"] == "Retry-After, WWW-Authenticate"
        assert allowed.headers["vary"] == "Origin"
        other = await client.get(
            "/api/v1/session", headers={**auth(token), "Origin": "https://evil.example"}
        )
        assert other.status_code == 200
        assert "access-control-allow-origin" not in other.headers
        assert "access-control-expose-headers" not in other.headers
        # Errors still carry CORS so the browser can surface 401 to the frontend.
        unauthorized = await client.get("/api/v1/session", headers={"Origin": ORIGIN})
        assert unauthorized.status_code == 401
        assert unauthorized.headers["access-control-allow-origin"] == ORIGIN
        assert unauthorized.headers["www-authenticate"] == "Bearer"
        assert "WWW-Authenticate" in unauthorized.headers["access-control-expose-headers"]
        lookalike = await client.options(
            "/api/v1/session",
            headers={"Origin": ORIGIN + ".evil.example", "Access-Control-Request-Method": "GET"},
        )
        assert lookalike.status_code == 403


async def test_cross_origin_rate_limit_exposes_retry_after(token_store, token):
    clock = FakeClock()
    hub, _ = static_hub()
    app = api.create_app(hub, token_store, [ORIGIN], monotonic=clock)
    async with client_for(app) as client:
        for _ in range(10):
            await client.get("/api/v1/session", headers={"Origin": ORIGIN})
        limited = await client.get("/api/v1/session", headers={"Origin": ORIGIN})
        denied = await client.get("/api/v1/session", headers={"Origin": "https://evil.example"})
    assert limited.status_code == 429
    assert limited.headers["access-control-allow-origin"] == ORIGIN
    exposed = {
        item.strip().casefold()
        for item in limited.headers["access-control-expose-headers"].split(",")
    }
    assert exposed == {"retry-after", "www-authenticate"}
    assert limited.headers["retry-after"] == "60"
    assert denied.status_code == 429
    assert "access-control-allow-origin" not in denied.headers
    assert "access-control-expose-headers" not in denied.headers


async def test_plain_options_without_origin(token_store):
    hub, _ = static_hub()
    app = api.create_app(hub, token_store)
    async with client_for(app) as client:
        response = await client.options("/api/v1/session")
    assert response.status_code == 204
    assert response.headers["allow"] == "GET, HEAD, OPTIONS, POST, PUT, PATCH, DELETE"
    assert_security(response)


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
async def test_wrong_method_on_read_route_is_405_with_route_allow(token_store, token, method):
    hub, _ = static_hub()
    app = api.create_app(hub, token_store)
    async with client_for(app) as client:
        response = await client.request(
            method, "/api/v1/dashboard", headers=auth(token), content=b'{"x":1}'
        )
    assert response.status_code == 405
    assert response.json() == {"error": "method_not_allowed"}
    assert response.headers["allow"] == "GET, HEAD, OPTIONS"
    assert_security(response)


@pytest.mark.parametrize("method", ["TRACE", "PROPFIND"])
async def test_unknown_methods_are_405_before_auth(token_store, method):
    hub, _ = static_hub()
    app = api.create_app(hub, token_store)
    async with client_for(app) as client:
        response = await client.request(method, "/api/v1/dashboard")
    assert response.status_code == 405
    assert response.headers["allow"] == "GET, HEAD, OPTIONS, POST, PUT, PATCH, DELETE"
    assert_security(response)


async def test_head_has_headers_without_body(token_store, token):
    hub, _ = static_hub()
    app = api.create_app(hub, token_store)
    await hub.start()
    async with client_for(app) as client:
        get = await client.get("/api/v1/dashboard", headers=auth(token))
        head = await client.head("/api/v1/dashboard", headers=auth(token))
    assert head.status_code == 200
    assert head.content == b""
    assert head.headers["content-length"] == get.headers["content-length"]
    assert_security(head)


async def test_long_paths_are_not_found(token_store, token):
    hub, _ = static_hub()
    app = api.create_app(hub, token_store)
    async with client_for(app) as client:
        response = await client.get("/api/v1/" + "a" * 600, headers=auth(token))
    assert response.status_code == 404
    assert "aaaa" not in response.text


async def test_dashboard_redacts_credentials_and_organization(token_store, token):
    snapshots = (
        snapshot(CLAUDE_ID, fetched_at=datetime(2026, 10, 28, 11, 59, tzinfo=UTC)),
        snapshot(PLATFORM_ID, organization_id="org-secretish-123", metrics=()),
        snapshot(DISABLED_ID),
    )
    hub, _ = static_hub(snapshots)
    app = api.create_app(hub, token_store)
    await hub.start()
    async with client_for(app) as client:
        response = await client.get("/api/v1/dashboard", headers=auth(token))
        single = await client.get(f"/api/v1/accounts/{PLATFORM_ID}", headers=auth(token))
    assert response.status_code == 200
    text = response.text + single.text
    for forbidden in (
        "credential_ref",
        "credential_selector",
        SECRET_REF,
        "/home/someone",
        "org-secretish-123",
        "selector-value",
    ):
        assert forbidden not in text
    data = response.json()
    assert data["mode"] == "live"
    assert data["server_time"] == "2026-10-28T12:00:00Z"
    assert [item["account"]["id"] for item in data["accounts"]] == [
        CLAUDE_ID,
        PLATFORM_ID,
        DISABLED_ID,
    ]
    first = data["accounts"][0]
    assert first["account"] == {
        "id": CLAUDE_ID,
        "provider": "claude_subscription",
        "label": "Claude main",
        "enabled": True,
        "credential_kind": "claude_code_file",
        "poll_interval_seconds": 180,
    }
    assert first["snapshot"]["metrics"][0]["quota"]["used_percent"] == "12.5"
    assert first["snapshot"]["organization_id"] is None
    assert first["freshness"] == {
        "age_seconds": 60.0,
        "attempted_age_seconds": 0.0,
        "stale": False,
        "reset_passed": False,
        "last_known": False,
    }
    platform = data["accounts"][1]
    assert set(platform["snapshot"]) == set(snapshots[1].to_dict())
    assert platform["snapshot"]["organization_id"] is None
    assert single.json() == platform
    disabled = data["accounts"][2]
    assert disabled["account"]["enabled"] is False
    assert disabled["snapshot"] is None
    assert disabled["freshness"] is None


async def test_account_without_snapshot_yet(token_store, token):
    hub, _ = static_hub()
    app = api.create_app(hub, token_store)
    await hub.start()
    async with client_for(app) as client:
        data = (await client.get(f"/api/v1/accounts/{CLAUDE_ID}", headers=auth(token))).json()
    assert data["snapshot"] is None
    assert data["freshness"] is None


async def test_internal_errors_are_curated(token_store, token):
    hub, _ = static_hub()

    def broken():
        raise RuntimeError("secret internal detail")

    hub._now = broken
    app = api.create_app(hub, token_store)
    async with client_for(app) as client:
        response = await client.get("/api/v1/session", headers=auth(token))
    assert response.status_code == 500
    assert response.json() == {"error": "internal_error"}
    assert "secret" not in response.text
    assert_security(response)


async def test_token_revocation_and_creation_reload_without_restart(token_store, token):
    clock = FakeClock()
    hub, _ = static_hub()
    app = api.create_app(hub, token_store, monotonic=clock)
    async with client_for(app) as client:
        assert (await client.get("/api/v1/session", headers=auth(token))).status_code == 200
        record = token_store.load()[0]
        assert token_store.revoke(record.id)
        # Reload checks at most once per second.
        assert (await client.get("/api/v1/session", headers=auth(token))).status_code == 200
        clock.value += 1
        assert (await client.get("/api/v1/session", headers=auth(token))).status_code == 401
        new, _ = token_store.create("second")
        clock.value += 1
        assert (await client.get("/api/v1/session", headers=auth(new))).status_code == 200


async def test_unreadable_token_file_fails_closed(token_store, token):
    clock = FakeClock()
    hub, _ = static_hub()
    app = api.create_app(hub, token_store, monotonic=clock)
    async with client_for(app) as client:
        assert (await client.get("/api/v1/session", headers=auth(token))).status_code == 200
        os.chmod(token_store.path, 0o644)
        clock.value += 1
        assert (await client.get("/api/v1/session", headers=auth(token))).status_code == 401
        os.chmod(token_store.path, 0o600)
        clock.value += 1
        assert (await client.get("/api/v1/session", headers=auth(token))).status_code == 200


def test_create_app_refuses_unauthenticated_live(token_store):
    hub, _ = static_hub()
    with pytest.raises(ValueError):
        api.create_app(hub, None)
    with pytest.raises(ValueError):
        api.create_app(hub, token_store, allow_unauthenticated=True)


async def test_unauthenticated_demo_requires_auth_once_a_token_exists(token_store):
    clock = FakeClock()
    app = api.create_app(
        api.demo_hub("healthy"), token_store, allow_unauthenticated=True, monotonic=clock
    )
    async with client_for(app, peer="127.0.0.1") as client:
        open_session = await client.get("/api/v1/session")
        assert open_session.status_code == 200
        assert open_session.json()["auth"] == "none"
        assert (await client.get("/api/v1/dashboard")).status_code == 200
        created, _ = token_store.create("later")
        clock.value += 1
        assert (await client.get("/api/v1/dashboard")).status_code == 401
        session = await client.get("/api/v1/session", headers=auth(created))
        assert session.status_code == 200
        assert session.json()["auth"] == "token"
        assert app.auth_mode == "token"
        # Revoking the last token reopens the explicitly allowed loopback demo.
        assert token_store.revoke(token_store.load()[0].id)
        clock.value += 1
        reopened = await client.get("/api/v1/session")
        assert reopened.status_code == 200
        assert reopened.json()["auth"] == "none"
        # An unreadable token file fails closed rather than counting as "no tokens".
        token_store.create("again")
        clock.value += 1
        os.chmod(token_store.path, 0o644)
        assert (await client.get("/api/v1/session")).status_code == 401
        os.chmod(token_store.path, 0o600)


async def test_demo_hub_constructs_no_live_dependencies(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("live dependency constructed")

    from cli_usage_api import cli, credentials, scheduler, storage, transport

    for module, name in (
        (storage, "AccountStore"),
        (storage, "CredentialStore"),
        (credentials, "CredentialResolver"),
        (transport, "Transport"),
        (scheduler, "Scheduler"),
        (cli, "LiveFactory"),
        (cli, "AccountStore"),
        (cli, "CredentialStore"),
    ):
        monkeypatch.setattr(module, name, forbidden)
    hub = api.demo_hub("errors")
    app = api.create_app(hub, None)
    lifespan = Lifespan(app)
    assert await lifespan.startup() == "lifespan.startup.complete"
    async with client_for(app, peer="127.0.0.1") as client:
        session = (await client.get("/api/v1/session")).json()
        assert session["mode"] == "demo"
        assert session["auth"] == "none"
        dashboard = (await client.get("/api/v1/dashboard")).json()
    assert await lifespan.shutdown() == "lifespan.shutdown.complete"
    assert dashboard["mode"] == "demo"
    assert any(item["snapshot"] is not None for item in dashboard["accounts"])
    for item in dashboard["accounts"]:
        if item["snapshot"] is not None:
            for metric in item["snapshot"]["metrics"]:
                assert metric["source"]["kind"] == "offline_demo"
            assert item["snapshot"]["organization_id"] is None
    assert hub.source is not None and hub._stopped


def test_demo_time_ticks_from_fixture_clock_only():
    ticks = [0.0]
    hub = api.demo_hub("healthy", monotonic=lambda: ticks[0])
    start = hub.now()
    assert start.isoformat().startswith("2026-10-28T12:00:00")
    ticks[0] = 5.0
    assert (hub.now() - start).total_seconds() == 5.0


async def test_lifespan_starts_and_stops_source(token_store, token):
    hub, holder = static_hub((snapshot(CLAUDE_ID),))
    app = api.create_app(hub, token_store)
    lifespan = Lifespan(app)
    assert await lifespan.startup() == "lifespan.startup.complete"
    assert holder["source"].started
    async with client_for(app) as client:
        data = (await client.get(f"/api/v1/accounts/{CLAUDE_ID}", headers=auth(token))).json()
    assert data["snapshot"]["account_id"] == CLAUDE_ID
    assert await lifespan.shutdown() == "lifespan.shutdown.complete"
    assert holder["source"].stopped


async def test_lifespan_startup_failure_is_curated(token_store):
    def factory(publish):
        raise RuntimeError("secret detail")

    hub = api.SnapshotHub(mode="live", accounts=(), source_factory=factory)
    app = api.create_app(hub, token_store)
    lifespan = Lifespan(app)
    task_result = await lifespan.startup()
    assert task_result == "lifespan.startup.failed"
    await asyncio.wait_for(lifespan.task, 5)
    assert app.startup_failed


def test_published_snapshot_for_unknown_account_is_ignored():
    hub, _ = static_hub()
    hub.publish(snapshot("99999999-9999-4999-8999-999999999999"))
    assert hub.snapshots == {}


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://App.Example.com", "https://app.example.com"),
        ("HTTPS://app.example.com:443", "https://app.example.com"),
        ("http://localhost:80", "http://localhost"),
        ("http://localhost:5173", "http://localhost:5173"),
        ("http://127.0.0.1:8080", "http://127.0.0.1:8080"),
        ("http://[::1]:5173", "http://[::1]:5173"),
        ("https://x.up.railway.app", "https://x.up.railway.app"),
    ],
)
def test_normalize_origin_accepts_exact_origins(value, expected):
    assert api.normalize_origin(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "*",
        "https://*.example.com",
        "null",
        "ftp://example.com",
        "https://example.com/",
        "https://example.com/path",
        "https://example.com?x=1",
        "https://example.com#frag",
        "https://user@example.com",
        "https://user:pw@example.com",
        "example.com",
        "https://",
        "https://exa mple.com",
        "https://example.com:0",
        "https://example.com:99999",
        "https://example.com:abc",
        "https://ex_ample.com",
        "",
    ],
)
def test_normalize_origin_rejects_non_origins(value):
    with pytest.raises(api.OriginError):
        api.normalize_origin(value)


@pytest.mark.parametrize(
    ("host", "loopback"),
    [
        ("127.0.0.1", True),
        ("::1", True),
        ("localhost", True),
        ("LOCALHOST", True),
        ("0.0.0.0", False),
        ("::", False),
        ("192.168.1.2", False),
        ("example.com", False),
    ],
)
def test_loopback_detection(host, loopback):
    assert api.is_loopback_host(host) is loopback


def test_token_store_private_file_and_schema(token_store, config_dir):
    token, record = token_store.create("  my\x1b[31m laptop  ")
    assert token.startswith("usk_") and len(token) >= 40
    mode = stat.S_IMODE(os.stat(token_store.path).st_mode)
    assert mode == 0o600
    assert stat.S_IMODE(os.stat(config_dir).st_mode) == 0o700
    content = token_store.path.read_text()
    assert token not in content
    assert record.sha256 == api_token_digest(token)
    data = json.loads(content)
    assert set(data) == {"schema_version", "tokens"}
    assert set(data["tokens"][0]) == {"id", "label", "sha256", "created_at"}
    assert record.label == "my laptop"
    assert token_store.create(None)[1].label == "token"
    assert len({item.id for item in token_store.load()}) == 2


def test_token_store_rejects_insecure_or_invalid_files(token_store, config_dir):
    token_store.create("a")
    os.chmod(token_store.path, 0o644)
    with pytest.raises(ConfigError):
        token_store.load()
    os.chmod(token_store.path, 0o600)
    token_store.path.write_text('{"schema_version": 1, "tokens": [{"id": "x"}]}')
    with pytest.raises(ConfigError):
        token_store.load()
    token_store.path.write_text('{"schema_version": 1, "tokens": [], "tokens": []}')
    with pytest.raises(ConfigError):
        token_store.load()


def test_token_store_revoke_and_signature(token_store):
    assert token_store.signature() is None
    assert token_store.load() == ()
    _, first = token_store.create("a")
    signature = token_store.signature()
    assert signature is not None
    assert not token_store.revoke("0" * 32)
    assert token_store.revoke(first.id)
    assert token_store.load() == ()
    assert token_store.signature() != signature


# --- account management over HTTP ------------------------------------------------------

BEARER = "synthetic-bearer-never-echo"
ALL_METHODS = "GET, HEAD, OPTIONS, POST, PUT, PATCH, DELETE"


@pytest.fixture
def no_keyring(monkeypatch):
    calls = []

    def unavailable():
        calls.append("get_keyring")
        raise RuntimeError("no real keyring in tests")

    monkeypatch.setattr(storage.keyring, "get_keyring", unavailable)
    return calls


class RecordingSource(StaticSource):
    def __init__(self, publish, snapshots):
        super().__init__(publish, snapshots)
        self.updates = []
        self.refreshes = []

    async def update_accounts(self, accounts, **kwargs):
        self.updates.append((tuple(accounts), kwargs.get("invalidate")))

    async def refresh(self, account_id=None):
        self.refreshes.append(account_id)


class Writable:
    """A live standalone hub with AccountOperations over a private temp config."""

    def __init__(self, tmp_path, token_store, accounts=(), snapshots=(), origins=()):
        directory = tmp_path / "accounts"
        directory.mkdir(mode=0o700)
        self.store = AccountStore(directory / "accounts.json")
        if accounts:
            self.store.save(tuple(accounts))
        self.holder = {}

        def factory(publish):
            self.holder["source"] = RecordingSource(publish, snapshots)
            return self.holder["source"]

        self.hub = api.SnapshotHub(
            mode="live", accounts=self.store.load(), source_factory=factory, now=lambda: NOW
        )
        self.credentials = CredentialStore()
        self.ops = AccountOperations(
            host=self.hub,
            account_store=self.store,
            credential_store=self.credentials,
            resolver=CredentialResolver(self.credentials),
            console_discovery=None,
        )
        self.app = api.create_app(self.hub, token_store, origins, operations=self.ops)


def plain(label, **kwargs):
    return Account(
        id=str(uuid.uuid4()), provider=ProviderId.GROK_SUBSCRIPTION, label=label, **kwargs
    )


async def raw_call(app, method, path, headers=(), chunks=(b"",), *, receive_fails=False):
    """Drive the ASGI app directly to control streamed bodies and receive()."""
    messages = [
        {"type": "http.request", "body": chunk, "more_body": index < len(chunks) - 1}
        for index, chunk in enumerate(chunks)
    ]
    sent = []

    async def receive():
        if receive_fails:
            raise AssertionError("request body must not be read")
        if messages:
            return messages.pop(0)
        await asyncio.sleep(3600)
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [(key.lower().encode(), value.encode()) for key, value in headers],
        "client": ("203.0.113.7", 50000),
    }
    await app(scope, receive, send)
    if not sent:
        return None, None, {}
    response_headers = {key.decode(): value.decode() for key, value in sent[0]["headers"]}
    body = sent[1]["body"]
    return sent[0]["status"], (json.loads(body) if body else None), response_headers


def json_headers(token, *extra):
    return (("authorization", f"Bearer {token}"), ("content-type", "application/json"), *extra)


async def test_writes_are_forbidden_without_reading_the_body(tmp_path, token_store, token):
    hub, _ = static_hub()
    read_only = api.create_app(hub, token_store)
    demo = api.create_app(api.demo_hub(), None)
    for app, headers in ((read_only, json_headers(token)), (demo, (("content-type", "x"),))):
        for method, path in (
            ("POST", "/api/v1/accounts"),
            ("PUT", "/api/v1/accounts/order"),
            ("PATCH", f"/api/v1/accounts/{CLAUDE_ID}"),
            ("DELETE", f"/api/v1/accounts/{CLAUDE_ID}"),
            ("POST", f"/api/v1/accounts/{CLAUDE_ID}/reconnect"),
            ("POST", "/api/v1/accounts/prepare"),
        ):
            status, body, _ = await raw_call(app, method, path, headers, receive_fails=True)
            assert (status, body) == (403, {"error": "read_only"})


def test_operations_with_demo_hub_are_refused(tmp_path, token_store, no_keyring):
    writable = Writable(tmp_path, token_store)
    with pytest.raises(ValueError):
        api.create_app(api.demo_hub(), None, operations=writable.ops)


async def test_unauthenticated_writes_are_401_and_valid_tokens_skip_the_limiter(
    tmp_path, token_store, token, no_keyring
):
    writable = Writable(tmp_path, token_store)
    status, _, headers = await raw_call(
        writable.app,
        "POST",
        "/api/v1/accounts",
        (("content-type", "application/json"),),
        receive_fails=True,
    )
    assert status == 401 and headers["www-authenticate"] == "Bearer"

    class Forbidden:
        def retry_after(self, key):
            pytest.fail("valid token consulted the limiter")

        record = retry_after

    writable.app.limiter = Forbidden()
    status, body, _ = await raw_call(
        writable.app,
        "POST",
        "/api/v1/accounts",
        json_headers(token),
        (json.dumps({"provider": "grok_subscription", "label": "x", "source": None}).encode(),),
    )
    assert status == 201 and body["account"]["label"] == "x"


async def test_per_route_405_allow(token_store, token):
    hub, _ = static_hub()
    app = api.create_app(hub, token_store)
    cases = [
        ("PUT", "/api/v1/accounts", "GET, HEAD, POST, OPTIONS"),
        ("DELETE", "/api/v1/accounts/prepare", "POST, OPTIONS"),
        ("POST", "/api/v1/accounts/order", "PUT, OPTIONS"),
        ("POST", f"/api/v1/accounts/{CLAUDE_ID}", "GET, HEAD, PATCH, DELETE, OPTIONS"),
        ("GET", f"/api/v1/accounts/{CLAUDE_ID}/reconnect", "POST, OPTIONS"),
        ("POST", "/api/v1/session", "GET, HEAD, OPTIONS"),
        ("POST", "/healthz", "GET, HEAD, OPTIONS"),
    ]
    for method, path, allow in cases:
        status, body, headers = await raw_call(app, method, path, json_headers(token))
        assert (status, body, headers["allow"]) == (405, {"error": "method_not_allowed"}, allow)
    for method, path in (
        ("GET", "/api/v1/accounts/prepare"),
        ("GET", "/api/v1/accounts/order"),
        ("GET", "/api/v1/accounts/AAAAAAAA-1111-4111-8111-111111111111"),
        ("POST", f"/api/v1/accounts/{CLAUDE_ID}/other"),
    ):
        status, _, _ = await raw_call(app, method, path, json_headers(token))
        assert status == 404


@pytest.mark.parametrize(
    ("headers", "chunks", "status", "code"),
    [
        ((("content-type", "text/plain"),), (b"{}",), 415, "unsupported_media_type"),
        ((("content-type", "application/json; charset=latin-1"),), (b"{}",), 415, None),
        ((("content-type", "application/json; charset=utf-8; x=y"),), (b"{}",), 415, None),
        ((), (b"{}",), 415, "unsupported_media_type"),
        ((("content-type", "application/json"), ("content-length", "70000")), (), 413, None),
        ((("content-type", "application/json"), ("content-length", "x")), (b"{}",), 400, None),
        (
            (
                ("content-type", "application/json"),
                ("content-length", "2"),
                ("content-length", "2"),
            ),
            (b"{}",),
            400,
            None,
        ),
        ((("content-type", "application/json"),), (b"a" * 40_000, b"a" * 40_000), 413, None),
        ((("content-type", "Application/JSON; Charset=UTF-8"),), (b'{"a":1,"a":2}',), 400, None),
        ((("content-type", "application/json"),), (b'{"x": NaN}',), 400, None),
        ((("content-type", "application/json"),), (b"[" * 100_000,), 413, None),
        ((("content-type", "application/json"),), (b"[" * 30_000 + b"]" * 30_000,), 400, None),
        ((("content-type", "application/json"),), (b'{"x": ' + b"9" * 5000 + b"}",), 400, None),
        ((("content-type", "application/json"),), (b'{"label": "\\ud800"}',), 400, None),
        ((("content-type", "application/json"),), (b"\xff\xfe",), 400, None),
        ((("content-type", "application/json"),), (b"[]",), 400, None),
        ((("content-type", "application/json"),), (b'{"unknown": 1}',), 400, None),
        (
            (("content-type", "application/json"),),
            (b'{"provider":"grok_subscription","label":"x","source":null,"enabled":1}',),
            400,
            None,
        ),
    ],
)
async def test_body_rules(tmp_path, token_store, token, no_keyring, headers, chunks, status, code):
    writable = Writable(tmp_path, token_store)
    auth_header = (("authorization", f"Bearer {token}"),)
    got, body, _ = await raw_call(
        writable.app, "POST", "/api/v1/accounts", auth_header + headers, chunks
    )
    expected = (
        code
        or {
            400: "invalid_request",
            413: "payload_too_large",
            415: "unsupported_media_type",
        }[status]
    )
    assert (got, body) == (status, {"error": expected})
    assert writable.store.load() == ()


async def test_body_deadline_and_disconnect(tmp_path, token_store, token, no_keyring, monkeypatch):
    writable = Writable(tmp_path, token_store)
    monkeypatch.setattr(api, "BODY_TIMEOUT_SECONDS", 0.05)
    sent = []

    async def stalled():
        await asyncio.sleep(3600)

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/accounts",
        "raw_path": b"/api/v1/accounts",
        "query_string": b"",
        "headers": [(key.encode(), value.encode()) for key, value in json_headers(token)],
        "client": ("203.0.113.7", 1),
    }
    await writable.app(scope, stalled, send)
    assert sent[0]["status"] == 408
    assert json.loads(sent[1]["body"]) == {"error": "request_timeout"}

    sent.clear()

    async def gone():
        return {"type": "http.disconnect"}

    await writable.app(scope, gone, send)
    assert sent == []


async def test_if_match_and_no_body_rules(tmp_path, token_store, token, no_keyring):
    item = plain("Grok")
    writable = Writable(tmp_path, token_store, (item,))
    path = f"/api/v1/accounts/{item.id}"
    status, body, _ = await raw_call(writable.app, "PATCH", path, json_headers(token), (b"{}",))
    assert (status, body) == (428, {"error": "precondition_required"})
    revision = writable.ops.revision(item)
    for value in (f'W/"{revision}"', revision[:-1], f'"{revision}', revision.upper()):
        status, _, _ = await raw_call(
            writable.app, "PATCH", path, json_headers(token, ("if-match", value)), (b"{}",)
        )
        assert status == 400
    status, _, _ = await raw_call(
        writable.app,
        "PATCH",
        path,
        json_headers(token, ("if-match", revision), ("if-match", revision)),
        (b"{}",),
    )
    assert status == 400
    status, _, _ = await raw_call(
        writable.app, "PATCH", path, json_headers(token, ("if-match", f'"{revision}"')), (b"{}",)
    )
    assert status == 200
    # DELETE ignores Content-Type but must have no body.
    auth_only = (("authorization", f"Bearer {token}"), ("if-match", revision))
    status, _, _ = await raw_call(writable.app, "DELETE", path, auth_only, (b"{}",))
    assert status == 400
    status, body, _ = await raw_call(writable.app, "DELETE", path, (auth_only[0],))
    assert (status, body) == (428, {"error": "precondition_required"})
    status, body, _ = await raw_call(writable.app, "DELETE", path, auth_only)
    assert status == 200 and body["accounts"] == [] and body["account"] is None
    assert writable.store.load() == ()


async def test_capabilities_live_read_only_and_demo(tmp_path, token_store, token, no_keyring):
    writable = Writable(tmp_path, token_store)
    await writable.ops.start()
    assert no_keyring == ["get_keyring"]
    async with client_for(writable.app) as client:
        session = (await client.get("/api/v1/session", headers=auth(token))).json()
        listing = (await client.get("/api/v1/accounts", headers=auth(token))).json()
    expected = {"writable": True, "secure_store_available": False}
    assert session["capabilities"] == listing["capabilities"] == expected
    # GET polling never re-probes the keyring.
    assert no_keyring == ["get_keyring"]
    hub, _ = static_hub()
    async with client_for(api.create_app(hub, token_store)) as client:
        listing = (await client.get("/api/v1/accounts", headers=auth(token))).json()
    assert listing["capabilities"] == {"writable": False, "secure_store_available": False}
    assert all(item["revision"] is None for item in listing["accounts"])
    async with client_for(api.create_app(api.demo_hub(), None)) as client:
        session = (await client.get("/api/v1/session")).json()
        accounts = (await client.get("/api/v1/accounts")).json()
    assert (
        session["capabilities"]
        == accounts["capabilities"]
        == {
            "writable": False,
            "secure_store_available": False,
        }
    )
    assert no_keyring == ["get_keyring"]


async def test_account_list_redacts_paths_selectors_orgs_and_refs(
    tmp_path, token_store, token, no_keyring
):
    custom = live_accounts()
    session_ref = Account(
        id=str(uuid.uuid4()),
        provider=ProviderId.CLAUDE_SUBSCRIPTION,
        label="Session",
        credential_kind=CredentialKind.MANUAL_BEARER,
        credential_ref="session:" + str(uuid.uuid4()),
    )
    writable = Writable(tmp_path, token_store, (*custom, session_ref))
    async with client_for(writable.app) as client:
        response = await client.get("/api/v1/accounts", headers=auth(token))
    text = response.text
    for secretish in (
        "/home/someone",
        "selector-value",
        "org-secretish-123",
        SECRET_REF,
        session_ref.credential_ref,
        "keyring:",
        "session:",
    ):
        assert secretish not in text
    views = {item["id"]: item for item in response.json()["accounts"]}
    assert [item["id"] for item in response.json()["accounts"]] == [
        *(item.id for item in custom),
        session_ref.id,
    ]
    assert views[CLAUDE_ID]["reference"] == "custom"
    assert views[CLAUDE_ID]["storage"] == "external_file"
    assert views[PLATFORM_ID] | {"revision": None} == {
        "id": PLATFORM_ID,
        "provider": "claude_platform",
        "label": "Console",
        "enabled": True,
        "poll_interval_seconds": 60,
        "effective_poll_interval_seconds": 60,
        "credential_kind": "console_session",
        "storage": "keyring",
        "reference": None,
        "session_available": None,
        "scope_selected": False,
        "organization_selected": True,
        "revision": None,
    }
    assert len(views[PLATFORM_ID]["revision"]) == 32
    assert views[DISABLED_ID]["reference"] == "default"
    assert views[DISABLED_ID]["scope_selected"] is True
    # A session secret lost with a restart is reported, never revealed.
    assert views[session_ref.id]["storage"] == "session"
    assert views[session_ref.id]["session_available"] is False


async def test_secret_never_echoed_and_dynamic_hub(tmp_path, token_store, token, no_keyring):
    keep, other = plain("Keep"), plain("Other")
    writable = Writable(
        tmp_path, token_store, (keep, other), snapshots=(snapshot(keep.id), snapshot(other.id))
    )
    observed = []

    class Observer:
        def accounts_changed(self, accounts):
            observed.append(tuple(accounts))

    writable.hub.add_observer(Observer())
    await writable.hub.start()
    source = writable.holder["source"]
    body = {
        "provider": "claude_subscription",
        "label": "Bearer",
        "source": {"credential_kind": "manual_bearer", "secret": BEARER, "persist": False},
    }
    async with client_for(writable.app) as client:
        created = await client.post("/api/v1/accounts", headers=auth(token), json=body)
        assert created.status_code == 201
        assert BEARER not in created.text
        new_id = created.json()["account"]["id"]
        assert created.json()["account"]["session_available"] is True
        assert created.json()["warning"] is None
        assert [item.id for item in writable.hub.accounts] == [keep.id, other.id, new_id]
        assert source.updates[-1][1] == frozenset({new_id})
        assert observed[-1] == writable.hub.accounts
        # Untouched accounts keep their observations.
        assert set(writable.hub.snapshots) == {keep.id, other.id}
        # Rename keeps the snapshot and the new label is rendered with it.
        revision = created.json()["accounts"][0]["revision"]
        renamed = await client.patch(
            f"/api/v1/accounts/{keep.id}",
            headers={**auth(token), "If-Match": f'"{revision}"'},
            json={"label": "Renamed"},
        )
        assert renamed.status_code == 200
        assert source.updates[-1][1] == frozenset()
        single = (await client.get(f"/api/v1/accounts/{keep.id}", headers=auth(token))).json()
        assert single["account"]["label"] == "Renamed" and single["snapshot"] is not None
        # Reorder: the dashboard follows the config order.
        ordered = await client.put(
            "/api/v1/accounts/order",
            headers=auth(token),
            json={"ids": [new_id, other.id, keep.id]},
        )
        assert ordered.status_code == 200
        dashboard = (await client.get("/api/v1/dashboard", headers=auth(token))).json()
        assert [item["account"]["id"] for item in dashboard["accounts"]] == [
            new_id,
            other.id,
            keep.id,
        ]
        assert dashboard["accounts"][1]["snapshot"] is not None
        stale = await client.put(
            "/api/v1/accounts/order", headers=auth(token), json={"ids": [keep.id]}
        )
        assert (stale.status_code, stale.json()) == (409, {"error": "conflict"})
        reconnect = await client.post(f"/api/v1/accounts/{other.id}/reconnect", headers=auth(token))
        assert (reconnect.status_code, reconnect.json()) == (200, {"status": "queued"})
        assert source.refreshes == [other.id]
        missing = await client.post(
            f"/api/v1/accounts/{uuid.uuid4()}/reconnect", headers=auth(token)
        )
        assert (missing.status_code, missing.json()) == (404, {"error": "not_found"})
        invalid = await client.post(
            "/api/v1/accounts",
            headers=auth(token),
            json={**body, "source": {**body["source"], "secret": "bad value " + BEARER}},
        )
        assert invalid.status_code == 422 and BEARER not in invalid.text
    await writable.hub.stop()


async def test_discovery_busy_carries_retry_after(tmp_path, token_store, token, no_keyring):
    writable = Writable(tmp_path, token_store, origins=[ORIGIN])

    async def discovery(credential):
        return (OrganizationChoice("org-1", "One"),)

    writable.ops.console_discovery = discovery
    body = {
        "provider": "claude_platform",
        "credential_kind": "console_session",
        "secret": "sk-ant-sid01-synthetic",
    }
    async with client_for(writable.app) as client:
        first = await client.post("/api/v1/accounts/prepare", headers=auth(token), json=body)
        assert first.status_code == 200 and first.json()["choices"][0]["label"] == "One"
        assert "sk-ant" not in first.text and "org-1" not in first.text
        busy = await client.post(
            "/api/v1/accounts/prepare", headers={**auth(token), "Origin": ORIGIN}, json=body
        )
    assert busy.status_code == 409
    assert busy.json() == {"error": "discovery_busy", "retry_after": 10}
    assert busy.headers["retry-after"] == "10"
    assert "Retry-After" in busy.headers["access-control-expose-headers"]


async def test_write_gate_is_evaluated_per_request(tmp_path, token_store, token, no_keyring):
    writable = Writable(tmp_path, token_store)
    body = json.dumps({"provider": "grok_subscription", "label": "x", "source": None}).encode()
    status, _, _ = await raw_call(
        writable.app, "POST", "/api/v1/accounts", json_headers(token), (body,)
    )
    assert status == 201
    # Anonymous serving (never a live default) makes the same app read-only at once.
    writable.app._anonymous = lambda: True
    status, payload, _ = await raw_call(
        writable.app, "POST", "/api/v1/accounts", json_headers(token), receive_fails=True
    )
    assert (status, payload) == (403, {"error": "read_only"})
    async with client_for(writable.app) as client:
        session = (await client.get("/api/v1/session")).json()
    assert session["capabilities"]["writable"] is False
    assert len(writable.store.load()) == 1
