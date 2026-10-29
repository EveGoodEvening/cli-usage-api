"""Grok contracts exercised only through synthetic in-memory HTTP."""

import copy
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from usage_tui.domain import (
    REQUIRED_METRIC_IDS,
    Account,
    CredentialKind,
    FetchState,
    MetricState,
    ProviderId,
    ResolvedCredential,
    SourceKind,
)
from usage_tui.providers.grok import GrokProvider
from usage_tui.transport import Transport

NOW = datetime(2026, 10, 28, 12, tzinfo=UTC)
ACCOUNT = Account(
    "00000000-0000-0000-0000-000000000006",
    ProviderId.GROK_SUBSCRIPTION,
    "Synthetic Grok",
    credential_ref="memory:synthetic",
    credential_kind=CredentialKind.MANUAL_BEARER,
)
CREDENTIAL = ResolvedCredential(
    ACCOUNT.provider, CredentialKind.MANUAL_BEARER, "synthetic-secret", "generation-1"
)
RESET = datetime(2026, 11, 2, tzinfo=UTC)


@pytest.fixture
def payload():
    return json.loads((Path(__file__).parent / "fixtures" / "grok_billing.json").read_text())


def provider_for(payload, *, status=200, headers=None, credential=CREDENTIAL):
    requests = []

    def handler(request):
        requests.append(request)
        assert request.method == "GET"
        assert str(request.url) == "https://cli-chat-proxy.grok.com/v1/billing?format=credits"
        assert request.headers["authorization"] == f"Bearer {credential.secret}"
        assert request.headers["x-xai-token-auth"] == "xai-grok-cli"
        assert request.headers["accept"] == "application/json"
        assert request.headers["x-grok-client-version"] == "1.0.70"
        assert request.headers["user-agent"].startswith("usage-tui/")
        assert "cookie" not in request.headers
        if credential.user_id is None:
            assert "x-userid" not in request.headers
        else:
            assert request.headers["x-userid"] == credential.user_id
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        return httpx.Response(status, content=body, headers=headers)

    return GrokProvider(Transport(http_transport=httpx.MockTransport(handler))), requests


def assert_rows(snapshot):
    assert tuple(row.id for row in snapshot.metrics[:3]) == REQUIRED_METRIC_IDS[ACCOUNT.provider]
    assert snapshot.grants == ()
    assert all(row.source.kind == SourceKind.PRIVATE_HTTP for row in snapshot.metrics)
    assert all(row.source.version_sensitive for row in snapshot.metrics)
    assert all(row.balance is None for row in snapshot.metrics)
    # Products must NEVER acquire 100-share independent remaining percentages.
    assert all(row.quota is None for row in snapshot.metrics[1:])


async def test_fixture_exact_single_read(payload):
    provider, requests = provider_for(payload)
    assert requests == []
    assert provider.requires_credential is True
    assert provider.metric_ids == REQUIRED_METRIC_IDS[ACCOUNT.provider]
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert_rows(snapshot)
    assert len(requests) == 1
    assert snapshot.fetch_state == FetchState.OK
    assert snapshot.diagnostic is None
    assert snapshot.fetched_at == snapshot.attempted_at == NOW
    pool, build, chat = snapshot.metrics
    assert pool.quota.used_percent == Decimal("42.5")
    assert pool.quota.remaining_percent == Decimal("57.5")
    assert pool.quota.limit_count is pool.quota.used_count is None
    assert "weekly" in pool.detail
    assert "Synthetic plan" in pool.detail
    assert all(row.reset_at == RESET for row in snapshot.metrics)
    assert "32.5%" in build.detail and "10%" in chat.detail
    assert build.share_percent == Decimal("32.5") and chat.share_percent == Decimal(10)
    assert pool.share_percent is None
    for row in (build, chat):
        assert row.shared_pool_id == pool.id
        assert "剩余/重置：共享池" in row.detail


@pytest.mark.parametrize("kind", [CredentialKind.MANUAL_BEARER, CredentialKind.GROK_AUTH_FILE])
async def test_supported_credentials_same_identity_user_header(payload, kind):
    credential = replace(CREDENTIAL, credential_kind=kind, user_id="synthetic-user")
    account = replace(ACCOUNT, credential_kind=kind)
    provider, requests = provider_for(payload, credential=credential)
    assert (await provider.fetch(account, credential, NOW)).fetch_state == FetchState.OK
    assert len(requests) == 1


