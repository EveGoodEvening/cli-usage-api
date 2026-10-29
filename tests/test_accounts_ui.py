"""Pilot drives production screens with isolated stores, never live services."""

import asyncio
import json
import os
import stat
from dataclasses import replace
from uuid import uuid4

import pytest
from textual import events
from textual.app import App
from textual.widgets import Input, Select, Static

from cli_usage_api.accounts import AccountForm, AccountManagerScreen, ConfirmDialog
from cli_usage_api.credentials import CredentialResolver
from cli_usage_api.domain import Account, CredentialKind, ProviderId
from cli_usage_api.providers.console import OrganizationChoice
from cli_usage_api.reorder import ReorderableOptionList
from cli_usage_api.storage import AccountStore, CredentialError, CredentialStore


class Host(App):
    def __init__(self, manager):
        super().__init__()
        self.manager = manager

    def on_mount(self):
        self.push_screen(self.manager)


@pytest.fixture
def manager(tmp_path):
    store = AccountStore(tmp_path / "private" / "accounts.json")
    credentials = CredentialStore()
    return AccountManagerScreen(store, credentials, CredentialResolver(credentials))


async def open_form(app, pilot):
    await pilot.press("a")
    await pilot.pause()
    assert isinstance(app.screen, AccountForm)
    app.screen.query_one("#label", Input).value = "Synthetic account"
    await pilot.pause()
    return app.screen


async def set_source(form, pilot, provider, kind):
    form.query_one("#provider", Select).value = provider
    await pilot.pause()
    form.query_one("#kind", Select).value = kind
    await pilot.pause()


@pytest.mark.parametrize("size", [(80, 24), (40, 12)])
async def test_cancel_clears_masked_input_and_never_writes(manager, size):
    async with Host(manager).run_test(size=size) as pilot:
        form = await open_form(pilot.app, pilot)
        await set_source(form, pilot, ProviderId.CLAUDE_SUBSCRIPTION, CredentialKind.MANUAL_BEARER)
        field = form.query_one("#secret", Input)
        assert field.password and field.value == ""
        field.focus()
        await pilot.press("a", "r", "q")
        assert field.value == "arq"  # Account/dashboard actions cannot steal secret keystrokes.
        await pilot.press("escape")
        await pilot.pause()
        assert field.value == ""
        assert pilot.app.screen is manager
        assert manager.account_store.load() == ()
        assert manager.credential_store._session == {}


async def test_add_session_edit_label_toggle_remove_confirm(manager):
    changes = []
    manager.on_changed = changes.append
    async with Host(manager).run_test() as pilot:
        form = await open_form(pilot.app, pilot)
        await set_source(form, pilot, ProviderId.CLAUDE_SUBSCRIPTION, CredentialKind.MANUAL_BEARER)
        secret_field = form.query_one("#secret", Input)
        secret_field.value = "synthetic-first"
        await form.save()
        await pilot.pause()
        assert secret_field.value == ""
        saved = manager.accounts[0]
        assert saved.credential_ref.startswith("session:")
        assert manager.credential_store.get(saved.credential_ref) == "synthetic-first"
        await pilot.press("e")
        await pilot.pause()
        form = pilot.app.screen
        assert form.query_one("#secret", Input).value == ""
        assert form.query_one("#kind", Select).value == CredentialKind.MANUAL_BEARER
        form.query_one("#label", Input).value = "Renamed"
        await form.save()
        await pilot.pause()
        assert manager.accounts[0].label == "Renamed"
        await pilot.press("space")
        await pilot.pause()
        assert not manager.accounts[0].enabled
        await pilot.press("d", "escape")
        await pilot.pause()
        assert len(manager.accounts) == 1
        await pilot.press("d")
        await pilot.pause()
        assert isinstance(pilot.app.screen, ConfirmDialog)
        await pilot.click("#confirm")
        await pilot.pause()
        assert manager.accounts == ()
        assert not manager.credential_store._session
        assert len(changes) == 4


