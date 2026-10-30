"""OpenAI Platform balance contract: synthetic responses through the real Transport."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from cli_usage_api.domain import (
    REQUIRED_METRIC_IDS,
    Account,
    CredentialKind,
    ExactMoney,
    FetchState,
    MetricId,
    MetricState,
    ProviderId,
    ResolvedCredential,
    Snapshot,
    SourceKind,
)
from cli_usage_api.providers import OpenAIPlatformProvider
from cli_usage_api.transport import Transport

NOW = datetime(2026, 10, 28, 12, tzinfo=UTC)
ORG = "org-Synthetic0123"
SESSION = "synthetic-openai-session-0000"
FIXTURES = Path(__file__).parent / "fixtures"
ACCOUNT = Account(
    "00000000-0000-0000-0000-000000000007",
    ProviderId.OPENAI_PLATFORM,
    "Synthetic OpenAI Platform",
    credential_kind=CredentialKind.OPENAI_PLATFORM_SESSION,
    credential_ref="memory:synthetic",
    organization_id=ORG,
)
CREDENTIAL = ResolvedCredential(
    ProviderId.OPENAI_PLATFORM,
    CredentialKind.OPENAI_PLATFORM_SESSION,
    SESSION,
    "generation-1",
    organization_id=ORG,
)


def raw(name):
    return (FIXTURES / f"openai_platform_credit_grants_{name}.json").read_bytes()


def provider_for(body, *, status=200, headers=None, clock=None):
    """``body`` is raw bytes (wire digits kept) or a JSON-serializable value."""
    requests = []
    content = body if isinstance(body, bytes) else json.dumps(body).encode()

    def handler(request):
        requests.append(request)
        return httpx.Response(
            status,
            content=content,
            headers={"content-type": "application/json", **(headers or {})},
        )

    transport = Transport(http_transport=httpx.MockTransport(handler), clock=clock)
    return OpenAIPlatformProvider(transport), requests


def assert_single_exact_read(requests):
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "GET"
    assert str(request.url) == "https://api.openai.com/v1/dashboard/billing/credit_grants"
    assert request.headers["authorization"] == f"Bearer {SESSION}"
    assert request.headers["openai-organization"] == ORG
    assert "cookie" not in request.headers
    assert "content-type" not in request.headers
    assert request.headers["user-agent"].startswith("cli-usage-api/")
    assert not request.content


def by_id(snapshot):
    return {row.id: row for row in snapshot.metrics}


def assert_safe(snapshot):
    assert snapshot.metrics[0].id == MetricId.OPENAI_AVAILABLE_BALANCE
    for row in snapshot.metrics:
        assert row.source.kind == SourceKind.PRIVATE_HTTP and row.source.version_sensitive
        assert row.quota is None and row.balance is None and row.reset_at is None
        assert row.credits is None and row.share_percent is None
    assert snapshot.grants == ()
    assert SESSION not in repr(snapshot)
    assert SESSION not in json.dumps(snapshot.to_dict())
    assert Snapshot.from_dict(snapshot.to_dict()) == snapshot


def test_provider_shape():
    provider, _ = provider_for({})
    assert provider.requires_credential is True
    assert provider.metric_ids == REQUIRED_METRIC_IDS[ProviderId.OPENAI_PLATFORM]
    assert not hasattr(provider, "discover_organizations")


async def test_2023_sample_keeps_exact_available_without_paid_row():
    provider, requests = provider_for(raw("2023"))
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert_single_exact_read(requests)
    assert_safe(snapshot)
    assert snapshot.fetch_state == FetchState.OK
    assert snapshot.diagnostic is None
    assert snapshot.fetched_at == snapshot.attempted_at == NOW
    assert snapshot.organization_id == ORG
    assert [row.id for row in snapshot.metrics] == [MetricId.OPENAI_AVAILABLE_BALANCE]
    row = snapshot.metrics[0]
    assert row.state == MetricState.READY
    assert row.exact_balance == ExactMoney(Decimal("17.3715455"), "USD")
    assert str(row.exact_balance.amount) == "17.3715455"
    assert row.exact_balance.rounded_to_cents() == (Decimal("17.37"), True)
    assert row.expires_at is None
    assert "Reported" not in row.detail and "not derived" not in row.detail
    # Detail text is shown on the dashboards as plain cents (no per-amount note).
    assert row.detail == "已授予 18.00 USD · 已用 0.63 USD · 1 笔授予，1 笔已过期"
    assert "舍入" not in row.detail
    assert "0.6284545" not in row.detail
    assert "≈" not in row.detail
    assert "到期" not in row.detail  # no future grant expiry


async def test_2024_sample_keeps_float_noise_exact_and_emits_paid_row():
    provider, requests = provider_for(raw("2024"))
    when = datetime(2024, 4, 2, tzinfo=UTC)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, when)
    assert_single_exact_read(requests)
    assert_safe(snapshot)
    assert snapshot.fetch_state == FetchState.OK
    rows = by_id(snapshot)
    assert list(rows) == [
        MetricId.OPENAI_AVAILABLE_BALANCE,
        MetricId.OPENAI_PAID_AVAILABLE_BALANCE,
    ]
    available = rows[MetricId.OPENAI_AVAILABLE_BALANCE]
    paid = rows[MetricId.OPENAI_PAID_AVAILABLE_BALANCE]
    assert available.exact_balance.amount == Decimal("4.9")
    assert paid.exact_balance.amount == Decimal("4.9")
    assert paid.state == MetricState.READY
    # granted - used (19.93) differs from the reported available: never derived.
    # The float noise stays in structured exact_balance data only; the dashboard
    # detail text rounds every OpenAI amount to plain cents.
    assert "已用 3.07 USD" in available.detail and "舍入" not in available.detail
    assert "已授予 23.00 USD" in available.detail
    assert "3.0700000000000003" not in available.detail
    assert "23.0 USD" not in available.detail
    assert "≈" not in available.detail
    assert "2 笔授予，1 笔已过期，最早 2025-04-01 到期" in available.detail
    assert "T00:00:00Z" not in available.detail
    # The paid row carries no explanatory note.
    assert paid.detail is None
    assert available.reset_at is None and available.expires_at is None
    # The serialized snapshot keeps the exact wire value.
    serialized = snapshot.to_dict()["metrics"][0]["exact_balance"]
    assert serialized == {"amount": "4.9", "currency": "USD"}


async def test_float_noise_in_available_is_preserved_exactly():
    body = b'{"total_available": 3.0700000000000003}'
    provider, _ = provider_for(body)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    amount = snapshot.metrics[0].exact_balance.amount
    assert str(amount) == "3.0700000000000003"
    assert snapshot.metrics[0].exact_balance.format_cents() == "3.07 USD"


@pytest.mark.parametrize(
    "body,expected",
    [
        (b'{"total_available": 0}', Decimal(0)),
        (b'{"total_available": 0.0}', Decimal("0.0")),
        (b'{"total_available": -1.25}', Decimal("-1.25")),
        (b'{"total_available": 12}', Decimal(12)),
    ],
)
async def test_zero_negative_and_integral_amounts_are_reported_values(body, expected):
    provider, _ = provider_for(body)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert snapshot.fetch_state == FetchState.OK
    assert snapshot.metrics[0].exact_balance.amount == expected


@pytest.mark.parametrize(
    "body",
    [
        b"{}",
        b'{"total_available": null}',
        b'{"total_available": "4.90"}',
        b'{"total_available": true}',
        b'{"total_available": false}',
        b'{"total_available": {}}',
        b'{"total_available": 1e999999}',
        b'{"total_available": 1E-999999}',
        b'{"total_available": 1e41}',
        b'{"total_available": 12345678901234567890123456789012345678901}',
        b'{"total_granted": 23.0, "total_used": 3.0}',
    ],
)
async def test_missing_or_invalid_available_is_unknown_schema_error(body):
    provider, _ = provider_for(body)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert_safe(snapshot)
    assert snapshot.fetch_state == FetchState.SCHEMA_ERROR
    assert snapshot.diagnostic.code == "schema_error"
    assert snapshot.fetched_at is None
    assert [row.id for row in snapshot.metrics] == [MetricId.OPENAI_AVAILABLE_BALANCE]
    row = snapshot.metrics[0]
    assert row.state == MetricState.UNKNOWN
    assert row.exact_balance is None
    assert row.detail.startswith("可用余额缺失或无效")


@pytest.mark.parametrize("body", [b"[]", b'[{"total_available": 1}]'])
async def test_non_object_root_is_schema_error(body):
    provider, _ = provider_for(body)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert snapshot.fetch_state == FetchState.SCHEMA_ERROR
    assert snapshot.metrics[0].state == MetricState.UNKNOWN


@pytest.mark.parametrize("non_json", [b"NaN", b'{"total_available": NaN}', b"not json"])
async def test_non_json_constants_are_schema_error(non_json):
    provider, _ = provider_for(non_json)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert snapshot.fetch_state == FetchState.SCHEMA_ERROR
    assert snapshot.metrics[0].exact_balance is None


async def test_paid_only_keeps_independent_evidence_as_partial():
    provider, _ = provider_for(b'{"total_available": "x", "total_paid_available": 2.5}')
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert snapshot.fetch_state == FetchState.PARTIAL
    assert snapshot.diagnostic.code == "partial_data"
    assert snapshot.fetched_at == NOW
    rows = by_id(snapshot)
    assert rows[MetricId.OPENAI_AVAILABLE_BALANCE].state == MetricState.UNKNOWN
    assert rows[MetricId.OPENAI_PAID_AVAILABLE_BALANCE].exact_balance.amount == Decimal("2.5")


@pytest.mark.parametrize("paid", [b'"4.9"', b"true", b"1e999999", b"{}"])
async def test_invalid_paid_is_not_a_row_and_marks_partial(paid):
    provider, _ = provider_for(b'{"total_available": 4.9, "total_paid_available": ' + paid + b"}")
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert snapshot.fetch_state == FetchState.PARTIAL
    assert [row.id for row in snapshot.metrics] == [MetricId.OPENAI_AVAILABLE_BALANCE]
    assert snapshot.metrics[0].exact_balance.amount == Decimal("4.9")
    assert snapshot.metrics[0].detail == "付费余额格式不受支持"


async def test_null_paid_is_absent_not_zero():
    provider, _ = provider_for(b'{"total_available": 4.9, "total_paid_available": null}')
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert snapshot.fetch_state == FetchState.OK
    assert [row.id for row in snapshot.metrics] == [MetricId.OPENAI_AVAILABLE_BALANCE]
    # Nothing beyond the balance itself was reported, so no detail is shown.
    assert snapshot.metrics[0].detail is None


@pytest.mark.parametrize(
    "grants",
    [
        {"data": "nope"},
        [],
        {"data": [{"grant_amount": "18.0", "used_amount": 0, "expires_at": 1}]},
        {"data": [{"grant_amount": 1, "used_amount": 0, "expires_at": True}]},
        {"data": [{"grant_amount": 1, "used_amount": 0, "expires_at": -5}]},
        {"data": [{"grant_amount": 1, "used_amount": 0, "expires_at": 1e30}]},
        {"data": [{"grant_amount": 1, "used_amount": 0, "expires_at": 1, "effective_at": "x"}]},
        {"data": [7]},
    ],
)
async def test_invalid_grants_make_summary_partial_never_zero(grants):
    provider, _ = provider_for({"total_available": 4, "grants": grants})
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert snapshot.fetch_state == FetchState.PARTIAL
    assert snapshot.diagnostic.code == "partial_data"
    row = snapshot.metrics[0]
    assert row.state == MetricState.READY
    assert row.exact_balance.amount == Decimal(4)
    assert "笔无效" in row.detail or row.detail == "授予列表无效"


async def test_hostile_grant_exponent_is_invalid_not_expanded():
    body = (
        b'{"total_available": 1, "grants": {"data": ['
        b'{"grant_amount": 1e999999, "used_amount": 0, "expires_at": 1}]}}'
    )
    provider, _ = provider_for(body)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert snapshot.fetch_state == FetchState.PARTIAL
    assert snapshot.metrics[0].detail == "0 笔授予，1 笔无效"


async def test_future_grant_expiry_is_detail_only_not_a_reset():
    future = int((NOW + timedelta(days=30)).timestamp())
    body = {
        "total_available": 5,
        "grants": {"data": [{"grant_amount": 5, "used_amount": 0, "expires_at": future}]},
    }
    provider, _ = provider_for(body)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    row = snapshot.metrics[0]
    assert snapshot.fetch_state == FetchState.OK
    assert row.reset_at is None and row.expires_at is None
    assert row.detail == "1 笔授予，最早 2026-11-27 到期"


PERMISSION_DETAIL = "权限不足：需要该组织的计费权限，且组织须为预付费。"


@pytest.mark.parametrize(
    "status,body,state,code,detail",
    [
        (
            401,
            {},
            FetchState.AUTH_REQUIRED,
            "auth_required",
            "会话被拒绝：请粘贴新的会话密钥重新连接。",
        ),
        (
            401,
            {"error": {"code": "expired_session_key", "message": "x"}},
            FetchState.AUTH_REQUIRED,
            "credential_expired",
            "会话已过期：请粘贴新的会话密钥重新连接。",
        ),
        (
            400,
            {"error": {"code": "expired_session_key"}},
            FetchState.AUTH_REQUIRED,
            "credential_expired",
            "会话已过期：请粘贴新的会话密钥重新连接。",
        ),
        (
            403,
            {"error": {"message": "Your request must be made with a session key (...)"}},
            FetchState.AUTH_REQUIRED,
            "credential_mismatch",
            "仅支持 platform.openai.com 会话密钥，API key（sk-...）不可用。",
        ),
        (403, {}, FetchState.PERMISSION_DENIED, "permission_denied", PERMISSION_DETAIL),
        (
            403,
            {"error": {"code": "personal_organization_access_blocked"}},
            FetchState.PERMISSION_DENIED,
            "permission_denied",
            PERMISSION_DETAIL,
        ),
        (404, {}, FetchState.PROVIDER_ERROR, "provider_error", "余额不可用。"),
        (503, {}, FetchState.PROVIDER_ERROR, "provider_error", "余额不可用。"),
    ],
)
async def test_http_failures_are_curated_unknown_rows(status, body, state, code, detail):
    provider, requests = provider_for(body, status=status)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert len(requests) == 1
    assert_safe(snapshot)
    assert snapshot.fetch_state == state
    assert snapshot.diagnostic.code == code
    assert snapshot.fetched_at is None
    assert [row.id for row in snapshot.metrics] == [MetricId.OPENAI_AVAILABLE_BALANCE]
    assert snapshot.metrics[0].state == MetricState.UNKNOWN
    assert snapshot.metrics[0].exact_balance is None
    assert snapshot.metrics[0].detail == detail
    assert "must be made" not in snapshot.metrics[0].detail


async def test_rate_limit_carries_retry_deadline():
    provider, _ = provider_for({}, status=429, headers={"Retry-After": "120"}, clock=lambda: NOW)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert snapshot.fetch_state == FetchState.RATE_LIMITED
    assert snapshot.diagnostic.code == "rate_limited"
    assert snapshot.retry_at == NOW + timedelta(seconds=120)
    assert snapshot.metrics[0].state == MetricState.UNKNOWN


def _foreign(**changes):
    return replace(CREDENTIAL, **changes)


@pytest.mark.parametrize(
    "account,credential,code",
    [
        (ACCOUNT, None, "credential_unavailable"),
        (
            ACCOUNT,
            _foreign(organization_id="org-OtherSynthetic9"),
            "credential_mismatch",
        ),
        (ACCOUNT, _foreign(secret="Bearer synthetic-openai-session"), "credential_mismatch"),
        (ACCOUNT, _foreign(secret="sk-a b-synthetic-openai-session"), "credential_mismatch"),
        (ACCOUNT, _foreign(secret="short-session"), "credential_mismatch"),
        (ACCOUNT, _foreign(secret=" synthetic-openai-session-0000"), "credential_mismatch"),
        (
            ACCOUNT,
            _foreign(expires_at=NOW - timedelta(seconds=1)),
            "credential_expired",
        ),
    ],
)
async def test_credential_problems_fail_before_any_request(account, credential, code):
    provider, requests = provider_for({"total_available": 1})
    snapshot = await provider.fetch(account, credential, NOW)
    assert requests == []
    assert snapshot.fetch_state == FetchState.AUTH_REQUIRED
    assert snapshot.diagnostic.code == code
    assert snapshot.metrics[0].state == MetricState.UNKNOWN


async def test_other_provider_credential_is_rejected_before_any_request():
    provider, requests = provider_for({"total_available": 1})
    claude = ResolvedCredential(
        ProviderId.CLAUDE_SUBSCRIPTION, CredentialKind.CLAUDE_CODE_FILE, SESSION, "generation-1"
    )
    console = ResolvedCredential(
        ProviderId.CLAUDE_PLATFORM, CredentialKind.CONSOLE_SESSION, SESSION, "generation-1"
    )
    for credential in (claude, console):
        snapshot = await provider.fetch(ACCOUNT, credential, NOW)
        assert snapshot.diagnostic.code == "credential_mismatch"
    assert requests == []


async def test_account_for_another_provider_is_rejected_before_any_request():
    provider, requests = provider_for({"total_available": 1})
    other = Account(
        "00000000-0000-0000-0000-000000000008",
        ProviderId.CLAUDE_PLATFORM,
        "Synthetic Platform",
        credential_kind=CredentialKind.CONSOLE_SESSION,
        credential_ref="memory:synthetic",
        organization_id="org-selected",
    )
    snapshot = await provider.fetch(other, CREDENTIAL, NOW)
    assert requests == []
    assert snapshot.diagnostic.code == "credential_mismatch"
    assert snapshot.organization_id is None


async def test_unexpired_credential_reads():
    provider, requests = provider_for({"total_available": 1})
    snapshot = await provider.fetch(ACCOUNT, _foreign(expires_at=NOW + timedelta(days=1)), NOW)
    assert len(requests) == 1
    assert snapshot.fetch_state == FetchState.OK


async def test_forged_api_key_kind_is_rejected_before_any_request():
    # Construction already refuses API keys for this provider; a forged object
    # still never reaches the network.
    forged = replace(CREDENTIAL)
    object.__setattr__(forged, "credential_kind", CredentialKind.API_KEY)
    provider, requests = provider_for({"total_available": 1})
    snapshot = await provider.fetch(ACCOUNT, forged, NOW)
    assert requests == []
    assert snapshot.diagnostic.code == "credential_mismatch"
