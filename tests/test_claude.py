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
    TransportError,
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
    # The row's "重置 — 未知" and the partial diagnostic say it; no extra note.
    assert snapshot.metrics[0].detail is None
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
    assert fable.detail is None
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


# --- Prepaid credits (explicitly selected organization) and discovery ---

ORG = "0f6a2b7c-1d2e-4f3a-8b9c-0123456789ab"
OTHER_ORG = "11111111-2222-4333-8444-555555555555"
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
CREDITS_URL = f"https://api.anthropic.com/api/oauth/organizations/{ORG}/prepaid/credits"
PROFILE_URL = "https://api.anthropic.com/api/oauth/profile"
ORG_ACCOUNT = replace(ACCOUNT, organization_id=ORG)
ORG_CREDENTIAL = replace(CREDENTIAL, organization_id=ORG)
CREDITS = {
    "amount": 13750,
    "currency": "usd",
    "auto_reload_settings": {"enabled": False},
    "expiry_policy_months": 12,
}


def routed(routes):
    """Real Transport over an in-memory server; each route is (status, body, headers)."""
    requests = []

    def handler(request):
        requests.append(request)
        status, body, headers = routes[str(request.url)]
        content = body if isinstance(body, bytes) else json.dumps(body).encode()
        return httpx.Response(status, content=content, headers=headers)

    return ClaudeProvider(Transport(http_transport=httpx.MockTransport(handler))), requests


def credit_row(snapshot):
    rows = [row for row in snapshot.metrics if row.id == MetricId.CLAUDE_CREDIT_BALANCE]
    assert len(rows) <= 1
    return rows[0] if rows else None


async def fetch_credits(payload, credits, *, status=200, headers=None):
    provider, requests = routed(
        {USAGE_URL: (200, payload, None), CREDITS_URL: (status, credits, headers)}
    )
    return await provider.fetch(ORG_ACCOUNT, ORG_CREDENTIAL, NOW), requests


async def test_without_organization_exactly_one_usage_request(payload):
    provider, requests = routed({USAGE_URL: (200, payload, None)})
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert [str(request.url) for request in requests] == [USAGE_URL]
    assert credit_row(snapshot) is None
    assert snapshot.fetch_state == FetchState.OK
    assert snapshot.organization_id is None


async def test_organization_makes_usage_then_credits_with_exact_headers(payload):
    snapshot, requests = await fetch_credits(payload, CREDITS)
    assert [str(request.url) for request in requests] == [USAGE_URL, CREDITS_URL]
    assert all(request.method == "GET" for request in requests)
    usage, credits = requests
    assert usage.headers["anthropic-beta"] == "oauth-2025-04-20"
    assert "x-organization-uuid" not in usage.headers
    assert credits.headers["authorization"] == "Bearer synthetic-secret"
    assert credits.headers["anthropic-version"] == "2023-06-01"
    assert credits.headers["x-organization-uuid"] == ORG
    assert credits.headers["accept"] == "application/json"
    assert credits.headers["user-agent"].startswith("cli-usage-api/")
    for absent in ("anthropic-beta", "anthropic-client-platform", "cookie", "content-type"):
        assert absent not in credits.headers
    assert snapshot.fetch_state == FetchState.OK
    assert snapshot.diagnostic is None
    assert snapshot.retry_at is None
    assert snapshot.organization_id == ORG
    ids = [row.id for row in snapshot.metrics]
    assert ids[:3] == list(REQUIRED_METRIC_IDS[ACCOUNT.provider])
    assert ids[-1] == MetricId.CLAUDE_CREDIT_BALANCE
    row = credit_row(snapshot)
    assert row.state == MetricState.READY
    assert row.label == "Claude 已购 credits 余额"
    assert row.balance == Money(13750, "USD", 2)
    assert row.quota is None and row.reset_at is None and row.spent is None
    assert row.source.contract == "claude.oauth.prepaid.credits"
    assert row.source.version_sensitive is True
    assert "自动充值关。" in row.detail
    assert "有效期 12 个月。" in row.detail
    assert "subscription allowance" not in row.detail and "no reset" not in row.detail
    assert "promotional" not in row.detail and "促销" not in row.detail
    assert snapshot.grants == ()


async def test_credits_row_round_trips_through_snapshot_serialization(payload):
    snapshot, _ = await fetch_credits(payload, CREDITS)
    assert Snapshot.from_dict(json.loads(json.dumps(snapshot.to_dict()))) == snapshot


