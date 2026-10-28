"""Actual UsageApp Pilot interactions, using only offline/injected services."""

import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock, Mock

import pytest
from textual.widgets import Input, OptionList, Select

from usage_tui.accounts import AccountForm, AccountManagerScreen
from usage_tui.app import InformationScreen, UsageApp
from usage_tui.domain import Account, CredentialKind, ProviderId


@pytest.mark.parametrize("size", [(80, 24), (40, 12)])
@pytest.mark.parametrize("scenario", ["healthy", "errors"])
async def test_actual_demo_surface_and_keyboard(size, scenario, monkeypatch):
    app = UsageApp(mode="demo", scenario=scenario)
    stop = AsyncMock(wraps=app.scheduler.stop)
    monkeypatch.setattr(app.scheduler, "stop", stop)
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        assert "DEMO" in str(app.banner.content)
        assert app.listing.option_count == sum(
            3 if a.provider != ProviderId.CHATGPT_SUBSCRIPTION else 1 for a in app.accounts
        )
        assert app.listing.size.height > 0
        assert app.listing.virtual_size.height > app.listing.size.height
        if size == (40, 12):
            assert "窗口较小" in str(app.hint.content)
        await pilot.press("down", "enter")
        assert isinstance(app.screen, InformationScreen)
        assert "provenance" in app.screen.content
        await pilot.press("escape", "?")
        assert isinstance(app.screen, InformationScreen)
        assert "Ctrl-C" in app.screen.content
        await pilot.press("escape", "a")
        assert isinstance(app.screen, AccountManagerScreen)
        assert app.screen.readonly
        await pilot.press("escape", "r")
        assert len(app.screen_stack) == 1
        assert "refresh pending" in str(app.status_line.content)
        await pilot.press("tab", "shift+tab")
        await pilot.press("q")
    stop.assert_awaited_once_with()
    with pytest.raises(RuntimeError, match="stopped"):
        await app.scheduler.start()


async def test_demo_does_not_touch_any_live_dependencies(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("live dependency touched by demo")

    monkeypatch.setattr("usage_tui.credentials.CredentialResolver", forbidden)
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

    async def start(self):
        self.started = True

    async def refresh(self, account_id=None):
        self.refreshes.append(account_id)

    async def update_accounts(self, accounts):
        self.updates.append(accounts)

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
        account = next(a for a in app.accounts if a.provider == ProviderId.CHATGPT_SUBSCRIPTION)
        selector.value = account.id
        await pilot.pause()
        assert app.query_one("#metrics", OptionList).option_count == 1
        assert all(a.id == account.id for a, _ in app.rows)
        await pilot.press("q")


def test_configured_live_requires_injection():
    account = Account(
        id="11111111-1111-4111-8111-111111111111",
        provider=ProviderId.CHATGPT_SUBSCRIPTION,
        label="Blocked",
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
