"""Claude adapter contracts using real Transport with synthetic in-memory HTTP."""

import asyncio
import copy
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
    FetchState,
    MetricId,
    MetricState,
    Money,
    ProviderId,
    ResolvedCredential,
    Snapshot,
    SourceKind,
)
from cli_usage_api.providers.claude import ClaudeProvider
from cli_usage_api.transport import Transport

NOW = datetime(2026, 10, 28, 12, tzinfo=UTC)
ACCOUNT = Account(
    "00000000-0000-0000-0000-000000000004",
    ProviderId.CLAUDE_SUBSCRIPTION,
    "Synthetic Claude",
    credential_ref="memory:synthetic",
    credential_kind=CredentialKind.MANUAL_BEARER,
)
CREDENTIAL = ResolvedCredential(
    ACCOUNT.provider, CredentialKind.MANUAL_BEARER, "synthetic-secret", "generation-1"
)


@pytest.fixture
def payload():
    return json.loads((Path(__file__).parent / "fixtures" / "claude_usage.json").read_text())


def provider_for(payload, *, status=200, headers=None):
    requests = []

    def handler(request):
        requests.append(request)
        assert request.method == "GET"
        assert str(request.url) == "https://api.anthropic.com/api/oauth/usage"
        assert request.headers["authorization"] == "Bearer synthetic-secret"
        assert request.headers["anthropic-beta"] == "oauth-2025-04-20"
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        return httpx.Response(status, content=body, headers=headers)

    return ClaudeProvider(Transport(http_transport=httpx.MockTransport(handler))), requests


def assert_rows(snapshot):
    assert tuple(row.id for row in snapshot.metrics) == REQUIRED_METRIC_IDS[ACCOUNT.provider]
    assert all(row.source.kind == SourceKind.PRIVATE_HTTP for row in snapshot.metrics)
    assert all(row.source.version_sensitive for row in snapshot.metrics)
    assert all(row.balance is None and row.shared_pool_id is None for row in snapshot.metrics)
    assert snapshot.grants == ()


async def test_complete_fixture_one_read_and_exact_values(payload):
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
    assert [row.quota.used_percent for row in snapshot.metrics] == [
        Decimal("12.5"),
        Decimal("110.25"),
        Decimal("23.75"),
    ]
    assert [row.quota.remaining_percent for row in snapshot.metrics] == [
        Decimal("87.5"),
        Decimal(0),
        Decimal("76.25"),
    ]
    assert snapshot.metrics[0].reset_at == datetime(2026, 10, 28, 18, tzinfo=UTC)
    assert snapshot.metrics[2].reset_at == datetime(2026, 11, 1, 12, tzinfo=UTC)
    assert all(row.quota.used_count is None for row in snapshot.metrics)
    assert all(row.quota.limit_count is None for row in snapshot.metrics)


@pytest.mark.parametrize("raw", [0, 100, 150, 0.1, "12.345678901234567890123456789", "1e-1000"])
async def test_percent_values_are_exact_and_overage_not_clamped(payload, raw):
    payload["five_hour"]["utilization"] = raw
    provider, _ = provider_for(payload)
    row = (await provider.fetch(ACCOUNT, CREDENTIAL, NOW)).metrics[0]
    assert row.quota.used_percent == Decimal(str(raw))
    assert row.state == MetricState.READY


@pytest.mark.parametrize(
    "raw",
    [
        True,
        False,
        None,
        -1,
        "NaN",
        "Infinity",
        "-Infinity",
        "1e1001",
        "1e-1001",
        "9" * 1025,
        [],
        {},
        "oops",
    ],
)
async def test_invalid_percent_preserves_siblings(payload, raw):
    payload["five_hour"]["utilization"] = raw
    provider, requests = provider_for(payload)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert_rows(snapshot)
    assert len(requests) == 1
    assert snapshot.fetch_state == FetchState.PARTIAL
    assert snapshot.diagnostic.code == "partial_data"
    assert snapshot.metrics[0].state == MetricState.UNKNOWN
    assert snapshot.metrics[0].quota is None
    assert all(row.state == MetricState.READY for row in snapshot.metrics[1:])


