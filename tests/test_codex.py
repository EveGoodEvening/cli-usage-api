"""Codex quota normalization through real Transport; synthetic raw HTTP only."""

import asyncio
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest

from cli_usage_api.domain import (
    REQUIRED_METRIC_IDS,
    Account,
    CredentialKind,
    FetchState,
    MetricId,
    MetricState,
    ProviderId,
    ResolvedCredential,
    Snapshot,
    SourceKind,
)
from cli_usage_api.providers.codex import CodexProvider
from cli_usage_api.transport import Transport

NOW = datetime(2026, 10, 28, 12, tzinfo=UTC)
RESET = 1793232000
ACCOUNT = Account(
    "00000000-0000-0000-0000-000000000017",
    ProviderId.CODEX_SUBSCRIPTION,
    "Synthetic Codex",
    credential_ref="file:/synthetic/auth.json",
    credential_kind=CredentialKind.CODEX_AUTH_FILE,
)
CREDENTIAL = ResolvedCredential(
    ACCOUNT.provider,
    CredentialKind.CODEX_AUTH_FILE,
    "synthetic-access-token",
    "synthetic-generation",
    codex_account_id="synthetic-selected-account",
)


def window(seconds=604800, used=12.5, reset=RESET):
    return {"limit_window_seconds": seconds, "used_percent": used, "reset_at": reset}


def provider_for(payload, *, status=200, headers=None):
    requests = []

    def handler(request):
        requests.append(request)
        assert request.method == "GET"
        assert str(request.url) == "https://chatgpt.com/backend-api/wham/usage"
        assert request.headers["authorization"] == f"Bearer {CREDENTIAL.secret}"
        assert request.headers["chatgpt-account-id"] == "synthetic-selected-account"
        for name in ("cookie", "x-xai-token-auth", "x-userid", "anthropic-beta", "x-api-key"):
            assert name not in request.headers
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        return httpx.Response(status, content=body, headers=headers)

    return (
        CodexProvider(Transport(http_transport=httpx.MockTransport(handler), clock=lambda: NOW)),
        requests,
    )


def rows(snapshot):
    assert snapshot.metrics[0].id == MetricId.CODEX_WEEKLY
    assert all(row.source.kind == SourceKind.PRIVATE_HTTP for row in snapshot.metrics)
    assert all(row.source.contract == "codex.wham.usage.v1" for row in snapshot.metrics)
    assert all(row.source.version_sensitive for row in snapshot.metrics)
    assert all(row.balance is None and row.shared_pool_id is None for row in snapshot.metrics)
    assert snapshot.grants == ()
    assert Snapshot.from_dict(snapshot.to_dict()) == snapshot
    rendered = repr(snapshot.to_dict())
    assert "synthetic-access-token" not in rendered
    assert "synthetic-selected-account" not in rendered
    return {row.id: row for row in snapshot.metrics}


@pytest.mark.parametrize("weekly_slot", ["primary_window", "secondary_window"])
async def test_slot_swapped_windows_use_duration_and_make_exactly_one_read(weekly_slot):
    other_slot = "secondary_window" if weekly_slot == "primary_window" else "primary_window"
    provider, requests = provider_for(
        {"rate_limit": {weekly_slot: window(), other_slot: window(18000, 110.25)}}
    )
    assert provider.requires_credential is True
    assert provider.metric_ids == REQUIRED_METRIC_IDS[ACCOUNT.provider] == (MetricId.CODEX_WEEKLY,)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    result = rows(snapshot)
    assert len(requests) == 1
    assert snapshot.fetch_state == FetchState.OK
    assert snapshot.attempted_at == snapshot.fetched_at == NOW
    assert set(result) == {MetricId.CODEX_WEEKLY, MetricId.CODEX_FIVE_HOUR}
    assert result[MetricId.CODEX_WEEKLY].quota.used_percent == Decimal("12.5")
    assert result[MetricId.CODEX_WEEKLY].quota.remaining_percent == Decimal("87.5")
    assert result[MetricId.CODEX_FIVE_HOUR].quota.used_percent == Decimal("110.25")
    assert result[MetricId.CODEX_FIVE_HOUR].quota.remaining_percent == 0
    assert all(row.reset_at == datetime.fromtimestamp(RESET, UTC) for row in result.values())
    assert all(row.quota.used_count is row.quota.limit_count is None for row in result.values())


