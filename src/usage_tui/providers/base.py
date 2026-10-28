"""Provider contract and explicit, side-effect-free adapter construction."""

from collections.abc import Mapping
from datetime import datetime
from typing import Protocol, runtime_checkable

from usage_tui.credentials import CredentialResolver
from usage_tui.domain import Account, ProviderId, ResolvedCredential, Snapshot
from usage_tui.providers.claude import ClaudeProvider
from usage_tui.providers.codex import CodexProvider
from usage_tui.providers.console import ConsoleProvider
from usage_tui.providers.grok import GrokProvider
from usage_tui.transport import Transport


@runtime_checkable
class Provider(Protocol):
    """Normalize every required row, including explicit unavailable capabilities."""

    @property
    def requires_credential(self) -> bool: ...

    @property
    def metric_ids(self) -> tuple[str, ...]: ...

    async def fetch(
        self, account: Account, credential: ResolvedCredential | None, now: datetime
    ) -> Snapshot: ...


def build_providers(
    transport: Transport, resolver: CredentialResolver
) -> Mapping[ProviderId, Provider]:
    """Wire adapters only; the scheduler resolves credentials per live fetch.

    The resolver is intentionally not accessed or retained here; the scheduler
    captures each account's current credential immediately before fetching.
    """
    return {
        ProviderId.CLAUDE_SUBSCRIPTION: ClaudeProvider(transport),
        ProviderId.CLAUDE_PLATFORM: ConsoleProvider(transport),
        ProviderId.CODEX_SUBSCRIPTION: CodexProvider(transport),
        ProviderId.GROK_SUBSCRIPTION: GrokProvider(transport),
    }
