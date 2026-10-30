"""Actual UsageApp Pilot interactions, using only offline/injected services."""

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from textual.widgets import Input, OptionList, Select

from cli_usage_api.accounts import AccountForm, AccountManagerScreen
from cli_usage_api.api import AppHub
from cli_usage_api.app import InformationScreen, UsageApp
from cli_usage_api.domain import (
    REQUIRED_METRIC_IDS,
    Account,
    CredentialKind,
    FetchState,
    MetricId,
    ProviderId,
    ResolvedCredential,
    Snapshot,
)
from cli_usage_api.providers.claude import ClaudeProvider
from cli_usage_api.providers.codex import CodexProvider
from cli_usage_api.providers.grok import GrokProvider
from cli_usage_api.reorder import ReorderableOptionList
from cli_usage_api.transport import Transport


@pytest.mark.parametrize("size", [(80, 24), (40, 12)])
@pytest.mark.parametrize("scenario", ["healthy", "errors"])
async def test_actual_demo_surface_and_keyboard(size, scenario, monkeypatch):
    app = UsageApp(mode="demo", scenario=scenario)
    stop = AsyncMock(wraps=app.scheduler.stop)
    monkeypatch.setattr(app.scheduler, "stop", stop)
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        assert "DEMO" in str(app.banner.content)
        assert app.metric_option_count() == sum(
            len(set(REQUIRED_METRIC_IDS[a.provider]) | {m.id for m in app.snapshots[a.id].metrics})
            for a in app.accounts
        )
        assert app.listing.option_count == app.metric_option_count() + len(app.accounts)
        assert app.listing.size.height > 0
        assert app.listing.virtual_size.height > app.listing.size.height
        if size == (40, 12):
            assert "窗口较小" in str(app.hint.content)
        await pilot.press("down")
        selected = app.highlighted_row()
        await pilot.press("enter")
        assert isinstance(app.screen, InformationScreen)
        assert "provenance" in app.screen.content
        await pilot.press("escape", "?")
        assert isinstance(app.screen, InformationScreen)
        assert app.highlighted_row() == selected
        assert "Ctrl-C" in app.screen.content
        assert "Codex weekly (7d)" in app.screen.content
        assert "Codex 5h" in app.screen.content
        assert "契约仍阻塞" not in app.screen.content
        await pilot.press("escape", "a")
        assert isinstance(app.screen, AccountManagerScreen)
        assert app.highlighted_row() == selected
        assert app.screen.readonly
        await pilot.press("escape", "r")
        assert len(app.screen_stack) == 1
        assert "refresh pending" in str(app.status_line.content)
        assert app.highlighted_row() == selected
        await pilot.press("escape")
        assert app.highlighted_row() is None
        await pilot.press("tab", "shift+tab")
        await pilot.press("q")
    stop.assert_awaited_once_with()
    with pytest.raises(RuntimeError, match="stopped"):
        await app.scheduler.start()