async def test_weekly_only_primary_does_not_invent_short_window_or_plan_entitlement():
    provider, requests = provider_for(
        {"plan_type": "pro", "rate_limit": {"primary_window": window(), "secondary_window": None}}
    )
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert tuple(rows(snapshot)) == (MetricId.CODEX_WEEKLY,)
    assert snapshot.fetch_state == FetchState.OK
    assert len(requests) == 1


async def test_arbitrary_main_durations_and_feature_pools_are_distinct_and_sanitized():
    feature = "synthetic-feature"
    pool_id = f"codex.pool.{hashlib.sha256(feature.encode()).hexdigest()}.window.604800"
    provider, _ = provider_for(
        {
            "rate_limit": {"primary_window": window(300, 1), "secondary_window": window(3600, 2)},
            "additional_rate_limits": [
                {
                    "metered_feature": feature,
                    "limit_name": "[red]Pool\x1b[31m\nName",
                    "rate_limit": {"primary_window": window(604800, 75)},
                }
            ],
        }
    )
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    result = rows(snapshot)
    assert set(result) == {
        MetricId.CODEX_WEEKLY,
        "codex.subscription.window.300",
        "codex.subscription.window.3600",
        pool_id,
    }
    assert result[MetricId.CODEX_WEEKLY].state == MetricState.UNKNOWN
    assert result[MetricId.CODEX_WEEKLY].quota is None
    assert result[pool_id].quota.used_percent == 75
    assert result["codex.subscription.window.300"].quota.used_percent == 1
    assert result["codex.subscription.window.300"].label == "Codex 5m"
    assert result["codex.subscription.window.3600"].label == "Codex 1h"
    assert result[pool_id].label.startswith("Codex ")
    assert result[pool_id].label.endswith(" (7d)")
    assert "\x1b" not in result[pool_id].label + (result[pool_id].detail or "")
    assert "\n" not in result[pool_id].label
    assert len(pool_id) <= 128


@pytest.mark.parametrize(
    "rate_limit", [None, {}, {"primary_window": None}, {"secondary_window": window(18000)}]
)
async def test_missing_weekly_is_unknown_never_zero_or_short_window_alias(rate_limit):
    provider, _ = provider_for({"rate_limit": rate_limit})
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    row = rows(snapshot)[MetricId.CODEX_WEEKLY]
    assert row.state == MetricState.UNKNOWN
    assert row.quota is None
    assert snapshot.fetch_state != FetchState.OK


@pytest.mark.parametrize(
    "usage", [None, True, False, -1, "NaN", "Infinity", "-Infinity", [], {}, "bad"]
)
async def test_invalid_usage_preserves_valid_reset_and_sibling(usage):
    provider, _ = provider_for(
        {
            "rate_limit": {
                "primary_window": window(604800, usage),
                "secondary_window": window(18000, 3),
            }
        }
    )
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    result = rows(snapshot)
    assert snapshot.fetch_state == FetchState.PARTIAL
    assert result[MetricId.CODEX_WEEKLY].state == MetricState.UNKNOWN
    assert result[MetricId.CODEX_WEEKLY].quota is None
    assert result[MetricId.CODEX_WEEKLY].reset_at == datetime.fromtimestamp(RESET, UTC)
    assert result[MetricId.CODEX_FIVE_HOUR].quota.used_percent == 3


@pytest.mark.parametrize("field", ["used_percent", "reset_at"])
async def test_missing_usage_and_reset_are_independent(field):
    value = window()
    del value[field]
    provider, _ = provider_for({"rate_limit": {"primary_window": value}})
    row = rows(await provider.fetch(ACCOUNT, CREDENTIAL, NOW))[MetricId.CODEX_WEEKLY]
    if field == "used_percent":
        assert row.quota is None
        assert row.reset_at == datetime.fromtimestamp(RESET, UTC)
    else:
        assert row.quota.used_percent == Decimal("12.5")
        assert row.reset_at is None