async def test_percentage_alias_and_precedence(payload):
    payload["five_hour"] = {"used_percentage": 33.3}
    payload["seven_day"] = {"utilization": 20, "used_percentage": 90}
    provider, _ = provider_for(payload)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert snapshot.metrics[0].quota.used_percent == Decimal("33.3")
    assert snapshot.metrics[1].quota.used_percent == 20
    assert snapshot.fetch_state == FetchState.OK
    assert snapshot.metrics[0].reset_at is None


@pytest.mark.parametrize(
    "raw",
    [1793188800, 1793188800000, 1793188800.5, "2026-10-28T14:00:00+02:00", "2026-10-28T12:00:00Z"],
)
async def test_timestamp_formats(payload, raw):
    payload["five_hour"]["resets_at"] = raw
    provider, _ = provider_for(payload)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    expected = NOW + timedelta(microseconds=500000) if raw == 1793188800.5 else NOW
    assert snapshot.metrics[0].reset_at == expected
    assert snapshot.fetch_state == FetchState.OK


@pytest.mark.parametrize("raw", ["1793188800.5", "1793188800500.0"])
async def test_raw_fractional_numeric_reset_seconds_and_milliseconds(payload, raw):
    payload["five_hour"]["resets_at"] = "WIRE_RESET"
    body = json.dumps(payload).encode().replace(b'"WIRE_RESET"', raw.encode())
    provider, _ = provider_for(body)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert snapshot.fetch_state == FetchState.OK
    assert snapshot.metrics[0].reset_at == NOW + timedelta(microseconds=500000)
    assert snapshot.metrics[0].quota.used_percent == Decimal("12.5")


@pytest.mark.parametrize("raw", ["true", "false", "-0.5", "1e1000000"])
async def test_raw_invalid_numeric_reset_preserves_quota(payload, raw):
    payload["five_hour"]["resets_at"] = "WIRE_RESET"
    body = json.dumps(payload).encode().replace(b'"WIRE_RESET"', raw.encode())
    provider, _ = provider_for(body)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert snapshot.fetch_state == FetchState.PARTIAL
    assert snapshot.metrics[0].state == MetricState.READY
    assert snapshot.metrics[0].quota.used_percent == Decimal("12.5")
    assert snapshot.metrics[0].reset_at is None


@pytest.mark.parametrize(
    "raw",
    [
        True,
        False,
        0,
        -1,
        10**100,
        "2026-10-28T12:00:00",
        "2026-02-30T12:00:00Z",
        "bad",
        [],
        {},
        "1793188800",
    ],
)
async def test_invalid_reset_keeps_valid_quota_and_flags_partial(payload, raw):
    payload["five_hour"]["resets_at"] = raw
    provider, _ = provider_for(payload)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert snapshot.fetch_state == FetchState.PARTIAL
    assert snapshot.metrics[0].state == MetricState.READY
    assert snapshot.metrics[0].quota.used_percent == Decimal("12.5")
    assert snapshot.metrics[0].reset_at is None
    assert "invalid" in snapshot.metrics[0].detail
    assert snapshot.fetched_at == NOW


@pytest.mark.parametrize("alias", ["fable_weekly", "fable_seven_day", "seven_day_fable"])
async def test_fable_legacy_aliases(payload, alias):
    payload.pop("limits")
    payload[alias] = {"used_percentage": 42, "resets_at": None}
    provider, _ = provider_for(payload)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert snapshot.fetch_state == FetchState.OK
    assert snapshot.metrics[2].quota.used_percent == 42


async def test_fable_scoped_and_alias_precedence(payload):
    payload.update(
        fable_weekly={"utilization": 1},
        fable_seven_day={"utilization": 2},
        seven_day_fable={"utilization": 3},
    )
    provider, _ = provider_for(payload)
    assert (await provider.fetch(ACCOUNT, CREDENTIAL, NOW)).metrics[
        2
    ].quota.used_percent == Decimal("23.75")
    payload.pop("limits")
    provider, _ = provider_for(payload)
    assert (await provider.fetch(ACCOUNT, CREDENTIAL, NOW)).metrics[2].quota.used_percent == 1
    payload["fable_weekly"]["utilization"] = -1
    provider, _ = provider_for(payload)
    assert (await provider.fetch(ACCOUNT, CREDENTIAL, NOW)).metrics[2].quota.used_percent == 2


