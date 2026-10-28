"""Pilot drives production screens with isolated stores, never live services."""

import json
import os
import stat
from dataclasses import replace
from uuid import uuid4

import pytest
from textual.app import App
from textual.widgets import Input, Select, Static

from usage_tui.accounts import AccountForm, AccountManagerScreen, ConfirmDialog
from usage_tui.credentials import CredentialResolver
from usage_tui.domain import Account, CredentialKind, ProviderId
from usage_tui.providers.console import OrganizationChoice
from usage_tui.storage import AccountStore, CredentialError, CredentialStore


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
    external = tmp_path / "grok-auth.json"
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


async def test_chatgpt_honestly_blocked_local_key_only(manager):
    calls = []
    manager.on_reconnect = calls.append
    async with Host(manager).run_test() as pilot:
        form = await open_form(pilot.app, pilot)
        await set_source(form, pilot, ProviderId.CHATGPT_SUBSCRIPTION, CredentialKind.API_KEY)
        assert "does not enable" in str(form.query_one("#guidance", Static).render())
        form.query_one("#secret", Input).value = "synthetic-api-key"
        await form.save()
        await pilot.pause()
        await pilot.press("r")
        await pilot.pause()
        assert not calls
        assert "blocked" in str(manager.query_one("#account-status", Static).render())


async def test_readonly_demo_never_touches_services():
    class Forbidden:
        def __getattr__(self, _):
            raise AssertionError("Demo accessed live service")

    original = Account(str(uuid4()), ProviderId.CLAUDE_SUBSCRIPTION, "DEMO")
    manager = AccountManagerScreen(
        Forbidden(), Forbidden(), Forbidden(), readonly=True, accounts=(original,)
    )
    async with Host(manager).run_test(size=(40, 12)) as pilot:
        await pilot.press("a", "e", "space", "d", "k", "r")
        await pilot.pause()
        assert pilot.app.screen is manager
        assert manager.accounts == (original,)


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


@pytest.mark.parametrize("provider", list(ProviderId))
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
            await manager._change(lambda: manager.service.remove(original))
        else:
            await manager._change(
                lambda: manager.service.save(
                    replace(original, credential_kind=None, credential_ref=None), original=original
                )
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
        await manager._change(lambda: manager.service.save(form._draft()))
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
        await manager._change(lambda: manager.service.remove(saved))
        assert changes == [()]
        assert manager.accounts == ()
        assert pilot.app.screen is manager
        assert "old credential cleanup failed" in str(
            manager.query_one("#account-status", Static).render()
        )
        assert manager.credential_store.get(saved.credential_ref) == "synthetic-old"
