"""Console contract tests: synthetic responses and real bounded Transport only."""

import json
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from cli_usage_api.domain import (
    REQUIRED_METRIC_IDS,
    Account,
    CredentialKind,
    DomainError,
    FetchState,
    GrantCategory,
    MetricState,
    ProviderId,
    ResolvedCredential,
    SourceKind,
    TransportError,
)
from cli_usage_api.providers.console import ConsoleProvider, OrganizationChoice
from cli_usage_api.transport import Transport

NOW = datetime(2026, 10, 28, 12, tzinfo=UTC)
ACCOUNT = Account(
    "00000000-0000-0000-0000-000000000005",
    ProviderId.CLAUDE_PLATFORM,
    "Synthetic Platform",
    credential_kind=CredentialKind.CONSOLE_SESSION,
    credential_ref="memory:synthetic",
    organization_id="org-selected",
)
CREDENTIAL = ResolvedCredential(
    ACCOUNT.provider, CredentialKind.CONSOLE_SESSION, "synthetic-session", "generation-1"
)


@pytest.fixture
def payload():
    return json.loads((Path(__file__).parent / "fixtures" / "console_credits.json").read_text())


def provider_for(payload, *, status=200, headers=None, path=None):
    requests = []

    def handler(request):
        requests.append(request)
        assert request.method == "GET"
        assert request.url.host == "platform.claude.com"
        assert request.url.path == (path or "/api/organizations/org-selected/prepaid/credits")
        assert not request.url.query
        assert request.headers["cookie"] == "sessionKey=synthetic-session"
        assert "authorization" not in request.headers
        return httpx.Response(status, json=payload, headers=headers)

    return ConsoleProvider(Transport(http_transport=httpx.MockTransport(handler))), requests


def assert_rows(snapshot):
    assert tuple(row.id for row in snapshot.metrics) == REQUIRED_METRIC_IDS[ACCOUNT.provider]
    assert all(
        row.source.kind == SourceKind.PRIVATE_HTTP and row.source.version_sensitive
        for row in snapshot.metrics
    )
    assert all(row.quota is None and row.reset_at is None for row in snapshot.metrics)
    assert "synthetic-session" not in repr(snapshot)


async def test_complete_all_grants_single_selected_org_read(payload):
    provider, requests = provider_for(payload)
    assert provider.requires_credential is True
    assert provider.metric_ids == REQUIRED_METRIC_IDS[ACCOUNT.provider]
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert_rows(snapshot)
    assert len(requests) == 1
    assert snapshot.fetch_state == FetchState.OK
    assert snapshot.fetched_at == snapshot.attempted_at == NOW
    assert snapshot.organization_id == ACCOUNT.organization_id
    assert [row.balance.minor for row in snapshot.metrics] == [1200, 250, 1450]
    assert snapshot.metrics[0].expires_at == datetime(2026, 11, 1, 12, tzinfo=UTC)
    assert snapshot.metrics[1].expires_at == datetime(2026, 11, 5, 12, tzinfo=UTC)
    assert snapshot.metrics[2].expires_at is None
    assert len(snapshot.grants) == 6
    assert snapshot.grants[2].remaining.minor == 0
    assert snapshot.grants[3].remaining.minor == 999
    assert snapshot.grants[4].category == GrantCategory.PROMOTIONAL
    assert snapshot.grants[4].program_id == "subscription_api_credit"
    assert "not subscription usage windows" in snapshot.metrics[1].detail


@pytest.mark.parametrize("raw", [None, "missing"])
@pytest.mark.parametrize("key,index", [("tranches", 0), ("promo_tranches", 1)])
async def test_missing_category_not_derived_from_total(payload, raw, key, index):
    if raw == "missing":
        payload.pop(key)
    else:
        payload[key] = raw
    provider, _ = provider_for(payload)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert_rows(snapshot)
    assert snapshot.fetch_state == FetchState.PARTIAL
    assert snapshot.diagnostic.code == "partial_data"
    assert snapshot.metrics[index].state == MetricState.UNKNOWN
    assert snapshot.metrics[index].balance is None
    assert snapshot.metrics[1 - index].state == MetricState.READY
    assert snapshot.metrics[2].balance.minor == 1450


