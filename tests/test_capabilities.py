"""Truthful ordinary-chat blocking and explicit offline provider wiring."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone

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
    Snapshot,
    SourceKind,
)
from usage_tui.providers import (
    ChatGPTProvider,
    ClaudeProvider,
    ConsoleProvider,
    GrokProvider,
    Provider,
    build_providers,
)
from usage_tui.transport import Transport

NOW = datetime(2026, 10, 28, 12, tzinfo=UTC)
ACCOUNT = Account(
    "00000000-0000-0000-0000-000000000007",
    ProviderId.CHATGPT_SUBSCRIPTION,
    "Synthetic ordinary ChatGPT",
    credential_ref=None,
)
ADAPTERS = {
    ProviderId.CLAUDE_SUBSCRIPTION: ClaudeProvider,
    ProviderId.CLAUDE_PLATFORM: ConsoleProvider,
    ProviderId.CHATGPT_SUBSCRIPTION: ChatGPTProvider,
    ProviderId.GROK_SUBSCRIPTION: GrokProvider,
}


class ForbiddenAccess:
    def __getattribute__(self, name):
        raise AssertionError("Blocked capability must not access dependencies or secrets.")


def assert_blocked(snapshot, now=NOW):
    assert snapshot.account_id == ACCOUNT.id
    assert snapshot.fetch_state == FetchState.UPSTREAM_CONTRACT_MISSING
    assert snapshot.attempted_at == now
    assert snapshot.fetched_at is snapshot.retry_at is None
    assert snapshot.grants == ()
    assert snapshot.diagnostic.code == "upstream_contract_missing"
    assert "Ordinary ChatGPT" in snapshot.diagnostic.message
    assert tuple(row.id for row in snapshot.metrics) == REQUIRED_METRIC_IDS[ACCOUNT.provider]
    (row,) = snapshot.metrics
    assert row.id == "chatgpt.subscription.weekly"
    assert row.state == MetricState.BLOCKED
    assert row.source.kind == SourceKind.UNRESOLVED
    assert row.source.contract == "chatgpt.subscription.weekly"
    assert row.quota is row.balance is row.reset_at is row.expires_at is None
    assert row.shared_pool_id is None
    assert "普通 ChatGPT" in row.detail
    assert "stored credentials do not enable retrieval" in row.detail
    assert Snapshot.from_dict(snapshot.to_dict()) == snapshot


@pytest.mark.parametrize("kind", [None, CredentialKind.MANUAL_BEARER, CredentialKind.API_KEY])
async def test_chatgpt_is_blocked_with_or_without_stored_credentials(kind):
    account = ACCOUNT
    credential = None
    if kind is not None:
        account = replace(ACCOUNT, credential_ref="memory:synthetic", credential_kind=kind)
        credential = ResolvedCredential(
            account.provider, kind, "synthetic-secret-do-not-render", "generation-1"
        )
    provider = ChatGPTProvider()
    assert provider.requires_credential is False
    assert provider.metric_ids == REQUIRED_METRIC_IDS[ACCOUNT.provider]
    snapshot = await provider.fetch(account, credential, NOW)
    assert_blocked(snapshot)
    assert "synthetic-secret-do-not-render" not in repr(snapshot.to_dict())
    assert "memory:synthetic" not in repr(snapshot.to_dict())


async def test_chatgpt_does_not_even_inspect_supplied_credential():
    snapshot = await ChatGPTProvider().fetch(ACCOUNT, ForbiddenAccess(), NOW)
    assert_blocked(snapshot)


async def test_chatgpt_attempt_time_is_normalized_and_never_a_success():
    now = NOW.astimezone(timezone(timedelta(hours=8)))
    snapshot = await ChatGPTProvider().fetch(ACCOUNT, None, now)
    assert_blocked(snapshot)
    assert snapshot.attempted_at.tzinfo is UTC


async def test_registry_construction_and_blocked_fetch_access_no_dependencies():
    providers = build_providers(ForbiddenAccess(), ForbiddenAccess())
    assert set(providers) == set(ProviderId) == set(REQUIRED_METRIC_IDS)
    for provider_id, adapter in ADAPTERS.items():
        provider = providers[provider_id]
        assert type(provider) is adapter
        assert isinstance(provider, Provider)
        assert provider.metric_ids == REQUIRED_METRIC_IDS[provider_id]
        assert provider.requires_credential is (provider_id != ACCOUNT.provider)
    snapshot = await providers[ACCOUNT.provider].fetch(ACCOUNT, None, NOW)
    assert_blocked(snapshot)


async def test_blocked_registry_never_requests_wham_codex_or_any_other_endpoint():
    requests = []

    def reject_request(request):
        requests.append(request)
        raise AssertionError("No ordinary-chat quota read contract exists.")

    transport = Transport(http_transport=httpx.MockTransport(reject_request))
    providers = build_providers(transport, ForbiddenAccess())
    assert requests == []
    provider = providers[ACCOUNT.provider]
    for kind in (None, CredentialKind.MANUAL_BEARER, CredentialKind.API_KEY):
        account = ACCOUNT
        if kind is not None:
            account = replace(ACCOUNT, credential_ref="memory:synthetic", credential_kind=kind)
        assert_blocked(await provider.fetch(account, None, NOW))
    assert requests == []


@pytest.mark.parametrize(
    "provider_id",
    [ProviderId.CLAUDE_SUBSCRIPTION, ProviderId.CLAUDE_PLATFORM, ProviderId.GROK_SUBSCRIPTION],
)
async def test_registered_live_adapters_keep_required_rows_without_credentials(provider_id):
    providers = build_providers(ForbiddenAccess(), ForbiddenAccess())
    account = replace(ACCOUNT, provider=provider_id)
    snapshot = await providers[provider_id].fetch(account, None, NOW)
    assert snapshot.fetch_state == FetchState.AUTH_REQUIRED
    assert tuple(row.id for row in snapshot.metrics) == REQUIRED_METRIC_IDS[provider_id]
    assert all(row.state == MetricState.UNKNOWN for row in snapshot.metrics)
    assert all(row.source.kind == SourceKind.PRIVATE_HTTP for row in snapshot.metrics)
    assert snapshot.fetched_at is None