async def test_invalid_scoped_percentage_can_fall_back(payload):
    payload["limits"][0]["percent"] = "Infinity"
    payload["fable_weekly"] = {"utilization": 4}
    provider, _ = provider_for(payload)
    assert (await provider.fetch(ACCOUNT, CREDENTIAL, NOW)).metrics[2].quota.used_percent == 4


async def test_scoped_bad_reset_keeps_preferred_percentage(payload):
    payload["limits"][0]["resets_at"] = "bad"
    payload["fable_weekly"] = {"utilization": 4}
    provider, _ = provider_for(payload)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert snapshot.fetch_state == FetchState.PARTIAL
    assert snapshot.metrics[2].quota.used_percent == Decimal("23.75")
    assert snapshot.metrics[2].reset_at is None


@pytest.mark.parametrize("malformed_first", [False, True])
async def test_duplicate_bad_reset_preserves_equal_quota_and_siblings(payload, malformed_first):
    valid = copy.deepcopy(payload["limits"][0])
    malformed = copy.deepcopy(valid)
    malformed.update(percent="23.750", resets_at="bad")
    payload["limits"] = [malformed, valid] if malformed_first else [valid, malformed]
    payload["fable_weekly"] = {"utilization": 4}
    provider, requests = provider_for(payload)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert_rows(snapshot)
    assert len(requests) == 1
    assert snapshot.fetch_state == FetchState.PARTIAL
    assert snapshot.diagnostic.code == "partial_data"
    assert snapshot.fetched_at == NOW
    fable = snapshot.metrics[2]
    assert fable.state == MetricState.READY
    assert fable.quota.used_percent == Decimal("23.75")
    assert fable.reset_at is None
    assert "invalid" in fable.detail
    assert [row.quota.used_percent for row in snapshot.metrics[:2]] == [
        Decimal("12.5"),
        Decimal("110.25"),
    ]
    assert all(row.state == MetricState.READY for row in snapshot.metrics[:2])
    assert all(row.reset_at is not None and row.detail is None for row in snapshot.metrics[:2])


@pytest.mark.parametrize("malformed_first", [False, True])
@pytest.mark.parametrize("change", [{"percent": 5}, {"resets_at": "2026-11-02T12:00:00Z"}])
async def test_bad_reset_does_not_hide_conflicting_duplicates(payload, malformed_first, change):
    valid = copy.deepcopy(payload["limits"][0])
    conflicting = copy.deepcopy(valid)
    conflicting.update(change)
    malformed = copy.deepcopy(valid)
    malformed["resets_at"] = "bad"
    payload["limits"] = (
        [malformed, valid, conflicting] if malformed_first else [valid, conflicting, malformed]
    )
    payload["fable_weekly"] = {"utilization": 4}
    provider, _ = provider_for(payload)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert snapshot.fetch_state == FetchState.PARTIAL
    assert snapshot.metrics[2].state == MetricState.UNKNOWN
    assert snapshot.metrics[2].quota is None
    assert "Conflicting" in snapshot.metrics[2].detail
    assert all(row.state == MetricState.READY for row in snapshot.metrics[:2])


@pytest.mark.parametrize("change", [{"percent": 5}, {"resets_at": "2026-11-02T12:00:00Z"}])
async def test_conflicting_valid_scoped_duplicates_reject_fable_not_siblings(payload, change):
    duplicate = copy.deepcopy(payload["limits"][0])
    duplicate.update(change)
    payload["limits"].append(duplicate)
    payload["fable_weekly"] = {"utilization": 4}
    provider, _ = provider_for(payload)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert snapshot.fetch_state == FetchState.PARTIAL
    assert snapshot.metrics[2].state == MetricState.UNKNOWN
    assert "Conflicting" in snapshot.metrics[2].detail
    assert all(row.state == MetricState.READY for row in snapshot.metrics[:2])


