"""Opt-in debug log: synthetic HTTP/scheduler only, never real accounts or sockets."""

from __future__ import annotations

import asyncio
import json
import os
import stat
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import httpx
import pytest

from cli_usage_api import cli, debuglog
from cli_usage_api import transport as transport_module
from cli_usage_api.domain import (
    Account,
    CredentialKind,
    ExactMoney,
    FetchState,
    Metric,
    MetricId,
    MetricState,
    Money,
    ProviderId,
    QuotaValue,
    ResolvedCredential,
    Snapshot,
    SourceKind,
    SourceRef,
    TransportError,
)
from cli_usage_api.providers.base import build_providers
from cli_usage_api.scheduler import Scheduler
from cli_usage_api.transport import Transport

SECRET = "synthetic-bearer-secret-value"
USER_ID = "synthetic-grok-user-id"
CODEX_ACCOUNT = "synthetic-codex-selected-account"
JWT = "eyJhbGciOiJub25lIn0.eyJzdWIiOiJzeW50aGV0aWMifQ.c2lnbmF0dXJl"
CLAUDE_BODY = (
    b'{"five_hour":{"utilization":43.500000000000000000000000000001,'
    b'"resets_at":"2026-10-28T18:00:00Z"},"seven_day":{"utilization":"bad"},'
    b'"email":"person@example.test","access_token":"leaked-token-value",'
    b'"nested":[{"sessionKey":"leaked-session"}],"note":"' + JWT.encode() + b'",'
    b'"echo":"' + SECRET.encode() + b'","totalTokens":7}'
)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / "config"))
    yield
    debuglog.close()


def credential(provider=ProviderId.CLAUDE_SUBSCRIPTION):
    kind = {
        ProviderId.CLAUDE_PLATFORM: CredentialKind.CONSOLE_SESSION,
        ProviderId.CODEX_SUBSCRIPTION: CredentialKind.CODEX_AUTH_FILE,
    }.get(provider, CredentialKind.MANUAL_BEARER)
    return ResolvedCredential(
        provider,
        kind,
        SECRET,
        "generation-1",
        user_id=USER_ID if provider == ProviderId.GROK_SUBSCRIPTION else None,
        codex_account_id=CODEX_ACCOUNT if provider == ProviderId.CODEX_SUBSCRIPTION else None,
    )


def transport(status=200, content=CLAUDE_BODY, headers=None):
    return Transport(
        http_transport=httpx.MockTransport(
            lambda _: httpx.Response(status, content=content, headers=headers)
        )
    )