async def test_explicit_empty_arrays_are_zero_and_default_units():
    provider, _ = provider_for({"amount": 0, "tranches": [], "promo_tranches": []})
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert snapshot.fetch_state == FetchState.OK
    assert snapshot.grants == ()
    assert [row.balance.format() for row in snapshot.metrics] == ["0.00 USD"] * 3


@pytest.mark.parametrize("key,index", [("tranches", 0), ("promo_tranches", 1)])
@pytest.mark.parametrize("field", ["granted_amount_minor_units", "remaining_amount_minor_units"])
@pytest.mark.parametrize("raw", [None, True, 1.5, "100", {}, []])
async def test_invalid_grant_numeric_isolates_complete_category(payload, key, index, field, raw):
    payload[key][-1][field] = raw
    provider, _ = provider_for(payload)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert snapshot.fetch_state == FetchState.PARTIAL
    assert snapshot.metrics[index].balance is None
    assert snapshot.metrics[1 - index].balance is not None
    assert snapshot.metrics[2].balance.minor == 1450
    assert all(
        grant.category != (GrantCategory.PURCHASED if index == 0 else GrantCategory.PROMOTIONAL)
        for grant in snapshot.grants
    )


@pytest.mark.parametrize("raw", [{}, "array", [None], [1], [True]])
async def test_malformed_category_does_not_discard_total_or_other_category(payload, raw):
    payload["tranches"] = raw
    provider, _ = provider_for(payload)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert snapshot.metrics[0].balance is None
    assert snapshot.metrics[1].balance.minor == 250
    assert snapshot.metrics[2].balance.minor == 1450


@pytest.mark.parametrize(
    "expiry", [None, "missing", "invalid", "2026-11-01T12:00:00", 1790000000, True]
)
async def test_unknown_expiry_retains_reported_money_with_uncertainty(payload, expiry):
    if expiry == "missing":
        payload["tranches"][0].pop("expires_at")
    else:
        payload["tranches"][0]["expires_at"] = expiry
    provider, _ = provider_for(payload)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert snapshot.fetch_state == FetchState.PARTIAL
    assert snapshot.metrics[0].balance.minor == 1200
    assert snapshot.grants[0].expires_at is None
    assert "uncertain" in snapshot.metrics[0].detail
    assert snapshot.metrics[0].expires_at == datetime(2026, 11, 2, 12, tzinfo=UTC)


async def test_expiry_timezone_normalization_and_all_expired(payload):
    for entry in payload["tranches"]:
        entry["expires_at"] = "2026-10-28T14:00:00+02:00"
    payload["amount"] = 250
    provider, _ = provider_for(payload)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert snapshot.fetch_state == FetchState.OK
    assert snapshot.metrics[0].balance.minor == 0
    assert snapshot.metrics[0].expires_at is None
    assert all(grant.expires_at == NOW for grant in snapshot.grants[:4])


async def test_negative_zero_and_nondefault_units_preserved(payload):
    payload.update(amount=-50, currency="JPY", balance={"credits": {"exponent": 0}})
    payload["tranches"] = [
        {
            "granted_amount_minor_units": -100,
            "remaining_amount_minor_units": -50,
            "expires_at": "2026-12-01T00:00:00Z",
        }
    ]
    payload["promo_tranches"] = []
    provider, _ = provider_for(payload)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert snapshot.fetch_state == FetchState.OK
    assert [row.balance.format() for row in snapshot.metrics] == ["-50 JPY", "0 JPY", "-50 JPY"]
    assert snapshot.grants[0].granted.minor == -100


@pytest.mark.parametrize("exponent", [0, 1, 2, 3, 4])
async def test_supported_exponents(payload, exponent):
    payload["balance"]["credits"]["exponent"] = exponent
    provider, _ = provider_for(payload)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert all(row.balance.exponent == exponent for row in snapshot.metrics)


@pytest.mark.parametrize(
    "patch",
    [
        {"currency": None},
        {"currency": "usd"},
        {"currency": "US"},
        {"currency": True},
        {"balance": None},
        {"balance": []},
        {"balance": {"credits": None}},
        *({"balance": {"credits": {"exponent": value}}} for value in [None, -1, 5, True, 2.0, "2"]),
    ],
)
async def test_invalid_units_never_assume_usd_or_cents(payload, patch):
    payload.update(patch)
    provider, _ = provider_for(payload)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert_rows(snapshot)
    assert snapshot.fetch_state == FetchState.SCHEMA_ERROR
    assert snapshot.fetched_at is None
    assert all(row.balance is None for row in snapshot.metrics)