async def test_replace_secret_requires_confirmation_and_old_value_never_prefilled(manager):
    async with Host(manager).run_test() as pilot:
        form = await open_form(pilot.app, pilot)
        await set_source(form, pilot, ProviderId.GROK_SUBSCRIPTION, CredentialKind.MANUAL_BEARER)
        form.query_one("#secret", Input).value = "synthetic-old"
        await form.save()
        await pilot.pause()
        old_ref = manager.accounts[0].credential_ref
        await pilot.press("e")
        await pilot.pause()
        form = pilot.app.screen
        field = form.query_one("#secret", Input)
        assert field.value == "" and field.password
        field.value = "synthetic-new"
        await form.save()
        await pilot.pause()
        assert isinstance(pilot.app.screen, ConfirmDialog)
        assert manager.credential_store.get(old_ref) == "synthetic-old"
        await pilot.click("#confirm")
        await pilot.pause()
        assert field.value == ""
        assert manager.credential_store.get(manager.accounts[0].credential_ref) == "synthetic-new"
        with pytest.raises(CredentialError):
            manager.credential_store.get(old_ref)
        await pilot.press("k")
        await pilot.pause()
        await pilot.click("#confirm")
        await pilot.pause()
        assert manager.accounts[0].credential_ref is None
        assert not manager.credential_store._session


async def test_console_discovery_explicit_selection_and_temporary_cleanup(manager):
    class Discovery:
        calls = 0

        async def discover_organizations(self, credential):
            self.calls += 1
            assert credential.secret == "synthetic-console"
            return (OrganizationChoice("org-one", "First"), OrganizationChoice("org-two", "Second"))

    discovery = Discovery()
    manager = AccountManagerScreen(
        manager.account_store,
        manager.credential_store,
        manager.resolver,
        console_discovery=discovery.discover_organizations,
    )
    async with Host(manager).run_test() as pilot:
        form = await open_form(pilot.app, pilot)
        await set_source(form, pilot, ProviderId.CLAUDE_PLATFORM, CredentialKind.CONSOLE_SESSION)
        form.query_one("#secret", Input).value = "synthetic-console"
        await pilot.pause()
        assert manager.account_store.load() == () and discovery.calls == 0
        await form.discover()
        await pilot.pause()
        assert discovery.calls == 1
        assert not manager.credential_store._session
        assert form.query_one("#organization", Select).value is Select.NULL
        assert manager.account_store.load() == ()
        form.query_one("#organization", Select).value = "org-two"
        await form.save()
        await pilot.pause()
        assert manager.accounts[0].organization_id == "org-two"
        assert discovery.calls == 1


async def test_console_discovery_failure_redacted_and_cancel_no_orphan(manager):
    class Discovery:
        async def discover_organizations(self, _credential):
            raise RuntimeError("synthetic-SECRET error body")

    manager.console_discovery = Discovery().discover_organizations
    async with Host(manager).run_test() as pilot:
        form = await open_form(pilot.app, pilot)
        await set_source(form, pilot, ProviderId.CLAUDE_PLATFORM, CredentialKind.CONSOLE_SESSION)
        form.query_one("#secret", Input).value = "synthetic-console"
        await pilot.pause()
        await form.discover()
        assert "synthetic-SECRET" not in str(form.query_one("#form-status", Static).render())
        assert not manager.credential_store._session
        await pilot.press("escape")
        assert manager.account_store.load() == ()


async def test_grok_scope_selection_external_file_untouched(manager, tmp_path):
    (tmp_path / "grok").mkdir(mode=0o700)
    external = tmp_path / "grok" / "auth.json"
    external.write_text(
        json.dumps(
            {
                "https://auth.x.ai::first": {"key": "synthetic-first"},
                "https://auth.x.ai::second": {"key": "synthetic-second"},
            }
        )
    )
    external.chmod(0o600)
    before = external.read_bytes()
    async with Host(manager).run_test() as pilot:
        form = await open_form(pilot.app, pilot)
        await set_source(form, pilot, ProviderId.GROK_SUBSCRIPTION, CredentialKind.GROK_AUTH_FILE)
        form.query_one("#reference", Input).value = str(external)
        await pilot.pause()
        await form.save()
        assert manager.account_store.load() == ()
        await form.discover()
        assert form.query_one("#scope", Select).value is Select.NULL
        form.query_one("#scope", Select).value = "https://auth.x.ai::second"
        await form.save()
        await pilot.pause()
        assert manager.accounts[0].credential_selector == "https://auth.x.ai::second"
        await pilot.press("d")
        await pilot.pause()
        await pilot.click("#confirm")
        await pilot.pause()
        assert external.read_bytes() == before