async def test_equivalent_duplicates_are_not_conflicts(payload):
    duplicate = copy.deepcopy(payload["limits"][0])
    duplicate.update(percent="23.750", resets_at="2026-11-01T12:00:00Z", is_active=True)
    payload["limits"].extend([duplicate, {"kind": "weekly_scoped", "scope": []}])
    provider, _ = provider_for(payload)
    assert (await provider.fetch(ACCOUNT, CREDENTIAL, NOW)).fetch_state == FetchState.OK


@pytest.mark.parametrize(
    "limits",
    [
        None,
        {},
        [],
        [
            None,
            {},
            {"kind": "weekly_scoped", "scope": {"model": {"display_name": "Opus"}}, "percent": 20},
        ],
        [{"kind": "daily_scoped", "scope": {"model": {"display_name": "Fable"}}, "percent": 20}],
    ],
)
async def test_absent_fable_never_infers_eligibility_or_substitutes_opus(payload, limits):
    payload["limits"] = limits
    provider, _ = provider_for(payload)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert snapshot.fetch_state == FetchState.PARTIAL
    assert snapshot.metrics[2].state == MetricState.UNKNOWN
    assert snapshot.metrics[2].quota is None
    assert "eligibility" in snapshot.metrics[2].detail


@pytest.mark.parametrize(
    "root",
    [
        [],
        {},
        {"unknown": 1},
        {"five_hour": None},
        {"seven_day": {"utilization": -1}},
        {"limits": [None]},
    ],
)
async def test_no_usable_windows_is_schema_error(root):
    provider, requests = provider_for(root)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert_rows(snapshot)
    assert len(requests) == 1
    assert snapshot.fetch_state == FetchState.SCHEMA_ERROR
    assert snapshot.fetched_at is None
    assert snapshot.diagnostic.code == "schema_error"
    assert all(row.state == MetricState.UNKNOWN for row in snapshot.metrics)


@pytest.mark.parametrize(
    "status,state,code",
    [
        (401, FetchState.AUTH_REQUIRED, "auth_required"),
        (403, FetchState.PERMISSION_DENIED, "permission_denied"),
        (429, FetchState.RATE_LIMITED, "rate_limited"),
        (503, FetchState.PROVIDER_ERROR, "provider_error"),
    ],
)
async def test_transport_errors_are_normalized_without_body_leak(status, state, code):
    provider, requests = provider_for(
        {"secret": "DO-NOT-ECHO"}, status=status, headers={"Retry-After": "120"}
    )
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert_rows(snapshot)
    assert len(requests) == 1
    assert snapshot.fetch_state == state
    assert snapshot.diagnostic.code == code
    assert snapshot.fetched_at is None
    assert "DO-NOT-ECHO" not in repr(snapshot)
    assert (snapshot.retry_at is not None) == (status == 429)


async def test_network_error_is_normalized():
    def handler(request):
        raise httpx.ConnectError("DO-NOT-ECHO", request=request)

    provider = ClaudeProvider(Transport(http_transport=httpx.MockTransport(handler)))
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert_rows(snapshot)
    assert snapshot.fetch_state == FetchState.NETWORK_ERROR
    assert "DO-NOT-ECHO" not in repr(snapshot)


@pytest.mark.parametrize(
    "credential,code",
    [
        (None, "credential_unavailable"),
        (replace(CREDENTIAL, provider=ProviderId.GROK_SUBSCRIPTION), "credential_mismatch"),
        (replace(CREDENTIAL, credential_kind=CredentialKind.API_KEY), "credential_mismatch"),
        (
            replace(CREDENTIAL, credential_kind=CredentialKind.CLAUDE_CODE_FILE),
            "credential_mismatch",
        ),
        (replace(CREDENTIAL, expires_at=NOW), "credential_expired"),
    ],
)
async def test_missing_expired_or_mismatched_credential_never_requests(credential, code):
    provider, requests = provider_for({})
    snapshot = await provider.fetch(ACCOUNT, credential, NOW)
    assert_rows(snapshot)
    assert requests == []
    assert snapshot.fetch_state == FetchState.AUTH_REQUIRED
    assert snapshot.diagnostic.code == code
    assert snapshot.fetched_at is None


async def test_wrong_account_provider_never_requests():
    provider, requests = provider_for({})
    account = replace(ACCOUNT, provider=ProviderId.GROK_SUBSCRIPTION)
    snapshot = await provider.fetch(account, CREDENTIAL, NOW)
    assert requests == []
    assert snapshot.diagnostic.code == "credential_mismatch"


