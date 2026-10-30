"""Behavior and hostile-input boundaries for the frozen domain contract."""

import json
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal, localcontext

import pytest

from cli_usage_api.domain import (
    REQUIRED_METRIC_IDS,
    Account,
    CredentialKind,
    Diagnostic,
    DomainError,
    ExactMoney,
    FetchState,
    Grant,
    GrantCategory,
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
    claude_organization_id,
    credit_amount,
    default_poll_interval_seconds,
    dumps,
    format_timestamp,
    format_two_decimals,
    loads,
    new_account_id,
    openai_organization_id,
    openai_session_key,
    parse_timestamp,
    percent,
    remaining_percent,
    sanitize_text,
    utc_datetime,
    validate_credential_binding,
    validate_credential_kind,
)

ACCOUNT_ID = "00000000-0000-4000-8000-000000000001"
NOW = datetime(2026, 10, 28, 12, tzinfo=UTC)
SOURCE = SourceRef(SourceKind.OFFLINE_DEMO, "domain-test-v1")


def account(**changes):
    return Account(
        id=ACCOUNT_ID, provider=ProviderId.CLAUDE_SUBSCRIPTION, label="Synthetic account", **changes
    )


def snapshot():
    return Snapshot(
        account_id=ACCOUNT_ID,
        metrics=(
            Metric(
                MetricId.CLAUDE_FIVE_HOUR,
                "Five hour",
                MetricState.READY,
                SOURCE,
                quota=QuotaValue(used_percent=Decimal("105.2500")),
                reset_at=NOW,
            ),
            Metric(MetricId.CLAUDE_FABLE_WEEKLY, "Fable", MetricState.UNKNOWN, SOURCE),
            Metric(
                MetricId.CLAUDE_PURCHASED_BALANCE,
                "Balance",
                MetricState.READY,
                SOURCE,
                balance=Money(-17, "USD", 2),
            ),
        ),
        grants=(
            Grant(
                GrantCategory.PROMOTIONAL,
                Money(100, "USD", 2),
                Money(17, "USD", 2),
                id="synthetic-grant",
                program_id="subscription_api_credit",
                name="Synthetic",
                expires_at=NOW,
            ),
        ),
        fetch_state=FetchState.PARTIAL,
        attempted_at=NOW,
        fetched_at=NOW,
        retry_at=NOW + timedelta(seconds=60),
        diagnostic=Diagnostic("partial_data"),
    )


def test_ids_and_required_metric_inventory():
    assert len(ProviderId) == 5
    assert {str(item) for items in REQUIRED_METRIC_IDS.values() for item in items} == {
        "claude.subscription.five_hour",
        "claude.subscription.weekly",
        "claude.subscription.fable_weekly",
        "claude.platform.purchased_balance",
        "claude.platform.promotional_balance",
        "claude.platform.total_balance",
        "codex.subscription.weekly",
        "grok.subscription.shared_pool",
        "grok.product.build",
        "grok.product.chat",
        "openai.platform.available_balance",
    }
    assert new_account_id() != new_account_id()
    with pytest.raises(TypeError):
        REQUIRED_METRIC_IDS[ProviderId.CLAUDE_SUBSCRIPTION] = ()


def test_account_defaults_and_immutability():
    value = account()
    assert value.poll_interval_seconds == 60
    assert value.enabled is True
    with pytest.raises(FrozenInstanceError):
        value.label = "changed"
    assert account(poll_interval_seconds=30).poll_interval_seconds == 30
    assert account(poll_interval_seconds=3600).poll_interval_seconds == 3600


@pytest.mark.parametrize("value", [True, False, 29, 3601, 60.0, "60"])
def test_account_interval_rejects_wrong_types_and_bounds(value):
    with pytest.raises(DomainError):
        account(poll_interval_seconds=value)


@pytest.mark.parametrize(
    "changes",
    [
        {"id": "upstream-user-id"},
        {"enabled": 1},
        {"provider": "unknown"},
        {"credential_ref": "memory:opaque"},
        {"credential_kind": CredentialKind.MANUAL_BEARER},
        {"organization_id": "org-one"},
        {"credential_selector": "profile"},
    ],
)
def test_account_invalid_values(changes):
    with pytest.raises(DomainError):
        replace(account(), **changes)


def test_detached_codex_profile_round_trips_without_credential():
    value = Account(ACCOUNT_ID, ProviderId.CODEX_SUBSCRIPTION, "Codex")
    assert value.credential_ref is None
    assert loads(dumps(value)) == value


@pytest.mark.parametrize(
    "provider,kind",
    [
        (ProviderId.CLAUDE_SUBSCRIPTION, CredentialKind.CLAUDE_CODE_FILE),
        (ProviderId.CLAUDE_SUBSCRIPTION, CredentialKind.MANUAL_BEARER),
        (ProviderId.CLAUDE_PLATFORM, CredentialKind.CONSOLE_SESSION),
        (ProviderId.GROK_SUBSCRIPTION, CredentialKind.GROK_AUTH_FILE),
        (ProviderId.GROK_SUBSCRIPTION, CredentialKind.MANUAL_BEARER),
    ],
)
def test_read_credentials_preserve_explicit_provider_binding(provider, kind):
    value = ResolvedCredential(provider, kind, "synthetic-secret", "generation-1")
    validate_credential_binding(provider, value)
    assert "synthetic-secret" not in repr(value)
    assert "generation-1" not in repr(value)
    other = (
        ProviderId.GROK_SUBSCRIPTION
        if provider != ProviderId.GROK_SUBSCRIPTION
        else ProviderId.CLAUDE_SUBSCRIPTION
    )
    with pytest.raises(DomainError):
        validate_credential_binding(other, value)