@pytest.mark.parametrize("seconds", [604800, 18000, 300])
@pytest.mark.parametrize("feature", [None, "synthetic-feature"])
async def test_recognized_identity_without_valid_fields_is_partial(seconds, feature):
    limit = {"primary_window": {"limit_window_seconds": seconds}}
    payload = (
        {"rate_limit": limit}
        if feature is None
        else {"additional_rate_limits": [{"metered_feature": feature, "rate_limit": limit}]}
    )
    provider, _ = provider_for(payload)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    result = rows(snapshot)
    assert all(row.state == MetricState.UNKNOWN for row in result.values())
    assert all(row.quota is None and row.reset_at is None for row in result.values())
    assert snapshot.fetch_state == FetchState.PARTIAL
    assert snapshot.fetched_at == NOW
    assert snapshot.diagnostic.code == "partial_data"


@pytest.mark.parametrize(
    "reset",
    [None, True, False, -62135596801, 253402300800, 1.5, "bad", "NaN", 1793232000000, 10**100],
)
async def test_invalid_absolute_reset_preserves_usage_without_relative_fallback(reset):
    value = window(reset=reset)
    value["reset_after_seconds"] = 60
    provider, _ = provider_for({"rate_limit": {"primary_window": value}})
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    row = rows(snapshot)[MetricId.CODEX_WEEKLY]
    assert snapshot.fetch_state == FetchState.PARTIAL
    assert row.state == MetricState.READY
    assert row.quota.used_percent == Decimal("12.5")
    assert row.reset_at is None


async def test_relative_only_reset_is_never_promoted_to_absolute_time():
    value = window()
    del value["reset_at"]
    value["reset_after_seconds"] = 120
    provider, _ = provider_for({"rate_limit": {"primary_window": value}})
    row = rows(await provider.fetch(ACCOUNT, CREDENTIAL, NOW))[MetricId.CODEX_WEEKLY]
    assert row.quota.used_percent == Decimal("12.5")
    assert row.reset_at is None


@pytest.mark.parametrize(
    ("literal", "expected"),
    [
        ("12.345678901234567890123456789", Decimal("12.345678901234567890123456789")),
        ("100.000000000000000000000000001", Decimal("100.000000000000000000000000001")),
        ("1e-1000", Decimal("1e-1000")),
        ("0", Decimal(0)),
    ],
)
async def test_raw_numeric_wire_retains_decimal_precision_and_overage(literal, expected):
    body = (
        '{"rate_limit":{"primary_window":{"limit_window_seconds":604800,'
        f'"used_percent":{literal},"reset_at":{RESET}'
        "}}}"
    ).encode()
    provider, _ = provider_for(body)
    row = rows(await provider.fetch(ACCOUNT, CREDENTIAL, NOW))[MetricId.CODEX_WEEKLY]
    assert row.state == MetricState.READY
    assert row.quota.used_percent == expected
    if expected > 100:
        assert row.quota.remaining_percent == 0


@pytest.mark.parametrize(
    "literal", ["true", "false", "-0.000000000000000000000001", "1e1001", "1e-1001"]
)
async def test_raw_invalid_numeric_usage_is_not_coerced_or_rounded(literal):
    body = (
        '{"rate_limit":{"primary_window":{"limit_window_seconds":604800,'
        f'"used_percent":{literal},"reset_at":{RESET}'
        "}}}"
    ).encode()
    provider, _ = provider_for(body)
    row = rows(await provider.fetch(ACCOUNT, CREDENTIAL, NOW))[MetricId.CODEX_WEEKLY]
    assert row.state == MetricState.UNKNOWN
    assert row.quota is None