@pytest.mark.parametrize("value", [0, 100, 150, 0.1, "1e-1000", "1e1000"])
async def test_aggregate_exact_overage_and_explicit_product_zero(payload, value):
    config = payload["config"]
    config["creditUsagePercent"] = value
    config["productUsage"] = [
        {"product": "GrokBuild", "usagePercent": value},
        {"product": "GrokChat", "usagePercent": 0},
    ]
    provider, _ = provider_for(payload)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert snapshot.fetch_state == FetchState.OK
    assert_rows(snapshot)
    pool, build, chat = snapshot.metrics
    assert pool.quota.used_percent == Decimal(str(value))
    assert pool.quota.remaining_percent >= 0
    if Decimal(str(value)) >= 100:
        assert pool.quota.remaining_percent == 0
    assert build.state == chat.state == MetricState.READY
    assert "0%" in chat.detail


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        False,
        -1,
        "NaN",
        "Infinity",
        "-Infinity",
        "1e1001",
        "1e-1001",
        "9" * 1025,
        "0" * 4097,
        [],
        {},
        "invalid",
    ],
)
async def test_invalid_present_aggregate_no_products_or_inference(payload, value):
    payload["config"]["creditUsagePercent"] = value
    payload["config"]["onDemandUsed"] = 10
    payload["config"]["onDemandCap"] = 100
    provider, _ = provider_for(payload)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert_rows(snapshot)
    assert snapshot.fetch_state == FetchState.SCHEMA_ERROR
    assert snapshot.fetched_at is None
    assert all(row.state == MetricState.UNKNOWN for row in snapshot.metrics)
    assert all(row.quota is None and row.reset_at is None for row in snapshot.metrics)


@pytest.mark.parametrize("value", ["1e1001", "1e-1001", "1." + "1" * 1024])
async def test_raw_numeric_aggregate_percent_bounds(payload, value):
    payload["config"]["creditUsagePercent"] = "WIRE_PERCENT"
    body = json.dumps(payload).encode().replace(b'"WIRE_PERCENT"', value.encode())
    provider, _ = provider_for(body)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert snapshot.fetch_state == FetchState.SCHEMA_ERROR
    assert snapshot.fetched_at is None
    assert all(row.state == MetricState.UNKNOWN for row in snapshot.metrics)
    assert all(row.quota is None and row.reset_at is None for row in snapshot.metrics)


@pytest.mark.parametrize("value", [False, None, 1, "true", [], {}])
async def test_only_boolean_true_proves_unified_semantics(payload, value):
    payload["config"]["isUnifiedBillingUser"] = value
    provider, _ = provider_for(payload)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert_rows(snapshot)
    assert snapshot.fetch_state == FetchState.PARTIAL
    assert snapshot.fetched_at == NOW
    assert all(row.state == MetricState.READY for row in snapshot.metrics)
    assert all(row.quota is None for row in snapshot.metrics)
    assert all(row.shared_pool_id is None and row.reset_at is None for row in snapshot.metrics)
    assert "42.5%" in snapshot.metrics[0].detail
    assert "Pool relationship unknown" in snapshot.metrics[0].detail
    # The aggregate is reported consumption only, never a derived remaining.
    assert snapshot.metrics[0].share_percent == Decimal("42.5")
    assert all(row.share_percent is not None for row in snapshot.metrics[1:])
    assert "32.5%" in snapshot.metrics[1].detail


async def test_absence_is_unknown_not_zero(payload):
    del payload["config"]["productUsage"][1]
    payload["config"]["creditUsagePercent"] = 32.5
    provider, _ = provider_for(payload)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert snapshot.fetch_state == FetchState.PARTIAL
    assert snapshot.metrics[1].state == MetricState.READY
    assert snapshot.metrics[2].state == MetricState.UNKNOWN
    assert snapshot.metrics[2].shared_pool_id is None
    assert snapshot.metrics[2].reset_at is None