async def test_matching_imported_kind_is_supported(payload):
    account = replace(ACCOUNT, credential_kind=CredentialKind.CLAUDE_CODE_FILE)
    credential = replace(CREDENTIAL, credential_kind=CredentialKind.CLAUDE_CODE_FILE)
    provider, requests = provider_for(payload)
    assert (await provider.fetch(account, credential, NOW)).fetch_state == FetchState.OK
    assert len(requests) == 1


async def test_cancellation_propagates():
    async def handler(request):
        raise asyncio.CancelledError

    provider = ClaudeProvider(Transport(http_transport=httpx.MockTransport(handler)))
    with pytest.raises(asyncio.CancelledError):
        await provider.fetch(ACCOUNT, CREDENTIAL, NOW)


async def test_fable_only_response_retains_scoped_value(payload):
    payload.pop("five_hour")
    payload.pop("seven_day")
    provider, _ = provider_for(payload)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert_rows(snapshot)
    assert snapshot.fetch_state == FetchState.PARTIAL
    assert snapshot.fetched_at == NOW
    assert all(row.state == MetricState.UNKNOWN for row in snapshot.metrics[:2])
    assert snapshot.metrics[2].quota.used_percent == Decimal("23.75")


async def test_invalid_duplicate_does_not_poison_valid_scoped_value(payload):
    duplicate = copy.deepcopy(payload["limits"][0])
    duplicate["percent"] = -1
    payload["limits"].append(duplicate)
    provider, _ = provider_for(payload)
    assert (await provider.fetch(ACCOUNT, CREDENTIAL, NOW)).fetch_state == FetchState.OK


async def test_null_primary_percentage_can_use_alias(payload):
    payload["five_hour"] = {"utilization": None, "used_percentage": 0}
    provider, _ = provider_for(payload)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert snapshot.metrics[0].quota.used_percent == 0
    assert snapshot.fetch_state == FetchState.OK


async def test_invalid_primary_percentage_is_not_hidden_by_alias(payload):
    payload["five_hour"] = {"utilization": -1, "used_percentage": 10}
    provider, _ = provider_for(payload)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert snapshot.metrics[0].state == MetricState.UNKNOWN
    assert snapshot.fetch_state == FetchState.PARTIAL


# --- Optional extra-usage spend row (parsed from the same usage response) ---

EXTRA = MetricId.CLAUDE_EXTRA_USAGE


def extra_row(snapshot):
    """Required rows stay first and intact; return the single optional row, if any."""
    required = REQUIRED_METRIC_IDS[ACCOUNT.provider]
    assert tuple(row.id for row in snapshot.metrics[:3]) == required
    extras = snapshot.metrics[3:]
    assert len(extras) <= 1
    assert all(row.id == EXTRA for row in extras)
    return extras[0] if extras else None


def capped(**overrides):
    value = {
        "is_enabled": True,
        "monthly_limit": 5000,
        "used_credits": 1234,
        "utilization": 24.68,
        "currency": "USD",
    }
    value.update(overrides)
    return value


async def fetch(payload):
    provider, requests = provider_for(payload)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert len(requests) == 1
    return snapshot


@pytest.mark.parametrize("present", [False, True])
async def test_absent_or_null_extra_usage_emits_no_row(payload, present):
    if present:
        payload["extra_usage"] = None
    snapshot = await fetch(payload)
    assert_rows(snapshot)
    assert extra_row(snapshot) is None
    assert snapshot.fetch_state == FetchState.OK


async def test_capped_extra_usage_reports_spend_cap_and_utilization(payload):
    payload["extra_usage"] = capped()
    snapshot = await fetch(payload)
    assert snapshot.fetch_state == FetchState.OK
    assert snapshot.diagnostic is None
    row = extra_row(snapshot)
    assert row.label == "Claude 额外用量"
    assert row.state == MetricState.READY
    assert row.source.kind == SourceKind.PRIVATE_HTTP and row.source.version_sensitive
    assert row.spent == Money(1234, "USD", 2)
    assert row.spend_limit == Money(5000, "USD", 2)
    assert row.spent.format() == "12.34 USD"
    assert row.quota.used_percent == Decimal("24.68")
    assert row.unlimited is False
    assert row.balance is None and row.credits is None and row.share_percent is None
    assert row.reset_at is None
    assert "no reset time" in row.detail
    assert "unavailable" not in row.detail