@pytest.mark.parametrize("conflict", [None, "usage", "reset"])
async def test_duplicate_main_identity_reconciles_agreement_not_last_wins(conflict):
    first, second = window(), window()
    if conflict == "usage":
        second["used_percent"] = 25
    elif conflict == "reset":
        second["reset_at"] = RESET + 60
    for primary, secondary in ((first, second), (second, first)):
        provider, _ = provider_for(
            {"rate_limit": {"primary_window": primary, "secondary_window": secondary}}
        )
        snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
        result = rows(snapshot)
        assert tuple(result) == (MetricId.CODEX_WEEKLY,)
        row = result[MetricId.CODEX_WEEKLY]
        if conflict == "usage":
            assert row.quota is None
            assert row.state == MetricState.UNKNOWN
        else:
            assert row.quota.used_percent == Decimal("12.5")
        if conflict == "reset":
            assert row.reset_at is None
        else:
            assert row.reset_at == datetime.fromtimestamp(RESET, UTC)
        if conflict is not None:
            assert snapshot.fetch_state == FetchState.PARTIAL
            assert snapshot.diagnostic.code == "partial_data"
            assert snapshot.fetched_at == NOW
        else:
            assert snapshot.fetch_state == FetchState.OK


async def test_duplicate_pool_conflict_does_not_corrupt_main_weekly():
    feature = "synthetic-feature"
    pool_id = f"codex.pool.{hashlib.sha256(feature.encode()).hexdigest()}.window.300"
    provider, _ = provider_for(
        {
            "rate_limit": {"primary_window": window()},
            "additional_rate_limits": [
                {"metered_feature": feature, "rate_limit": {"primary_window": window(300, used)}}
                for used in (1, 2)
            ],
        }
    )
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    result = rows(snapshot)
    assert snapshot.fetch_state == FetchState.PARTIAL
    assert result[MetricId.CODEX_WEEKLY].quota.used_percent == Decimal("12.5")
    assert result[pool_id].state == MetricState.UNKNOWN
    assert result[pool_id].quota is None


@pytest.mark.parametrize(
    "bad", [None, [], {}, {"limit_window_seconds": True}, window(0), window(-1), window(1.5)]
)
async def test_malformed_sibling_never_discards_valid_weekly_or_invents_duration(bad):
    provider, _ = provider_for(
        {"rate_limit": {"primary_window": window(), "secondary_window": bad}}
    )
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    result = rows(snapshot)
    assert tuple(result) == (MetricId.CODEX_WEEKLY,)
    assert result[MetricId.CODEX_WEEKLY].quota.used_percent == Decimal("12.5")
    if bad is not None:
        assert snapshot.fetch_state == FetchState.PARTIAL


@pytest.mark.parametrize("feature", [None, "", True, 42, [], {}])
async def test_invalid_feature_pool_cannot_supply_main_weekly(feature):
    provider, _ = provider_for(
        {
            "rate_limit": {"primary_window": window()},
            "additional_rate_limits": [
                {"metered_feature": feature, "rate_limit": {"primary_window": window(604800, 99)}}
            ],
        }
    )
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    result = rows(snapshot)
    assert tuple(result) == (MetricId.CODEX_WEEKLY,)
    assert result[MetricId.CODEX_WEEKLY].quota.used_percent == Decimal("12.5")
    assert snapshot.fetch_state == FetchState.PARTIAL


async def test_enforcement_plan_credits_and_review_limits_do_not_fabricate_usage():
    value = window()
    del value["used_percent"]
    provider, _ = provider_for(
        {
            "plan_type": "pro",
            "rate_limit": {
                "allowed": False,
                "limit_reached": True,
                "primary_window": value,
            },
            "rate_limit_reached_type": {"type": "rate_limit_reached"},
            "credits": {"has_credits": True, "unlimited": True, "balance": "999"},
            "code_review_rate_limit": {"primary_window": window(604800, 99)},
        }
    )
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    result = rows(snapshot)
    # Credits are a separate optional balance row; they never supply weekly usage.
    assert tuple(result) == (MetricId.CODEX_WEEKLY, MetricId.CODEX_CREDITS)
    assert result[MetricId.CODEX_WEEKLY].state == MetricState.UNKNOWN
    assert result[MetricId.CODEX_WEEKLY].quota is None
    # The response-level reached type is not shown: it names no window.
    assert "rate_limit_reached" not in (result[MetricId.CODEX_WEEKLY].detail or "")
    credits = result[MetricId.CODEX_CREDITS]
    assert credits.unlimited is True
    assert credits.credits is None and credits.quota is None