@pytest.mark.parametrize(
    "entries",
    [
        None,
        {},
        [None],
        [{}],
        [{"product": True, "usagePercent": 42.5}],
        [{"product": "", "usagePercent": 42.5}],
        [{"product": "GrokBuild", "usagePercent": 42.5}] * 2,
        [
            {"product": "GrokBuild", "usagePercent": 32.5},
            {"product": "GrokChat", "usagePercent": -1},
        ],
        [
            {"product": "GrokBuild", "usagePercent": 32.5},
            {"product": "Other", "usagePercent": "NaN"},
        ],
        [{"product": "GrokBuild", "usagePercent": True}],
        [{"product": "GrokBuild", "usagePercent": "1e1001"}],
        [{"product": "GrokBuild", "usagePercent": None}],
        [],
    ],
)
async def test_entire_breakdown_rejected_preserving_aggregate(payload, entries):
    payload["config"]["productUsage"] = entries
    provider, _ = provider_for(payload)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert_rows(snapshot)
    assert snapshot.fetch_state == FetchState.PARTIAL
    assert snapshot.metrics[0].quota.used_percent == Decimal("42.5")
    assert all(row.state == MetricState.UNKNOWN for row in snapshot.metrics[1:])


@pytest.mark.parametrize(
    "share",
    ["0", "41.499999999999999999999999999999", "43.500000000000000000000000000001", "150"],
)
@pytest.mark.parametrize("raw_number", [False, True])
async def test_informational_products_need_not_reconcile_with_total(payload, share, raw_number):
    payload["config"]["productUsage"] = [
        {"product": "GrokBuild", "usagePercent": "WIRE_SHARE" if raw_number else share},
        {"product": "GrokChat", "usagePercent": 0},
    ]
    body = (
        json.dumps(payload).encode().replace(b'"WIRE_SHARE"', share.encode())
        if raw_number
        else payload
    )
    provider, _ = provider_for(body)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert snapshot.fetch_state == FetchState.OK
    assert snapshot.metrics[0].quota.used_percent == Decimal("42.5")
    assert all(row.state == MetricState.READY for row in snapshot.metrics)
    assert f"{Decimal(share)}%" in snapshot.metrics[1].detail
    # Raw wire numbers stay exact Decimals in the structured share.
    assert type(snapshot.metrics[1].share_percent) is Decimal
    assert str(snapshot.metrics[1].share_percent) == str(Decimal(share))
    assert snapshot.metrics[1].quota is None
    assert snapshot.metrics[1].shared_pool_id == snapshot.metrics[0].id


@pytest.mark.parametrize("share", ["1e1001", "1e-1001", "1." + "1" * 1024])
async def test_raw_numeric_product_percent_bounds_preserve_aggregate(payload, share):
    payload["config"]["productUsage"] = [
        {"product": "GrokBuild", "usagePercent": "WIRE_SHARE"},
        {"product": "GrokChat", "usagePercent": 0},
    ]
    body = json.dumps(payload).encode().replace(b'"WIRE_SHARE"', share.encode())
    provider, _ = provider_for(body)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert snapshot.fetch_state == FetchState.PARTIAL
    assert snapshot.metrics[0].quota.used_percent == Decimal("42.5")
    assert all(row.state == MetricState.UNKNOWN for row in snapshot.metrics[1:])
    assert all(row.share_percent is None for row in snapshot.metrics[1:])


async def test_unknown_products_retained_sanitized_and_informational(payload):
    config = payload["config"]
    config["creditUsagePercent"] = 50
    config["productUsage"].append({"product": "\u001b[31m[Other]\n", "usagePercent": 7.5})
    provider, _ = provider_for(payload)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert snapshot.fetch_state == FetchState.OK
    assert len(snapshot.metrics) == 4
    extra = snapshot.metrics[3]
    assert extra.id.startswith("grok.product.other.")
    assert "Other" in extra.label
    assert "\u001b" not in extra.label and "[" not in extra.label and "\n" not in extra.label
    assert "7.5%" in extra.detail
    assert extra.shared_pool_id == snapshot.metrics[0].id
    assert extra.quota is None
    # Repeat payload and order changes retain the same nonsecret stable extra ID.
    config["productUsage"].reverse()
    again = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert again.metrics[3].id == extra.id


@pytest.mark.parametrize("period_type", ["USAGE_PERIOD_TYPE_MONTHLY", "FUTURE", None, {}])
async def test_period_type_does_not_infer_plan_or_quota(payload, period_type):
    payload["config"]["currentPeriod"]["type"] = period_type
    provider, _ = provider_for(payload)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    expected = "monthly" if period_type == "USAGE_PERIOD_TYPE_MONTHLY" else "period"
    assert f"Server period: {expected}." in snapshot.metrics[0].detail
    assert snapshot.metrics[0].reset_at == RESET