async def test_utilization_is_never_derived_from_amounts(payload):
    payload["extra_usage"] = capped(utilization=None)
    row = extra_row(await fetch(payload))
    assert row.quota is None
    assert row.spent == Money(1234, "USD", 2)
    payload["extra_usage"] = capped(utilization=-1)
    row = extra_row(await fetch(payload))
    assert row.quota is None
    assert "utilization" in row.detail


async def test_unlimited_extra_usage_has_no_cap_or_quota(payload):
    payload["extra_usage"] = capped(monthly_limit=None, utilization=50)
    row = extra_row(await fetch(payload))
    assert row.state == MetricState.READY
    assert row.unlimited is True
    assert row.spend_limit is None
    assert row.quota is None
    assert row.spent == Money(1234, "USD", 2)
    assert "No monthly spending cap" in row.detail


@pytest.mark.parametrize(
    "reason,shown",
    [
        ("out_of_credits", True),
        (None, False),
        ("Out Of Credits", False),
        ("<script>alert(1)</script>", False),
        ("a" * 65, False),
        (7, False),
    ],
)
async def test_disabled_extra_usage_sanitizes_reason(payload, reason, shown):
    value = capped(is_enabled=False, monthly_limit=None, utilization=None)
    if reason is not None:
        value["disabled_reason"] = reason
    payload["extra_usage"] = value
    row = extra_row(await fetch(payload))
    assert row.state == MetricState.READY
    # A disabled account with no monthly limit is not positively unlimited.
    assert row.unlimited is False
    assert "currently unavailable" in row.detail
    assert ("Reason: out_of_credits." in row.detail) is shown
    assert "script" not in row.detail and "Out Of" not in row.detail
    assert "Reason" in row.detail if shown else "Reason" not in row.detail


@pytest.mark.parametrize("currency", ["absent", None, "XYZ", "US", "usd$", 840])
async def test_missing_or_unsupported_currency_leaves_amounts_unknown(payload, currency):
    value = capped()
    if currency == "absent":
        value.pop("currency")
    else:
        value["currency"] = currency
    payload["extra_usage"] = value
    row = extra_row(await fetch(payload))
    assert row.state == MetricState.READY
    assert row.spent is None and row.spend_limit is None
    # Other fields remain usable; no USD default is assumed.
    assert row.quota.used_percent == Decimal("24.68")
    assert "Currency" in row.detail
    assert "USD" not in repr(row)


async def test_currency_is_uppercased_and_zero_exponent_respected(payload):
    payload["extra_usage"] = capped(currency="jpy", used_credits=1500, monthly_limit=10000)
    row = extra_row(await fetch(payload))
    assert row.spent == Money(1500, "JPY", 0)
    assert row.spend_limit == Money(10000, "JPY", 0)
    assert row.spent.format() == "1500 JPY"


@pytest.mark.parametrize("raw", [-1, True, False, 12.5, "100", 10**15 + 1, [], {}])
async def test_invalid_amounts_are_unknown_not_zero(payload, raw):
    payload["extra_usage"] = capped(used_credits=raw, monthly_limit=raw)
    snapshot = await fetch(payload)
    assert snapshot.fetch_state == FetchState.OK
    row = extra_row(snapshot)
    assert row.state == MetricState.READY
    assert row.spent is None and row.spend_limit is None
    assert "spend is invalid" in row.detail
    assert "monthly limit is invalid" in row.detail
    # An invalid (non-null) cap is not "unlimited"; utilization still describes it.
    assert row.unlimited is False
    assert row.quota.used_percent == Decimal("24.68")