@pytest.mark.parametrize(
    "provider",
    [p for p in ProviderId if p not in (ProviderId.CODEX_SUBSCRIPTION, ProviderId.OPENAI_PLATFORM)],
)
def test_api_keys_can_be_stored_but_never_enable_reads(provider):
    value = ResolvedCredential(provider, CredentialKind.API_KEY, "synthetic", "generation-1")
    with pytest.raises(DomainError):
        validate_credential_binding(provider, value)
    Account(ACCOUNT_ID, provider, "Stored only", "memory:opaque", CredentialKind.API_KEY)


def test_incompatible_imports_and_console_bearer_are_rejected():
    for provider, kind in (
        (ProviderId.CLAUDE_PLATFORM, CredentialKind.MANUAL_BEARER),
        (ProviderId.CLAUDE_SUBSCRIPTION, CredentialKind.CONSOLE_SESSION),
        (ProviderId.GROK_SUBSCRIPTION, CredentialKind.CLAUDE_CODE_FILE),
        (ProviderId.CODEX_SUBSCRIPTION, CredentialKind.GROK_AUTH_FILE),
    ):
        with pytest.raises(DomainError):
            validate_credential_kind(provider, kind)
    validate_credential_kind(ProviderId.CODEX_SUBSCRIPTION, CredentialKind.CODEX_AUTH_FILE)
    validate_credential_kind(
        ProviderId.CODEX_SUBSCRIPTION, CredentialKind.CODEX_AUTH_FILE, for_read=True
    )


def test_codex_identity_has_only_one_required_row_and_no_active_legacy_alias():
    assert REQUIRED_METRIC_IDS[ProviderId.CODEX_SUBSCRIPTION] == (MetricId.CODEX_WEEKLY,)
    assert MetricId.CODEX_FIVE_HOUR not in REQUIRED_METRIC_IDS[ProviderId.CODEX_SUBSCRIPTION]
    with pytest.raises(ValueError):
        ProviderId("chatgpt_subscription")
    with pytest.raises(ValueError):
        MetricId("chatgpt.subscription.weekly")


@pytest.mark.parametrize("kind", [k for k in CredentialKind if k != CredentialKind.CODEX_AUTH_FILE])
@pytest.mark.parametrize("for_read", [False, True])
def test_codex_rejects_every_other_credential_kind(kind, for_read):
    with pytest.raises(DomainError):
        validate_credential_kind(ProviderId.CODEX_SUBSCRIPTION, kind, for_read=for_read)
    with pytest.raises(DomainError):
        Account(ACCOUNT_ID, ProviderId.CODEX_SUBSCRIPTION, "Codex", "synthetic", kind)


def test_codex_resolved_selection_is_bound_redacted_and_not_serializable():
    value = ResolvedCredential(
        ProviderId.CODEX_SUBSCRIPTION,
        CredentialKind.CODEX_AUTH_FILE,
        "synthetic-bearer",
        "selection-generation",
        codex_account_id="synthetic-selected-account",
    )
    validate_credential_binding(ProviderId.CODEX_SUBSCRIPTION, value)
    assert value.codex_account_id == "synthetic-selected-account"
    for hidden in (value.secret, value.codex_account_id, value.generation_fingerprint):
        assert hidden not in repr(value)
    with pytest.raises(DomainError):
        dumps(value)


@pytest.mark.parametrize("selected", [None, "", " ", "a b", "a\r\nb", "a\x00b", "é", "x" * 257, 1])
def test_codex_selection_requires_a_nonempty_header_safe_id(selected):
    with pytest.raises(DomainError):
        ResolvedCredential(
            ProviderId.CODEX_SUBSCRIPTION,
            CredentialKind.CODEX_AUTH_FILE,
            "synthetic",
            "generation",
            codex_account_id=selected,
        )


@pytest.mark.parametrize(
    "provider,kind",
    [
        (ProviderId.CLAUDE_SUBSCRIPTION, CredentialKind.MANUAL_BEARER),
        (ProviderId.CLAUDE_PLATFORM, CredentialKind.CONSOLE_SESSION),
        (ProviderId.GROK_SUBSCRIPTION, CredentialKind.MANUAL_BEARER),
    ],
)
def test_codex_selection_is_forbidden_on_other_providers(provider, kind):
    with pytest.raises(DomainError):
        ResolvedCredential(provider, kind, "synthetic", "generation", codex_account_id="selected")