async def test_fallback_only_when_current_end_absent(payload):
    config = payload["config"]
    config["billingPeriodEnd"] = "2026-12-01T00:00:00Z"
    provider, _ = provider_for(payload)
    assert (await provider.fetch(ACCOUNT, CREDENTIAL, NOW)).metrics[0].reset_at == RESET
    del config["currentPeriod"]["end"]
    provider, _ = provider_for(payload)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert snapshot.metrics[0].reset_at == datetime(2026, 12, 1, tzinfo=UTC)
    config["currentPeriod"]["end"] = None
    provider, _ = provider_for(payload)
    assert (await provider.fetch(ACCOUNT, CREDENTIAL, NOW)).metrics[0].reset_at is None


@pytest.mark.parametrize(
    "bad",
    [None, 1793577600, 1793577600000, "2026-11-02", "2026-11-02T00:00:00", "invalid", {}, []],
)
async def test_invalid_reset_keeps_aggregate_and_products(payload, bad):
    payload["config"]["currentPeriod"]["end"] = bad
    payload["config"]["billingPeriodEnd"] = "2026-12-01T00:00:00Z"
    provider, _ = provider_for(payload)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert snapshot.fetch_state == FetchState.PARTIAL
    assert all(row.state == MetricState.READY for row in snapshot.metrics)
    assert all(row.reset_at is None for row in snapshot.metrics)
    assert snapshot.metrics[0].quota.used_percent == Decimal("42.5")


@pytest.mark.parametrize(
    "period",
    [
        None,
        [],
        {},
        {"start": "2026-12-01T00:00:00Z", "end": "2026-11-02T00:00:00Z"},
        {"start": "bad", "end": "2026-11-02T00:00:00Z"},
    ],
)
async def test_missing_or_reversed_period_preserves_consumption(payload, period):
    payload["config"]["currentPeriod"] = period
    provider, _ = provider_for(payload)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert snapshot.fetch_state == FetchState.PARTIAL
    assert snapshot.metrics[0].quota is not None
    assert all(row.reset_at is None for row in snapshot.metrics)


async def test_missing_optional_period_start_and_timezone_normalization(payload):
    period = payload["config"]["currentPeriod"]
    del period["start"]
    period["end"] = "2026-11-02T02:00:00+02:00"
    provider, _ = provider_for(payload)
    assert (await provider.fetch(ACCOUNT, CREDENTIAL, NOW)).metrics[0].reset_at == RESET


@pytest.mark.parametrize("root", [[], None, {}, {"config": None}, {"config": []}])
async def test_malformed_root_returns_safe_required_unknown_rows(root):
    provider, requests = provider_for(root)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert_rows(snapshot)
    assert len(requests) == 1
    assert snapshot.fetch_state == FetchState.SCHEMA_ERROR
    assert snapshot.fetched_at is None
    assert snapshot.diagnostic.code == "schema_error"


async def test_no_cross_payload_or_account_enrichment(payload):
    provider, _ = provider_for(payload)
    first = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert first.metrics[1].state == MetricState.READY
    missing = copy.deepcopy(payload)
    missing["config"]["creditUsagePercent"] = None
    next_provider, _ = provider_for(missing)
    second = await next_provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert all(row.state == MetricState.UNKNOWN for row in second.metrics)
    del payload["config"]["productUsage"]
    next_provider, _ = provider_for(payload)
    third = await next_provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert third.metrics[0].state == MetricState.READY
    assert all(row.state == MetricState.UNKNOWN for row in third.metrics[1:])


@pytest.mark.parametrize(
    "status,expected",
    [
        (401, FetchState.AUTH_REQUIRED),
        (403, FetchState.PERMISSION_DENIED),
        (429, FetchState.RATE_LIMITED),
        (426, FetchState.PROVIDER_ERROR),
        (500, FetchState.PROVIDER_ERROR),
    ],
)
async def test_transport_errors_safe_and_retry_preserved(status, expected):
    secret_body = {"message": "synthetic-secret personal@example.invalid sensitive"}
    provider, _ = provider_for(secret_body, status=status, headers={"Retry-After": "120"})
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert_rows(snapshot)
    assert snapshot.fetch_state == expected
    assert snapshot.fetched_at is None
    assert all(row.state == MetricState.UNKNOWN for row in snapshot.metrics)
    assert "synthetic-secret" not in repr(snapshot)
    assert "personal@" not in repr(snapshot)
    if status == 429:
        assert snapshot.retry_at is not None