@pytest.mark.parametrize(
    ("status", "state"),
    [
        (401, FetchState.AUTH_REQUIRED),
        (403, FetchState.PERMISSION_DENIED),
        (429, FetchState.RATE_LIMITED),
    ],
)
async def test_http_failures_keep_required_row_and_safe_diagnostics(status, state):
    provider, requests = provider_for(
        b"synthetic-access-token synthetic-selected-account",
        status=status,
        headers={"Retry-After": "3600"},
    )
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert snapshot.fetch_state == state
    assert len(requests) == 1
    assert tuple(rows(snapshot)) == (MetricId.CODEX_WEEKLY,)
    assert snapshot.metrics[0].quota is None
    if status == 429:
        assert snapshot.retry_at == NOW + timedelta(hours=1)


@pytest.mark.parametrize(
    "bad_kind",
    [CredentialKind.API_KEY, CredentialKind.MANUAL_BEARER, CredentialKind.GROK_AUTH_FILE],
)
async def test_non_codex_auth_file_kind_refused_before_io(bad_kind):
    credential = replace(CREDENTIAL)
    object.__setattr__(credential, "credential_kind", bad_kind)
    provider, requests = provider_for({})
    snapshot = await provider.fetch(ACCOUNT, credential, NOW)
    assert requests == []
    assert snapshot.fetch_state == FetchState.AUTH_REQUIRED
    assert tuple(rows(snapshot)) == (MetricId.CODEX_WEEKLY,)


async def test_wrong_provider_binding_refused_before_io():
    credential = ResolvedCredential(
        ProviderId.GROK_SUBSCRIPTION,
        CredentialKind.GROK_AUTH_FILE,
        "synthetic-other-secret",
        "other-generation",
    )
    provider, requests = provider_for({})
    snapshot = await provider.fetch(ACCOUNT, credential, NOW)
    assert requests == []
    assert snapshot.fetch_state == FetchState.AUTH_REQUIRED
    assert "synthetic-other-secret" not in repr(snapshot.to_dict())


@pytest.mark.parametrize("reset", [0, -1, RESET, -62135596800, 253402300799])
async def test_absolute_epoch_seconds_accept_valid_utc_bounds(reset):
    provider, _ = provider_for({"rate_limit": {"primary_window": window(reset=reset)}})
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    row = rows(snapshot)[MetricId.CODEX_WEEKLY]
    assert row.reset_at == datetime.fromtimestamp(reset, UTC)
    assert snapshot.fetch_state == FetchState.OK


@pytest.mark.parametrize("expiry", [NOW, NOW - timedelta(seconds=1)])
async def test_expired_credential_refused_without_request_or_refresh(expiry):
    provider, requests = provider_for({})
    snapshot = await provider.fetch(ACCOUNT, replace(CREDENTIAL, expires_at=expiry), NOW)
    assert requests == []
    assert snapshot.fetch_state == FetchState.AUTH_REQUIRED
    assert tuple(rows(snapshot)) == (MetricId.CODEX_WEEKLY,)


async def test_wrong_account_provider_refused_before_request():
    account = replace(
        ACCOUNT,
        provider=ProviderId.GROK_SUBSCRIPTION,
        credential_kind=CredentialKind.GROK_AUTH_FILE,
    )
    provider, requests = provider_for({})
    snapshot = await provider.fetch(account, CREDENTIAL, NOW)
    assert requests == []
    assert snapshot.fetch_state == FetchState.AUTH_REQUIRED