def test_codex_selection_cannot_be_substituted_with_grok_user_id():
    with pytest.raises(DomainError):
        ResolvedCredential(
            ProviderId.CODEX_SUBSCRIPTION,
            CredentialKind.CODEX_AUTH_FILE,
            "synthetic",
            "generation",
            user_id="synthetic-user",
            codex_account_id="selected",
        )


def test_money_exact_addition_and_rendering():
    assert Money(1, "USD", 2) + Money(2, "USD", 2) == Money(3, "USD", 2)
    assert Money(-123, "USD", 2).format() == "-1.23 USD"
    assert Money(0, "JPY", 0).format() == "0 JPY"
    assert Money(1, "USD", 4).format() == "0.0001 USD"
    for other in (Money(1, "EUR", 2), Money(1, "USD", 3)):
        with pytest.raises(DomainError):
            Money(1, "USD", 2) + other


@pytest.mark.parametrize(
    "minor,currency,exponent",
    [
        (True, "USD", 2),
        (1.0, "USD", 2),
        ("1", "USD", 2),
        (1, "usd", 2),
        (1, "USD", True),
        (1, "USD", -1),
        (1, "USD", 5),
    ],
)
def test_money_numeric_and_unit_validation(minor, currency, exponent):
    with pytest.raises(DomainError):
        Money(minor, currency, exponent)


def test_percentage_preserves_overage_and_never_invents_counts():
    value = QuotaValue(used_percent=Decimal("125.12500"))
    assert value.used_percent == Decimal("125.12500")
    assert value.remaining_percent == 0
    assert value.used_count is value.limit_count is value.remaining_count is None
    assert QuotaValue().remaining_percent is None
    assert QuotaValue(remaining_percent="12.125").used_percent is None
    assert QuotaValue(used_count=1).limit_count is None
    assert QuotaValue(used_percent=0).remaining_percent == 100


def test_percentage_math_is_independent_of_ambient_decimal_precision():
    raw = "0.123456789012345678901234567890123456789"
    with localcontext() as context:
        context.prec = 4
        assert remaining_percent(raw) == Decimal("99.876543210987654321098765432109876543211")


@pytest.mark.parametrize("raw", ["1e-10000000000", "1e+10000000000", "0e-10000000000"])
@pytest.mark.parametrize("representation", [str, Decimal])
def test_extreme_percentage_exponents_rejected_before_arithmetic(raw, representation, monkeypatch):
    def unexpected_arithmetic():
        pytest.fail("Out-of-bounds percentages must be rejected before subtraction")

    monkeypatch.setattr("cli_usage_api.domain.localcontext", unexpected_arithmetic)
    value = representation(raw)
    for operation in (
        lambda: percent(value),
        lambda: remaining_percent(value),
        lambda: QuotaValue(used_percent=value),
        lambda: QuotaValue(remaining_percent=value),
    ):
        with pytest.raises(DomainError):
            operation()


@pytest.mark.parametrize("raw", ["1e-10000000000", "1e+10000000000", "0e-10000000000"])
@pytest.mark.parametrize("field", ["used_percent", "remaining_percent"])
def test_serialized_extreme_percentage_exponents_are_rejected(raw, field, monkeypatch):
    payload = json.loads(dumps(snapshot()))
    payload["value"]["metrics"][0]["quota"] = {field: raw}

    def unexpected_arithmetic():
        pytest.fail("Serialized percentages must be bounded before subtraction")

    monkeypatch.setattr("cli_usage_api.domain.localcontext", unexpected_arithmetic)
    with pytest.raises(DomainError):
        loads(json.dumps(payload))


def test_percentage_bounds_preserve_exact_values_and_snapshot_round_trips():
    with localcontext() as context:
        context.prec = 4
        tiny = QuotaValue(used_percent="1e-1000")
        assert tiny.remaining_percent == Decimal("99." + "9" * 1000)
        overage = QuotaValue(used_percent="1e+1000")
        assert overage.used_percent == Decimal("1e+1000")
        assert overage.remaining_percent == 0
        coefficient = "1" * 1024
        assert percent(coefficient).as_tuple().digits == (1,) * 1024
        for quota in (tiny, overage, QuotaValue(used_percent=coefficient)):
            value = replace(snapshot(), metrics=(replace(snapshot().metrics[0], quota=quota),))
            assert loads(dumps(value)) == value


@pytest.mark.parametrize("raw", ["1e-1001", "1e+1001", "1" * 1025, "0" * 4097])
def test_percentage_precision_and_scale_limits(raw):
    with pytest.raises(DomainError):
        percent(raw)


@pytest.mark.parametrize("value", [True, False, -1, "-0.1", "NaN", "sNaN", "Infinity", 1.5, "bad"])
def test_invalid_percentages(value):
    with pytest.raises(DomainError):
        percent(value)
    with pytest.raises(DomainError):
        QuotaValue(used_percent=value)


@pytest.mark.parametrize("field", ["used_count", "limit_count", "remaining_count"])
@pytest.mark.parametrize("value", [True, False, -1, 1.5, "1"])
def test_invalid_count_fields(field, value):
    with pytest.raises(DomainError):
        QuotaValue(**{field: value})


