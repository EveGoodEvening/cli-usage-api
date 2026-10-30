"""Explicit registry wiring and credential-required Codex capability."""

from dataclasses import replace
from datetime import UTC, datetime

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
from cli_usage_api.providers import (
    ClaudeProvider,
    CodexProvider,
    ConsoleProvider,
    GrokProvider,
    OpenAIPlatformProvider,
    Provider,
    build_providers,
)
from cli_usage_api.transport import Transport

NOW = datetime(2026, 10, 28, 12, tzinfo=UTC)
ACCOUNT = Account(
    "00000000-0000-0000-0000-000000000007",
    ProviderId.CODEX_SUBSCRIPTION,
    "Synthetic Codex",
    credential_ref=None,
)
ADAPTERS = {
    ProviderId.CLAUDE_SUBSCRIPTION: ClaudeProvider,
    ProviderId.CLAUDE_PLATFORM: ConsoleProvider,
    ProviderId.CODEX_SUBSCRIPTION: CodexProvider,
    ProviderId.GROK_SUBSCRIPTION: GrokProvider,
    ProviderId.OPENAI_PLATFORM: OpenAIPlatformProvider,
}


class ForbiddenAccess:
    def __getattribute__(self, name):
        raise AssertionError("Registry construction must not access dependencies or secrets.")


def test_registry_construction_accesses_no_dependencies():
    providers = build_providers(ForbiddenAccess(), ForbiddenAccess())
    assert set(providers) == set(ProviderId) == set(REQUIRED_METRIC_IDS)
    for provider_id, adapter in ADAPTERS.items():
        provider = providers[provider_id]
        assert type(provider) is adapter
        assert isinstance(provider, Provider)
        assert provider.metric_ids == REQUIRED_METRIC_IDS[provider_id]
        assert provider.requires_credential is True
    assert providers[ACCOUNT.provider].metric_ids == (MetricId.CODEX_WEEKLY,)


@pytest.mark.parametrize("provider_id", list(ProviderId))
async def test_registered_adapters_keep_required_rows_without_credentials(provider_id):
    providers = build_providers(ForbiddenAccess(), ForbiddenAccess())
    organization = "org-SyntheticOrg0001" if provider_id == ProviderId.OPENAI_PLATFORM else None
    account = replace(ACCOUNT, provider=provider_id, organization_id=organization)
    snapshot = await providers[provider_id].fetch(account, None, NOW)
    assert snapshot.fetch_state == FetchState.AUTH_REQUIRED
    assert tuple(row.id for row in snapshot.metrics) == REQUIRED_METRIC_IDS[provider_id]
    assert all(row.state == MetricState.UNKNOWN for row in snapshot.metrics)
    assert all(row.source.kind == SourceKind.PRIVATE_HTTP for row in snapshot.metrics)
    assert snapshot.fetched_at is None
    assert Snapshot.from_dict(snapshot.to_dict()) == snapshot


async def test_registered_codex_performs_real_credentialed_read_not_blocked_capability():
    requests = []

    def handler(request):
        requests.append(request)
        assert str(request.url) == "https://chatgpt.com/backend-api/wham/usage"
        return httpx.Response(
            200,
            content=b'{"rate_limit":{"primary_window":{"limit_window_seconds":604800,'
            b'"used_percent":12.5,"reset_at":1793232000}}}',
        )

    transport = Transport(http_transport=httpx.MockTransport(handler))
    providers = build_providers(transport, ForbiddenAccess())
    assert requests == []
    account = replace(
        ACCOUNT,
        credential_ref="file:/synthetic/auth.json",
        credential_kind=CredentialKind.CODEX_AUTH_FILE,
    )
    credential = ResolvedCredential(
        account.provider,
        CredentialKind.CODEX_AUTH_FILE,
        "synthetic-secret",
        "generation-1",
        codex_account_id="synthetic-selected-account",
    )
    snapshot = await providers[account.provider].fetch(account, credential, NOW)
    assert len(requests) == 1
    assert snapshot.fetch_state == FetchState.OK
    assert tuple(row.id for row in snapshot.metrics) == (MetricId.CODEX_WEEKLY,)
    assert snapshot.metrics[0].state == MetricState.READY
    assert snapshot.metrics[0].source.contract == "codex.wham.usage.v1"
    assert snapshot.metrics[0].source.version_sensitive is True
    assert "synthetic-secret" not in repr(snapshot.to_dict())
    assert "synthetic-selected-account" not in repr(snapshot.to_dict())