async def test_matching_duplicate_pool_values_reconcile_to_one_identity():
    feature = "synthetic-feature"
    pool_id = f"codex.pool.{hashlib.sha256(feature.encode()).hexdigest()}.window.300"
    pool = {"metered_feature": feature, "rate_limit": {"primary_window": window(300, 1)}}
    provider, _ = provider_for(
        {"rate_limit": {"primary_window": window()}, "additional_rate_limits": [pool, pool]}
    )
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    result = rows(snapshot)
    assert set(result) == {MetricId.CODEX_WEEKLY, pool_id}
    assert result[pool_id].quota.used_percent == 1
    assert snapshot.fetch_state == FetchState.OK


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        True,
        "malformed",
        {},
        {"rate_limit": {}},
        {"rate_limit": {"primary_window": []}},
        {"rate_limit": {"primary_window": {"limit_window_seconds": True}}},
        {"rate_limit": {"primary_window": {"limit_window_seconds": 0}}},
        {"rate_limit": {"primary_window": {"used_percent": 12.5, "reset_at": RESET}}},
        {"additional_rate_limits": [{"rate_limit": {"primary_window": window()}}]},
    ],
)
async def test_unrecognizable_root_or_shape_keeps_unknown_required_weekly(payload):
    provider, requests = provider_for(payload)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert len(requests) == 1
    assert snapshot.fetch_state == FetchState.SCHEMA_ERROR
    assert tuple(rows(snapshot)) == (MetricId.CODEX_WEEKLY,)
    assert snapshot.metrics[0].quota is None
    assert snapshot.fetched_at is None
    assert snapshot.diagnostic.code == "schema_error"


async def test_cancellation_propagates_without_fabricated_snapshot():
    entered = asyncio.Event()

    async def handler(_):
        entered.set()
        await asyncio.Event().wait()

    provider = CodexProvider(Transport(http_transport=httpx.MockTransport(handler)))
    task = asyncio.create_task(provider.fetch(ACCOUNT, CREDENTIAL, NOW))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.parametrize("literal", ["1793232000.000000000000000000001", "true", "1e1001"])
async def test_raw_reset_tokens_never_round_fraction_or_boolean_into_valid_epoch(literal):
    body = (
        '{"rate_limit":{"primary_window":{"limit_window_seconds":604800,'
        f'"used_percent":12.5,"reset_at":{literal}'
        "}}}"
    ).encode()
    provider, _ = provider_for(body)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    row = rows(snapshot)[MetricId.CODEX_WEEKLY]
    assert row.quota.used_percent == Decimal("12.5")
    assert row.reset_at is None
    assert snapshot.fetch_state == FetchState.PARTIAL


async def test_distinct_feature_pools_with_same_duration_are_not_summed_or_aliased():
    features = ("synthetic-feature-a", "synthetic-feature-b")
    provider, _ = provider_for(
        {
            "rate_limit": {"primary_window": window(604800, 5)},
            "additional_rate_limits": [
                {
                    "metered_feature": feature,
                    "limit_name": f"Synthetic pool {index}",
                    "rate_limit": {"primary_window": window(604800, used)},
                }
                for index, (feature, used) in enumerate(zip(features, (20, 30), strict=True))
            ],
        }
    )
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    result = rows(snapshot)
    assert len(result) == 3
    assert result[MetricId.CODEX_WEEKLY].quota.used_percent == 5
    for index, (feature, used) in enumerate(zip(features, (20, 30), strict=True)):
        metric_id = f"codex.pool.{hashlib.sha256(feature.encode()).hexdigest()}.window.604800"
        assert result[metric_id].quota.used_percent == used
        assert result[metric_id].label == f"Codex Synthetic pool {index} (7d)"
        assert result[metric_id].detail is None
    assert snapshot.fetch_state == FetchState.OK


@pytest.mark.parametrize("bad", [True, "invalid", {}, [None], [{"metered_feature": "valid"}]])
async def test_malformed_additional_pools_preserve_main_quota(bad):
    provider, _ = provider_for(
        {"rate_limit": {"primary_window": window()}, "additional_rate_limits": bad}
    )
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    result = rows(snapshot)
    assert tuple(result) == (MetricId.CODEX_WEEKLY,)
    assert result[MetricId.CODEX_WEEKLY].quota.used_percent == Decimal("12.5")
    assert snapshot.fetch_state == FetchState.PARTIAL