def test_remaining_percentage_must_be_consistent():
    with pytest.raises(DomainError):
        QuotaValue(used_percent="10", remaining_percent="80")
    with pytest.raises(DomainError):
        QuotaValue(remaining_percent="101")


def test_timestamp_utc_normalization_and_subseconds():
    value = parse_timestamp("2026-10-28T14:00:00.123456+02:00")
    assert value == NOW.replace(microsecond=123456)
    assert value.tzinfo is UTC
    assert format_timestamp(value) == "2026-10-28T12:00:00.123456Z"
    assert utc_datetime(NOW.astimezone(timezone(timedelta(hours=-5)))) == NOW


@pytest.mark.parametrize(
    "value",
    [
        "2026-10-28T12:00:00",
        "2026-10-28",
        "2026-02-30T12:00:00Z",
        "2026-10-28T12:00:00+25:00",
        "2026-10-28T12:00:00+01:60",
        1793188800,
        True,
    ],
)
def test_timestamp_rejects_naive_numeric_and_invalid_values(value):
    with pytest.raises(DomainError):
        parse_timestamp(value)


def test_dataclasses_reject_naive_timestamps():
    naive = NOW.replace(tzinfo=None)
    for operation in (
        lambda: replace(snapshot(), attempted_at=naive),
        lambda: replace(snapshot().metrics[0], reset_at=naive),
        lambda: replace(snapshot().grants[0], expires_at=naive),
        lambda: ResolvedCredential(
            ProviderId.GROK_SUBSCRIPTION,
            CredentialKind.MANUAL_BEARER,
            "synthetic",
            "g1",
            expires_at=naive,
        ),
    ):
        with pytest.raises(DomainError):
            operation()


def test_round_trip_full_snapshot_and_account():
    connection = account(credential_ref="external:opaque", credential_kind="claude_code_file")
    for value in (connection, snapshot()):
        serialized = dumps(value)
        assert loads(serialized) == value
        assert type(value).from_dict(value.to_dict()) == value
        assert json.loads(serialized)["schema_version"] == 1
    payload = json.loads(dumps(snapshot()))
    assert payload["value"]["metrics"][0]["quota"]["used_percent"] == "105.2500"
    assert payload["value"]["metrics"][2]["balance"]["minor"] == -17
    assert payload["value"]["fetched_at"] == "2026-10-28T12:00:00Z"
    assert payload["value"]["metrics"][1]["quota"] is None


def test_snapshot_collection_immutability_and_duplicate_rejection():
    value = snapshot()
    with pytest.raises(FrozenInstanceError):
        value.fetch_state = FetchState.OK
    with pytest.raises(DomainError):
        replace(value, metrics=list(value.metrics))
    with pytest.raises(DomainError):
        replace(value, grants=list(value.grants))
    with pytest.raises(DomainError):
        replace(value, metrics=(value.metrics[0], value.metrics[0]))
    with pytest.raises(FrozenInstanceError):
        value.metrics[0].quota.used_percent = Decimal(0)


def test_all_metric_states_and_fetch_states_are_representable():
    for state in MetricState:
        assert replace(snapshot().metrics[0], state=state).state == state
    for state in FetchState:
        assert loads(dumps(replace(snapshot(), fetch_state=state))).fetch_state == state


def test_grant_units_and_metric_value_types_are_checked():
    with pytest.raises(DomainError):
        Grant("purchased", Money(1, "USD", 2), Money(1, "EUR", 2))
    with pytest.raises(DomainError):
        replace(snapshot().metrics[0], balance=Money(1, "USD", 2))
    with pytest.raises(DomainError):
        replace(snapshot().metrics[0], source={})
    assert replace(snapshot(), organization_id="synthetic-org-1").organization_id
    with pytest.raises(DomainError):
        replace(snapshot(), organization_id="../other")


def test_product_share_is_exact_bounded_and_never_a_quota():
    product = Metric(
        MetricId.GROK_BUILD, "GrokBuild", MetricState.READY, SOURCE, share_percent="150.25"
    )
    assert product.share_percent == Decimal("150.25") and product.quota is None
    assert Metric(MetricId.GROK_CHAT, "c", MetricState.READY, SOURCE).share_percent is None
    for bad in (-1, "nan", "1e1001", "1." + "1" * 1024, 1.5, True):
        with pytest.raises(DomainError):
            replace(product, share_percent=bad)
    with pytest.raises(DomainError):
        replace(product, quota=QuotaValue(used_percent=10))
    with pytest.raises(DomainError):
        replace(product, balance=Money(1, "USD", 2))


def test_display_text_is_sanitized_and_bounded():
    raw = "\x1b[31m[bold]hello[/bold]\n\x00\x1b]8;;https://invalid\x07world"
    assert sanitize_text(raw) == "boldhello/boldworld"
    assert len(replace(account(), label="a" * 1000).label) == 80
    assert "[" not in replace(snapshot().grants[0], name=raw).name
    assert "\x1b" not in replace(snapshot().metrics[0], detail=raw).detail