async def test_claude_default_reference_missing_profile_reconnect_guidance(
    manager, tmp_path, monkeypatch
):
    root = tmp_path / "claude"
    root.mkdir(mode=0o700)
    source = root / ".credentials.json"
    source.write_text(json.dumps({"claudeAiOauth": {"accessToken": "synthetic", "scopes": []}}))
    source.chmod(0o600)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(root))
    original = Account(
        str(uuid4()),
        ProviderId.CLAUDE_SUBSCRIPTION,
        "Claude",
        "default",
        CredentialKind.CLAUDE_CODE_FILE,
    )
    manager.account_store.mutate(lambda _: (original,))
    calls = []
    manager.on_reconnect = calls.append
    async with Host(manager).run_test() as pilot:
        await pilot.press("r")
        await pilot.pause()
        assert "user:profile" in str(manager.query_one("#account-status", Static).render())
        assert not calls
        assert source.exists()


async def test_codex_file_only_default_save_and_missing_login_guidance(manager, monkeypatch):
    calls = []
    manager.on_reconnect = calls.append

    def forbidden(*_args, **_kwargs):
        pytest.fail("Codex file management must not touch stored secrets")

    monkeypatch.setattr(manager.credential_store, "put", forbidden)
    monkeypatch.setattr(manager.credential_store, "get", forbidden)
    monkeypatch.setattr(manager.credential_store, "delete", forbidden)
    monkeypatch.setenv("CODEX_HOME", str(manager.account_store.path.parent / "missing-codex"))
    async with Host(manager).run_test() as pilot:
        form = await open_form(pilot.app, pilot)
        form.query_one("#provider", Select).value = ProviderId.CODEX_SUBSCRIPTION
        await pilot.pause()
        assert form.query_one("#kind", Select).value == CredentialKind.CODEX_AUTH_FILE
        assert {kind for _, kind in form._kinds(ProviderId.CODEX_SUBSCRIPTION)} == {
            "none",
            CredentialKind.CODEX_AUTH_FILE,
        }
        assert not form.query_one("#secret").display
        assert not form.query_one("#persist").display
        assert "codex login" in str(form.query_one("#guidance", Static).render())
        form.query_one("#label", Input).value = "Codex synthetic"
        await form.save()
        await pilot.pause()
        (saved,) = manager.account_store.load()
        assert saved.credential_kind == CredentialKind.CODEX_AUTH_FILE
        assert saved.credential_ref == "default"
        await pilot.press("r")
        await pilot.pause()
        assert not calls
        assert "codex login" in str(manager.query_one("#account-status", Static).render())


async def test_readonly_demo_never_touches_services():
    class Forbidden:
        def __getattr__(self, _):
            raise AssertionError("Demo accessed live service")

    original = Account(str(uuid4()), ProviderId.CLAUDE_SUBSCRIPTION, "DEMO")
    manager = AccountManagerScreen(
        Forbidden(), Forbidden(), Forbidden(), readonly=True, accounts=(original,)
    )
    second = Account(str(uuid4()), ProviderId.CLAUDE_SUBSCRIPTION, "DEMO 2")
    manager.accounts = (original, second)
    async with Host(manager).run_test(size=(40, 12)) as pilot:
        await pilot.press("a", "e", "space", "d", "k", "r")
        await pilot.press("shift+down", "ctrl+down", "shift+up", "ctrl+up")
        listing = listing_of(manager)
        await pilot.mouse_down(listing, offset=line(listing, 0))
        assert not listing.dragging
        await pilot.hover(listing, offset=line(listing, 1))
        await pilot.mouse_up(listing, offset=line(listing, 1))
        await pilot.pause()
        assert pilot.app.screen is manager
        assert manager.accounts == (original, second)


async def test_async_callbacks_and_sanitized_label(manager):
    changes, reconnects = [], []

    async def changed(accounts):
        changes.append(accounts)

    async def reconnect(account_id):
        reconnects.append(account_id)

    manager.on_changed, manager.on_reconnect = changed, reconnect
    async with Host(manager).run_test() as pilot:
        form = await open_form(pilot.app, pilot)
        form.query_one("#label", Input).value = "[red]Synthetic[/red]"
        await set_source(form, pilot, ProviderId.CLAUDE_SUBSCRIPTION, CredentialKind.MANUAL_BEARER)
        form.query_one("#secret", Input).value = "synthetic-only"
        await form.save()
        await pilot.pause()
        await pilot.press("r")
        await pilot.pause()
        assert changes and reconnects == [manager.accounts[0].id]
        assert "[" not in manager.accounts[0].label
        assert "synthetic-only" not in manager.account_store.path.read_text()


