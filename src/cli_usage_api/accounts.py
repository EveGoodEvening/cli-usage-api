"""Reusable account management; no live services are constructed by these screens.

Callbacks receive the committed account tuple, or an opaque account ID for an
explicit reconnect. Demo callers supply ``readonly=True, accounts=...`` and may
omit all services. Secret input is never populated from stored credentials.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import os
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import replace
from uuid import uuid4

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Input, Label, OptionList, Select, Static
from textual.widgets.option_list import Option

from cli_usage_api.credentials import CredentialResolutionError, CredentialResolver, _read_file
from cli_usage_api.domain import (
    READ_CREDENTIAL_KINDS,
    Account,
    CredentialKind,
    DomainError,
    ProviderId,
    ResolvedCredential,
    default_poll_interval_seconds,
    openai_organization_id,
    openai_session_key,
    sanitize_text,
    validate_credential_kind,
)
from cli_usage_api.providers.console import OrganizationChoice
from cli_usage_api.storage import (
    AccountStore,
    ConfigCommittedError,
    ConfigError,
    CredentialError,
    CredentialStore,
)
from cli_usage_api.transport import _cookie_value, _header_token

FILE_KINDS = {
    CredentialKind.CLAUDE_CODE_FILE,
    CredentialKind.GROK_AUTH_FILE,
    CredentialKind.CODEX_AUTH_FILE,
}
PROVIDERS = {
    ProviderId.CLAUDE_SUBSCRIPTION: "Claude subscription",
    ProviderId.CLAUDE_PLATFORM: "Claude Platform",
    ProviderId.CODEX_SUBSCRIPTION: "Codex subscription",
    ProviderId.GROK_SUBSCRIPTION: "Grok subscription",
    ProviderId.OPENAI_PLATFORM: "OpenAI Platform",
}
KINDS = {
    CredentialKind.CLAUDE_CODE_FILE: "External Claude Code file",
    CredentialKind.GROK_AUTH_FILE: "External Grok auth file",
    CredentialKind.CODEX_AUTH_FILE: "External Codex auth file",
    CredentialKind.CONSOLE_SESSION: "Console session (not an API key)",
    CredentialKind.OPENAI_PLATFORM_SESSION: "OpenAI Platform dashboard session key (not an API key)",
    CredentialKind.MANUAL_BEARER: "Manual bearer",
    CredentialKind.API_KEY: "API key — local storage only, no quota reads",
}
GUIDANCE = {
    ProviderId.CLAUDE_SUBSCRIPTION: (
        "Reconnect using Claude Code login with user:profile scope, then retry. "
        "A missing user:profile scope requires signing in again; an API key does not enable quotas. "
        "For prepaid credits, edit the account, explicitly Discover the organization and select it."
    ),
    ProviderId.CLAUDE_PLATFORM: (
        "Replace the Console session, explicitly Discover organizations and select one. "
        "API keys do not enable prepaid balance reads."
    ),
    ProviderId.GROK_SUBSCRIPTION: (
        "Sign in again with Grok, select the intended auth-file scope, then retry. "
        "API keys are local storage only."
    ),
    ProviderId.CODEX_SUBSCRIPTION: (
        "Run codex login with file-backed credential storage, then select default or auth.json. "
        "CODEX_HOME/auth.json (otherwise ~/.codex/auth.json) is read only; API keys, manual "
        "bearers and keyring-only Codex login are unsupported. Reconnect after signing in again."
    ),
    ProviderId.OPENAI_PLATFORM: (
        "Sign in at platform.openai.com, copy a new dashboard session key, then edit this account "
        "and paste it. Session keys expire within days and are never refreshed here. Enter the "
        "organization ID (org-...) from the organization settings. API keys (sk-...) do not work."
    ),
}

CONSOLE_SESSION_WARNING = (
    "High-sensitivity account session: enter only the sessionKey value. "
    "Do not enter your password, a full Cookie header, or a HAR file."
)

OPENAI_SESSION_WARNING = (
    "High-sensitivity account session: this is the platform.openai.com dashboard session key. "
    "It grants full dashboard access to the account (billing, purchases, creating API keys); "
    "treat it like a password session. Paste only the token value; never your password, a "
    "full Cookie or Authorization header, or a HAR file. It expires within days and must be "
    "pasted again (no refresh). It is stored only in the encrypted OS store or kept for this "
    "session only. This app performs only one read-only GET of the credit balance. "
    "API keys (sk-...) do not work here."
)

CREDITS_ORGANIZATION_HELP = (
    "Optional prepaid credits: Discover reads the signed-in profile (read-only) and lists its "
    "organization. Selecting it adds one read-only prepaid-credits request to each refresh; "
    "nothing is selected automatically. Choose no organization to skip that request."
)

# Providers whose organization is chosen from an explicit, read-only discovery.
DISCOVERY_PROVIDERS = frozenset({ProviderId.CLAUDE_PLATFORM, ProviderId.CLAUDE_SUBSCRIPTION})
NO_ORGANIZATION = "none"

OrganizationDiscovery = Callable[[ResolvedCredential], Awaitable[tuple[OrganizationChoice, ...]]]


MAX_ACCOUNTS = 100
MAX_HTTP_SECRET = 16_384
MAX_REFERENCE_LENGTH = 4096
_BASENAMES = {
    CredentialKind.CLAUDE_CODE_FILE: ".credentials.json",
    CredentialKind.CODEX_AUTH_FILE: "auth.json",
    CredentialKind.GROK_AUTH_FILE: "auth.json",
}
_PSEUDO_FILESYSTEMS = frozenset({"proc", "sys", "dev"})
_LEGACY_GROK_SCOPE = "https://accounts.x.ai/sign-in"
_MODERN_GROK_SCOPE = "https://auth.x.ai::"


class AccountFlowError(ValueError):
    """Curated UI failure; never includes backend exception text.

    ``code`` classifies the failure for hosts (HTTP status, CLI exit code);
    ``updated`` is set only when the config change was already committed.
    """

    def __init__(
        self, message: str, *, updated: tuple[Account, ...] | None = None, code: str = "failed"
    ) -> None:
        super().__init__(message)
        self.updated = updated
        self.code = code


def allowed_kinds(provider: ProviderId) -> tuple[CredentialKind, ...]:
    """Selectable credential kinds in display order; the domain decides API-key records.

    Codex and OpenAI Platform accept only their read kinds (no local API-key records).
    """
    allowed = set(READ_CREDENTIAL_KINDS[provider])
    try:
        validate_credential_kind(provider, CredentialKind.API_KEY)
    except DomainError:
        pass
    else:
        allowed.add(CredentialKind.API_KEY)
    return tuple(kind for kind in KINDS if kind in allowed)


def validate_reference(kind: CredentialKind, reference: object) -> str:
    """Return ``default`` or a normalized absolute path ending in the kind's login file.

    The basename and pseudo-filesystem rules bound which server files a reference can
    probe. Saved references are not revalidated; this applies to new entries only.
    """
    basename = _BASENAMES.get(kind, "auth.json")
    if reference == "default" and kind in _BASENAMES:
        return "default"
    if (
        kind not in _BASENAMES
        or not isinstance(reference, str)
        or not 1 <= len(reference) <= MAX_REFERENCE_LENGTH
        or any(
            ord(char) < 32 or ord(char) == 127 or 0xD800 <= ord(char) <= 0xDFFF
            for char in reference
        )
        or not reference.startswith("/")
        or reference.startswith("//")
        or os.path.normpath(reference) != reference
        or reference.split("/")[1] in _PSEUDO_FILESYSTEMS
        or reference.rsplit("/", 1)[-1] != basename
    ):
        raise AccountFlowError(
            f"Choose default or an absolute path to {basename}.", code="invalid_reference"
        )
    return reference


def validate_secret(kind: CredentialKind, value: object, *, maximum: int = 1_048_576) -> str:
    """Accept only a bare header token; a Console session must also be a cookie value.

    An OpenAI Platform session key follows the stricter dashboard-session rule and is
    returned without surrounding whitespace.
    """
    if kind == CredentialKind.OPENAI_PLATFORM_SESSION:
        if isinstance(value, str) and value.strip().lower().startswith("sk-"):
            raise AccountFlowError(
                "API keys (sk-...) do not work here; paste the dashboard session key.",
                code="invalid_secret",
            )
        try:
            if not isinstance(value, str) or len(value) > maximum:
                raise DomainError("Invalid session key.")
            return openai_session_key(value)
        except DomainError:
            raise AccountFlowError(
                "Invalid session key; paste only the dashboard session token value, not an API "
                "key, header, cookie text or HAR.",
                code="invalid_secret",
            ) from None
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= maximum
        or not _header_token(value)
        or (kind == CredentialKind.CONSOLE_SESSION and not _cookie_value(value))
    ):
        raise AccountFlowError(
            "Invalid credential value; enter only the value, not headers or a HAR.",
            code="invalid_secret",
        )
    return value


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate key.")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError("Non-JSON numeric constant.")


def grok_scopes(raw: bytes) -> tuple[str, ...]:
    """Selectable Grok auth-file scope keys, in file order; values are never returned."""
    try:
        payload = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (ValueError, UnicodeError, RecursionError):
        payload = None
    if not isinstance(payload, dict):
        raise AccountFlowError(
            "Invalid Grok auth file; sign in with Grok again.", code="invalid_credential_file"
        ) from None
    return tuple(
        key
        for key in payload
        if key == _LEGACY_GROK_SCOPE
        or (key.startswith(_MODERN_GROK_SCOPE) and key != _MODERN_GROK_SCOPE)
    )


def storage_class(account: Account) -> str:
    """Where the credential lives: ``external_file``, ``session``, ``keyring`` or ``none``."""
    ref = account.credential_ref
    if account.credential_kind is None or ref is None:
        return "none"
    if account.credential_kind in FILE_KINDS:
        return "external_file"
    if ref.startswith("session:"):
        return "session"
    if ref.startswith("keyring:"):
        return "keyring"
    return "none"


def credential_identity(account: Account) -> tuple[object, ...]:
    """Fields whose change makes prior observations belong to another connection."""
    return (
        account.provider,
        account.credential_kind,
        account.credential_ref,
        account.credential_selector,
        account.organization_id,
    )


def _too_many() -> AccountFlowError:
    return AccountFlowError(f"Too many accounts (limit {MAX_ACCOUNTS}).", code="too_many_accounts")


class AccountService:
    """Synchronous local transactions; network discovery is a separate UI action.

    Failures carry ``AccountFlowError.code``. Errors raised while handling another
    exception keep it as ``__context__`` for hosts, but never print its text.
    """

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
        storing = False
        try:
            if secret is not None:
                storing = True
                new_ref = self.credentials.put(account.id, secret, persist=persist)
                storing = False
                account = replace(account, credential_ref=new_ref)

            def change(current: tuple[Account, ...]) -> tuple[Account, ...]:
                existing = next((item for item in current if item.id == account.id), None)
                if existing != original:
                    raise AccountFlowError(
                        "Account changed elsewhere; reopen the form.", code="conflict"
                    )
                if original is None:
                    if len(current) >= MAX_ACCOUNTS:
                        raise _too_many()
                    return current + (account,)
                return tuple(account if item.id == account.id else item for item in current)

            updated = self.accounts.mutate(change)
        except AccountFlowError:
            # A curated rejection from the change callback: nothing was committed.
            self._rollback(new_ref)
            raise
        except ConfigCommittedError as error:
            raise AccountFlowError(
                "Config saved, but crash durability could not be confirmed. Credentials were "
                "retained; reopen the account manager and save again before removing obsolete secrets.",
                updated=error.accounts,
                code="committed_uncertain",
            ) from None
        except Exception as error:  # noqa: BLE001 - Injected stores may expose secrets; rollback new refs.
            if storing and persist and isinstance(error, CredentialError):
                code = "secure_store_unavailable"
            elif isinstance(error, ConfigError):
                code = "config_unavailable"
            else:
                code = "save_failed"
            self._rollback(new_ref)
            raise AccountFlowError(
                "Cannot save account. Check private config permissions and unlock the secure store; "
                "or explicitly choose session only. No config change was accepted.",
                code=code,
            ) from None
        if original and original.credential_ref != account.credential_ref:
            self._delete_owned(original, updated)
        return updated

    def _rollback(self, new_ref: str | None) -> None:
        if new_ref is None:
            return
        try:
            self.credentials.delete(new_ref)
        except Exception:  # noqa: BLE001 - Redact injected credential cleanup errors.
            raise AccountFlowError(
                "Save failed; new credential cleanup failed. Unlock the secure store and retry.",
                code="credential_cleanup_failed",
            ) from None

    def _delete_owned(self, account: Account, updated: tuple[Account, ...]) -> None:
        if account.credential_kind not in FILE_KINDS and account.credential_ref:
            try:
                self.credentials.delete(account.credential_ref)
            except Exception:  # noqa: BLE001 - Redact injected credential cleanup errors.
                raise AccountFlowError(
                    "Config saved, but old credential cleanup failed. Unlock the secure store "
                    "and remove the obsolete cli-usage-api entry there. External files were not touched.",
                    updated=updated,
                    code="cleanup_failed",
                ) from None

    def remove(self, account: Account) -> tuple[Account, ...]:
        def change(current: tuple[Account, ...]) -> tuple[Account, ...]:
            if account not in current:
                raise AccountFlowError(
                    "Account changed elsewhere; reopen the manager.", code="conflict"
                )
            return tuple(item for item in current if item.id != account.id)

        try:
            updated = self.accounts.mutate(change)
        except AccountFlowError:
            raise
        except ConfigCommittedError as error:
            raise AccountFlowError(
                "Account removed, but crash durability could not be confirmed. Its credential "
                "was retained; reopen the manager before removing the obsolete secret.",
                updated=error.accounts,
                code="committed_uncertain",
            ) from None
        except Exception as error:  # noqa: BLE001 - Redact injected account-store errors.
            code = "config_unavailable" if isinstance(error, ConfigError) else "save_failed"
            raise AccountFlowError(
                "Cannot remove account; config was not changed.", code=code
            ) from None
        self._delete_owned(account, updated)
        return updated

    def reorder(self, ids: Sequence[str]) -> tuple[Account, ...]:
        """Persist a permutation of the current accounts; no credential effects.

        The permutation is validated against the stored tuple under the config lock,
        so a list built from a stale view is a conflict rather than a lost update.
        """

        def change(current: tuple[Account, ...]) -> tuple[Account, ...]:
            by_id = {item.id: item for item in current}
            if (
                not isinstance(ids, (list, tuple))
                or len(ids) > MAX_ACCOUNTS
                or not all(type(item) is str for item in ids)
                or len(set(ids)) != len(ids)
                or set(ids) != set(by_id)
            ):
                raise AccountFlowError(
                    "Accounts changed elsewhere; reopen the manager.", code="conflict"
                )
            return tuple(by_id[item] for item in ids)

        try:
            return self.accounts.mutate(change)
        except AccountFlowError:
            raise
        except ConfigCommittedError as error:
            raise AccountFlowError(
                "Account order saved, but crash durability could not be confirmed; "
                "reopen the manager before making further changes.",
                updated=error.accounts,
                code="committed_uncertain",
            ) from None
        except Exception as error:  # noqa: BLE001 - Redact injected account-store errors.
            code = "config_unavailable" if isinstance(error, ConfigError) else "save_failed"
            raise AccountFlowError(
                "Cannot reorder accounts; config was not changed.", code=code
            ) from None


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

    DISCOVERY_SECONDS = 30.0

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
        # Claude subscription prepaid-credits organizations from the latest discovery.
        self.credit_organizations: set[str] = set()
        self._busy = False
        # An explicit source submission invalidates the scheduler generation and
        # snapshot even when the saved value is equal (file contents can change).
        self.source_dirty = False
        self._initial: dict[str, object] = {}

    def compose(self) -> ComposeResult:
        account = self.original
        provider = account.provider if account else ProviderId.CLAUDE_SUBSCRIPTION
        kind = account.credential_kind if account and account.credential_kind else "none"
        reference = (
            account.credential_ref
            if account and account.credential_kind in FILE_KINDS
            else "default"
        )
        self._initial = {
            "kind": kind,
            "reference": reference,
            "secret": "",
            "scope": Select.NULL,
            "organization": Select.NULL,
            "credits-organization": Select.NULL,
            "openai-organization": (
                account.organization_id
                if account and account.provider == ProviderId.OPENAI_PLATFORM
                else ""
            ),
        }
        saved_credits = bool(
            account
            and account.provider == ProviderId.CLAUDE_SUBSCRIPTION
            and account.organization_id
        )
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
            yield Input(
                str(self._initial["openai-organization"]),
                placeholder="OpenAI organization ID (org-...)",
                max_length=80,
                id="openai-organization",
            )
            yield Select(self._kinds(provider), value=kind, allow_blank=False, id="kind")
            yield Input(
                reference,
                placeholder="External file: default or absolute path",
                max_length=4096,
                id="reference",
            )
            yield Static(CONSOLE_SESSION_WARNING, id="session-warning", markup=False)
            yield Static(OPENAI_SESSION_WARNING, id="openai-session-warning", markup=False)
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
            yield Static(CREDITS_ORGANIZATION_HELP, id="credits-help", markup=False)
            yield Button("Discover organizations / Grok scopes (explicit check)", id="discover")
            yield Select([], prompt="Select discovered organization", id="organization")
            yield Select(
                self._credit_options(()),
                prompt=(
                    "Keep saved prepaid-credits organization"
                    if saved_credits
                    else "No prepaid-credits organization"
                ),
                id="credits-organization",
            )
            yield Select([], prompt="Select discovered Grok scope", id="scope")
            yield Static("No secret is ever prefilled or revealed.", id="form-status", markup=False)
            with Horizontal():
                yield Button("Cancel", id="cancel")
                yield Button("Save", id="save", variant="primary")

    @staticmethod
    def _kinds(provider: ProviderId) -> list[tuple[str, str]]:
        return [
            ("No credential / local profile", "none"),
            *((KINDS[kind], kind) for kind in allowed_kinds(provider)),
        ]

    @staticmethod
    def _credit_options(choices: Sequence[OrganizationChoice]) -> list[tuple[str, str]]:
        return [
            ("No organization — skip the prepaid credits read", NO_ORGANIZATION),
            *((sanitize_text(choice.label, max_length=120), choice.id) for choice in choices),
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
        self.query_one("#kind", Select).value = {
            ProviderId.CODEX_SUBSCRIPTION: CredentialKind.CODEX_AUTH_FILE,
            ProviderId.OPENAI_PLATFORM: CredentialKind.OPENAI_PLATFORM_SESSION,
        }.get(provider, "none")
        self.query_one("#guidance", Static).update(GUIDANCE[provider])
        self._invalidate_discovery()
        self._visibility()

    @on(Select.Changed, "#kind")
    def kind_changed(self, event: Select.Changed) -> None:
        self._mark_source(event)
        self._visibility()
        self._invalidate_discovery()

    @on(Input.Changed, "#secret")
    @on(Input.Changed, "#reference")
    def source_changed(self, event: Input.Changed) -> None:
        self._mark_source(event)
        self._invalidate_discovery()

    @on(Select.Changed, "#scope")
    @on(Select.Changed, "#organization")
    @on(Select.Changed, "#credits-organization")
    @on(Input.Changed, "#openai-organization")
    def selection_changed(self, event: Select.Changed | Input.Changed) -> None:
        # An organization belongs to the credential identity: a change invalidates
        # prior observations, but it does not replace the stored secret.
        self._mark_source(event)

    def _mark_source(self, event: Input.Changed | Select.Changed) -> None:
        # Mount-time and reset events carry the initial value; any user edit of a
        # source field passes through a different value, even if it ends equal.
        if event.value != self._initial.get(event.control.id or ""):
            self.source_dirty = True

    def _invalidate_discovery(self) -> None:
        self.organizations.clear()
        self.credit_organizations.clear()
        self.query_one("#organization", Select).set_options([])
        self.query_one("#credits-organization", Select).set_options(self._credit_options(()))
        self.query_one("#scope", Select).set_options([])

    def _visibility(self) -> None:
        kind = self.query_one("#kind", Select).value
        self.query_one("#reference").display = kind in FILE_KINDS
        self.query_one("#secret").display = kind != "none" and kind not in FILE_KINDS
        self.query_one("#persist").display = kind != "none" and kind not in FILE_KINDS
        self.query_one("#session-warning").display = kind == CredentialKind.CONSOLE_SESSION
        self.query_one("#openai-session-warning").display = (
            kind == CredentialKind.OPENAI_PLATFORM_SESSION
        )
        provider = self.query_one("#provider", Select).value
        self.query_one("#openai-organization").display = provider == ProviderId.OPENAI_PLATFORM
        self.query_one("#organization").display = provider == ProviderId.CLAUDE_PLATFORM
        credits = (
            provider == ProviderId.CLAUDE_SUBSCRIPTION
            and kind in READ_CREDENTIAL_KINDS[ProviderId.CLAUDE_SUBSCRIPTION]
        )
        self.query_one("#credits-organization").display = credits
        self.query_one("#credits-help").display = credits
        self.query_one("#scope").display = kind == CredentialKind.GROK_AUTH_FILE
        discover = self.query_one("#discover", Button)
        discover.display = (
            kind == CredentialKind.CONSOLE_SESSION
            or kind == CredentialKind.GROK_AUTH_FILE
            or credits
        )
        if credits:
            discover.label = "Discover organization for prepaid credits (read-only check)"
        elif kind == CredentialKind.GROK_AUTH_FILE:
            discover.label = "Discover Grok scopes (explicit check)"
        else:
            discover.label = "Discover organizations (explicit check)"

    def _draft(self) -> Account:
        provider = ProviderId(self.query_one("#provider", Select).value)
        raw_kind = self.query_one("#kind", Select).value
        kind = None if raw_kind == "none" else CredentialKind(raw_kind)
        original = self.original
        if kind in FILE_KINDS:
            ref = self.query_one("#reference", Input).value.strip()
            # Saved references are not revalidated; new entries follow the shared rule.
            if not (
                original and original.credential_kind == kind and original.credential_ref == ref
            ):
                ref = validate_reference(kind, ref)
        elif kind is None:
            ref = None
        elif original and original.credential_kind == kind:
            ref = original.credential_ref
        else:
            # A valid temporary placeholder, replaced before config mutation.
            ref = f"session:{uuid4()}"
            if not self.query_one("#secret", Input).value:
                raise AccountFlowError("Enter a new secret for the selected source kind.")
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
            organization_id=self._organization_id(provider, kind),
            enabled=original.enabled if original else True,
            poll_interval_seconds=(
                original.poll_interval_seconds
                if original
                else default_poll_interval_seconds(provider)
            ),
        )

    def _organization_id(self, provider: ProviderId, kind: CredentialKind | None) -> str | None:
        original = self.original
        kept = original.organization_id if original and original.provider == provider else None
        if provider == ProviderId.OPENAI_PLATFORM:
            # Entered by the user (no discovery endpoint is evidenced); not a secret.
            try:
                return openai_organization_id(self.query_one("#openai-organization", Input).value)
            except DomainError:
                raise AccountFlowError(
                    "Enter the OpenAI organization ID (org- followed by 8-64 letters or digits) "
                    "from the platform.openai.com organization settings.",
                    code="invalid_organization",
                ) from None
        if provider == ProviderId.CLAUDE_SUBSCRIPTION:
            if kind not in READ_CREDENTIAL_KINDS[provider]:
                return None
            selected = self.query_one("#credits-organization", Select).value
            if selected == NO_ORGANIZATION:
                return None
            return kept if selected is Select.NULL else str(selected)
        if provider == ProviderId.CLAUDE_PLATFORM:
            selected = self.query_one("#organization", Select).value
            return kept if selected is Select.NULL else str(selected)
        return None

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
            credits = (
                draft.provider == ProviderId.CLAUDE_SUBSCRIPTION
                and draft.credential_kind in READ_CREDENTIAL_KINDS[draft.provider]
            )
            if draft.credential_kind in (
                CredentialKind.GROK_AUTH_FILE,
                CredentialKind.CONSOLE_SESSION,
            ):
                self.source_dirty = True
            if credits:
                await self._discover_credit_organizations(draft)
            elif draft.credential_kind == CredentialKind.GROK_AUTH_FILE:
                scopes = grok_scopes(_read_file(self.manager.resolver._path(draft)))
                self.query_one("#scope", Select).set_options(
                    [(f"Grok scope {index + 1}", scope) for index, scope in enumerate(scopes)]
                )
                self._status("Select the intended Grok scope explicitly.")
            elif draft.credential_kind == CredentialKind.CONSOLE_SESSION:
                discovery = self.manager.discovery_for(ProviderId.CLAUDE_PLATFORM)
                if discovery is None:
                    raise AccountFlowError("Organization discovery is unavailable in this host.")
                secret = self.query_one("#secret", Input).value
                if secret:
                    temporary = self.manager.credential_store.put(draft.id, secret, persist=False)
                    draft = replace(draft, credential_ref=temporary)
                credential = self.manager.resolver.resolve(draft)
                choices = await discovery(credential)
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

    async def _discover_credit_organizations(self, draft: Account) -> None:
        """Read the Claude profile's organization as an explicit, unselected choice.

        A typed bearer is held only in a temporary session ref for this read. The
        draft's saved organization is not sent: the profile read is unscoped.
        """
        discovery = self.manager.discovery_for(ProviderId.CLAUDE_SUBSCRIPTION)
        if discovery is None:
            raise AccountFlowError("Organization discovery is unavailable in this host.")
        draft = replace(draft, organization_id=None)
        temporary = None
        try:
            secret = self.query_one("#secret", Input).value
            if draft.credential_kind not in FILE_KINDS and secret:
                temporary = self.manager.credential_store.put(draft.id, secret, persist=False)
                draft = replace(draft, credential_ref=temporary)
            credential = self.manager.resolver.resolve(draft)
            async with asyncio.timeout(self.DISCOVERY_SECONDS):
                choices = tuple(await discovery(credential))
        finally:
            if temporary is not None:
                try:
                    self.manager.credential_store.delete(temporary)
                except Exception:  # noqa: BLE001 - Redact injected credential cleanup errors.
                    raise AccountFlowError(
                        "Temporary credential cleanup failed; close this session to discard it."
                    ) from None
        self.credit_organizations = {choice.id for choice in choices}
        self.query_one("#credits-organization", Select).set_options(self._credit_options(choices))
        if not choices:
            self._status(
                "The profile reported no organization; prepaid credits cannot be read for this "
                "login. Choose no organization."
            )
        else:
            self._status(
                "Select the organization explicitly to read its prepaid credits on each refresh "
                "(one extra read-only request), or choose no organization. Nothing was selected."
            )

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
            if draft.provider == ProviderId.CLAUDE_SUBSCRIPTION and draft.organization_id:
                selected = self.query_one("#credits-organization", Select).value
                explicit = selected is not Select.NULL and selected in self.credit_organizations
                if not explicit and (
                    not original
                    or changed_source
                    or draft.organization_id != original.organization_id
                ):
                    raise AccountFlowError(
                        "The login changed: Discover and explicitly select the prepaid-credits "
                        "organization again, or choose no organization."
                    )
            if (
                secret is not None
                and draft.credential_kind == CredentialKind.OPENAI_PLATFORM_SESSION
            ):
                secret = validate_secret(draft.credential_kind, secret)
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
        # A rename/interval edit keeps observations; a source submission or create does not.
        invalidate = (
            frozenset({draft.id}) if self.original is None or self.source_dirty else frozenset()
        )
        try:
            async with self.manager.account_lock():
                try:
                    updated = self.manager.service.save(
                        draft, original=self.original, secret=secret, persist=persist
                    )
                except AccountFlowError as error:
                    if error.updated is None:
                        if error.code == "conflict":
                            await self.manager.resync()
                        raise
                    await self.manager.changed(error.updated, invalidate)
                    self.manager.status(str(error))
                else:
                    await self.manager.changed(updated, invalidate)
        except AccountFlowError as error:
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
    """Inject stores/resolver/discovery; readonly mode performs no service calls.

    Discovery is ``{ProviderId: async callable}`` (see ``discovery_for``); a bare
    callable is the Console discovery only.

    Every mutation holds the host's ``account_lock`` (or a screen-local lock for a
    host without one) across the service call and the ``on_changed`` notification,
    so publication order matches commit order with other writers such as the API.
    ``on_changed(updated, invalidate=...)`` receives the committed tuple and the
    account IDs whose credential generation must be replaced; a one-argument
    callback is also accepted.
    """

    BINDINGS = (
        ("escape", "back", "Back"),
        ("a", "add", "Add"),
        ("e", "edit", "Edit"),
        ("space", "toggle", "Enable/disable"),
        ("d", "remove", "Remove"),
        ("k", "delete_key", "Delete key"),
        ("r", "reconnect", "Reconnect"),
        # Ctrl+↑/↓ are aliases; the footer shows the first key only.
        ("shift+up,ctrl+up", "move(-1)", "Move up"),
        ("shift+down,ctrl+down", "move(1)", "Move down"),
    )
    DEFAULT_CSS = """
    AccountManagerScreen { padding: 1; }
    AccountManagerScreen #accounts { height: 1fr; min-height: 2; }
    AccountManagerScreen #account-status { height: auto; max-height: 5; }
    AccountManagerScreen Horizontal { height: auto; }
    """
    HINT = (
        "a Add · e Edit · Space enable/disable · d Remove · k Delete key · r Reconnect · "
        "Shift+↑/↓ or drag Move · Esc Back"
    )
    MOVE_CONFLICT = "Accounts changed elsewhere; reloaded. Move again."
    CONFLICT = "Accounts changed elsewhere; reloaded. Try again."

    def __init__(
        self,
        account_store: AccountStore | None = None,
        credential_store: CredentialStore | None = None,
        resolver: CredentialResolver | None = None,
        console_discovery: OrganizationDiscovery
        | Mapping[ProviderId, OrganizationDiscovery]
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
        self.accounts = tuple(accounts)
        self.on_changed = on_changed
        self.on_reconnect = on_reconnect
        self._local_lock = asyncio.Lock()

    def discovery_for(self, provider: ProviderId) -> OrganizationDiscovery | None:
        """The explicit discovery operation for ``provider``, if this host supplies one.

        ``console_discovery`` is either a mapping keyed by provider (Claude Platform
        and Claude subscription) or, for older hosts, the Console callable alone.
        """
        discovery = self.console_discovery
        if isinstance(discovery, Mapping):
            return discovery.get(provider) if provider in DISCOVERY_PROVIDERS else None
        return discovery if provider == ProviderId.CLAUDE_PLATFORM else None

    def compose(self) -> ComposeResult:
        from cli_usage_api.reorder import ReorderableOptionList

        yield Label("DEMO — Accounts (read only)" if self.readonly else "Accounts")
        listing = ReorderableOptionList(id="accounts")
        listing.readonly = self.readonly
        yield listing
        yield Static("", id="account-status", markup=False)
        with Horizontal():
            yield Button("Add", id="add", disabled=self.readonly)
            yield Button("Edit", id="edit", disabled=self.readonly)
            yield Button("Back", id="back")
        yield Static(self.HINT, id="account-hint", markup=False)

    async def on_mount(self) -> None:
        await self.reload()
        self.query_one("#accounts", OptionList).focus()

    def account_lock(self):
        """The host's account lock, else this screen's own (a standalone manager)."""
        lock = getattr(self.app, "account_lock", None)
        return lock if lock is not None else self._local_lock

    async def reload(self, accounts: Sequence[Account] | None = None) -> None:
        """Render ``accounts`` without disk I/O, or load the store when omitted."""
        listing = self.query_one("#accounts", OptionList)
        listing.cancel_drag("reloaded")
        if accounts is not None:
            self.accounts = tuple(accounts)
        elif not self.readonly:
            try:
                self.accounts = self.account_store.load()
            except ConfigError:
                self.status(
                    "Cannot load accounts. Check private config permissions/schema. Legacy ChatGPT "
                    "profiles require usage accounts migrate-chatgpt-to-codex in a terminal; "
                    "migration disables and detaches them, retaining old secrets. No data was overwritten."
                )
                return
        previous = listing.highlighted
        selected = self._option_id(previous)
        listing.clear_options()
        for account in self.accounts:
            text = (
                f"{sanitize_text(account.label, max_length=80)} — {PROVIDERS[account.provider]} — "
                f"{'enabled' if account.enabled else 'disabled'} — "
                f"{STORAGE_LABELS[storage_class(account)]}"
            )
            listing.add_option(Option(text, id=account.id))
        if self.accounts:
            # Selection follows the account, not the row it used to occupy.
            if not self._highlight(selected):
                listing.highlighted = min(previous or 0, len(self.accounts) - 1)
        else:
            self.status(
                "No accounts. Press a to add." if not self.readonly else "DEMO — no accounts."
            )

    def _option_id(self, index: int | None) -> str | None:
        listing = self.query_one("#accounts", OptionList)
        if index is None or not 0 <= index < listing.option_count:
            return None
        return listing.get_option_at_index(index).id

    def _highlight(self, account_id: str | None) -> bool:
        index = next(
            (number for number, item in enumerate(self.accounts) if item.id == account_id), None
        )
        if index is None:
            return False
        self.query_one("#accounts", OptionList).highlighted = index
        return True

    def _dragging(self) -> bool:
        """Mid-drag the highlight is the hover target, not the grabbed account."""
        if self.query_one("#accounts", OptionList).dragging:
            self.status("Finish the move first: release to drop or Esc to cancel.")
            return True
        return False

    def selected(self) -> Account | None:
        account_id = self._option_id(self.query_one("#accounts", OptionList).highlighted)
        return next((item for item in self.accounts if item.id == account_id), None)

    def status(self, message: str) -> None:
        self.query_one("#account-status", Static).update(message)

    async def changed(
        self, updated: tuple[Account, ...], invalidate: frozenset[str] | None = None
    ) -> None:
        """Render the committed tuple, then notify the host (caller holds the lock)."""
        self.accounts = tuple(updated)
        await self.reload(self.accounts)
        await self._notify(self.accounts, invalidate)

    async def _notify(
        self, updated: tuple[Account, ...], invalidate: frozenset[str] | None
    ) -> None:
        if not self.on_changed:
            return
        app = self.app
        # The host reloads every open manager except the one reporting the change.
        app._account_origin = self
        try:
            if _accepts_invalidate(self.on_changed):
                result = self.on_changed(updated, invalidate=invalidate)
            else:
                result = self.on_changed(updated)
            if inspect.isawaitable(result):
                await result
        except Exception:  # noqa: BLE001 - Redact arbitrary injected host callback errors.
            self.status("Account saved; host refresh failed. Reopen the manager to refresh.")
        finally:
            app._account_origin = None

    async def resync(self, message: str | None = None) -> None:
        """Reload after a conflict and publish the stored set if the host lags (lock held)."""
        before = tuple(getattr(self.app, "accounts", self.accounts))
        await self.reload()
        if message:
            self.status(message)
        if not self.readonly and self.accounts != before:
            await self._notify(self.accounts, frozenset())

    def action_add(self) -> None:
        if not self.readonly and not self._dragging():
            self.app.push_screen(AccountForm(self))

    def action_edit(self) -> None:
        if not self.readonly and not self._dragging() and (account := self.selected()):
            self.app.push_screen(AccountForm(self, account))

    async def action_toggle(self) -> None:
        if not self.readonly and not self._dragging() and (account := self.selected()):
            await self._change(
                lambda: self.service.save(
                    replace(account, enabled=not account.enabled), original=account
                ),
                frozenset(),
            )

    async def _change(
        self,
        change: Callable[[], tuple[Account, ...]],
        invalidate: frozenset[str],
        *,
        conflict: str = CONFLICT,
    ) -> None:
        async with self.account_lock():
            await self._apply(change, invalidate, conflict=conflict)

    async def _apply(
        self,
        change: Callable[[], tuple[Account, ...]],
        invalidate: frozenset[str],
        *,
        conflict: str = CONFLICT,
    ) -> None:
        try:
            updated = change()
        except DomainError:
            # An invalid draft is rejected before any write; never crash the app.
            self.status("Account change rejected: invalid account values.")
        except AccountFlowError as error:
            if error.updated is not None:
                await self.changed(error.updated, invalidate)
                self.status(str(error))
            elif error.code == "conflict":
                # Nothing was written: show the stored order and catch the host up.
                await self.resync(conflict)
            else:
                self.status(str(error))
        else:
            await self.changed(updated, invalidate)

    async def action_move(self, delta: int) -> None:
        if not self.readonly and not self._dragging() and (account := self.selected()):
            index = self.accounts.index(account)
            if 0 <= index + delta < len(self.accounts):
                await self._move(account.id, index + delta)

    async def _move(self, account_id: str, target: int) -> None:
        async with self.account_lock():
            # Built under the lock, so another writer's commit is already rendered.
            ids = [item.id for item in self.accounts]
            if account_id not in ids:
                self.status("List changed; drag again.")
                return
            target = max(0, min(target, len(ids) - 1))
            if ids.index(account_id) == target:
                return
            ids.remove(account_id)
            ids.insert(target, account_id)
            await self._apply(
                lambda: self.service.reorder(ids), frozenset(), conflict=self.MOVE_CONFLICT
            )
            order = [item.id for item in self.accounts]
            if account_id in order and order.index(account_id) == target:
                account = self.accounts[target]
                label = sanitize_text(account.label, max_length=80)
                self.status(f"Moved “{label}” to position {target + 1}/{len(order)}.")
        self._highlight(account_id)

    async def on_reorderable_option_list_moved(self, event) -> None:
        event.stop()
        if not self.readonly:
            await self._move(event.account_id, event.target_index)

    def on_reorderable_option_list_drag_ended(self, event) -> None:
        event.stop()
        messages = {
            "cancelled": "Move cancelled.",
            "unchanged": "Order unchanged.",
            "reloaded": "Move cancelled: accounts changed. Drag again.",
            # A Moved message follows and reports the saved position.
            "moved": "",
        }
        self.status(messages.get(event.reason, ""))

    def on_reorderable_option_list_drag_status(self, event) -> None:
        event.stop()
        account = next((item for item in self.accounts if item.id == event.account_id), None)
        if account is None:
            return
        label = sanitize_text(account.label, max_length=80)
        self.status(f"Moving “{label}” → position {event.target + 1}/{event.total} (Esc cancels)")

    def action_remove(self) -> None:
        if not self.readonly and not self._dragging() and (account := self.selected()):
            self.app.push_screen(
                ConfirmDialog(
                    "Remove account and this tool's secret? External files are never deleted. "
                    "This does not revoke any remote login session."
                ),
                lambda yes: (
                    self._change(lambda: self.service.remove(account), frozenset({account.id}))
                    if yes
                    else None
                ),
            )

    def action_delete_key(self) -> None:
        if (
            not self.readonly
            and not self._dragging()
            and (account := self.selected())
            and account.credential_ref
        ):
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
                                # OpenAI's organization is required, nonsecret
                                # metadata, not credential state (as in the CLI).
                                organization_id=(
                                    account.organization_id
                                    if account.provider == ProviderId.OPENAI_PLATFORM
                                    else None
                                ),
                            ),
                            original=account,
                        ),
                        frozenset({account.id}),
                    )
                    if yes
                    else None
                ),
            )

    async def action_reconnect(self) -> None:
        if self.readonly or self._dragging() or not (account := self.selected()):
            return
        self.status(GUIDANCE[account.provider])
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
        self.query_one("#accounts", OptionList).cancel_drag()
        self.dismiss(None)

    @on(Button.Pressed)
    def buttons(self, event: Button.Pressed) -> None:
        actions = {"add": self.action_add, "edit": self.action_edit, "back": self.action_back}
        if event.button.id in actions:
            actions[event.button.id]()


STORAGE_LABELS = {
    "external_file": "external credential reference",
    "session": "session only",
    "keyring": "stored securely",
    "none": "no credential",
}


def _accepts_invalidate(callback: Callable) -> bool:
    """Whether a host callback takes ``invalidate``; older hosts take the tuple only."""
    try:
        parameters = inspect.signature(callback).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(
        parameter.kind == parameter.VAR_KEYWORD
        or (parameter.name == "invalidate" and parameter.kind != parameter.POSITIONAL_ONLY)
        for parameter in parameters
    )