def test_safe_diagnostics_do_not_accept_arbitrary_messages_or_codes():
    value = Diagnostic("auth_required")
    assert value.message == "Reconnect this account using a supported credential."
    with pytest.raises(TypeError):
        Diagnostic("auth_required", "synthetic-secret")
    with pytest.raises(DomainError) as caught:
        Diagnostic("synthetic-secret /private/credential/path")
    assert "synthetic-secret" not in str(caught.value)


def test_safe_transport_error_fields_and_serialization_refusal():
    value = TransportError(FetchState.RATE_LIMITED, "rate_limited", status=429, retry_at=NOW)
    assert value.status == 429
    assert value.retry_at == NOW
    assert value.fetch_state == FetchState.RATE_LIMITED
    assert "Wait until" in str(value)
    for kwargs in ({"status": True}, {"status": 600}, {"retry_at": NOW.replace(tzinfo=None)}):
        with pytest.raises(DomainError):
            TransportError(FetchState.NETWORK_ERROR, "network_error", **kwargs)
    with pytest.raises(DomainError):
        TransportError(FetchState.OK, "network_error")
    credential = ResolvedCredential(
        ProviderId.GROK_SUBSCRIPTION, CredentialKind.MANUAL_BEARER, "synthetic-secret", "g1"
    )
    with pytest.raises(DomainError):
        dumps(credential)


@pytest.mark.parametrize(
    "payload",
    [
        "null",
        "[]",
        "{}",
        '{"schema_version":1,"schema_version":1}',
        '{"schema_version":NaN}',
        "not JSON",
    ],
)
def test_bad_json_is_safely_rejected(payload):
    with pytest.raises(DomainError):
        loads(payload)


def test_schema_and_nested_unknown_fields_are_rejected():
    for version in (True, 0, 2, 1.0):
        data = json.loads(dumps(account()))
        data["schema_version"] = version
        with pytest.raises(DomainError):
            loads(json.dumps(data))
    data = snapshot().to_dict()
    data["metrics"][0]["raw_response"] = "synthetic-secret"
    with pytest.raises(DomainError) as caught:
        Snapshot.from_dict(data)
    assert "synthetic-secret" not in str(caught.value)
    data = snapshot().to_dict()
    data["diagnostic"]["message"] = "synthetic-secret"
    with pytest.raises(DomainError):
        Snapshot.from_dict(data)
    with pytest.raises(DomainError):
        Account.from_dict({"id": ACCOUNT_ID})


def test_optional_extra_metric_ids_are_not_required_rows():
    assert MetricId.CLAUDE_EXTRA_USAGE == "claude.subscription.extra_usage"
    assert MetricId.CODEX_CREDITS == "codex.subscription.credits"
    required = {item for items in REQUIRED_METRIC_IDS.values() for item in items}
    assert MetricId.CLAUDE_EXTRA_USAGE not in required
    assert MetricId.CODEX_CREDITS not in required


def extra(**changes):
    return Metric(
        MetricId.CLAUDE_EXTRA_USAGE, "Claude 额外用量", MetricState.READY, SOURCE, **changes
    )


def credits_row(**changes):
    return Metric(MetricId.CODEX_CREDITS, "Codex credits", MetricState.READY, SOURCE, **changes)


def test_new_metric_fields_default_to_absent():
    row = Metric(MetricId.CODEX_WEEKLY, "Weekly", MetricState.UNKNOWN, SOURCE)
    assert (row.spent, row.spend_limit, row.credits, row.unlimited) == (None, None, None, False)


def test_spend_against_cap_may_carry_cap_utilization_quota():
    row = extra(
        spent=Money(1250, "USD", 2),
        spend_limit=Money(5000, "USD", 2),
        quota=QuotaValue(used_percent=Decimal("25.0")),
    )
    assert row.spent.format() == "12.50 USD"
    assert row.spend_limit.format() == "50.00 USD"
    assert row.quota.used_percent == Decimal("25.0")
    assert row.balance is None and row.reset_at is None
    assert extra(spent=Money(0, "JPY", 0)).spend_limit is None
    assert extra(spend_limit=Money(0, "USD", 2)).spent is None
    assert extra(spent=Money(1, "USD", 2), unlimited=True).unlimited is True


@pytest.mark.parametrize(
    "changes",
    [
        {"spent": 1250},
        {"spent": Decimal(1)},
        {"spend_limit": {"minor": 1, "currency": "USD", "exponent": 2}},
        {"spent": Money(1, "USD", 2), "spend_limit": Money(1, "EUR", 2)},
        {"spent": Money(1, "USD", 2), "spend_limit": Money(1, "USD", 0)},
        {"spent": Money(1, "USD", 2), "balance": Money(1, "USD", 2)},
        {"spend_limit": Money(1, "USD", 2), "balance": Money(1, "USD", 2)},
        {"spent": Money(1, "USD", 2), "share_percent": Decimal(1)},
        {"spend_limit": Money(1, "USD", 2), "share_percent": Decimal(1)},
        {"spent": Money(1, "USD", 2), "credits": Decimal(1)},
        {"spend_limit": Money(1, "USD", 2), "credits": Decimal(1)},
        {"credits": Decimal(1), "quota": QuotaValue(used_percent=1)},
        {"credits": Decimal(1), "balance": Money(1, "USD", 2)},
        {"credits": Decimal(1), "share_percent": Decimal(1)},
        {"unlimited": True, "spend_limit": Money(1, "USD", 2)},
        {"unlimited": True, "credits": Decimal(1)},
        {"unlimited": 1},
        {"unlimited": 0},
        {"unlimited": "true"},
        {"unlimited": None},
    ],
)
def test_spend_credit_and_unlimited_invariants(changes):
    with pytest.raises(DomainError):
        extra(**changes)


