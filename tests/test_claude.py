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
from usage_tui.providers.claude import ClaudeProvider
from usage_tui.transport import Transport

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
        return httpx.Response(status, json=payload, headers=headers)

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