async def test_network_error_safe():
    def handler(request):
        raise httpx.ConnectError("synthetic-secret sensitive path", request=request)

    provider = GrokProvider(Transport(http_transport=httpx.MockTransport(handler)))
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert snapshot.fetch_state == FetchState.NETWORK_ERROR
    assert "synthetic-secret" not in repr(snapshot)


@pytest.mark.parametrize(
    "case", ["missing", "provider", "kind", "account_provider", "expired", "api_prefix"]
)
async def test_credential_rejection_happens_before_http(payload, case):
    account, credential = ACCOUNT, CREDENTIAL
    if case == "missing":
        credential = None
    elif case == "provider":
        credential = replace(CREDENTIAL, provider=ProviderId.CLAUDE_SUBSCRIPTION)
    elif case == "kind":
        account = replace(ACCOUNT, credential_kind=CredentialKind.API_KEY)
        credential = replace(CREDENTIAL, credential_kind=CredentialKind.API_KEY)
    elif case == "account_provider":
        account = replace(ACCOUNT, provider=ProviderId.CLAUDE_SUBSCRIPTION)
    elif case == "expired":
        credential = replace(CREDENTIAL, expires_at=NOW - timedelta(seconds=1))
    else:
        credential = replace(CREDENTIAL, secret="xai-synthetic-key")
    provider, requests = provider_for(payload)
    snapshot = await provider.fetch(account, credential, NOW)
    assert snapshot.fetch_state == FetchState.AUTH_REQUIRED
    assert requests == []
    assert snapshot.fetched_at is None


async def test_plan_metadata_sanitized_not_assumed_quota(payload):
    config = payload["config"]
    del config["subscriptionTier"]
    config["subscription_tier"] = "\u001b[31m[Unknown plan]\n"
    provider, _ = provider_for(payload)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    detail = snapshot.metrics[0].detail
    assert "Unknown plan" in detail and "no assumed quota" in detail
    assert "\u001b" not in detail and "[" not in detail and "\n" not in detail
    assert snapshot.metrics[0].quota.limit_count is None


@pytest.mark.parametrize("field", ["productUsage", "isUnifiedBillingUser"])
async def test_omitted_non_scalar_usage_fields_never_inferred(payload, field):
    del payload["config"][field]
    provider, _ = provider_for(payload)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    if field == "productUsage":
        assert snapshot.metrics[0].quota.used_percent == Decimal("42.5")
        assert all(row.state == MetricState.UNKNOWN for row in snapshot.metrics[1:])
    else:
        assert all(row.quota is None and row.shared_pool_id is None for row in snapshot.metrics)
        assert all(row.reset_at is None for row in snapshot.metrics)


async def test_no_current_period_can_use_explicit_fallback(payload):
    del payload["config"]["currentPeriod"]
    payload["config"]["billingPeriodEnd"] = "2026-11-02T00:00:00Z"
    provider, _ = provider_for(payload)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert snapshot.fetch_state == FetchState.OK
    assert all(row.reset_at == RESET for row in snapshot.metrics)
    assert "Server period: period." in snapshot.metrics[0].detail


async def test_empty_array_does_not_prove_build_chat_zero(payload):
    payload["config"]["creditUsagePercent"] = 0
    payload["config"]["productUsage"] = []
    provider, _ = provider_for(payload)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert snapshot.metrics[0].quota.used_percent == 0
    assert all(row.state == MetricState.UNKNOWN for row in snapshot.metrics[1:])


async def test_unknown_duplicate_invalidates_entire_array(payload):
    payload["config"]["productUsage"] += [
        {"product": "Other", "usagePercent": 0},
        {"product": "Other", "usagePercent": 0},
    ]
    provider, _ = provider_for(payload)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert len(snapshot.metrics) == 3
    assert all(row.state == MetricState.UNKNOWN for row in snapshot.metrics[1:])


@pytest.mark.parametrize("name", ["\ud800", "\u001b[31m[]\n"])
async def test_unknown_product_hostile_identifier_remains_visible(payload, name):
    payload["config"]["productUsage"].append({"product": name, "usagePercent": 0})
    provider, _ = provider_for(payload)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert snapshot.fetch_state == FetchState.OK
    assert snapshot.metrics[3].label
    assert snapshot.metrics[3].id.startswith("grok.product.other.")