def test_unlimited_alone_and_credits_alone_are_valid():
    assert extra(unlimited=True).unlimited is True
    assert credits_row(unlimited=True).credits is None
    row = credits_row(credits="1234.5")
    assert row.credits == Decimal("1234.5") and type(row.credits) is Decimal
    assert row.quota is None and row.balance is None and row.unlimited is False


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0", Decimal(0)),
        ("-5", Decimal(-5)),
        ("-0.25", Decimal("-0.25")),
        (0, Decimal(0)),
        (-3, Decimal(-3)),
        (Decimal("12.3400"), Decimal("12.3400")),
        ("1e40", Decimal("1e40")),
        ("1e-40", Decimal("1e-40")),
        ("9" * 40, Decimal("9" * 40)),
        (10**40 - 1, Decimal(10**40 - 1)),
        ("1" * 64, None),
    ],
)
def test_credit_amount_accepts_bounded_exact_values(raw, expected):
    if expected is None:
        with pytest.raises(DomainError):
            credit_amount(raw)
        return
    value = credit_amount(raw)
    assert value == expected and type(value) is Decimal
    assert str(value) == str(expected)


@pytest.mark.parametrize(
    "raw",
    [
        1.5,
        0.0,
        True,
        False,
        None,
        [],
        {"balance": "1"},
        b"1",
        "",
        " ",
        "abc",
        "nan",
        "NaN",
        "-sNaN",
        "inf",
        "-Infinity",
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
        "1e41",
        "1e-41",
        "1e999999999",
        "1E-999999999",
        Decimal("1e1000000"),
        "1" * 41,
        "0." + "1" * 41,
        "1" * 65,
        " " * 30 + "1" * 35,
        10**40,
        -(10**40),
        pytest.param(10**5000, id="huge-int"),
        Decimal("1" * 41),
    ],
)
def test_credit_amount_rejects_hostile_or_unsupported_values(raw):
    with pytest.raises(DomainError):
        credit_amount(raw)
    if type(raw) in (Decimal, int, str):
        with pytest.raises(DomainError):
            credits_row(credits=raw)


def test_credit_amount_rejects_long_strings_before_parsing(monkeypatch):
    from cli_usage_api import domain

    def forbidden(*args, **kwargs):
        pytest.fail("Oversized text must be rejected before Decimal parsing")

    monkeypatch.setattr(domain, "Decimal", forbidden)
    with pytest.raises(DomainError):
        credit_amount("1" * 65)


def test_credit_amount_is_independent_of_ambient_decimal_precision():
    with localcontext() as context:
        context.prec = 3
        assert credit_amount("1234567.891") == Decimal("1234567.891")


def test_spend_credits_and_unlimited_round_trip_through_json():
    rows = (
        extra(
            spent=Money(1250, "USD", 2),
            spend_limit=Money(5000, "USD", 2),
            quota=QuotaValue(used_percent=Decimal("25.00")),
            detail="Synthetic billing-period spend.",
        ),
        replace(
            extra(),
            id="claude.subscription.extra_usage_b",
            spent=Money(7, "JPY", 0),
            unlimited=True,
        ),
        credits_row(credits=Decimal("-0.5000")),
        replace(credits_row(), id="codex.subscription.credits_b", unlimited=True),
    )
    value = replace(snapshot(), metrics=rows)
    serialized = dumps(value)
    restored = loads(serialized)
    assert restored == value
    assert Snapshot.from_dict(value.to_dict()) == value
    payload = json.loads(serialized)["value"]["metrics"]
    assert payload[0]["spent"] == {"minor": 1250, "currency": "USD", "exponent": 2}
    assert payload[0]["spend_limit"] == {"minor": 5000, "currency": "USD", "exponent": 2}
    assert payload[0]["unlimited"] is False and payload[0]["credits"] is None
    assert payload[1]["unlimited"] is True and payload[1]["spend_limit"] is None
    assert payload[2]["credits"] == "-0.5000"
    assert str(restored.metrics[2].credits) == "-0.5000"
    assert json.loads(serialized)["schema_version"] == 1