async def test_demo_does_not_touch_any_live_dependencies(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("live dependency touched by demo")

    monkeypatch.setattr("cli_usage_api.credentials.CredentialResolver", forbidden)
    factory = Mock(side_effect=forbidden)
    stores = Mock()
    stores.load.side_effect = forbidden
    stores.get.side_effect = forbidden
    app = UsageApp(
        mode="demo", scheduler_factory=factory, account_store=stores, credential_store=stores
    )
    async with app.run_test() as pilot:
        await pilot.press("a", "r", "escape", "r", "ctrl+c")
    factory.assert_not_called()
    stores.load.assert_not_called()
    stores.get.assert_not_called()


async def test_live_empty_guidance_and_priority_ctrl_c():
    app = UsageApp(mode="live")
    async with app.run_test(size=(40, 12)) as pilot:
        assert "No accounts" in str(app.status_line.content)
        await pilot.press("a")
        assert isinstance(app.screen, InformationScreen)
        assert "存储" in app.screen.content
        await pilot.press("ctrl+c")
    assert not app.is_running


class InjectedScheduler:
    def __init__(self):
        self.started = False
        self.stopped = False
        self.refreshes = []
        self.updates = []
        self.invalidations = []

    async def start(self):
        self.started = True

    async def refresh(self, account_id=None):
        self.refreshes.append(account_id)

    async def update_accounts(self, accounts, **kwargs):
        self.updates.append(accounts)
        self.invalidations.append(kwargs.get("invalidate"))

    async def stop(self):
        self.stopped = True


class InjectedFactory:
    def __init__(self):
        self.scheduler = InjectedScheduler()
        self.closed = False
        self.resolver = Mock()
        self.console_discovery = Mock()

    def __call__(self, accounts, *, publish):
        self.accounts = accounts
        self.publish = publish
        return self.scheduler

    async def aclose(self):
        assert self.scheduler.stopped
        self.closed = True


async def test_live_generations_refresh_manager_discovery_and_shutdown(monkeypatch):
    account = Account(
        id="11111111-1111-4111-8111-111111111111",
        provider=ProviderId.CLAUDE_SUBSCRIPTION,
        label="Synthetic",
    )
    factory = InjectedFactory()
    close = AsyncMock(wraps=factory.aclose)
    monkeypatch.setattr(factory, "aclose", close)
    store = Mock()
    store.load.return_value = (account,)
    app = UsageApp(
        mode="live",
        accounts=(account,),
        scheduler_factory=factory,
        account_store=store,
        credential_store=Mock(),
    )
    async with app.run_test() as pilot:
        assert factory.scheduler.started
        assert factory.accounts == (account,)
        await pilot.press("a")
        assert isinstance(app.screen, AccountManagerScreen)
        assert app.screen.console_discovery is factory.console_discovery
        updated = (replace(account, label="New label"),)
        await app.accounts_changed(updated)
        assert factory.scheduler.updates == [updated]
        await app.reconnect(account.id)
        assert factory.scheduler.refreshes == [account.id]
        await pilot.press("escape", "r")
        assert factory.scheduler.refreshes[-1] is None
        await pilot.press("ctrl+c")
    assert factory.closed
    assert factory.scheduler.stopped
    close.assert_awaited_once_with()
    await app.on_unmount()
    close.assert_awaited_once_with()


async def test_cancelled_scheduler_stop_still_closes_factory_once(monkeypatch):
    factory = InjectedFactory()

    async def cancelled_stop():
        factory.scheduler.stopped = True
        raise asyncio.CancelledError

    monkeypatch.setattr(factory.scheduler, "stop", cancelled_stop)
    close = AsyncMock(wraps=factory.aclose)
    monkeypatch.setattr(factory, "aclose", close)
    app = UsageApp(mode="live", scheduler_factory=factory)
    app.scheduler = factory.scheduler
    with pytest.raises(asyncio.CancelledError):
        await app.on_unmount()
    assert factory.closed
    close.assert_awaited_once_with()
    await app.on_unmount()
    close.assert_awaited_once_with()


async def test_account_selection_filters_rows():
    app = UsageApp(mode="demo")
    async with app.run_test() as pilot:
        selector = app.query_one("#account-selector", Select)
        account = next(a for a in app.accounts if a.provider == ProviderId.CODEX_SUBSCRIPTION)
        selector.value = account.id
        await pilot.pause()
        assert app.query_one("#metrics", OptionList).option_count == 4
        assert app.metric_option_count() == 3
        assert [metric_id for _, metric_id in app.rows] == [
            "codex.subscription.weekly",
            "codex.subscription.five_hour",
            "codex.subscription.credits",
        ]
        assert all(a.id == account.id for a, _ in app.rows)
        await pilot.press("q")


async def test_real_grok_extra_product_mount_details_filter_and_refresh():
    grok = Account(
        id="11111111-1111-4111-8111-111111111111",
        provider=ProviderId.GROK_SUBSCRIPTION,
        label="Synthetic Grok",
        credential_kind=CredentialKind.MANUAL_BEARER,
        credential_ref="memory:synthetic",
    )
    other_account = Account(
        id="22222222-2222-4222-8222-222222222222",
        provider=ProviderId.CODEX_SUBSCRIPTION,
        label="Detached Codex",
    )
    credential = ResolvedCredential(
        grok.provider, CredentialKind.MANUAL_BEARER, "synthetic-secret", "generation-1"
    )
    bodies = [
        (
            b'{"config":{"isUnifiedBillingUser":true,"creditUsagePercent":50,'
            b'"currentPeriod":{"end":"2099-11-02T00:00:00Z"},"productUsage":['
            b'{"product":"GrokBuild","usagePercent":20},'
            b'{"product":"GrokChat","usagePercent":20},'
            b'{"product":"Other","usagePercent":10}]}}'
        ),
        (
            b'{"config":{"isUnifiedBillingUser":true,"creditUsagePercent":40,'
            b'"currentPeriod":{"end":"2099-11-02T00:00:00Z"},"productUsage":['
            b'{"product":"GrokBuild","usagePercent":20},'
            b'{"product":"GrokChat","usagePercent":20}]}}'
        ),
    ]
    requests = []

    def respond(request):
        requests.append(request)
        assert str(request.url) == "https://cli-chat-proxy.grok.com/v1/billing?format=credits"
        return httpx.Response(200, content=bodies.pop(0))

    provider = GrokProvider(Transport(http_transport=httpx.MockTransport(respond)))

    class ProviderScheduler(InjectedScheduler):
        async def start(self):
            await super().start()
            await self.refresh()

        async def refresh(self, account_id=None):
            await super().refresh(account_id)
            factory.publish(await provider.fetch(grok, credential, datetime.now(UTC)))

    factory = InjectedFactory()
    factory.scheduler = ProviderScheduler()
    app = UsageApp(mode="live", accounts=(grok, other_account), scheduler_factory=factory)
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.pause()
        required = list(REQUIRED_METRIC_IDS[grok.provider])
        assert [metric_id for _, metric_id in app.rows[:3]] == required
        extra = app.snapshots[grok.id].metrics[-1]
        assert extra.label == "Other" and extra.id.startswith("grok.product.other.")
        assert app.rows[3] == (grok, extra.id)
        assert app.metric_option_count() == 5
        prompt = str(app.listing.get_option_at_index(app.option_index(app.rows[3])).prompt)
        # Extra products render like known products: tree, bar and used share only.
        assert "└ Other" in prompt and "已用 10%" in prompt and "█" in prompt
        assert "剩余" not in prompt and "consumption share" not in prompt
        assert extra.quota is None and extra.share_percent == 10
        app.listing.highlighted = app.option_index(app.rows[3])
        await pilot.press("enter")
        assert isinstance(app.screen, InformationScreen)
        assert "Other" in app.screen.content and "10%" in app.screen.content
        assert "private_http" in app.screen.content
        assert "grok.cli.billing.credits" in app.screen.content
        assert "consumption share: 10%" in app.screen.content
        assert "剩余 90%" not in app.screen.content
        assert f"属于共享池 {app.snapshots[grok.id].metrics[0].id}" in app.screen.content
        await pilot.press("escape")
        selector = app.query_one("#account-selector", Select)
        selector.value = other_account.id
        await pilot.pause()
        assert app.rows == [(other_account, REQUIRED_METRIC_IDS[other_account.provider][0])]
        selector.value = grok.id
        await pilot.pause()
        assert [metric_id for _, metric_id in app.rows] == [*required, extra.id]
        selector.value = "all"
        await pilot.pause()
        # Removing a row before the selected account must preserve its identity.
        app.listing.highlighted = app.option_index(app.rows[4])
        app.listing.focus()
        await pilot.press("r")
        await pilot.pause()
        assert len(requests) == 2 and not bodies
        assert [metric_id for _, metric_id in app.rows[:3]] == required
        assert app.metric_option_count() == 4
        assert extra.id not in [metric_id for _, metric_id in app.rows]
        assert app.highlighted_row()[0] == other_account
        await pilot.press("q")
    assert factory.closed and factory.scheduler.stopped


def test_configured_live_requires_injection():
    account = Account(
        id="11111111-1111-4111-8111-111111111111",
        provider=ProviderId.CODEX_SUBSCRIPTION,
        label="Detached Codex",
    )
    with pytest.raises(ValueError, match="factory"):
        UsageApp(mode="live", accounts=(account,))


async def test_account_form_accepts_q_in_label_reference_and_masked_secret(monkeypatch):
    factory = InjectedFactory()
    store = Mock()
    store.load.return_value = ()
    app = UsageApp(
        mode="live",
        scheduler_factory=factory,
        account_store=store,
        credential_store=Mock(),
    )
    quit_action = AsyncMock(wraps=app.action_quit)
    monkeypatch.setattr(app, "action_quit", quit_action)
    async with app.run_test() as pilot:
        await pilot.press("a", "a")
        assert isinstance(app.screen, AccountForm)
        form = app.screen
        label = form.query_one("#label", Input)
        await pilot.press("q")
        assert label.value == "q"
        for kind, selector in (
            (CredentialKind.CLAUDE_CODE_FILE, "#reference"),
            (CredentialKind.MANUAL_BEARER, "#secret"),
        ):
            form.query_one("#kind", Select).value = kind
            await pilot.pause()
            field = form.query_one(selector, Input)
            field.value = ""
            field.focus()
            await pilot.press("q")
            assert field.value == "q"
            assert app.screen is form
            assert app.is_running
        assert form.query_one("#secret", Input).password
        quit_action.assert_not_awaited()
        await pilot.press("ctrl+c")
        quit_action.assert_awaited_once_with()


@pytest.mark.parametrize("open_manager", [False, True])
async def test_nonpriority_q_quits_dashboard_and_account_manager(open_manager, monkeypatch):
    app = UsageApp(mode="demo")
    quit_action = AsyncMock(wraps=app.action_quit)
    monkeypatch.setattr(app, "action_quit", quit_action)
    async with app.run_test() as pilot:
        if open_manager:
            await pilot.press("a")
            assert isinstance(app.screen, AccountManagerScreen)
        await pilot.press("q")
        quit_action.assert_awaited_once_with()


def synthetic(number, provider=ProviderId.CLAUDE_SUBSCRIPTION, **fields):
    return Account(
        id=f"{number}{number}{number}{number}{number}{number}{number}{number}-1111-4111-8111-111111111111",
        provider=provider,
        label=f"Synthetic {number}",
        **fields,
    )


def observed(account):
    now = datetime.now(UTC)
    return Snapshot(account.id, (), (), FetchState.OK, attempted_at=now, fetched_at=now)


async def test_accounts_changed_keeps_snapshots_by_credential_identity():
    first, second, third, fourth = (
        synthetic(1),
        synthetic(2, credential_kind=CredentialKind.MANUAL_BEARER, credential_ref="session:a"),
        synthetic(3),
        synthetic(4),
    )
    factory = InjectedFactory()
    app = UsageApp(mode="live", accounts=(first, second, third, fourth), scheduler_factory=factory)
    hub = AppHub.attach(app)
    async with app.run_test(size=(120, 45)) as pilot:
        for account in app.accounts:
            factory.publish(observed(account))
        selector = app.query_one("#account-selector", Select)
        updated = (
            replace(fourth, label="Renamed"),  # Same identity: kept, and reordered first.
            replace(second, credential_ref="session:b"),  # New credential: dropped.
            first,  # Explicitly invalidated (a source submission): dropped.
            replace(third, enabled=False),  # Toggle keeps the observation.
        )
        await app.accounts_changed(updated, invalidate=frozenset({first.id}))
        await pilot.pause()
        assert set(app.snapshots) == {fourth.id, third.id}
        assert factory.scheduler.updates[-1] == updated
        assert factory.scheduler.invalidations[-1] == frozenset({first.id})
        assert hub.accounts == updated
        assert hub.snapshots == app.snapshots
        assert [value for _, value in selector._options[1:]] == [a.id for a in updated]
        assert [account.id for account, _ in app._groups()] == [a.id for a in updated]
        assert "Renamed" in str(app.listing.get_option_at_index(0).prompt)
        await app.accounts_changed(updated)
        assert app.snapshots == {} and hub.snapshots == {}
        assert factory.scheduler.invalidations[-1] is None
        await pilot.press("q")


async def test_open_manager_reloads_from_tuple_and_cancels_a_drag(monkeypatch):
    first, second = synthetic(1), synthetic(2)
    factory = InjectedFactory()
    store = Mock()
    store.load.return_value = (first, second)
    app = UsageApp(
        mode="live",
        accounts=(first, second),
        scheduler_factory=factory,
        account_store=store,
        credential_store=Mock(),
    )
    async with app.run_test() as pilot:
        await pilot.press("a")
        manager = app.screen
        assert isinstance(manager, AccountManagerScreen)
        listing = manager.query_one("#accounts", ReorderableOptionList)
        await pilot.mouse_down(listing, offset=(3, listing.gutter.top))
        assert listing.dragging
        store.load.side_effect = AssertionError("A host reload must not read the store")
        added = synthetic(3)
        # A web write publishes through the app while the manager is open.
        async with app.account_lock:
            await app.accounts_changed((second, first, added), invalidate=frozenset({added.id}))
        await pilot.pause()
        assert manager.accounts == (second, first, added)
        assert listing.option_count == 3
        assert not listing.dragging
        await pilot.hover(listing, offset=(3, listing.gutter.top + 2))
        await pilot.mouse_up(listing, offset=(3, listing.gutter.top + 2))
        await pilot.pause()
        store.mutate.assert_not_called()
        assert manager.accounts == (second, first, added)
        await pilot.press("ctrl+c")


async def test_manager_writes_notify_app_once_with_invalidate_sets(tmp_path):
    from cli_usage_api.storage import AccountStore, CredentialStore

    first, second = synthetic(1), synthetic(2)
    store = AccountStore(tmp_path / "private" / "accounts.json")
    store.save((first, second))
    factory = InjectedFactory()
    app = UsageApp(
        mode="live",
        accounts=(first, second),
        scheduler_factory=factory,
        account_store=store,
        credential_store=CredentialStore(),
    )
    async with app.run_test() as pilot:
        for account in app.accounts:
            factory.publish(observed(account))
        await pilot.press("a")
        manager = app.screen
        reloads = []
        original = manager.reload

        async def counted(accounts=None):
            reloads.append(accounts)
            await original(accounts)

        manager.reload = counted
        await pilot.press("shift+down")
        await pilot.pause()
        assert app.accounts == (second, first) == store.load()
        assert factory.scheduler.invalidations == [frozenset()]
        # The reporting manager renders once; the app does not reload it again.
        assert reloads == [(second, first)]
        assert set(app.snapshots) == {first.id, second.id}
        await pilot.press("escape")
        await pilot.pause()
        assert [account.id for account, _ in app._groups()] == [second.id, first.id]
        await pilot.press("q")


async def test_real_codex_credits_shown_and_claude_extra_usage_parse_only():
    claude = Account(
        id="33333333-3333-4333-8333-333333333333",
        provider=ProviderId.CLAUDE_SUBSCRIPTION,
        label="Synthetic Claude",
        credential_kind=CredentialKind.MANUAL_BEARER,
        credential_ref="memory:synthetic",
    )
    codex = Account(
        id="44444444-4444-4444-8444-444444444444",
        provider=ProviderId.CODEX_SUBSCRIPTION,
        label="Synthetic Codex",
        credential_kind=CredentialKind.CODEX_AUTH_FILE,
        credential_ref="file:/synthetic/auth.json",
    )
    claude_body = json.loads((Path(__file__).parent / "fixtures" / "claude_usage.json").read_text())
    claude_body["extra_usage"] = {
        "is_enabled": True,
        "monthly_limit": 5000,
        "used_credits": 1234,
        "utilization": 24.68,
        "currency": "USD",
    }
    window = {"limit_window_seconds": 604800, "used_percent": 12.5, "reset_at": 4102444800}
    codex_bodies = [
        json.dumps({"rate_limit": {"primary_window": window}, "credits": credits}).encode()
        for credits in (
            {"has_credits": True, "unlimited": False, "balance": "1234.50"},
            {"has_credits": False, "unlimited": True},
        )
    ]

    def respond(request):
        if request.url.host == "api.anthropic.com":
            return httpx.Response(200, content=json.dumps(claude_body).encode())
        assert str(request.url) == "https://chatgpt.com/backend-api/wham/usage"
        return httpx.Response(200, content=codex_bodies.pop(0))

    transport = Transport(http_transport=httpx.MockTransport(respond))
    claude_provider, codex_provider = ClaudeProvider(transport), CodexProvider(transport)
    claude_credential = ResolvedCredential(
        claude.provider, CredentialKind.MANUAL_BEARER, "synthetic-secret", "generation-1"
    )
    codex_credential = ResolvedCredential(
        codex.provider,
        CredentialKind.CODEX_AUTH_FILE,
        "synthetic-access-token",
        "generation-1",
        codex_account_id="synthetic-selected-account",
    )

    class ProviderScheduler(InjectedScheduler):
        async def start(self):
            await super().start()
            await self.refresh()

        async def refresh(self, account_id=None):
            await super().refresh(account_id)
            now = datetime.now(UTC)
            factory.publish(await claude_provider.fetch(claude, claude_credential, now))
            factory.publish(await codex_provider.fetch(codex, codex_credential, now))

    factory = InjectedFactory()
    factory.scheduler = ProviderScheduler()
    app = UsageApp(mode="live", accounts=(claude, codex), scheduler_factory=factory)
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.pause()
        # The provider still parses and publishes the Claude extra-usage metric...
        extra = next(
            m for m in app.snapshots[claude.id].metrics if m.id == MetricId.CLAUDE_EXTRA_USAGE
        )
        assert extra.spent is not None and extra.spend_limit is not None
        # ...but the dashboard shows exactly the required Claude rows and nothing of it.
        assert [m for a, m in app.rows if a == claude] == list(REQUIRED_METRIC_IDS[claude.provider])
        screen = "\n".join(str(o.prompt) for o in app.listing._options)
        assert "额外用量" not in screen and "12.34" not in screen and "50.00" not in screen
        assert app.rows[-1] == (codex, MetricId.CODEX_CREDITS)
        credits_prompt = str(app.listing.get_option_at_index(app.option_index(app.rows[-1])).prompt)
        assert "Codex credits" in credits_prompt and "1234.50 credits" in credits_prompt
        app.listing.highlighted = app.option_index(app.rows[-1])
        await pilot.press("enter")
        assert isinstance(app.screen, InformationScreen)
        assert "1234.50 credits" in app.screen.content
        assert "codex.wham.usage.v1" in app.screen.content
        await pilot.press("escape")
        app.listing.focus()
        await pilot.press("r")
        await pilot.pause()
        assert not codex_bodies
        unlimited = str(app.listing.get_option_at_index(app.option_index(app.rows[-1])).prompt)
        assert "不限量 / Unlimited" in unlimited and "未知" not in unlimited
        await pilot.press("q")
    assert factory.closed and factory.scheduler.stopped