def credit_rows(snapshot):
    return [row for row in snapshot.metrics if row.id == MetricId.CODEX_CREDITS]


@pytest.mark.parametrize("include", [False, True])
async def test_absent_or_null_credits_emit_no_row(include):
    payload = {"rate_limit": {"primary_window": window()}}
    if include:
        payload["credits"] = None
    provider, _ = provider_for(payload)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert tuple(rows(snapshot)) == (MetricId.CODEX_WEEKLY,)
    assert snapshot.fetch_state == FetchState.OK


@pytest.mark.parametrize("has_credits", [True, False, None, "yes"])
@pytest.mark.parametrize("balance", [None, "0", "bad"])
async def test_unlimited_credits_win_over_other_fields(has_credits, balance):
    provider, _ = provider_for(
        {
            "rate_limit": {"primary_window": window()},
            "credits": {"has_credits": has_credits, "unlimited": True, "balance": balance},
        }
    )
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    (row,) = credit_rows(snapshot)
    assert row.state == MetricState.READY
    assert row.unlimited is True
    assert row.credits is None and row.quota is None and row.balance is None
    assert row.label == "Codex credits"
    assert snapshot.fetch_state == FetchState.OK
    assert snapshot.diagnostic is None
    rows(snapshot)


@pytest.mark.parametrize("unlimited", [False, None, "true"])
async def test_no_credits_emit_no_row_like_official_client(unlimited):
    credits = {"has_credits": False, "balance": "50"}
    if unlimited is not None:
        credits["unlimited"] = unlimited
    provider, _ = provider_for({"rate_limit": {"primary_window": window()}, "credits": credits})
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert tuple(rows(snapshot)) == (MetricId.CODEX_WEEKLY,)
    assert snapshot.fetch_state == FetchState.OK


@pytest.mark.parametrize(
    ("balance", "expected"),
    [("9.99", "9.99"), ("25", "25"), ("0", "0"), ("-3", "-3"), ("0.50", "0.50")],
)
async def test_credit_balance_text_is_exact_and_not_money(balance, expected):
    provider, _ = provider_for(
        {
            "rate_limit": {"primary_window": window()},
            "credits": {"has_credits": True, "unlimited": False, "balance": balance},
        }
    )
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    result = rows(snapshot)
    assert tuple(result) == (MetricId.CODEX_WEEKLY, MetricId.CODEX_CREDITS)
    row = result[MetricId.CODEX_CREDITS]
    assert row.state == MetricState.READY
    assert str(row.credits) == expected
    assert row.unlimited is False
    assert row.balance is None and row.quota is None and row.spent is None
    assert row.reset_at is None and row.expires_at is None
    assert row.detail is None  # the row's value speaks for itself
    assert result[MetricId.CODEX_WEEKLY].quota.used_percent == Decimal("12.5")
    assert snapshot.fetch_state == FetchState.OK
    assert snapshot.diagnostic is None


@pytest.mark.parametrize(("literal", "expected"), [("150.0", "150.0"), ("42", "42")])
async def test_raw_numeric_credit_balance_is_tolerated_exactly(literal, expected):
    body = (
        '{"rate_limit":{"primary_window":{"limit_window_seconds":604800,'
        f'"used_percent":12.5,"reset_at":{RESET}}}}},'
        f'"credits":{{"has_credits":true,"unlimited":false,"balance":{literal}}}}}'
    ).encode()
    provider, _ = provider_for(body)
    (row,) = credit_rows(await provider.fetch(ACCOUNT, CREDENTIAL, NOW))
    assert row.state == MetricState.READY
    assert str(row.credits) == expected