@pytest.mark.parametrize(
    "amount,currency,exponent,difference",
    [(1451, "USD", 2, "0.01 USD"), (-123, "USD", 2, "-15.73 USD"), (1451, "JPY", 0, "1 JPY")],
)
async def test_authoritative_total_disagreement_is_a_warning_without_overwriting_amounts(
    payload, amount, currency, exponent, difference
):
    payload.update(amount=amount, currency=currency)
    payload["balance"]["credits"]["exponent"] = exponent
    provider, _ = provider_for(payload)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert [row.balance.minor for row in snapshot.metrics] == [1200, 250, amount]
    assert all(row.state == MetricState.READY for row in snapshot.metrics)
    assert snapshot.fetch_state == FetchState.OK
    assert snapshot.fetched_at == NOW
    assert snapshot.diagnostic.code == "balance_mismatch"
    assert difference in snapshot.metrics[2].detail


async def test_unknown_expiry_with_total_disagreement_remains_partial(payload):
    payload["amount"] = 1451
    payload["tranches"][0]["expires_at"] = None
    provider, _ = provider_for(payload)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert snapshot.fetch_state == FetchState.PARTIAL
    assert snapshot.diagnostic.code == "partial_data"
    assert [row.balance.minor for row in snapshot.metrics] == [1200, 250, 1451]
    assert snapshot.grants[0].expires_at is None
    assert "0.01 USD" in snapshot.metrics[2].detail


@pytest.mark.parametrize("amount", [None, True, "1450", 1450.5])
async def test_invalid_total_independent_from_valid_categories(payload, amount):
    payload["amount"] = amount
    provider, _ = provider_for(payload)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert snapshot.fetch_state == FetchState.PARTIAL
    assert snapshot.diagnostic.code == "partial_data"
    assert [row.balance.minor for row in snapshot.metrics[:2]] == [1200, 250]
    assert snapshot.metrics[2].balance is None


@pytest.mark.parametrize("payload", [[], None, "secret upstream body", {}, {"amount": True}])
async def test_wholly_unusable_response_keeps_unknown_rows(payload):
    provider, _ = provider_for(payload)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert_rows(snapshot)
    assert snapshot.fetch_state == FetchState.SCHEMA_ERROR
    assert snapshot.fetched_at is None
    assert snapshot.diagnostic.code == "schema_error"
    assert all(row.balance is None for row in snapshot.metrics)


async def test_grant_display_metadata_is_sanitized(payload):
    payload["tranches"][0].update(name="\x1b[31m[red]bad\nname", program_id="[bold]example\r")
    provider, _ = provider_for(payload)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert "\x1b" not in snapshot.grants[0].name
    assert "[" not in snapshot.grants[0].name
    assert "\n" not in snapshot.grants[0].name
    assert "[" not in snapshot.grants[0].program_id


@pytest.mark.parametrize("count", [0, 1, 2])
async def test_discovery_returns_explicit_choices_never_selects_or_fetches_credits(count):
    organizations = [
        {"uuid": f"org-{index}", "name": "[bold]Organization\n", "capabilities": ["api"]}
        for index in range(count)
    ]
    organizations.append({"uuid": "chat-only", "capabilities": ["chat"]})
    provider, requests = provider_for(organizations, path="/api/organizations")
    choices = await provider.discover_organizations(CREDENTIAL)
    assert isinstance(choices, tuple)
    assert len(choices) == count
    assert len(requests) == 1
    assert ACCOUNT.organization_id == "org-selected"
    assert all("[" not in choice.label and "\n" not in choice.label for choice in choices)
    if choices:
        with pytest.raises(FrozenInstanceError):
            choices[0].id = "other"


@pytest.mark.parametrize(
    "organizations",
    [
        {},
        None,
        [None],
        [{"uuid": "org-a"}],
        [{"uuid": "../escape", "capabilities": ["api"]}],
        [{"uuid": "x" * 65, "capabilities": ["api"]}],
        [{"uuid": "org-a", "capabilities": "api"}],
        [{"uuid": "org-a", "capabilities": ["api"]}] * 2,
    ],
)
async def test_discovery_invalid_candidates_safe_schema_error(organizations):
    provider, _ = provider_for(organizations, path="/api/organizations")
    with pytest.raises(TransportError) as raised:
        await provider.discover_organizations(CREDENTIAL)
    assert raised.value.code == "schema_error"