def test_old_snapshots_without_new_metric_keys_still_load():
    payload = json.loads(dumps(snapshot()))
    for metric in payload["value"]["metrics"]:
        for name in ("spent", "spend_limit", "credits", "unlimited"):
            del metric[name]
    restored = loads(json.dumps(payload))
    assert restored == snapshot()
    assert all(
        (m.spent, m.spend_limit, m.credits, m.unlimited) == (None, None, None, False)
        for m in restored.metrics
    )


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("credits", "1e999999999"),
        ("credits", "1" * 65),
        ("credits", "NaN"),
        ("credits", [1]),
        ("credits", True),
        ("unlimited", "true"),
        ("unlimited", 1),
        ("spent", {"minor": 1, "currency": "usd", "exponent": 2}),
        ("spent", {"minor": 1, "currency": "USD", "exponent": 2, "extra": 1}),
        ("spent", "12.50"),
        ("spend_limit", {"minor": True, "currency": "USD", "exponent": 2}),
    ],
)
def test_serialized_new_metric_fields_are_validated(name, value):
    payload = json.loads(dumps(replace(snapshot(), metrics=(credits_row(),))))
    payload["value"]["metrics"][0][name] = value
    with pytest.raises(DomainError):
        loads(json.dumps(payload))


def test_serialized_unit_mismatch_and_exclusivity_are_rejected():
    payload = json.loads(dumps(replace(snapshot(), metrics=(extra(),))))
    metric = payload["value"]["metrics"][0]
    metric["spent"] = {"minor": 1, "currency": "USD", "exponent": 2}
    metric["spend_limit"] = {"minor": 1, "currency": "EUR", "exponent": 2}
    with pytest.raises(DomainError):
        loads(json.dumps(payload))
    metric["spend_limit"] = None
    metric["credits"] = "1"
    with pytest.raises(DomainError):
        loads(json.dumps(payload))


# --- Claude subscription organization, OpenAI Platform and exact money -------------

CLAUDE_ORG = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
OPENAI_ORG = "org-Synthetic0123"


def test_claude_subscription_accepts_only_an_optional_canonical_uuid_organization():
    assert account().organization_id is None
    assert account(organization_id=CLAUDE_ORG).organization_id == CLAUDE_ORG
    for value in (CLAUDE_ORG.upper(), CLAUDE_ORG.replace("-", ""), "{" + CLAUDE_ORG + "}", "org-1"):
        with pytest.raises(DomainError):
            account(organization_id=value)
    credential = ResolvedCredential(
        ProviderId.CLAUDE_SUBSCRIPTION,
        CredentialKind.MANUAL_BEARER,
        "synthetic",
        "generation-1",
        organization_id=CLAUDE_ORG,
    )
    assert credential.organization_id == CLAUDE_ORG
    with pytest.raises(DomainError):
        replace(credential, organization_id=CLAUDE_ORG.upper())
    # Saved accounts without an organization keep loading unchanged.
    saved = account(poll_interval_seconds=200)
    assert loads(dumps(saved)) == saved
    assert loads(dumps(account(organization_id=CLAUDE_ORG))).organization_id == CLAUDE_ORG


def openai_account(**changes):
    values = {
        "id": ACCOUNT_ID,
        "provider": ProviderId.OPENAI_PLATFORM,
        "label": "Synthetic OpenAI",
        "organization_id": OPENAI_ORG,
    }
    return Account(**{**values, **changes})


def test_openai_platform_requires_its_session_kind_and_organization():
    value = openai_account(
        credential_ref="session:" + ACCOUNT_ID,
        credential_kind=CredentialKind.OPENAI_PLATFORM_SESSION,
    )
    assert value.organization_id == OPENAI_ORG
    assert loads(dumps(value)) == value
    for org in (None, "org-short", "org-" + "a" * 65, "Org-Synthetic0123", "org-Synthetic_0123"):
        with pytest.raises(DomainError):
            openai_account(organization_id=org)
    for kind in (
        CredentialKind.API_KEY,
        CredentialKind.MANUAL_BEARER,
        CredentialKind.CONSOLE_SESSION,
        CredentialKind.CODEX_AUTH_FILE,
    ):
        with pytest.raises(DomainError):
            validate_credential_kind(ProviderId.OPENAI_PLATFORM, kind)
    for provider in ProviderId:
        if provider != ProviderId.OPENAI_PLATFORM:
            with pytest.raises(DomainError):
                validate_credential_kind(provider, CredentialKind.OPENAI_PLATFORM_SESSION)
    resolved = ResolvedCredential(
        ProviderId.OPENAI_PLATFORM,
        CredentialKind.OPENAI_PLATFORM_SESSION,
        "synthetic-session-value-0000",
        "generation-1",
        organization_id=OPENAI_ORG,
    )
    validate_credential_binding(ProviderId.OPENAI_PLATFORM, resolved)
    with pytest.raises(DomainError):
        replace(resolved, organization_id=None)
    with pytest.raises(DomainError):
        validate_credential_binding(ProviderId.CLAUDE_PLATFORM, resolved)
    # Other providers never carry an OpenAI-shaped organization.
    with pytest.raises(DomainError):
        account(organization_id=OPENAI_ORG)


def test_poll_floors_apply_to_saved_intervals_and_new_defaults():
    assert openai_account().effective_poll_interval_seconds == 300
    assert openai_account(poll_interval_seconds=900).effective_poll_interval_seconds == 900
    assert account().effective_poll_interval_seconds == 180
    assert default_poll_interval_seconds(ProviderId.OPENAI_PLATFORM) == 300
    assert default_poll_interval_seconds(ProviderId.CLAUDE_SUBSCRIPTION) == 180
    assert default_poll_interval_seconds(ProviderId.GROK_SUBSCRIPTION) == 60