async def test_credits_are_not_merged_with_extra_usage(payload):
    payload["extra_usage"] = {
        "is_enabled": True,
        "monthly_limit": 50000,
        "used_credits": 1200,
        "currency": "USD",
    }
    snapshot, _ = await fetch_credits(payload, {**CREDITS, "amount": 7})
    extra = next(row for row in snapshot.metrics if row.id == MetricId.CLAUDE_EXTRA_USAGE)
    assert extra.spend_limit == Money(50000, "USD", 2)
    assert extra.balance is None
    credits = credit_row(snapshot)
    assert credits.balance == Money(7, "USD", 2)
    assert credits.spent is None and credits.spend_limit is None


@pytest.mark.parametrize(
    ("status", "state"),
    [
        (401, FetchState.AUTH_REQUIRED),
        (403, FetchState.PERMISSION_DENIED),
        (429, FetchState.RATE_LIMITED),
        (500, FetchState.PROVIDER_ERROR),
    ],
)
async def test_usage_failure_never_requests_credits(status, state):
    provider, requests = routed(
        {USAGE_URL: (status, b'{"secret":"body"}', {"Retry-After": "60"}), CREDITS_URL: None}
    )
    snapshot = await provider.fetch(ORG_ACCOUNT, ORG_CREDENTIAL, NOW)
    assert [str(request.url) for request in requests] == [USAGE_URL]
    assert snapshot.fetch_state == state
    assert credit_row(snapshot) is None


async def test_unusable_usage_payload_never_requests_credits():
    provider, requests = routed({USAGE_URL: (200, {"unrelated": 1}, None), CREDITS_URL: None})
    snapshot = await provider.fetch(ORG_ACCOUNT, ORG_CREDENTIAL, NOW)
    assert len(requests) == 1
    assert snapshot.fetch_state == FetchState.SCHEMA_ERROR


@pytest.mark.parametrize(
    ("status", "fragment"),
    [
        (401, "reconnect"),
        (403, "No billing permission"),
        (404, "re-select the organization"),
        (429, "rate limited"),
        (500, "Credits request failed"),
        (502, "Credits request failed"),
    ],
)
async def test_credits_failure_keeps_usage_rows_and_is_partial(payload, status, fragment):
    snapshot, requests = await fetch_credits(payload, {"secret": "leak"}, status=status)
    assert len(requests) == 2
    assert snapshot.fetch_state == FetchState.PARTIAL
    assert snapshot.diagnostic.code == "partial_data"
    assert snapshot.fetched_at == NOW
    assert all(row.state == MetricState.READY for row in snapshot.metrics[:3])
    assert snapshot.metrics[0].quota.used_percent == Decimal("12.5")
    row = credit_row(snapshot)
    assert row.state == MetricState.UNKNOWN
    assert row.balance is None
    assert fragment in row.detail
    assert "leak" not in json.dumps(snapshot.to_dict())


async def test_credits_429_retry_deadline_is_carried(payload):
    snapshot, _ = await fetch_credits(payload, b"", status=429, headers={"Retry-After": "900"})
    assert snapshot.fetch_state == FetchState.PARTIAL
    assert snapshot.retry_at is not None
    assert snapshot.retry_at >= datetime.now(UTC) + timedelta(seconds=800)
    assert credit_row(snapshot).state == MetricState.UNKNOWN


@pytest.mark.parametrize("headers", [None, {"Retry-After": "not-a-deadline"}])
async def test_credits_429_without_usable_retry_after_gets_local_embargo(payload, headers):
    snapshot, requests = await fetch_credits(payload, b"", status=429, headers=headers)
    assert len(requests) == 2
    assert snapshot.fetch_state == FetchState.PARTIAL
    # Conservative no-header cooldown: the Claude 429 base; the scheduler escalates.
    assert snapshot.retry_at == NOW + timedelta(seconds=180)
    assert credit_row(snapshot).state == MetricState.UNKNOWN
    assert snapshot.metrics[0].state == MetricState.READY


@pytest.mark.parametrize("status", [403, 404, 500])
async def test_credits_non_rate_limit_failure_carries_no_embargo(payload, status):
    snapshot, _ = await fetch_credits(payload, b"", status=status)
    assert snapshot.fetch_state == FetchState.PARTIAL
    assert snapshot.retry_at is None