async def test_service_failure_clears_input_and_redacts_error(manager, monkeypatch):
    def fail(_change):
        raise RuntimeError("synthetic-SECRET")

    async with Host(manager).run_test() as pilot:
        form = await open_form(pilot.app, pilot)
        await set_source(form, pilot, ProviderId.CLAUDE_SUBSCRIPTION, CredentialKind.MANUAL_BEARER)
        field = form.query_one("#secret", Input)
        field.value = "synthetic-only"
        monkeypatch.setattr(manager.account_store, "mutate", fail)
        await form.save()
        await pilot.pause()
        assert field.value == ""
        assert "synthetic-SECRET" not in str(form.query_one("#form-status", Static).render())
        assert not manager.credential_store._session
        assert manager.accounts == ()


@pytest.mark.parametrize(
    "provider", [provider for provider in ProviderId if provider != ProviderId.CODEX_SUBSCRIPTION]
)
async def test_api_key_storage_never_discovers_or_implies_reads(manager, provider):
    class ForbiddenDiscovery:
        async def discover_organizations(self, _credential):
            raise AssertionError("Local API key must not trigger discovery")

    manager.console_discovery = ForbiddenDiscovery().discover_organizations
    async with Host(manager).run_test() as pilot:
        form = await open_form(pilot.app, pilot)
        await set_source(form, pilot, provider, CredentialKind.API_KEY)
        form.query_one("#secret", Input).value = "synthetic-local-key"
        await form.save()
        await pilot.pause()
        assert manager.accounts[0].credential_kind == CredentialKind.API_KEY
        assert "API key" in str(AccountForm._kinds(provider))
        assert not manager.accounts[0].organization_id


async def test_default_claude_external_reference_needs_no_file_read_on_save(manager):
    async with Host(manager).run_test() as pilot:
        form = await open_form(pilot.app, pilot)
        await set_source(
            form, pilot, ProviderId.CLAUDE_SUBSCRIPTION, CredentialKind.CLAUDE_CODE_FILE
        )
        assert form.query_one("#reference", Input).value == "default"
        await form.save()
        await pilot.pause()
        assert manager.accounts[0].credential_ref == "default"
        assert not manager.credential_store._session


async def test_invalid_console_submit_clears_secret_and_stores_nothing(manager):
    async with Host(manager).run_test() as pilot:
        form = await open_form(pilot.app, pilot)
        await set_source(form, pilot, ProviderId.CLAUDE_PLATFORM, CredentialKind.CONSOLE_SESSION)
        field = form.query_one("#secret", Input)
        field.value = "synthetic-unselected-console"
        await pilot.pause()
        await form.save()
        await pilot.pause()
        assert field.value == ""
        assert manager.account_store.load() == ()
        assert not manager.credential_store._session


async def test_encrypted_backend_failure_requires_explicit_session_retry(manager, monkeypatch):
    def unavailable(*_args, **_kwargs):
        raise RuntimeError("synthetic-sensitive-backend-detail")

    monkeypatch.setattr(manager.credential_store, "_secure_backend", unavailable)
    async with Host(manager).run_test() as pilot:
        form = await open_form(pilot.app, pilot)
        await set_source(form, pilot, ProviderId.CLAUDE_SUBSCRIPTION, CredentialKind.API_KEY)
        form.query_one("#persist", Select).value = True
        form.query_one("#secret", Input).value = "synthetic-key"
        await form.save()
        await pilot.pause()
        assert manager.account_store.load() == ()
        assert not manager.credential_store._session
        assert form.query_one("#secret", Input).value == ""
        assert "synthetic-sensitive" not in str(form.query_one("#form-status", Static).render())
        form.query_one("#persist", Select).value = False
        form.query_one("#secret", Input).value = "synthetic-key"
        await form.save()
        await pilot.pause()
        assert manager.accounts[0].credential_ref.startswith("session:")