def records(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


async def get(source, provider=ProviderId.CLAUDE_SUBSCRIPTION, path="/api/oauth/usage"):
    return await source.get_json(provider, path, credential=credential(provider))


async def test_disabled_mode_writes_nothing(tmp_path):
    log = tmp_path / "debug.jsonl"
    assert not debuglog.enabled(ProviderId.CLAUDE_SUBSCRIPTION)
    await get(transport())
    debuglog.configure(log)
    debuglog.close()
    await get(transport())
    assert log.read_text() == ""


async def test_response_body_is_logged_privately_with_exact_decimals_and_redaction(tmp_path):
    log = tmp_path / "debug.jsonl"
    debuglog.configure(log)
    await get(transport())
    assert stat.S_IMODE(os.stat(log).st_mode) == 0o600
    text = log.read_text()
    for secret in (SECRET, "leaked-token-value", "leaked-session", JWT):
        assert secret not in text
    # Exact wire numeral, emitted as a JSON number rather than through float.
    assert '"utilization": 43.500000000000000000000000000001' in text
    (record,) = records(log)
    assert record["provider"] == "claude-subscription"
    assert record["event"] == "http_response"
    assert record["path"] == "/api/oauth/usage"
    assert record["status"] == 200
    assert record["bytes"] == len(CLAUDE_BODY)
    assert record["ts"].endswith("Z")
    body = record["body"]
    assert body["email"] == "person@example.test"
    assert body["access_token"] == body["nested"][0]["sessionKey"] == "[redacted]"
    assert body["note"] == body["echo"] == "[redacted]"
    assert body["totalTokens"] == 7
    assert body["seven_day"] == {"utilization": "bad"}


async def test_headers_and_request_secrets_never_logged(tmp_path):
    log = tmp_path / "debug.jsonl"
    debuglog.configure(log)
    for provider, path in (
        (ProviderId.CLAUDE_PLATFORM, "/api/organizations"),
        (ProviderId.CODEX_SUBSCRIPTION, "/backend-api/wham/usage"),
        (ProviderId.GROK_SUBSCRIPTION, "/v1/billing?format=credits"),
    ):
        # The server echoes this request's own bound values under innocuous keys.
        bound = credential(provider)
        echo = json.dumps({"user": bound.user_id, "account": bound.codex_account_id, "e": SECRET})
        await get(transport(content=echo.encode()), provider, path)
    text = log.read_text()
    for value in (SECRET, USER_ID, CODEX_ACCOUNT, "Bearer", "sessionKey=", "x-userid"):
        assert value not in text
    assert [record["provider"] for record in records(log)] == [
        "claude-platform",
        "codex-subscription",
        "grok-subscription",
    ]


async def test_error_body_status_and_failure_codes(tmp_path):
    log = tmp_path / "debug.jsonl"
    debuglog.configure(log)
    with pytest.raises(TransportError) as raised:
        await get(transport(401, b'{"error":{"type":"authentication_error"}}'))
    assert raised.value.code == "auth_required"
    with pytest.raises(TransportError):
        await get(transport(200, b"<html>not json</html>"))

    def broken(request):
        raise httpx.ConnectError(f"failed with {SECRET}", request=request)

    with pytest.raises(TransportError):
        await get(Transport(http_transport=httpx.MockTransport(broken)))
    assert SECRET not in log.read_text()
    response, failure, invalid, invalid_failure, network = records(log)
    assert response["status"] == 401
    assert response["body"] == {"error": {"type": "authentication_error"}}
    assert failure["event"] == "http_error"
    assert (failure["code"], failure["fetch_state"], failure["status"]) == (
        "auth_required",
        "auth_required",
        401,
    )
    assert invalid["body_text"] == "<html>not json</html>"
    assert invalid_failure["code"] == "schema_error"
    assert network["code"] == "network_error"
    assert network["exception"] == "ConnectError"


@pytest.mark.parametrize(
    ("status", "content", "headers"),
    [
        (429, b'{"error":"slow down"}', {"Retry-After": "120"}),
        (403, b"x" * 2_000_000, None),
        (500, b"{}", {"Content-Encoding": "gzip"}),
    ],
)
async def test_debug_does_not_change_error_results(tmp_path, status, content, headers):
    async def outcome():
        with pytest.raises(TransportError) as raised:
            await get(transport(status, content, headers))
        error = raised.value
        return error.fetch_state, error.code, error.status, error.retry_at is not None

    plain = await outcome()
    debuglog.configure(tmp_path / "debug.jsonl")
    assert await outcome() == plain
    assert plain[0] != FetchState.OK


DEEP = b'{"a":' + b"[" * 5000 + b"]" * 5000 + b"}"


@pytest.mark.parametrize(
    ("status", "headers"),
    [(200, None), (429, {"Retry-After": "120"})],
)
async def test_unserializable_deep_body_does_not_change_result(tmp_path, status, headers):
    async def outcome():
        try:
            result = await get(transport(status, DEEP, headers))
        except TransportError as error:
            return error.fetch_state, error.code, error.retry_at is not None
        return "ok", type(result).__name__

    plain = await outcome()
    log = tmp_path / "debug.jsonl"
    debuglog.configure(log)
    assert await outcome() == plain
    response = records(log)[0]
    assert response["event"] == "http_response"
    assert response["status"] == status
    assert response["bytes"] == len(DEEP)
    assert response["body_unloggable"] is True
    assert "body" not in response


class StalledBody(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b'{"error":'
        await asyncio.sleep(3600)


@pytest.mark.parametrize(
    ("status", "headers", "state"),
    [
        (429, {"Retry-After": "120"}, FetchState.RATE_LIMITED),
        (401, None, FetchState.AUTH_REQUIRED),
    ],
)
async def test_stalled_error_body_keeps_status_classification(
    tmp_path, monkeypatch, status, headers, state
):
    monkeypatch.setattr(transport_module, "TOTAL_TIMEOUT_SECONDS", 1.0)

    async def outcome():
        source = Transport(
            http_transport=httpx.MockTransport(
                lambda _: httpx.Response(status, headers=headers, stream=StalledBody())
            )
        )
        with pytest.raises(TransportError) as raised:
            await get(source)
        error = raised.value
        return error.fetch_state, error.code, error.status, error.retry_at is not None

    plain = await outcome()
    assert plain[0] == state
    log = tmp_path / "debug.jsonl"
    debuglog.configure(log)
    assert await outcome() == plain
    response, failure = records(log)
    assert response["body_unread"] is True
    assert failure["code"] == plain[1]


async def test_undecodable_text_redacts_secret_keys(tmp_path):
    log = tmp_path / "debug.jsonl"
    debuglog.configure(log)
    body = (
        b'{"email":"person@example.test","sessionKey":"sk-ant-sid01-OTHERVALUE",'
        b'"refresh_token":"abcdefREFRESH","api_key":12345,"password":"unterminat'
    )
    with pytest.raises(TransportError):
        await get(transport(200, body))
    with pytest.raises(TransportError):
        await get(transport(500, b"<html>token=formTOKEN&ok=1; sessionKey=cookieVALUE</html>"))
    text = log.read_text()
    for secret in (
        "OTHERVALUE",
        "abcdefREFRESH",
        "12345",
        "unterminat",
        "formTOKEN",
        "cookieVALUE",
    ):
        assert secret not in text
    first, _, second, _ = records(log)
    assert "person@example.test" in first["body_text"]
    assert "ok=1" in second["body_text"]


@pytest.mark.parametrize("decodes", [True, False])
async def test_truncation_never_leaves_credential_prefix(tmp_path, decodes):
    log = tmp_path / "debug.jsonl"
    debuglog.configure(log)
    # Place the request's own secret across the truncation point.
    pad = "x" * (debuglog.MAX_BODY_CHARS - 5 - len('{"pad": "') - len('", "echo": "'))
    body = {"pad": pad, "echo": SECRET, "tail": "y" * 1000}
    content = json.dumps(body).encode()
    content = content if decodes else content[:-2]
    if decodes:
        await get(transport(content=content))
    else:
        with pytest.raises(TransportError):
            await get(transport(content=content))
    text = log.read_text()
    assert SECRET[:4] not in text.replace("[redacted]", "")
    (record, *_) = records(log)
    assert ("body_truncated" if decodes else "body_text") in record


async def test_provider_filter_excludes_other_providers(tmp_path):
    log = tmp_path / "debug.jsonl"
    debuglog.configure(log, {ProviderId.GROK_SUBSCRIPTION})
    await get(transport())
    await get(transport(content=b"{}"), ProviderId.GROK_SUBSCRIPTION, "/v1/billing?format=credits")
    assert [record["provider"] for record in records(log)] == ["grok-subscription"]


async def test_scheduler_snapshot_summarizes_every_metric(tmp_path):
    log = tmp_path / "debug.jsonl"
    debuglog.configure(log)

    class Resolver:
        def resolve(self, item):
            return credential(item.provider)

    item = Account(
        id=str(UUID(int=1)),
        provider=ProviderId.CLAUDE_SUBSCRIPTION,
        label="Synthetic",
        credential_ref="synthetic",
        credential_kind=CredentialKind.MANUAL_BEARER,
    )
    published = asyncio.Queue()
    scheduler = Scheduler(
        (item,),
        build_providers(transport(), Resolver()),
        Resolver(),
        publish=published.put_nowait,
    )
    await scheduler.start()
    try:
        await asyncio.wait_for(published.get(), timeout=5)
    finally:
        await scheduler.stop()
    response, summary = records(log)
    assert response["event"] == "http_response"
    assert summary["event"] == "snapshot"
    assert summary["account_id"] == item.id
    assert summary["fetch_state"] == "partial"
    metrics = {metric["id"]: metric for metric in summary["metrics"]}
    five_hour = next(metric for metric in metrics.values() if metric["quota"])
    assert five_hour["state"] in {"ready", "over_limit"}
    assert str(five_hour["quota"]["used_percent"]).startswith("43.5")
    assert five_hour["reset_at"] == datetime(2026, 10, 28, 18, tzinfo=UTC).isoformat()
    assert any(metric["state"] == "unknown" for metric in metrics.values())
    assert SECRET not in log.read_text()


def test_snapshot_summary_includes_spend_credits_and_unlimited(tmp_path):
    log = tmp_path / "debug.jsonl"
    debuglog.configure(log)
    source = SourceRef(SourceKind.OFFLINE_DEMO, "debuglog.test")
    now = datetime(2026, 10, 28, 12, tzinfo=UTC)
    debuglog.snapshot(
        ProviderId.CLAUDE_SUBSCRIPTION,
        Snapshot(
            str(UUID(int=1)),
            (
                Metric(
                    MetricId.CLAUDE_EXTRA_USAGE,
                    "Claude 额外用量",
                    MetricState.READY,
                    source,
                    quota=QuotaValue(used_percent=Decimal(25)),
                    spent=Money(1250, "USD", 2),
                    spend_limit=Money(5000, "USD", 2),
                ),
                Metric("test.unlimited", "u", MetricState.READY, source, unlimited=True),
                Metric(
                    MetricId.CODEX_CREDITS,
                    "Codex credits 余额",
                    MetricState.READY,
                    source,
                    credits=Decimal("-0.50"),
                ),
            ),
            (),
            FetchState.OK,
            now,
        ),
    )
    (summary,) = records(log)
    extra, unlimited, credits = summary["metrics"]
    assert extra["spent"] == {"minor": 1250, "currency": "USD", "exponent": 2}
    assert extra["spend_limit"] == {"minor": 5000, "currency": "USD", "exponent": 2}
    assert extra["credits"] is None and extra["unlimited"] is False
    assert extra["balance"] is None
    assert unlimited["unlimited"] is True and unlimited["spend_limit"] is None
    assert Decimal(str(credits["credits"])) == Decimal("-0.50")
    assert credits["spent"] is None and credits["spend_limit"] is None


def test_open_refuses_unsafe_targets(tmp_path):
    loose = tmp_path / "loose.jsonl"
    loose.write_text("")
    loose.chmod(0o644)
    link = tmp_path / "link.jsonl"
    link.symlink_to(tmp_path / "target.jsonl")
    for target in (loose, link, tmp_path, tmp_path / "missing" / "debug.jsonl"):
        with pytest.raises(debuglog.DebugLogError):
            debuglog.configure(target)
    assert not (tmp_path / "target.jsonl").exists()
    assert not debuglog.enabled(ProviderId.CLAUDE_SUBSCRIPTION)


def forbid_live(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Rejected arguments must not construct services")

    for name in ("AccountStore", "CredentialStore", "LiveFactory", "UsageApp"):
        monkeypatch.setattr(cli, name, forbidden)


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--debug-provider", "codex-subscription"], "--debug-provider requires --debug-log."),
        (["--demo", "--debug-log", "LOG"], "--debug-log cannot be combined with --demo."),
        (["--debug-log", "LOG", "accounts", "list"], "only to the live dashboard"),
        (["--debug-log", "LOG", "--debug-provider", "chatgpt"], "usage --help"),
        (["--debug-log"], "usage --help"),
        (["--debug-log", "MISSING/debug.jsonl"], "Cannot open debug log"),
    ],
)
def test_cli_rejects_invalid_debug_arguments(monkeypatch, capsys, tmp_path, args, message):
    forbid_live(monkeypatch)
    log = tmp_path / "LOG"
    args = [
        str(tmp_path / value) if value in {"LOG", "MISSING/debug.jsonl"} else value
        for value in args
    ]
    assert cli.main(args) == 2
    captured = capsys.readouterr()
    assert message in captured.err
    assert "Traceback" not in captured.out + captured.err
    assert not log.exists()


def test_cli_live_dashboard_logs_selected_providers_then_closes(monkeypatch, tmp_path):
    log = tmp_path / "debug.jsonl"
    seen = []

    def run(app):
        assert app.mode == "live"
        seen.append(debuglog.enabled(ProviderId.CODEX_SUBSCRIPTION))
        seen.append(debuglog.enabled(ProviderId.CLAUDE_SUBSCRIPTION))
        asyncio.run(get(transport()))
        asyncio.run(
            get(
                transport(content=b'{"rate_limit":null}'),
                ProviderId.CODEX_SUBSCRIPTION,
                "/backend-api/wham/usage",
            )
        )

    monkeypatch.setattr(cli.UsageApp, "run", run)
    args = ["--debug-log", str(log), "--debug-provider", "codex-subscription"]
    assert cli.main(args) == 0
    assert seen == [True, False]
    assert stat.S_IMODE(os.stat(log).st_mode) == 0o600
    assert [(record["provider"], record["body"]) for record in records(log)] == [
        ("codex-subscription", {"rate_limit": None})
    ]
    assert not debuglog.enabled(ProviderId.CODEX_SUBSCRIPTION)


OPENAI_SESSION = "synthetic-openai-session-value"
OPENAI_ORG = "org-Synthetic0123"
CLAUDE_ORG = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"


def openai_credential():
    return ResolvedCredential(
        ProviderId.OPENAI_PLATFORM,
        CredentialKind.OPENAI_PLATFORM_SESSION,
        OPENAI_SESSION,
        "generation-1",
        organization_id=OPENAI_ORG,
    )


async def test_openai_credit_grants_log_redacts_the_session(tmp_path):
    log = tmp_path / "debug.jsonl"
    debuglog.configure(log)
    body = json.dumps(
        {
            "object": "credit_summary",
            "total_available": 17.3715455,
            "echo": OPENAI_SESSION,
            "session": {"sensitive_id": "leaked-sensitive"},
            "sensitive_id": "leaked-sensitive",
        }
    ).encode()
    result = await transport(content=body).get_json(
        ProviderId.OPENAI_PLATFORM,
        "/v1/dashboard/billing/credit_grants",
        credential=openai_credential(),
    )
    assert result["total_available"] == Decimal("17.3715455")
    text = log.read_text()
    for value in (OPENAI_SESSION, "leaked-sensitive", "Bearer", "OpenAI-Organization"):
        assert value not in text
    (record,) = records(log)
    assert record["provider"] == "openai-platform"
    assert record["path"] == "/v1/dashboard/billing/credit_grants"
    assert '"total_available": 17.3715455' in text


@pytest.mark.parametrize("enabled", [True, False])
async def test_openai_error_classification_is_identical_with_and_without_debug(tmp_path, enabled):
    log = tmp_path / "debug.jsonl"
    if enabled:
        debuglog.configure(log)
    body = json.dumps({"error": {"code": "expired_session_key", "message": OPENAI_SESSION}})
    with pytest.raises(TransportError) as caught:
        await transport(401, body.encode()).get_json(
            ProviderId.OPENAI_PLATFORM,
            "/v1/dashboard/billing/credit_grants",
            credential=openai_credential(),
        )
    assert (caught.value.fetch_state, caught.value.code) == (
        FetchState.AUTH_REQUIRED,
        "credential_expired",
    )
    if enabled:
        text = log.read_text()
        assert OPENAI_SESSION not in text
        assert [record["event"] for record in records(log)] == ["http_response", "http_error"]
    else:
        assert not log.exists()


async def test_claude_prepaid_credits_log_keeps_organization_path(tmp_path):
    log = tmp_path / "debug.jsonl"
    debuglog.configure(log)
    path = transport_module.claude_credits_path(CLAUDE_ORG)
    await transport(content=b'{"amount": 1234, "currency": "USD"}').get_json(
        ProviderId.CLAUDE_SUBSCRIPTION,
        path,
        credential=ResolvedCredential(
            ProviderId.CLAUDE_SUBSCRIPTION,
            CredentialKind.MANUAL_BEARER,
            SECRET,
            "generation-1",
            organization_id=CLAUDE_ORG,
        ),
    )
    (record,) = records(log)
    assert record["path"] == path
    assert record["body"] == {"amount": 1234, "currency": "USD"}
    assert SECRET not in log.read_text()


def test_snapshot_summary_includes_exact_balance(tmp_path):
    log = tmp_path / "debug.jsonl"
    debuglog.configure(log)
    source = SourceRef(SourceKind.OFFLINE_DEMO, "debuglog.test")
    now = datetime(2026, 10, 28, 12, tzinfo=UTC)
    debuglog.snapshot(
        ProviderId.OPENAI_PLATFORM,
        Snapshot(
            str(UUID(int=1)),
            (
                Metric(
                    MetricId.OPENAI_AVAILABLE_BALANCE,
                    "OpenAI 可用余额",
                    MetricState.READY,
                    source,
                    exact_balance=ExactMoney(Decimal("3.0700000000000003"), "USD"),
                ),
                Metric(MetricId.OPENAI_PAID_AVAILABLE_BALANCE, "p", MetricState.UNKNOWN, source),
            ),
            (),
            FetchState.OK,
            now,
        ),
    )
    text = log.read_text()
    assert '"amount": 3.0700000000000003' in text
    (summary,) = records(log)
    ready, unknown = summary["metrics"]
    assert ready["exact_balance"]["currency"] == "USD"
    assert ready["balance"] is None and ready["credits"] is None
    assert unknown["exact_balance"] is None