def test_organization_and_session_input_helpers():
    assert claude_organization_id(CLAUDE_ORG) == CLAUDE_ORG
    assert openai_organization_id(f"  {OPENAI_ORG}\n") == OPENAI_ORG
    for value in (None, 7, CLAUDE_ORG.upper()):
        with pytest.raises(DomainError):
            claude_organization_id(value)
    with pytest.raises(DomainError):
        openai_organization_id("org-a b")
    token = "sess-" + "A1b2C3d4" * 3
    assert openai_session_key(f"  {token}\n") == token
    assert openai_session_key("x" * 20) == "x" * 20
    for value in (
        None,
        "x" * 19,
        "x" * 4097,
        f"Bearer {token}",
        f"bearer{token}",
        f"Cookie: a={token}",
        f"sessionKey={token}",
        f"__Secure-next-auth.session-token={token}",
        f"Authorization: Bearer {token}",
        token[:10] + " " + token[10:],
        token[:10] + "\r\n" + token[10:],
        json.dumps({"token": token}),
        '{"log": {"entries": []}}',
        token + "é",
    ):
        with pytest.raises(DomainError):
            openai_session_key(value)


def test_exact_money_bounds_rounding_and_round_trip():
    value = ExactMoney(Decimal("17.3715455"), "USD")
    assert value.rounded_to_cents() == (Decimal("17.37"), True)
    assert value.format_cents() == "17.37 USD"
    assert ExactMoney(Decimal("4.9"), "USD").rounded_to_cents() == (Decimal("4.90"), False)
    # Half-even: ties go to the even cent.
    assert ExactMoney(Decimal("0.125"), "USD").format_cents() == "0.12 USD"
    assert ExactMoney(Decimal("0.135"), "USD").format_cents() == "0.14 USD"
    assert ExactMoney(Decimal("-3.075"), "USD").format_cents() == "-3.08 USD"
    assert ExactMoney(Decimal("1E+3"), "USD").format_cents() == "1000.00 USD"
    assert ExactMoney(5, "USD").amount == Decimal(5)
    assert format_two_decimals(Decimal("137.5")) == "137.50"
    assert format_two_decimals(Decimal("1E-30")) == "0.00"
    for amount in (
        True,
        1.5,
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("1E+100000"),
        Decimal("1E-100000"),
        "1" * 65,
    ):
        with pytest.raises(DomainError):
            ExactMoney(amount, "USD")
    for currency in ("usd", "US", "USDX", None):
        with pytest.raises(DomainError):
            ExactMoney(Decimal(1), currency)


def test_metric_exact_balance_is_exclusive_and_serializable():
    exact = ExactMoney(Decimal("3.0700000000000003"), "USD")
    row = Metric(
        MetricId.OPENAI_AVAILABLE_BALANCE, "OpenAI", MetricState.READY, SOURCE, exact_balance=exact
    )
    value = Snapshot(
        ACCOUNT_ID,
        (row,),
        (),
        FetchState.OK,
        NOW,
        fetched_at=NOW,
        organization_id=OPENAI_ORG,
    )
    restored = loads(dumps(value))
    assert restored == value
    assert restored.metrics[0].exact_balance.amount == Decimal("3.0700000000000003")
    assert json.loads(dumps(value))["value"]["metrics"][0]["exact_balance"] == {
        "amount": "3.0700000000000003",
        "currency": "USD",
    }
    for extra in (
        {"quota": QuotaValue(used_percent=Decimal(1))},
        {"balance": Money(1, "USD", 2)},
        {"share_percent": Decimal(1)},
        {"spent": Money(1, "USD", 2)},
        {"spend_limit": Money(1, "USD", 2)},
        {"credits": Decimal(1)},
        {"unlimited": True},
    ):
        with pytest.raises(DomainError):
            replace(row, **extra)
    with pytest.raises(DomainError):
        replace(row, exact_balance=Money(1, "USD", 2))
    # Snapshots serialized before the field existed still load.
    data = json.loads(dumps(snapshot()))
    for metric in data["value"]["metrics"]:
        metric.pop("exact_balance")
    assert loads(json.dumps(data)) == snapshot()
    # A hostile serialized amount is rejected, not expanded.
    data = json.loads(dumps(value))
    data["value"]["metrics"][0]["exact_balance"]["amount"] = "1E+999999999"
    with pytest.raises(DomainError):
        loads(json.dumps(data))


def test_new_metric_ids_are_optional_extras():
    required = {item for items in REQUIRED_METRIC_IDS.values() for item in items}
    assert MetricId.CLAUDE_CREDIT_BALANCE == "claude.subscription.credit_balance"
    assert MetricId.OPENAI_PAID_AVAILABLE_BALANCE == "openai.platform.paid_available_balance"
    assert MetricId.CLAUDE_CREDIT_BALANCE not in required
    assert MetricId.OPENAI_PAID_AVAILABLE_BALANCE not in required
    assert REQUIRED_METRIC_IDS[ProviderId.OPENAI_PLATFORM] == (MetricId.OPENAI_AVAILABLE_BALANCE,)