async def test_credits_failure_does_not_mask_worse_usage_detail(payload):
    del payload["five_hour"]
    snapshot, _ = await fetch_credits(payload, CREDITS, status=500)
    assert snapshot.fetch_state == FetchState.PARTIAL
    assert snapshot.metrics[0].state == MetricState.UNKNOWN
    assert credit_row(snapshot).state == MetricState.UNKNOWN


async def test_credits_network_error_is_unknown_partial(payload):
    def handler(request):
        if str(request.url) == CREDITS_URL:
            raise httpx.ConnectError("synthetic")
        return httpx.Response(200, content=json.dumps(payload).encode())

    provider = ClaudeProvider(Transport(http_transport=httpx.MockTransport(handler)))
    snapshot = await provider.fetch(ORG_ACCOUNT, ORG_CREDENTIAL, NOW)
    assert snapshot.fetch_state == FetchState.PARTIAL
    assert credit_row(snapshot).state == MetricState.UNKNOWN


@pytest.mark.parametrize("body", [b"not json", [], [{"amount": 1}], b"[]"])
async def test_credits_schema_error_is_unknown_partial(payload, body):
    snapshot, _ = await fetch_credits(payload, body)
    assert snapshot.fetch_state == FetchState.PARTIAL
    row = credit_row(snapshot)
    assert row.state == MetricState.UNKNOWN
    assert "format is invalid" in row.detail


@pytest.mark.parametrize("currency", ["absent", None, "", "US", "XYZ", "usd$", 840, ["USD"]])
async def test_missing_or_unsupported_currency_is_unknown_not_usd(payload, currency):
    credits = dict(CREDITS)
    if currency == "absent":
        del credits["currency"]
    else:
        credits["currency"] = currency
    snapshot, _ = await fetch_credits(payload, credits)
    row = credit_row(snapshot)
    assert row.state == MetricState.UNKNOWN
    assert row.balance is None
    assert "Currency is missing or unsupported" in row.detail
    assert snapshot.fetch_state == FetchState.PARTIAL


async def test_zero_exponent_currency_and_zero_balance(payload):
    snapshot, _ = await fetch_credits(payload, {"amount": 0, "currency": "JPY"})
    row = credit_row(snapshot)
    assert row.state == MetricState.READY
    assert row.balance == Money(0, "JPY", 0)


@pytest.mark.parametrize(
    "amount",
    ["absent", None, True, False, -1, 12.5, "100", 10**15 + 1, [], {}],
)
async def test_invalid_amount_is_unknown_not_zero(payload, amount):
    credits = dict(CREDITS)
    if amount == "absent":
        del credits["amount"]
    else:
        credits["amount"] = amount
    snapshot, _ = await fetch_credits(payload, credits)
    row = credit_row(snapshot)
    assert row.state == MetricState.UNKNOWN
    assert row.balance is None
    assert snapshot.fetch_state == FetchState.PARTIAL


@pytest.mark.parametrize(
    ("wire", "expected"),
    [
        (b"13750", 13750),
        (b"13750.0", 13750),
        (b"1.375e4", 13750),
        (b"1e15", 10**15),
        (b"1e16", None),
        (b"1e999999999", None),
        (b"1e-999999999", None),
        (b"12.5", None),
        (b"-0.0", 0),
        (b"-1", None),
        (b"Infinity", None),
        (b"NaN", None),
    ],
)
async def test_raw_json_credit_amounts_through_real_transport(payload, wire, expected):
    body = b'{"amount": ' + wire + b', "currency": "USD"}'
    snapshot, _ = await fetch_credits(payload, body)
    row = credit_row(snapshot)
    if expected is None:
        assert row.state == MetricState.UNKNOWN
        assert row.balance is None
    else:
        assert row.balance == Money(expected, "USD", 2)


@pytest.mark.parametrize("months", [0, -3, True, "12", 1.5, None])
async def test_invalid_or_absent_optional_settings_are_omitted(payload, months):
    snapshot, _ = await fetch_credits(
        payload,
        {
            "amount": 5,
            "currency": "USD",
            "auto_reload_settings": {"enabled": "yes"},
            "expiry_policy_months": months,
        },
    )
    row = credit_row(snapshot)
    assert row.state == MetricState.READY
    assert row.detail is None
    assert snapshot.fetch_state == FetchState.OK


def tranche(amount=500, expires="2026-12-01T00:00:00Z", currency="USD", **extra):
    return {
        "remaining_amount_minor_units": amount,
        "expires_at": expires,
        "currency": currency,
        **extra,
    }