@pytest.mark.parametrize(
    "status,state", [(401, FetchState.AUTH_REQUIRED), (403, FetchState.AUTH_REQUIRED)]
)
async def test_discovery_auth_and_permission_require_reconnect(status, state):
    provider, _ = provider_for(
        {"message": "synthetic-session"}, status=status, path="/api/organizations"
    )
    with pytest.raises(TransportError) as raised:
        await provider.discover_organizations(CREDENTIAL)
    assert raised.value.fetch_state == state
    assert "synthetic-session" not in str(raised.value)


@pytest.mark.parametrize(
    "status,state,code",
    [
        (401, FetchState.AUTH_REQUIRED, "auth_required"),
        (403, FetchState.PERMISSION_DENIED, "permission_denied"),
        (429, FetchState.RATE_LIMITED, "rate_limited"),
        (503, FetchState.PROVIDER_ERROR, "provider_error"),
    ],
)
async def test_selected_org_errors_always_rows_no_switch(status, state, code):
    provider, requests = provider_for(
        {"message": "synthetic-session"}, status=status, headers={"Retry-After": "600"}
    )
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert_rows(snapshot)
    assert len(requests) == 1
    assert snapshot.fetch_state == state
    assert snapshot.diagnostic.code == code
    assert snapshot.fetched_at is None
    assert snapshot.organization_id == ACCOUNT.organization_id
    if status == 429:
        assert snapshot.retry_at is not None


async def test_missing_selection_never_discovers_or_selects_single_candidate(payload):
    provider, requests = provider_for(payload)
    snapshot = await provider.fetch(replace(ACCOUNT, organization_id=None), CREDENTIAL, NOW)
    assert_rows(snapshot)
    assert requests == []
    assert snapshot.fetch_state == FetchState.UNCONFIGURED
    assert snapshot.diagnostic.code == "organization_selection_required"


async def test_removed_selected_organization_requires_explicit_reselection():
    provider, requests = provider_for({}, status=404)
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert_rows(snapshot)
    assert len(requests) == 1
    assert snapshot.fetch_state == FetchState.PERMISSION_DENIED
    assert snapshot.diagnostic.code == "organization_selection_required"


@pytest.mark.parametrize(
    "secret",
    [
        "has\rreturn",
        "has\nnewline",
        "cookie;other=value",
        "has space",
        "has\x00null",
        '"quoted"',
        "a,b",
        "a\\b",
        "非ascii",
    ],
)
async def test_invalid_cookie_rejected_without_request(payload, secret):
    provider, requests = provider_for(payload)
    credential = replace(CREDENTIAL, secret=secret)
    snapshot = await provider.fetch(ACCOUNT, credential, NOW)
    assert_rows(snapshot)
    assert requests == []
    assert snapshot.fetch_state == FetchState.AUTH_REQUIRED
    with pytest.raises(TransportError):
        await provider.discover_organizations(credential)
    assert requests == []


async def test_credentials_missing_wrong_provider_expired_and_org_bound(payload):
    provider, requests = provider_for(payload)
    wrong = ResolvedCredential(
        ProviderId.CLAUDE_SUBSCRIPTION,
        CredentialKind.MANUAL_BEARER,
        "synthetic-session",
        "generation-1",
    )
    cases = [
        None,
        wrong,
        replace(CREDENTIAL, expires_at=NOW),
        replace(CREDENTIAL, organization_id="org-other"),
    ]
    for credential in cases:
        snapshot = await provider.fetch(ACCOUNT, credential, NOW)
        assert_rows(snapshot)
        assert snapshot.fetch_state == FetchState.AUTH_REQUIRED
    assert requests == []


async def test_network_error_is_safe_and_keeps_rows():
    def handler(request):
        raise httpx.ConnectError("synthetic-session must not escape", request=request)

    provider = ConsoleProvider(Transport(http_transport=httpx.MockTransport(handler)))
    snapshot = await provider.fetch(ACCOUNT, CREDENTIAL, NOW)
    assert_rows(snapshot)
    assert snapshot.fetch_state == FetchState.NETWORK_ERROR
    assert snapshot.diagnostic.code == "network_error"


def test_organization_choice_rejects_path_injection():
    with pytest.raises(DomainError):
        OrganizationChoice("../other", "Unsafe")