@pytest.mark.parametrize("size", [(80, 24), (40, 12)])
async def test_console_session_warning_visible_before_secret_entry(manager, size):
    async with Host(manager).run_test(size=size) as pilot:
        form = await open_form(pilot.app, pilot)
        warning = form.query_one("#session-warning", Static)
        assert not warning.display
        await set_source(form, pilot, ProviderId.CLAUDE_PLATFORM, CredentialKind.CONSOLE_SESSION)
        assert form.query_one("#secret", Input).value == ""
        assert warning.display and warning.visible
        warning.scroll_visible(animate=False)
        await pilot.pause()
        assert warning.region.overlaps(form.region)
        text = str(warning.render())
        for required in (
            "High-sensitivity",
            "only the sessionKey value",
            "password",
            "Cookie",
            "HAR",
        ):
            assert required in text
        await set_source(form, pilot, ProviderId.CLAUDE_PLATFORM, CredentialKind.API_KEY)
        assert not warning.display


@pytest.mark.parametrize("operation", ["add", "replace", "remove", "detach"])
async def test_committed_directory_sync_failure_notifies_host_once(manager, monkeypatch, operation):
    draft = Account(
        str(uuid4()),
        ProviderId.CLAUDE_SUBSCRIPTION,
        "Synthetic account",
        credential_kind=CredentialKind.MANUAL_BEARER,
        credential_ref=f"session:{uuid4()}",
    )
    original = None
    if operation != "add":
        original = manager.service.save(draft, secret="synthetic-old")[0]
    changes = []
    manager.on_changed = changes.append
    fsync = os.fsync

    def fail_directory(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("synthetic-sensitive-directory-error")
        fsync(fd)

    async with Host(manager).run_test() as pilot:
        monkeypatch.setattr(os, "fsync", fail_directory)
        if operation == "add":
            form = await open_form(pilot.app, pilot)
            await set_source(
                form, pilot, ProviderId.CLAUDE_SUBSCRIPTION, CredentialKind.MANUAL_BEARER
            )
            form.query_one("#secret", Input).value = "synthetic-new"
            await form.save()
        elif operation == "replace":
            await pilot.press("e")
            await pilot.pause()
            form = pilot.app.screen
            form.query_one("#secret", Input).value = "synthetic-new"
            await form.save()
            await pilot.pause()
            await pilot.click("#confirm")
        elif operation == "remove":
            await manager._change(lambda: manager.service.remove(original), {original.id})
        else:
            await manager._change(
                lambda: manager.service.save(
                    replace(original, credential_kind=None, credential_ref=None), original=original
                ),
                {original.id},
            )
        await pilot.pause()
        committed = AccountStore(manager.account_store.path).load()
        assert changes == [committed]
        assert manager.accounts == committed
        assert pilot.app.screen is manager
        assert "crash durability" in str(manager.query_one("#account-status", Static).render())
        if operation in {"add", "replace"}:
            assert manager.resolver.resolve(committed[0]).secret == "synthetic-new"
        if original is not None:
            assert manager.credential_store.get(original.credential_ref) == "synthetic-old"


async def test_rejected_mutation_does_not_notify_host(manager, monkeypatch):
    changes = []
    manager.on_changed = changes.append

    def fail(_change):
        raise RuntimeError("synthetic-sensitive-rejection")

    async with Host(manager).run_test() as pilot:
        form = await open_form(pilot.app, pilot)
        monkeypatch.setattr(manager.account_store, "mutate", fail)
        await form.save()
        await manager._change(lambda: manager.service.save(form._draft()), frozenset())
        assert changes == []
        assert manager.account_store.load() == ()


async def test_committed_cleanup_failure_notifies_host_once(manager, monkeypatch):
    draft = Account(
        str(uuid4()),
        ProviderId.CLAUDE_SUBSCRIPTION,
        "Synthetic account",
        credential_kind=CredentialKind.MANUAL_BEARER,
        credential_ref=f"session:{uuid4()}",
    )
    saved = manager.service.save(draft, secret="synthetic-old")[0]
    changes = []
    manager.on_changed = changes.append

    def fail_delete(_ref):
        raise RuntimeError("synthetic-sensitive-cleanup-error")

    async with Host(manager).run_test() as pilot:
        monkeypatch.setattr(manager.credential_store, "delete", fail_delete)
        await manager._change(lambda: manager.service.remove(saved), {saved.id})
        assert changes == [()]
        assert manager.accounts == ()
        assert pilot.app.screen is manager
        assert "old credential cleanup failed" in str(
            manager.query_one("#account-status", Static).render()
        )
        assert manager.credential_store.get(saved.credential_ref) == "synthetic-old"


async def test_live_empty_dialog_cancels_without_writes(manager):
    async with Host(manager).run_test() as pilot:
        assert "No accounts" in str(manager.query_one("#account-status", Static).render())
        await open_form(pilot.app, pilot)
        await pilot.press("escape")
        await pilot.pause()
        assert pilot.app.screen is manager
        assert not manager.account_store.path.exists()


async def test_legacy_config_guidance_never_migrates(manager):
    manager.account_store.path.parent.mkdir(mode=0o700)
    record = Account(str(uuid4()), ProviderId.CLAUDE_SUBSCRIPTION, "Legacy").to_dict()
    record["provider"] = "chatgpt_subscription"
    content = json.dumps({"schema_version": 1, "accounts": [record]})
    manager.account_store.path.write_text(content)
    manager.account_store.path.chmod(0o600)
    async with Host(manager).run_test():
        assert "usage accounts migrate-chatgpt-to-codex" in str(
            manager.query_one("#account-status", Static).render()
        )
        assert manager.account_store.path.read_text() == content


async def test_codex_file_reconnect_after_external_login(manager, tmp_path, monkeypatch):
    root = tmp_path / "codex"
    root.mkdir(mode=0o700)
    source = root / "auth.json"
    source.write_text(
        json.dumps({"tokens": {"access_token": "e30.e30.c2ln", "account_id": "synthetic-account"}})
    )
    source.chmod(0o600)
    monkeypatch.setenv("CODEX_HOME", str(root))
    account = Account(
        str(uuid4()),
        ProviderId.CODEX_SUBSCRIPTION,
        "Codex",
        credential_kind=CredentialKind.CODEX_AUTH_FILE,
        credential_ref="default",
        enabled=False,
    )
    manager.account_store.save((account,))
    calls = []
    manager.on_reconnect = calls.append
    async with Host(manager).run_test() as pilot:
        await pilot.press("r")
        await pilot.pause()
        assert calls == [account.id]
        assert manager.account_store.load() == (account,)
        assert source.exists()


class LockedHost(Host):
    """A host that owns ``account_lock`` like UsageApp and the API hub."""

    def __init__(self, manager):
        super().__init__(manager)
        self.account_lock = asyncio.Lock()


def seed(manager, count=3):
    accounts = tuple(
        Account(str(uuid4()), ProviderId.CLAUDE_SUBSCRIPTION, f"Account {index}")
        for index in range(count)
    )
    manager.account_store.save(accounts)
    return accounts


def recorder(changes):
    def changed(accounts, *, invalidate=None):
        changes.append((accounts, invalidate))

    return changed


def ids(accounts):
    return [account.id for account in accounts]


def line(listing, index):
    """Offset of an option's first line, relative to the list widget."""
    return (3, listing.gutter.top + index)


def listing_of(manager):
    return manager.query_one("#accounts", ReorderableOptionList)


@pytest.mark.parametrize(("down", "up"), [("shift+down", "shift+up"), ("ctrl+down", "ctrl+up")])
async def test_keyboard_move_persists_order_and_follows_account(manager, down, up):
    first, second, third = seed(manager)
    changes = []
    manager.on_changed = recorder(changes)
    async with LockedHost(manager).run_test() as pilot:
        assert "Shift+↑/↓ or drag Move" in str(manager.query_one("#account-hint").render())
        await pilot.press(down)
        await pilot.pause()
        assert ids(manager.account_store.load()) == ids((second, first, third))
        assert manager.selected() == first
        await pilot.press(down)
        await pilot.pause()
        assert ids(manager.account_store.load()) == ids((second, third, first))
        assert manager.selected() == first
        await pilot.press(up)
        await pilot.pause()
        assert ids(manager.account_store.load()) == ids((second, first, third))
        assert manager.selected() == first
        assert [invalidate for _, invalidate in changes] == [frozenset()] * 3
        assert changes[-1][0] == manager.account_store.load() == manager.accounts


async def test_boundary_moves_never_write(manager, monkeypatch):
    seed(manager, 2)
    async with Host(manager).run_test() as pilot:

        def forbidden(_ids):
            pytest.fail("A boundary move must not write")

        monkeypatch.setattr(manager.service, "reorder", forbidden)
        await pilot.press("shift+up", "ctrl+up")
        await pilot.press("end", "shift+down", "ctrl+down")
        await pilot.pause()


async def test_stale_move_resyncs_without_writing(manager):
    first, second, _ = seed(manager)
    changes = []
    manager.on_changed = recorder(changes)
    async with Host(manager).run_test() as pilot:
        # Another process removes an account after the manager loaded the list.
        manager.account_store.save((first, second))
        before = manager.account_store.path.read_bytes()
        await pilot.press("shift+down")
        await pilot.pause()
        assert manager.account_store.path.read_bytes() == before
        assert "Accounts changed elsewhere; reloaded. Move again." in str(
            manager.query_one("#account-status", Static).render()
        )
        assert manager.accounts == (first, second)
        assert listing_of(manager).option_count == 2
        assert changes == [((first, second), frozenset())]


async def test_drag_reorders_and_swallows_the_release_click(manager):
    first, second, third = seed(manager)
    changes = []
    manager.on_changed = recorder(changes)
    async with Host(manager).run_test() as pilot:
        listing = listing_of(manager)
        await pilot.mouse_down(listing, offset=line(listing, 0))
        assert listing.dragging
        await pilot.hover(listing, offset=line(listing, 2))
        assert "position 3/3 (Esc cancels)" in str(
            manager.query_one("#account-status", Static).render()
        )
        await pilot.mouse_up(listing, offset=line(listing, 2))
        await pilot.pause()
        assert ids(manager.account_store.load()) == ids((second, third, first))
        assert manager.selected() == first
        assert changes == [(manager.accounts, frozenset())]
        # The drag is over: its Esc hint is replaced by the saved position.
        status = str(manager.query_one("#account-status", Static).render())
        assert "Esc cancels" not in status and "position 3/3" in status
        assert listing._suppress_click
        # Textual synthesizes a Click for a release over the pressed widget.
        listing.post_message(events.Click(listing, *line(listing, 1), 0, 0, 1, False, False, False))
        await pilot.pause()
        assert not listing._suppress_click
        # The base click handler would have highlighted (and selected) row 1.
        assert manager.selected() == first
        assert not isinstance(pilot.app.screen, AccountForm)


async def test_drop_below_list_clamps_and_next_click_selects(manager):
    first, second, third = seed(manager)
    async with Host(manager).run_test() as pilot:
        listing = listing_of(manager)
        await pilot.mouse_down(listing, offset=line(listing, 0))
        status = manager.query_one("#account-status", Static)
        await pilot.mouse_up(status, offset=(3, 0))
        await pilot.pause()
        assert ids(manager.account_store.load()) == ids((second, third, first))
        assert not listing._suppress_click
        await pilot.click(listing, offset=line(listing, 0))
        await pilot.pause()
        assert manager.selected() == second


async def test_escape_cancels_drag_without_leaving_manager(manager):
    accounts = seed(manager)
    async with Host(manager).run_test() as pilot:
        listing = listing_of(manager)
        await pilot.mouse_down(listing, offset=line(listing, 0))
        await pilot.hover(listing, offset=line(listing, 2))
        await pilot.press("escape")
        await pilot.pause()
        assert pilot.app.screen is manager
        assert not listing.dragging
        assert manager.selected() == accounts[0]
        assert "cancelled" in str(manager.query_one("#account-status", Static).render())
        await pilot.mouse_up(listing, offset=line(listing, 2))
        await pilot.pause()
        assert manager.account_store.load() == accounts


async def test_drop_on_origin_and_reload_end_drag_feedback(manager):
    accounts = seed(manager)
    async with Host(manager).run_test() as pilot:
        listing = listing_of(manager)
        status = manager.query_one("#account-status", Static)
        await pilot.mouse_down(listing, offset=line(listing, 0))
        await pilot.hover(listing, offset=line(listing, 2))
        await pilot.hover(listing, offset=line(listing, 0))
        assert "Esc cancels" in str(status.render())
        await pilot.mouse_up(listing, offset=line(listing, 0))
        await pilot.pause()
        assert "Esc cancels" not in str(status.render())
        assert manager.account_store.load() == accounts
        # Another writer's change rebuilds the list and ends a live drag.
        await pilot.mouse_down(listing, offset=line(listing, 0))
        await pilot.hover(listing, offset=line(listing, 2))
        await manager.reload(tuple(reversed(accounts)))
        await pilot.pause()
        assert not listing.dragging
        rendered = str(status.render())
        assert "Esc cancels" not in rendered and "accounts changed" in rendered
        await pilot.mouse_up(listing, offset=line(listing, 2))
        await pilot.pause()
        assert pilot.app.screen is manager
        await pilot.press("escape")
        await pilot.pause()
        assert pilot.app.screen is not manager


async def test_mutating_shortcuts_are_ignored_mid_drag(manager):
    accounts = seed(manager)
    async with Host(manager).run_test() as pilot:
        listing = listing_of(manager)
        await pilot.mouse_down(listing, offset=line(listing, 0))
        await pilot.hover(listing, offset=line(listing, 2))
        await pilot.press("space", "d", "k", "e", "a", "shift+down")
        await pilot.pause()
        # Nothing acted on the hovered row and the drag is still live.
        assert pilot.app.screen is manager
        assert manager.account_store.load() == accounts
        assert listing.dragging
        assert "Finish the move first" in str(manager.query_one("#account-status", Static).render())
        await pilot.mouse_up(listing, offset=line(listing, 2))
        await pilot.pause()
        assert ids(manager.account_store.load()) == ids(accounts[1:] + accounts[:1])


async def test_tui_writers_hold_the_host_account_lock(manager, monkeypatch):
    seed(manager, 2)
    host = LockedHost(manager)
    held = []

    def watch(method):
        def locked(*args, **kwargs):
            held.append(host.account_lock.locked())
            return method(*args, **kwargs)

        return locked

    async with host.run_test() as pilot:
        monkeypatch.setattr(manager.service, "save", watch(manager.service.save))
        monkeypatch.setattr(manager.service, "reorder", watch(manager.service.reorder))
        monkeypatch.setattr(manager.service, "remove", watch(manager.service.remove))
        await pilot.press("shift+down", "space")
        await pilot.pause()
        listing = listing_of(manager)
        await pilot.mouse_down(listing, offset=line(listing, 0))
        await pilot.mouse_up(listing, offset=line(listing, 1))
        await pilot.pause()
        await pilot.press("e")
        await pilot.pause()
        form = pilot.app.screen
        form.query_one("#label", Input).value = "Renamed"
        await form.save()
        await pilot.pause()
        await pilot.press("d")
        await pilot.pause()
        await pilot.click("#confirm")
        await pilot.pause()
        assert held == [True] * 5
        assert not host.account_lock.locked()


async def test_form_rename_keeps_observations_and_source_edit_invalidates(manager, tmp_path):
    root = tmp_path / "codex"
    root.mkdir(mode=0o700)
    account = Account(
        str(uuid4()),
        ProviderId.CODEX_SUBSCRIPTION,
        "Codex",
        credential_kind=CredentialKind.CODEX_AUTH_FILE,
        credential_ref="default",
    )
    manager.account_store.save((account,))
    changes = []
    manager.on_changed = recorder(changes)
    async with Host(manager).run_test() as pilot:
        await pilot.press("e")
        await pilot.pause()
        form = pilot.app.screen
        assert not form.source_dirty
        form.query_one("#label", Input).value = "Renamed"
        await form.save()
        await pilot.pause()
        assert changes[-1][1] == frozenset()
        await pilot.press("e")
        await pilot.pause()
        form = pilot.app.screen
        reference = form.query_one("#reference", Input)
        # Retyping the same reference is still an explicit source submission.
        reference.value = "defaul"
        await pilot.pause()
        reference.value = "default"
        await pilot.pause()
        await form.save()
        await pilot.pause()
        assert changes[-1][1] == frozenset({account.id})
        assert manager.accounts[0].credential_ref == "default"


async def test_form_rejects_new_reference_with_wrong_basename(manager, tmp_path):
    async with Host(manager).run_test() as pilot:
        form = await open_form(pilot.app, pilot)
        await set_source(form, pilot, ProviderId.CODEX_SUBSCRIPTION, CredentialKind.CODEX_AUTH_FILE)
        form.query_one("#reference", Input).value = str(tmp_path / "codex.json")
        await form.save()
        await pilot.pause()
        assert "absolute path to auth.json" in str(form.query_one("#form-status", Static).render())
        assert manager.account_store.load() == ()