async def test_exact_expiry_and_kind_mismatch_rejected_before_http(payload):
    provider, requests = provider_for(payload)
    for credential in (
        replace(CREDENTIAL, expires_at=NOW),
        replace(CREDENTIAL, credential_kind=CredentialKind.GROK_AUTH_FILE),
    ):
        snapshot = await provider.fetch(ACCOUNT, credential, NOW)
        assert snapshot.fetch_state == FetchState.AUTH_REQUIRED
    assert requests == []


async def test_malformed_json_response_is_safe():
    def handler(request):
        return httpx.Response(200, content=b'{"secret": synthetic-secret}')

    provider = GrokProvider(Transport(http_transport=httpx.MockTransport(handler)))
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert snapshot.fetch_state == FetchState.SCHEMA_ERROR
    assert "synthetic-secret" not in repr(snapshot)


async def test_raw_http_protojson_omitted_zero_with_weekly_context():
    body = (Path(__file__).parent / "fixtures" / "grok_billing_omitted_zero.json").read_bytes()
    provider, requests = provider_for(body)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert len(requests) == 1
    assert snapshot.fetch_state == FetchState.OK
    assert_rows(snapshot)
    assert snapshot.metrics[0].quota.used_percent == Decimal(0)
    assert snapshot.metrics[0].quota.remaining_percent == Decimal(100)
    assert all(row.reset_at == RESET for row in snapshot.metrics)
    assert all(row.state == MetricState.READY for row in snapshot.metrics)
    assert all("0%" in row.detail for row in snapshot.metrics)
    assert all(row.shared_pool_id == snapshot.metrics[0].id for row in snapshot.metrics[1:])


@pytest.mark.parametrize(
    "period",
    [
        None,
        [],
        {},
        {"type": "USAGE_PERIOD_TYPE_MONTHLY"},
        {"type": "FUTURE"},
        {"type": "USAGE_PERIOD_TYPE_WEEKLY", "end": None},
        {"type": "USAGE_PERIOD_TYPE_WEEKLY", "start": "2026-12-01T00:00:00Z"},
    ],
)
async def test_missing_aggregate_without_valid_weekly_context_is_not_zero(payload, period):
    config = payload["config"]
    del config["creditUsagePercent"]
    config["currentPeriod"] = period
    config["billingPeriodEnd"] = "2026-11-02T00:00:00Z"
    provider, _ = provider_for(payload)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert snapshot.fetch_state == FetchState.SCHEMA_ERROR
    assert snapshot.fetched_at is None
    assert all(row.state == MetricState.UNKNOWN for row in snapshot.metrics)


async def test_no_period_or_reset_cannot_prove_omitted_aggregate_zero(payload):
    config = payload["config"]
    del config["creditUsagePercent"]
    del config["currentPeriod"]
    config["billingPeriodEnd"] = "2026-11-02T00:00:00Z"
    provider, _ = provider_for(payload)
    assert (await provider.fetch(ACCOUNT, CREDENTIAL, NOW)).fetch_state == FetchState.SCHEMA_ERROR
    config["currentPeriod"] = {"type": "USAGE_PERIOD_TYPE_WEEKLY"}
    del config["billingPeriodEnd"]
    provider, _ = provider_for(payload)
    assert (await provider.fetch(ACCOUNT, CREDENTIAL, NOW)).fetch_state == FetchState.SCHEMA_ERROR


@pytest.mark.parametrize("weekly", [False, True])
async def test_present_product_omitted_percent_requires_weekly_context(payload, weekly):
    config = payload["config"]
    if not weekly:
        config["currentPeriod"]["type"] = "USAGE_PERIOD_TYPE_MONTHLY"
    config["productUsage"] = [{"product": "GrokBuild"}]
    provider, _ = provider_for(payload)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert snapshot.fetch_state == FetchState.PARTIAL
    assert snapshot.metrics[0].quota.used_percent == Decimal("42.5")
    assert snapshot.metrics[1].state == (MetricState.READY if weekly else MetricState.UNKNOWN)
    if weekly:
        assert "0%" in snapshot.metrics[1].detail
    assert snapshot.metrics[2].state == MetricState.UNKNOWN
    assert snapshot.metrics[2].shared_pool_id is None


async def test_empty_config_cannot_be_defaulted_to_zero():
    provider, _ = provider_for(b'{"config":{}}')
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert snapshot.fetch_state == FetchState.SCHEMA_ERROR
    assert all(row.state == MetricState.UNKNOWN for row in snapshot.metrics)