async def test_promo_summary_is_detail_only_and_excludes_expired(payload):
    credits = {
        **CREDITS,
        "promo_tranches": [
            tranche(500, "2026-12-01T00:00:00Z", name="Launch"),
            tranche(250, "2026-11-15T00:00:00Z", "usd"),
            tranche(900, "2026-10-01T00:00:00Z"),
            tranche(0, "2026-11-02T00:00:00Z"),
        ],
    }
    snapshot, _ = await fetch_credits(payload, credits)
    row = credit_row(snapshot)
    assert row.state == MetricState.READY
    # Promo remaining is already part of the balance; never added to it.
    assert row.balance == Money(13750, "USD", 2)
    assert row.expires_at is None and row.reset_at is None
    assert snapshot.grants == ()
    assert "含促销 7.50 USD（2 笔），最早 2026-11-15 到期。" in row.detail
    assert "T00:00:00Z" not in row.detail
    assert "1 笔促销已过期。" in row.detail
    assert "无效" not in row.detail
    assert snapshot.fetch_state == FetchState.OK


@pytest.mark.parametrize(
    "bad",
    [
        "not-an-object",
        tranche(amount=-1),
        tranche(amount=True),
        tranche(amount=1.5),
        tranche(expires="soon"),
        tranche(expires=None),
        tranche(currency="EUR"),
        tranche(currency=None),
    ],
)
async def test_invalid_promo_entries_make_summary_partial_never_zero(payload, bad):
    credits = {**CREDITS, "promo_tranches": [tranche(300), bad]}
    snapshot, _ = await fetch_credits(payload, credits)
    row = credit_row(snapshot)
    assert row.state == MetricState.READY
    assert row.balance == Money(13750, "USD", 2)
    assert "含促销 3.00 USD（1 笔）" in row.detail
    assert "部分促销条目无效。" in row.detail


async def test_only_invalid_promo_entries_do_not_claim_none_active(payload):
    snapshot, _ = await fetch_credits(payload, {**CREDITS, "promo_tranches": [tranche("x")]})
    row = credit_row(snapshot)
    assert "含促销" not in row.detail
    assert "0.00" not in row.detail
    assert "部分促销条目无效。" in row.detail


@pytest.mark.parametrize("raw", [{}, "x", 1])
async def test_malformed_promo_array_is_unknown_summary(payload, raw):
    snapshot, _ = await fetch_credits(payload, {**CREDITS, "promo_tranches": raw})
    row = credit_row(snapshot)
    assert row.balance == Money(13750, "USD", 2)
    assert "促销信息格式无效。" in row.detail


async def test_empty_promo_array_adds_no_promo_note(payload):
    snapshot, _ = await fetch_credits(payload, {**CREDITS, "promo_tranches": []})
    row = credit_row(snapshot)
    assert row.balance == Money(13750, "USD", 2)
    assert "promotional" not in row.detail and "促销" not in row.detail


@pytest.mark.parametrize(
    "credential",
    [
        CREDENTIAL,
        replace(CREDENTIAL, organization_id=OTHER_ORG),
    ],
)
async def test_credential_organization_must_match_saved_selection(credential):
    provider, requests = routed({})
    snapshot = await provider.fetch(ORG_ACCOUNT, credential, NOW)
    assert requests == []
    assert snapshot.fetch_state == FetchState.AUTH_REQUIRED
    assert snapshot.diagnostic.code == "credential_mismatch"


async def test_credential_organization_without_saved_selection_is_rejected():
    provider, requests = routed({})
    snapshot = await provider.fetch(ACCOUNT, ORG_CREDENTIAL, NOW)
    assert requests == []
    assert snapshot.diagnostic.code == "credential_mismatch"


async def test_failure_snapshot_keeps_organization_and_emits_no_credit_row():
    provider, _ = routed({USAGE_URL: (401, b"", None)})
    snapshot = await provider.fetch(ORG_ACCOUNT, ORG_CREDENTIAL, NOW)
    assert snapshot.organization_id == ORG
    assert credit_row(snapshot) is None


PROFILE = {
    "account": {"uuid": "a0a0a0a0-0000-4000-8000-000000000000", "email": "x@example.invalid"},
    "organization": {
        "uuid": ORG,
        "name": "Synthetic \x1b[31mOrg[1]",
        "organization_type": "claude_max",
        "billing_type": "stripe_subscription",
    },
}