@pytest.mark.parametrize(
    "balance", [None, "1e999999", "1" * 65, "NaN", "Infinity", "", "abc", True, False, [], {}]
)
@pytest.mark.parametrize("present", [True, False])
async def test_invalid_or_missing_credit_amount_is_unknown_not_zero(balance, present):
    credits = {"has_credits": True, "unlimited": False}
    if present:
        credits["balance"] = balance
    provider, _ = provider_for({"rate_limit": {"primary_window": window()}, "credits": credits})
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    (row,) = credit_rows(snapshot)
    assert row.state == MetricState.UNKNOWN
    assert row.credits is None and row.unlimited is False
    assert "数量未知" in row.detail
    assert snapshot.fetch_state == FetchState.OK
    assert snapshot.diagnostic is None
    rows(snapshot)


@pytest.mark.parametrize("literal", ["1e999999", "true", "1e-41"])
async def test_raw_hostile_numeric_credit_balance_is_unknown(literal):
    body = (
        '{"rate_limit":{"primary_window":{"limit_window_seconds":604800,'
        f'"used_percent":12.5,"reset_at":{RESET}}}}},'
        f'"credits":{{"has_credits":true,"unlimited":false,"balance":{literal}}}}}'
    ).encode()
    provider, _ = provider_for(body)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    (row,) = credit_rows(snapshot)
    assert row.state == MetricState.UNKNOWN
    assert row.credits is None
    assert snapshot.fetch_state == FetchState.OK


@pytest.mark.parametrize(
    "credits",
    [
        True,
        "100",
        [],
        42,
        {},
        {"has_credits": None, "balance": "5"},
        {"has_credits": "true", "balance": "5"},
        {"has_credits": 1, "balance": "5"},
        {"unlimited": False, "balance": "5"},
    ],
)
async def test_malformed_credits_object_is_unknown_without_changing_fetch_state(credits):
    provider, _ = provider_for({"rate_limit": {"primary_window": window()}, "credits": credits})
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    result = rows(snapshot)
    assert tuple(result) == (MetricId.CODEX_WEEKLY, MetricId.CODEX_CREDITS)
    row = result[MetricId.CODEX_CREDITS]
    assert row.state == MetricState.UNKNOWN
    assert row.credits is None and row.unlimited is False
    assert result[MetricId.CODEX_WEEKLY].quota.used_percent == Decimal("12.5")
    assert snapshot.fetch_state == FetchState.OK
    assert snapshot.diagnostic is None


async def test_credits_do_not_mask_partial_or_schema_error_state():
    credits = {"has_credits": True, "unlimited": False, "balance": "5"}
    provider, _ = provider_for(
        {"rate_limit": {"primary_window": window(), "secondary_window": []}, "credits": credits}
    )
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert snapshot.fetch_state == FetchState.PARTIAL
    assert snapshot.diagnostic.code == "partial_data"
    assert credit_rows(snapshot)[0].credits == 5

    # A response with no recognizable quota is a schema error, not an observation:
    # credits alone neither rescue it nor add a row.
    provider, _ = provider_for({"credits": credits})
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert snapshot.fetch_state == FetchState.SCHEMA_ERROR
    assert snapshot.diagnostic.code == "schema_error"
    assert tuple(rows(snapshot)) == (MetricId.CODEX_WEEKLY,)


@pytest.mark.parametrize("status", [401, 429, 500])
async def test_failure_snapshot_emits_no_credits_row(status):
    provider, _ = provider_for(
        json.dumps({"credits": {"has_credits": True, "balance": "5"}}).encode(), status=status
    )
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert tuple(rows(snapshot)) == (MetricId.CODEX_WEEKLY,)
    assert credit_rows(snapshot) == []


async def test_ignored_credit_siblings_never_become_rows_or_money():
    provider, _ = provider_for(
        {
            "rate_limit": {"primary_window": window()},
            "credits": {
                "has_credits": True,
                "unlimited": False,
                "balance": "7",
                "approx_local_messages": [1, 2],
                "approx_cloud_messages": [3, 4],
            },
            "spend_control": {"reached": True},
            "rate_limit_reset_credits": {"available": 3},
        }
    )
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    result = rows(snapshot)
    assert tuple(result) == (MetricId.CODEX_WEEKLY, MetricId.CODEX_CREDITS)
    assert result[MetricId.CODEX_CREDITS].credits == 7
    assert result[MetricId.CODEX_CREDITS].balance is None