@pytest.mark.parametrize(
    "wire,expected",
    [
        ("0", 0),
        ("1234", 1234),
        ("1234.0", 1234),
        ("1.5e3", 1500),
        ("1000000000000000", 10**15),
        ("1234.5", None),
        ("-0.5", None),
        ("1e16", None),
        ("1e1000000", None),
        ("1e-1000000", None),
        ("true", None),
    ],
)
async def test_raw_json_amounts_through_real_transport(payload, wire, expected):
    payload["extra_usage"] = capped(used_credits="WIRE_AMOUNT", utilization="WIRE_UTIL")
    body = (
        json.dumps(payload)
        .encode()
        .replace(b'"WIRE_AMOUNT"', wire.encode())
        .replace(b'"WIRE_UTIL"', b"33.333333333333333333333")
    )
    snapshot = await fetch(body)
    assert snapshot.fetch_state == FetchState.OK
    row = extra_row(snapshot)
    assert row.spent == (None if expected is None else Money(expected, "USD", 2))
    assert row.quota.used_percent == Decimal("33.333333333333333333333")
    assert row.spend_limit == Money(5000, "USD", 2)


@pytest.mark.parametrize("raw", [[], "enabled", 1, True])
async def test_malformed_extra_usage_is_unknown_row(payload, raw):
    payload["extra_usage"] = raw
    snapshot = await fetch(payload)
    assert snapshot.fetch_state == FetchState.OK
    assert snapshot.diagnostic is None
    row = extra_row(snapshot)
    assert row.state == MetricState.UNKNOWN
    assert "invalid" in row.detail
    assert row.spent is None and row.spend_limit is None and row.quota is None


@pytest.mark.parametrize("enabled", ["absent", None, "true", 1])
async def test_invalid_enabled_flag_is_unknown_row(payload, enabled):
    value = capped()
    if enabled == "absent":
        value.pop("is_enabled")
    else:
        value["is_enabled"] = enabled
    payload["extra_usage"] = value
    row = extra_row(await fetch(payload))
    assert row.state == MetricState.UNKNOWN
    assert row.spent is None and row.quota is None and row.unlimited is False


async def test_missing_monthly_limit_key_is_unknown_cap_not_unlimited(payload):
    value = capped()
    value.pop("monthly_limit")
    payload["extra_usage"] = value
    row = extra_row(await fetch(payload))
    assert row.unlimited is False
    assert row.spend_limit is None
    assert row.quota is None
    assert "cap is unknown" in row.detail


async def test_optional_row_does_not_change_partial_state(payload):
    payload["five_hour"]["utilization"] = -1
    payload["extra_usage"] = capped()
    snapshot = await fetch(payload)
    assert snapshot.fetch_state == FetchState.PARTIAL
    assert snapshot.diagnostic.code == "partial_data"
    assert snapshot.metrics[0].state == MetricState.UNKNOWN
    assert extra_row(snapshot).spent == Money(1234, "USD", 2)


async def test_extra_usage_alone_does_not_make_response_usable():
    snapshot = await fetch({"extra_usage": capped()})
    assert snapshot.fetch_state == FetchState.SCHEMA_ERROR
    assert snapshot.diagnostic.code == "schema_error"
    assert snapshot.fetched_at is None
    assert_rows(snapshot)
    assert extra_row(snapshot) is None


async def test_failure_snapshots_emit_no_extra_row(payload):
    payload["extra_usage"] = capped()
    provider, _ = provider_for(payload, status=503)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert snapshot.fetch_state == FetchState.PROVIDER_ERROR
    assert_rows(snapshot)
    snapshot = await provider.fetch(ACCOUNT, None, NOW)
    assert snapshot.fetch_state == FetchState.AUTH_REQUIRED
    assert_rows(snapshot)


async def test_sibling_extra_objects_are_ignored(payload):
    payload["extra_usage"] = capped()
    for key in ("wattle_ember", "iguana_necktie", "cinder_cove", "cedar_ember"):
        payload[key] = {"is_enabled": True, "used_credits": 1, "currency": "USD"}
    snapshot = await fetch(payload)
    assert [row.id for row in snapshot.metrics[3:]] == [EXTRA]


async def test_extra_usage_round_trips_through_snapshot_serialization(payload):
    payload["extra_usage"] = capped(currency="eur")
    snapshot = await fetch(payload)
    assert Snapshot.from_dict(json.loads(json.dumps(snapshot.to_dict()))) == snapshot