async def test_discovery_reads_profile_and_returns_unselected_choice():
    provider, requests = routed({PROFILE_URL: (200, PROFILE, None)})
    choices = await provider.discover_organizations(CREDENTIAL, now=NOW)
    assert [(choice.id, choice.label) for choice in choices] == [(ORG, "Synthetic Org1")]
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "GET"
    assert str(request.url) == PROFILE_URL
    assert request.headers["authorization"] == "Bearer synthetic-secret"
    assert request.headers["cache-control"] == "no-cache"
    for absent in ("anthropic-beta", "anthropic-version", "x-organization-uuid", "cookie"):
        assert absent not in request.headers


@pytest.mark.parametrize("name", ["absent", None, "", "   ", "\x1b[0m", 42])
async def test_discovery_label_falls_back_to_uuid(name):
    profile = copy.deepcopy(PROFILE)
    if name == "absent":
        del profile["organization"]["name"]
    else:
        profile["organization"]["name"] = name
    provider, _ = routed({PROFILE_URL: (200, profile, None)})
    choices = await provider.discover_organizations(CREDENTIAL, now=NOW)
    assert [(choice.id, choice.label) for choice in choices] == [(ORG, ORG)]


async def test_discovery_null_organization_returns_no_choices():
    provider, _ = routed({PROFILE_URL: (200, {"organization": None}, None)})
    assert await provider.discover_organizations(CREDENTIAL, now=NOW) == ()


@pytest.mark.parametrize(
    "body",
    [
        [],
        {},
        {"organization": "x"},
        {"organization": {}},
        {"organization": {"uuid": ORG.upper()}},
        {"organization": {"uuid": "not-a-uuid"}},
        {"organization": {"uuid": 1}},
        b"not json",
    ],
)
async def test_malformed_profile_is_curated_schema_error(body):
    provider, _ = routed({PROFILE_URL: (200, body, None)})
    with pytest.raises(TransportError) as raised:
        await provider.discover_organizations(CREDENTIAL, now=NOW)
    assert raised.value.fetch_state == FetchState.SCHEMA_ERROR
    assert raised.value.code == "schema_error"


@pytest.mark.parametrize(
    ("status", "state"),
    [(401, FetchState.AUTH_REQUIRED), (403, FetchState.PERMISSION_DENIED)],
)
async def test_discovery_http_errors_are_curated(status, state):
    provider, _ = routed({PROFILE_URL: (status, {"secret": "leak"}, None)})
    with pytest.raises(TransportError) as raised:
        await provider.discover_organizations(CREDENTIAL, now=NOW)
    assert raised.value.fetch_state == state
    assert "leak" not in str(raised.value)


@pytest.mark.parametrize(
    ("credential", "code"),
    [
        (None, "credential_unavailable"),
        (replace(CREDENTIAL, expires_at=NOW), "credential_expired"),
    ],
)
async def test_discovery_rejects_unusable_credentials_without_request(credential, code):
    provider, requests = routed({})
    with pytest.raises(TransportError) as raised:
        await provider.discover_organizations(credential, now=NOW)
    assert raised.value.code == code
    assert requests == []


async def test_discovery_rejects_other_provider_credential():
    provider, requests = routed({})
    foreign = ResolvedCredential(
        ProviderId.CLAUDE_PLATFORM, CredentialKind.CONSOLE_SESSION, "cookie-value", "g"
    )
    with pytest.raises(TransportError) as raised:
        await provider.discover_organizations(foreign, now=NOW)
    assert raised.value.code == "credential_mismatch"
    assert requests == []


@pytest.mark.parametrize(
    "path",
    [
        f"/api/oauth/organizations/{ORG}/contracts/prepaid/credits",
        f"/api/oauth/organizations/{ORG}/setup_overage_billing",
        f"/api/oauth/organizations/{ORG}/overage_spend_limit",
        f"/api/oauth/organizations/{ORG}/contracts/auto_reload_settings",
        f"/api/oauth/organizations/{OTHER_ORG}/prepaid/credits",
        f"/api/oauth/organizations/{ORG.upper()}/prepaid/credits",
    ],
)
async def test_neighbouring_and_foreign_paths_never_reach_http(path):
    requests = []
    transport = Transport(http_transport=httpx.MockTransport(lambda r: requests.append(r)))
    with pytest.raises(TransportError) as raised:
        await transport.get_json(ACCOUNT.provider, path, credential=ORG_CREDENTIAL)
    assert raised.value.code == "forbidden_request"
    assert requests == []
