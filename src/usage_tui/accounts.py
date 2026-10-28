"""Reusable account management; no live services are constructed by these screens.

Callbacks receive the committed account tuple, or an opaque account ID for an
explicit reconnect. Demo callers supply ``readonly=True, accounts=...`` and may
omit all services. Secret input is never populated from stored credentials.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Awaitable, Callable
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Input, Label, OptionList, Select, Static
from textual.widgets.option_list import Option

from usage_tui.credentials import CredentialResolutionError, CredentialResolver, _read_file
from usage_tui.domain import (
    READ_CREDENTIAL_KINDS,
    Account,
    CredentialKind,
    ProviderId,
    ResolvedCredential,
    sanitize_text,
)
from usage_tui.providers.console import OrganizationChoice
from usage_tui.storage import AccountStore, ConfigCommittedError, ConfigError, CredentialStore

FILE_KINDS = {CredentialKind.CLAUDE_CODE_FILE, CredentialKind.GROK_AUTH_FILE}
PROVIDERS = {
    ProviderId.CLAUDE_SUBSCRIPTION: "Claude subscription",
    ProviderId.CLAUDE_PLATFORM: "Claude Platform",
    ProviderId.CHATGPT_SUBSCRIPTION: "ChatGPT subscription (weekly blocked)",
    ProviderId.GROK_SUBSCRIPTION: "Grok subscription",
}
KINDS = {
    CredentialKind.CLAUDE_CODE_FILE: "External Claude Code file",
    CredentialKind.GROK_AUTH_FILE: "External Grok auth file",
    CredentialKind.CONSOLE_SESSION: "Console session (not an API key)",
    CredentialKind.MANUAL_BEARER: "Manual bearer",
    CredentialKind.API_KEY: "API key — local storage only, no quota reads",
}
GUIDANCE = {
    ProviderId.CLAUDE_SUBSCRIPTION: (
        "Reconnect using Claude Code login with user:profile scope, then retry. "
        "A missing user:profile scope requires signing in again; an API key does not enable quotas."
    ),
    ProviderId.CLAUDE_PLATFORM: (
        "Replace the Console session, explicitly Discover organizations and select one. "
        "API keys do not enable prepaid balance reads."
    ),
    ProviderId.GROK_SUBSCRIPTION: (
        "Sign in again with Grok, select the intended auth-file scope, then retry. "
        "API keys are local storage only."
    ),
    ProviderId.CHATGPT_SUBSCRIPTION: (
        "Ordinary ChatGPT weekly quota is blocked: upstream read-only contract missing. "
        "Optional bearer/API-key storage does not enable retrieval. Do not supply cookies."
    ),
}

CONSOLE_SESSION_WARNING = (
    "High-sensitivity account session: enter only the sessionKey value. "
    "Do not enter your password, a full Cookie header, or a HAR file."
)


class AccountFlowError(ValueError):
    """Curated UI failure; never includes backend exception text."""

    def __init__(self, message: str, *, updated: tuple[Account, ...] | None = None) -> None:
        super().__init__(message)
        self.updated = updated


class AccountService:
    """Synchronous local transactions; network discovery is a separate UI action."""

    def __init__(self, account_store: AccountStore, credential_store: CredentialStore) -> None:
        self.accounts = account_store
        self.credentials = credential_store

    def save(
        self,
        account: Account,
        *,
        original: Account | None = None,
        secret: str | None = None,
        persist: bool = False,
    ) -> tuple[Account, ...]:
        new_ref = None
        try:
            if secret is not None:
                new_ref = self.credentials.put(account.id, secret, persist=persist)
                account = replace(account, credential_ref=new_ref)

            def change(current: tuple[Account, ...]) -> tuple[Account, ...]:
                existing = next((item for item in current if item.id == account.id), None)
                if existing != original:
                    raise AccountFlowError("Account changed elsewhere; reopen the form.")
                if original is None:
                    return current + (account,)
                return tuple(account if item.id == account.id else item for item in current)

            updated = self.accounts.mutate(change)
        except ConfigCommittedError as error:
            raise AccountFlowError(
                "Config saved, but crash durability could not be confirmed. Credentials were "
                "retained; reopen the account manager and save again before removing obsolete secrets.",
                updated=error.accounts,
            ) from None
        except Exception:  # noqa: BLE001 - Injected stores may expose secrets; rollback new refs.
            if new_ref is not None:
                try:
                    self.credentials.delete(new_ref)
                except Exception:  # noqa: BLE001 - Redact injected credential cleanup errors.
                    raise AccountFlowError(
                        "Save failed; new credential cleanup failed. Unlock the secure store and retry."
                    ) from None
            raise AccountFlowError(
                "Cannot save account. Check private config permissions and unlock the secure store; "
                "or explicitly choose session only. No config change was accepted."
            ) from None
        if original and original.credential_ref != account.credential_ref:
            self._delete_owned(original, updated)
        return updated

    def _delete_owned(self, account: Account, updated: tuple[Account, ...]) -> None:
        if account.credential_kind not in FILE_KINDS and account.credential_ref:
            try:
                self.credentials.delete(account.credential_ref)
            except Exception:  # noqa: BLE001 - Redact injected credential cleanup errors.
                raise AccountFlowError(
                    "Config saved, but old credential cleanup failed. Unlock the secure store "
                    "and remove the obsolete usage-tui entry there. External files were not touched.",
                    updated=updated,
                ) from None

    def remove(self, account: Account) -> tuple[Account, ...]:
        def change(current: tuple[Account, ...]) -> tuple[Account, ...]:
            if account not in current:
                raise AccountFlowError("Account changed elsewhere; reopen the manager.")
            return tuple(item for item in current if item.id != account.id)

        try:
            updated = self.accounts.mutate(change)
        except ConfigCommittedError as error:
            raise AccountFlowError(
                "Account removed, but crash durability could not be confirmed. Its credential "
                "was retained; reopen the manager before removing the obsolete secret.",
                updated=error.accounts,
            ) from None
        except Exception:  # noqa: BLE001 - Redact injected account-store errors.
            raise AccountFlowError("Cannot remove account; config was not changed.") from None
        self._delete_owned(account, updated)
        return updated


class ConfirmDialog(ModalScreen[bool]):
    BINDINGS = (("escape", "cancel", "Cancel"),)
    DEFAULT_CSS = """
    ConfirmDialog { align: center middle; }
    ConfirmDialog > VerticalScroll { width: 64; max-height: 90%; border: round $accent; padding: 1; }
    ConfirmDialog Horizontal { height: auto; }
    """

    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Static(self.message, markup=False)
            with Horizontal():
                yield Button("Cancel", id="cancel")
                yield Button("Confirm", id="confirm", variant="warning")

    @on(Button.Pressed)
    def pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm")

    def action_cancel(self) -> None:
        self.dismiss(False)


class AccountForm(ModalScreen[bool]):
    """A credential-free initial form; discovery uses a short-lived session ref."""

    BINDINGS = (("escape", "cancel", "Cancel"),)
    DEFAULT_CSS = """
    AccountForm { align: center middle; }
    AccountForm > VerticalScroll { width: 76; max-width: 100%; max-height: 96%; border: round $accent; padding: 1; }
    AccountForm Horizontal { height: auto; }
    AccountForm Select { margin-bottom: 1; }
    AccountForm #form-status { height: auto; min-height: 2; }
    """

    def __init__(self, manager: AccountManagerScreen, account: Account | None = None) -> None:
        super().__init__()
        self.manager = manager
        self.original = account
        self.account_id = account.id if account else str(uuid4())
        self.organizations: set[str] = set()
        self._busy = False

    def compose(self) -> ComposeResult:
        account = self.original
        provider = account.provider if account else ProviderId.CLAUDE_SUBSCRIPTION
        kind = account.credential_kind if account and account.credential_kind else "none"
        with VerticalScroll():
            yield Label("Edit account" if account else "Add account")
            yield Input(
                account.label if account else "",
                placeholder="Account label",
                max_length=80,
                id="label",
            )
            yield Select(
                [(label, value) for value, label in PROVIDERS.items()],
                value=provider,
                allow_blank=False,
                id="provider",
                disabled=account is not None,
            )
            yield Static(GUIDANCE[provider], id="guidance", markup=False)
            yield Select(self._kinds(provider), value=kind, allow_blank=False, id="kind")
            yield Input(
                account.credential_ref
                if account and account.credential_kind in FILE_KINDS
                else "default",
                placeholder="External file: default or absolute path",
                max_length=4096,
                id="reference",
            )
            yield Static(CONSOLE_SESSION_WARNING, id="session-warning", markup=False)
            yield Input(
                "",
                password=True,
                max_length=1_048_576,
                placeholder="New secret only; blank keeps existing",
                id="secret",
            )
            yield Select(
                [
                    ("Session only — lost on exit", False),
                    ("Encrypted OS store — must be available/unlocked", True),
                ],
                value=False,
                allow_blank=False,
                id="persist",
            )
            yield Static(
                "Session-only secrets disappear on exit. Process-memory zeroization is not promised.",
                markup=False,
            )
            yield Button("Discover organizations / Grok scopes (explicit check)", id="discover")
            yield Select([], prompt="Select discovered organization", id="organization")
            yield Select([], prompt="Select discovered Grok scope", id="scope")
            yield Static("No secret is ever prefilled or revealed.", id="form-status", markup=False)
            with Horizontal():
                yield Button("Cancel", id="cancel")
                yield Button("Save", id="save", variant="primary")

    @staticmethod
    def _kinds(provider: ProviderId) -> list[tuple[str, str]]:
        allowed = set(READ_CREDENTIAL_KINDS[provider]) | {CredentialKind.API_KEY}
        if provider == ProviderId.CHATGPT_SUBSCRIPTION:
            allowed.add(CredentialKind.MANUAL_BEARER)
        return [("No credential / local profile", "none")] + [
            (label, kind) for kind, label in KINDS.items() if kind in allowed
        ]

    def on_mount(self) -> None:
        self._visibility()
        self.query_one("#label", Input).focus()

    @on(Select.Changed, "#provider")
    def provider_changed(self, event: Select.Changed) -> None:
        if event.value is Select.NULL:
            return
        provider = ProviderId(event.value)
        if self.original and provider == self.original.provider:
            return
        self.query_one("#kind", Select).set_options(self._kinds(provider))
        self.query_one("#kind", Select).value = "none"
        self.query_one("#guidance", Static).update(GUIDANCE[provider])
        self._invalidate_discovery()

    @on(Select.Changed, "#kind")
    def kind_changed(self) -> None:
        self._visibility()
        self._invalidate_discovery()

    @on(Input.Changed, "#secret")
    @on(Input.Changed, "#reference")
    def source_changed(self) -> None:
        self._invalidate_discovery()

    def _invalidate_discovery(self) -> None:
        self.organizations.clear()
        self.query_one("#organization", Select).set_options([])
        self.query_one("#scope", Select).set_options([])

    def _visibility(self) -> None:
        kind = self.query_one("#kind", Select).value
        self.query_one("#reference").display = kind in FILE_KINDS
        self.query_one("#secret").display = kind != "none" and kind not in FILE_KINDS
        self.query_one("#persist").display = kind != "none" and kind not in FILE_KINDS
        self.query_one("#session-warning").display = kind == CredentialKind.CONSOLE_SESSION
        provider = self.query_one("#provider", Select).value
        self.query_one("#organization").display = provider == ProviderId.CLAUDE_PLATFORM
        self.query_one("#scope").display = kind == CredentialKind.GROK_AUTH_FILE
        self.query_one("#discover").display = (
            kind == CredentialKind.CONSOLE_SESSION or kind == CredentialKind.GROK_AUTH_FILE
        )

    def _draft(self) -> Account:
        provider = ProviderId(self.query_one("#provider", Select).value)
        raw_kind = self.query_one("#kind", Select).value
        kind = None if raw_kind == "none" else CredentialKind(raw_kind)
        original = self.original
        if kind in FILE_KINDS:
            ref = self.query_one("#reference", Input).value.strip()
            if ref != "default" and not Path(ref).is_absolute():
                raise AccountFlowError("Choose default or an absolute external-file path.")
        elif kind is None:
            ref = None
        elif original and original.credential_kind == kind:
            ref = original.credential_ref
        else:
            # A valid temporary placeholder, replaced before config mutation.
            ref = f"session:{uuid4()}"
            if not self.query_one("#secret", Input).value:
                raise AccountFlowError("Enter a new secret for the selected source kind.")
        organization = self.query_one("#organization", Select).value
        scope = self.query_one("#scope", Select).value
        return Account(
            id=self.account_id,
            provider=provider,
            label=self.query_one("#label", Input).value,
            credential_kind=kind,
            credential_ref=ref,
            credential_selector=(
                str(scope)
                if scope is not Select.NULL
                else original.credential_selector
                if original and kind == original.credential_kind and ref == original.credential_ref
                else None
            ),
            organization_id=(
                str(organization)
                if organization is not Select.NULL
                else original.organization_id
                if original
                else None
            ),
            enabled=original.enabled if original else True,
            poll_interval_seconds=original.poll_interval_seconds if original else 60,
        )

    @on(Button.Pressed, "#discover")
    async def discover(self) -> None:
        if self._busy:
            return
        self._busy = True
        button = self.query_one("#discover", Button)
        button.disabled = True
        temporary = None
        try:
            draft = self._draft()
            if draft.credential_kind == CredentialKind.GROK_AUTH_FILE:
                path = self.manager.resolver._path(draft)
                payload = json.loads(_read_file(path))
                if not isinstance(payload, dict):
                    raise ValueError
                scopes = [
                    key
                    for key in payload
                    if isinstance(key, str)
                    and (
                        key == "https://accounts.x.ai/sign-in"
                        or (key.startswith("https://auth.x.ai::") and key != "https://auth.x.ai::")
                    )
                ]
                self.query_one("#scope", Select).set_options(
                    [(f"Grok scope {index + 1}", scope) for index, scope in enumerate(scopes)]
                )
                self._status("Select the intended Grok scope explicitly.")
            elif draft.credential_kind == CredentialKind.CONSOLE_SESSION:
                if self.manager.console_discovery is None:
                    raise AccountFlowError("Organization discovery is unavailable in this host.")
                secret = self.query_one("#secret", Input).value
                if secret:
                    temporary = self.manager.credential_store.put(draft.id, secret, persist=False)
                    draft = replace(draft, credential_ref=temporary)
                credential = self.manager.resolver.resolve(draft)
                choices = await self.manager.console_discovery(credential)
                self.organizations = {choice.id for choice in choices}
                self.query_one("#organization", Select).set_options(
                    [(sanitize_text(choice.label, max_length=120), choice.id) for choice in choices]
                )
                self._status("Select an organization explicitly; no automatic selection is saved.")
        except AccountFlowError as error:
            self._status(str(error))
        except Exception:  # noqa: BLE001 - Redact injected discovery errors and response bodies.
            self._status(
                "Discovery failed. Check credentials, file permissions and reconnect guidance."
            )
        finally:
            if temporary is not None:
                try:
                    self.manager.credential_store.delete(temporary)
                except Exception:  # noqa: BLE001 - Redact injected credential cleanup errors.
                    self._status(
                        "Temporary credential cleanup failed; close this session to discard it."
                    )
            self._busy = False
            button.disabled = False

    def _status(self, text: str) -> None:
        self.query_one("#form-status", Static).update(text)

    @on(Button.Pressed, "#save")
    async def save(self) -> None:
        if self._busy:
            return
        try:
            draft = self._draft()
            secret = self.query_one("#secret", Input).value or None
            if draft.credential_kind in FILE_KINDS or draft.credential_kind is None:
                secret = None
            original = self.original
            changed_source = original and (
                secret is not None
                or draft.credential_kind != original.credential_kind
                or draft.credential_ref != original.credential_ref
            )
            if (
                draft.credential_kind == CredentialKind.CONSOLE_SESSION
                and (
                    not original
                    or changed_source
                    or draft.organization_id != original.organization_id
                )
                and (
                    self.query_one("#organization", Select).value is Select.NULL
                    or draft.organization_id not in self.organizations
                )
            ):
                raise AccountFlowError(
                    "Discover and explicitly select a Console organization first."
                )
            if (
                draft.credential_kind == CredentialKind.GROK_AUTH_FILE
                and not draft.credential_selector
            ):
                raise AccountFlowError("Discover and explicitly select a Grok scope first.")
            self._clear_secret()
            if changed_source:
                self.app.push_screen(
                    ConfirmDialog(
                        "Replace/remove the existing credential reference? Its old value will never be shown. "
                        "Only this tool's old secret is deleted; external login files are never deleted."
                    ),
                    lambda confirmed: self._commit(draft, secret) if confirmed else None,
                )
            else:
                await self._commit(draft, secret)
        except AccountFlowError as error:
            self._clear_secret()
            self._status(str(error))
        except (ValueError, TypeError):
            self._clear_secret()
            self._status("Invalid account settings. Check label, source and selection.")

    async def _commit(self, draft: Account, secret: str | None) -> None:
        self._busy = True
        persist = self.query_one("#persist", Select).value is True
        self._clear_secret()
        try:
            updated = self.manager.service.save(
                draft, original=self.original, secret=secret, persist=persist
            )
            await self.manager.changed(updated)
        except AccountFlowError as error:
            if error.updated is not None:
                await self.manager.changed(error.updated)
                self.manager.status(str(error))
                self.dismiss(True)
            else:
                self._status(str(error))
        else:
            self.dismiss(True)
        finally:
            self._busy = False

    def _clear_secret(self) -> None:
        for field in self.query(Input):
            if field.id == "secret":
                field.value = ""

    @on(Button.Pressed, "#cancel")
    def action_cancel(self) -> None:
        if not self._busy:
            self._clear_secret()
            self.dismiss(False)

    def on_unmount(self) -> None:
        self._clear_secret()


class AccountManagerScreen(Screen[None]):
    """Inject stores/resolver/discovery; readonly mode performs no service calls."""

    BINDINGS = (
        ("escape", "back", "Back"),
        ("a", "add", "Add"),
        ("e", "edit", "Edit"),
        ("space", "toggle", "Enable/disable"),
        ("d", "remove", "Remove"),
        ("k", "delete_key", "Delete key"),
        ("r", "reconnect", "Reconnect"),
    )
    DEFAULT_CSS = """
    AccountManagerScreen { padding: 1; }
    AccountManagerScreen #accounts { height: 1fr; min-height: 2; }
    AccountManagerScreen #account-status { height: auto; max-height: 5; }
    AccountManagerScreen Horizontal { height: auto; }
    """

    def __init__(
        self,
        account_store: AccountStore | None = None,
        credential_store: CredentialStore | None = None,
        resolver: CredentialResolver | None = None,
        console_discovery: Callable[[ResolvedCredential], Awaitable[tuple[OrganizationChoice, ...]]]
        | None = None,
        *,
        on_changed: Callable | None = None,
        on_reconnect: Callable | None = None,
        readonly: bool = False,
        accounts: tuple[Account, ...] = (),
    ) -> None:
        super().__init__()
        if not readonly and any(
            item is None for item in (account_store, credential_store, resolver)
        ):
            raise ValueError("Live account management requires injected stores and resolver.")
        self.account_store = account_store
        self.credential_store = credential_store
        self.resolver = resolver
        self.console_discovery = console_discovery
        self.service = AccountService(account_store, credential_store) if not readonly else None
        self.readonly = readonly
        self.accounts = accounts
        self.on_changed = on_changed
        self.on_reconnect = on_reconnect

    def compose(self) -> ComposeResult:
        yield Label("DEMO — Accounts (read only)" if self.readonly else "Accounts")
        yield OptionList(id="accounts")
        yield Static("", id="account-status", markup=False)
        with Horizontal():
            yield Button("Add", id="add", disabled=self.readonly)
            yield Button("Edit", id="edit", disabled=self.readonly)
            yield Button("Back", id="back")
        yield Static(
            "a Add · e Edit · Space enable/disable · d Remove · k Delete key · r Reconnect · Esc Back",
            markup=False,
        )

    async def on_mount(self) -> None:
        await self.reload()
        self.query_one("#accounts", OptionList).focus()

    async def reload(self) -> None:
        if not self.readonly:
            try:
                self.accounts = self.account_store.load()
            except ConfigError:
                self.status(
                    "Cannot load accounts. Fix private config permissions; no data was overwritten."
                )
                return
        listing = self.query_one("#accounts", OptionList)
        selected = listing.highlighted
        listing.clear_options()
        for account in self.accounts:
            ref = account.credential_ref or ""
            storage = (
                "external credential reference"
                if account.credential_kind in FILE_KINDS
                else "session only"
                if ref.startswith("session:")
                else "stored securely"
                if ref.startswith("keyring:")
                else "no credential"
            )
            text = (
                f"{sanitize_text(account.label, max_length=80)} — {PROVIDERS[account.provider]} — "
                f"{'enabled' if account.enabled else 'disabled'} — {storage}"
            )
            listing.add_option(Option(text, id=account.id))
        if self.accounts:
            listing.highlighted = min(selected or 0, len(self.accounts) - 1)
        else:
            self.status(
                "No accounts. Press a to add." if not self.readonly else "DEMO — no accounts."
            )

    def selected(self) -> Account | None:
        index = self.query_one("#accounts", OptionList).highlighted
        return self.accounts[index] if index is not None and index < len(self.accounts) else None

    def status(self, message: str) -> None:
        self.query_one("#account-status", Static).update(message)

    async def changed(self, updated: tuple[Account, ...]) -> None:
        self.accounts = updated
        await self.reload()
        if self.on_changed:
            try:
                result = self.on_changed(updated)
                if inspect.isawaitable(result):
                    await result
            except Exception:  # noqa: BLE001 - Redact arbitrary injected host callback errors.
                self.status("Account saved; host refresh failed. Reopen the manager to refresh.")

    def action_add(self) -> None:
        if not self.readonly:
            self.app.push_screen(AccountForm(self))

    def action_edit(self) -> None:
        if not self.readonly and (account := self.selected()):
            self.app.push_screen(AccountForm(self, account))

    async def action_toggle(self) -> None:
        if not self.readonly and (account := self.selected()):
            await self._change(
                lambda: self.service.save(
                    replace(account, enabled=not account.enabled), original=account
                )
            )

    async def _change(self, change: Callable) -> None:
        try:
            await self.changed(change())
        except AccountFlowError as error:
            if error.updated is not None:
                await self.changed(error.updated)
            self.status(str(error))

    def action_remove(self) -> None:
        if not self.readonly and (account := self.selected()):
            self.app.push_screen(
                ConfirmDialog(
                    "Remove account and this tool's secret? External files are never deleted. "
                    "This does not revoke any remote login session."
                ),
                lambda yes: self._change(lambda: self.service.remove(account)) if yes else None,
            )

    def action_delete_key(self) -> None:
        if not self.readonly and (account := self.selected()) and account.credential_ref:
            self.app.push_screen(
                ConfirmDialog(
                    "Delete this tool's secret / detach external reference? External files are never deleted."
                ),
                lambda yes: (
                    self._change(
                        lambda: self.service.save(
                            replace(
                                account,
                                credential_ref=None,
                                credential_kind=None,
                                credential_selector=None,
                                organization_id=None,
                            ),
                            original=account,
                        )
                    )
                    if yes
                    else None
                ),
            )

    async def action_reconnect(self) -> None:
        if self.readonly or not (account := self.selected()):
            return
        self.status(GUIDANCE[account.provider])
        if account.provider == ProviderId.CHATGPT_SUBSCRIPTION:
            return
        try:
            self.resolver.resolve(account)
        except CredentialResolutionError:
            # The guidance covers missing profile scope without echoing file/backend errors.
            return
        if self.on_reconnect:
            try:
                result = self.on_reconnect(account.id)
                if inspect.isawaitable(result):
                    await result
            except Exception:  # noqa: BLE001 - Redact arbitrary injected host callback errors.
                self.status("Reconnect failed. " + GUIDANCE[account.provider])

    def action_back(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed)
    def buttons(self, event: Button.Pressed) -> None:
        actions = {"add": self.action_add, "edit": self.action_edit, "back": self.action_back}
        if event.button.id in actions:
            actions[event.button.id]()
