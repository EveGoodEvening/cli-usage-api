"""Production entry point and interactive, secret-safe local account commands."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import sys
import warnings
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from usage_tui.accounts import (
    CONSOLE_SESSION_WARNING,
    FILE_KINDS,
    GUIDANCE,
    KINDS,
    AccountFlowError,
    AccountService,
)
from usage_tui.app import UsageApp
from usage_tui.credentials import CredentialResolutionError, CredentialResolver, _read_file
from usage_tui.domain import (
    READ_CREDENTIAL_KINDS,
    Account,
    CredentialKind,
    DomainError,
    ProviderId,
    sanitize_text,
)
from usage_tui.providers.base import build_providers
from usage_tui.scheduler import Scheduler
from usage_tui.storage import (
    AccountStore,
    ConfigCommittedError,
    ConfigError,
    CredentialError,
    CredentialStore,
)
from usage_tui.transport import Transport, TransportError, _cookie_value, _header_token

PROVIDER_NAMES = {
    "claude-subscription": ProviderId.CLAUDE_SUBSCRIPTION,
    "claude-platform": ProviderId.CLAUDE_PLATFORM,
    "codex-subscription": ProviderId.CODEX_SUBSCRIPTION,
    "grok-subscription": ProviderId.GROK_SUBSCRIPTION,
}


class CommandError(ValueError):
    """A curated error, never arbitrary input or backend exception text."""

    def __init__(self, message: str, code: int = 2) -> None:
        super().__init__(message)
        self.code = code


class Cancelled(Exception):
    """Interactive cancellation before any local transaction."""


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        # argparse normally echoes unrecognized arguments, which may be a pasted secret.
        raise CommandError("Invalid command. Run usage --help for supported arguments.")


class LiveFactory:
    """Own live composition; UsageApp stops schedulers and awaits aclose on exit.

    Transport owns a fresh async HTTP client inside every request, not a persistent
    client. Closing this factory also stops any scheduler created before app startup
    completed, and prevents its reuse after shutdown.
    """

    def __init__(self, credential_store: CredentialStore) -> None:
        self.resolver = CredentialResolver(credential_store)
        self.transport = Transport()
        self.providers = build_providers(self.transport, self.resolver)
        self.console_discovery = self.providers[ProviderId.CLAUDE_PLATFORM].discover_organizations
        self._schedulers: list[Scheduler] = []
        self._closed = False

    def __call__(self, accounts, *, publish) -> Scheduler:
        if self._closed:
            raise RuntimeError("Live services are closed.")
        scheduler = Scheduler(accounts, self.providers, self.resolver, publish=publish)
        self._schedulers.append(scheduler)
        return scheduler

    async def aclose(self) -> None:
        self._closed = True
        for scheduler in self._schedulers:
            await scheduler.stop()
        self._schedulers.clear()


def _parser() -> Parser:
    parser = Parser(prog="usage", description="Read-only terminal account usage dashboard.")
    parser.add_argument(
        "--demo", action="store_true", help="Offline synthetic demo; no live files."
    )
    parser.add_argument("--scenario", choices=("healthy", "errors"), default=None)
    commands = parser.add_subparsers(dest="command")
    accounts = commands.add_parser("accounts", help="Manage local accounts and secure credentials")
    actions = accounts.add_subparsers(dest="action", required=True)
    actions.add_parser("list", help="List local nonsecret account metadata")
    actions.add_parser(
        "migrate-chatgpt-to-codex",
        help="Explicitly migrate all legacy profiles, disabled and detached",
    )
    add = actions.add_parser("add", help="Interactively add an account")
    add.add_argument("--provider", required=True, choices=tuple(PROVIDER_NAMES))
    for name in ("edit", "remove"):
        action = actions.add_parser(name)
        action.add_argument("account_id")
    key = actions.add_parser("key", help="Set or delete a credential without revealing it")
    key_actions = key.add_subparsers(dest="key_action", required=True)
    for name in ("set", "delete"):
        action = key_actions.add_parser(name)
        action.add_argument("account_id")
    return parser


def _tty() -> None:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise CommandError("Interactive account and secret input requires a TTY. Use a terminal.")


def _ask(prompt: str, default: str | None = None) -> str:
    value = input(prompt + (f" [{default}]" if default is not None else "") + ": ")
    if "\x1b" in value:
        raise Cancelled
    return value.strip() or (default if default is not None else "")


def _confirm(prompt: str) -> bool:
    value = _ask(prompt + " [y/N]").casefold()
    if value not in {"", "n", "no", "y", "yes"}:
        raise CommandError("Enter yes or no; no changes were made.")
    return value in {"y", "yes"}


def _choose(prompt: str, choices: list[tuple[str, object]]):
    if not choices:
        raise CommandError("No eligible organizations or scopes found; reconnect and retry.", 3)
    for index, (label, _) in enumerate(choices, 1):
        print(f"  {index}. {sanitize_text(label, max_length=120)}")
    value = _ask(prompt)
    if not value.isascii() or not value.isdigit() or not 1 <= int(value) <= len(choices):
        raise CommandError("Select a listed number explicitly; no changes were made.")
    return choices[int(value) - 1][1]


def _secret(kind: CredentialKind) -> str:
    _tty()
    if kind == CredentialKind.CONSOLE_SESSION:
        print(CONSOLE_SESSION_WARNING)
    if kind == CredentialKind.API_KEY:
        print("API key: local secure storage only; does not enable subscription or balance reads.")
    print("Stored only in the encrypted OS keyring. No CLI session-only persistence is offered.")
    print("No saved value is shown. Escape then Enter or Ctrl-C cancels without changes.")
    with warnings.catch_warnings():
        # Never permit getpass's fallback to echoed input if /dev/tty is unavailable.
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            value = getpass.getpass("New secret (hidden): ")
        except getpass.GetPassWarning:
            raise CommandError("Cannot disable terminal echo; no secret was accepted.") from None
    if "\x1b" in value:
        raise Cancelled
    if not value or len(value) > 1_048_576:
        raise CommandError("Secret must be nonempty and at most 1 MiB; no changes were made.")
    if not _header_token(value) or (
        kind == CredentialKind.CONSOLE_SESSION and not _cookie_value(value)
    ):
        raise CommandError("Invalid credential value; enter only the value, not headers or a HAR.")
    return value


def _source(account: Account, credentials: CredentialStore) -> tuple[Account, str | None]:
    allowed = set(READ_CREDENTIAL_KINDS[account.provider])
    if account.provider != ProviderId.CODEX_SUBSCRIPTION:
        allowed.add(CredentialKind.API_KEY)
    kind = _choose(
        "Credential source number",
        [("No credential / local profile", None)]
        + [(label, kind) for kind, label in KINDS.items() if kind in allowed],
    )
    draft = replace(
        account,
        credential_kind=kind,
        credential_ref=None if kind is None else "default",
        organization_id=None,
        credential_selector=None,
    )
    if kind is None:
        return draft, None
    resolver = CredentialResolver(credentials)
    secret = None
    temporary = None
    try:
        if kind in FILE_KINDS:
            reference = _ask(
                "External credential reference: default or absolute file path", "default"
            )
            if reference != "default" and not Path(reference).is_absolute():
                raise CommandError("Choose default or an absolute external-file path.")
            draft = replace(draft, credential_ref=reference)
            if kind == CredentialKind.GROK_AUTH_FILE:
                payload = json.loads(_read_file(resolver._path(draft)))
                if not isinstance(payload, dict):
                    raise CommandError("Invalid Grok auth file; sign in with Grok again.", 3)
                scopes = [
                    scope
                    for scope in payload
                    if scope == "https://accounts.x.ai/sign-in"
                    or (scope.startswith("https://auth.x.ai::") and scope != "https://auth.x.ai::")
                ]
                selector = _choose(
                    "Select intended Grok scope explicitly",
                    [
                        (f"Grok scope {index + 1}: {scope}", scope)
                        for index, scope in enumerate(scopes)
                    ],
                )
                draft = replace(draft, credential_selector=selector)
        else:
            secret = _secret(kind)
            temporary = credentials.put(account.id, secret, persist=False)
            draft = replace(draft, credential_ref=temporary)
        credential = resolver.resolve(draft)
        if kind == CredentialKind.CONSOLE_SESSION:
            if not _confirm("Discover Console organizations now (read-only connection check)?"):
                raise Cancelled
            transport = Transport()
            providers = build_providers(transport, resolver)
            choices = asyncio.run(
                providers[ProviderId.CLAUDE_PLATFORM].discover_organizations(credential)
            )
            organization = _choose(
                "Select organization explicitly (even for one result)",
                [(choice.label, choice.id) for choice in choices],
            )
            draft = replace(draft, organization_id=organization)
        return draft, secret
    finally:
        if temporary is not None:
            credentials.delete(temporary)


def _metadata(account: Account) -> Account:
    label = _ask("Label", account.label)
    interval = _ask("Poll interval seconds (30..3600)", str(account.poll_interval_seconds))
    if not interval.isascii() or not interval.isdigit() or not 30 <= int(interval) <= 3600:
        raise CommandError("Poll interval must be an integer from 30 to 3600.")
    enabled = _ask("Enabled: yes/no", "yes" if account.enabled else "no").casefold()
    if enabled not in {"yes", "no"}:
        raise CommandError("Enabled must be yes or no.")
    return replace(
        account, label=label, poll_interval_seconds=int(interval), enabled=enabled == "yes"
    )


def _accounts(args) -> int:
    store = AccountStore()
    if args.action == "migrate-chatgpt-to-codex":
        _tty()
        profiles = store.legacy_chatgpt_profiles()
        if not profiles:
            print("No legacy ChatGPT profiles to migrate.")
            return 0
        print("Migrate every listed legacy ChatGPT profile to Codex:")
        for account_id, label in profiles:
            print(f"{account_id}  {sanitize_text(label, max_length=120)}")
        print(
            "All listed profiles will be disabled and their credential references detached. "
            "Old keyring secrets are retained, never read or deleted. Configure a file-backed "
            "Codex login before enabling them; other accounts are unchanged."
        )
        if not _confirm("Migrate the complete listed set?"):
            raise Cancelled
        try:
            store.migrate_legacy_chatgpt_to_codex(
                confirmed_account_ids=tuple(account_id for account_id, _ in profiles)
            )
        except ConfigCommittedError:
            raise CommandError(
                "Migration saved, but crash durability could not be confirmed. Profiles are "
                "disabled and detached; old secrets were retained. Reopen accounts list before retrying.",
                2,
            ) from None
        print("Migration saved. Profiles are disabled and detached; old secrets were retained.")
        return 0
    accounts = store.load()
    if args.action == "list":
        if not accounts:
            print("No accounts configured. Use usage accounts add --provider PROVIDER.")
        for account in accounts:
            kind = account.credential_kind.value if account.credential_kind else "none"
            print(
                f"{account.id}  {account.provider.value}  {sanitize_text(account.label, max_length=120)}"
                f"  {'enabled' if account.enabled else 'disabled'}  source={kind}"
                f"  poll={account.effective_poll_interval_seconds}s"
            )
        return 0
    _tty()
    original = None
    if args.action != "add":
        original = next((item for item in accounts if item.id == args.account_id), None)
        if original is None:
            raise CommandError("Account not found. Use usage accounts list for a local account ID.")
    credentials = CredentialStore()
    service = AccountService(store, credentials)
    if args.action == "remove":
        print("Removes only usage-tui config/owned secrets. External login files are not deleted.")
        print("This does not revoke any remote session.")
        if not _confirm("Remove this account?"):
            raise Cancelled
        service.remove(original)
        print("Account removed.")
        return 0
    if args.action == "key" and args.key_action == "delete":
        print("External login files are never deleted; remote sessions are not revoked.")
        if not _confirm("Delete this account's saved credential/reference?"):
            raise Cancelled
        draft = replace(
            original,
            credential_ref=None,
            credential_kind=None,
            credential_selector=None,
            organization_id=None,
        )
        service.save(draft, original=original)
        print("Credential removed from account.")
        return 0
    draft = original or Account(
        id=str(uuid4()),
        provider=PROVIDER_NAMES[args.provider],
        label="New account",
        credential_ref=None,
    )
    print(GUIDANCE[draft.provider])
    secret = None
    if args.action in {"add", "edit"}:
        draft = _metadata(draft)
    if args.action in {"add", "key"} or _confirm(
        "Change credential source / organization / scope?"
    ):
        draft, secret = _source(draft, credentials)
    if not _confirm("Save account and replace any changed credential/reference?"):
        raise Cancelled
    service.save(draft, original=original, secret=secret, persist=True)
    print(f"Account saved: {draft.id}")
    if draft.credential_kind == CredentialKind.API_KEY:
        print("API key stored securely for local management only; no usage reads enabled.")
    elif secret is not None:
        print("Credential stored securely in OS keyring.")
    elif draft.credential_kind in FILE_KINDS:
        print("External credential reference saved; login file was not modified.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the actual CLI. Errors use fixed safe messages and exit codes 2/3."""
    try:
        args = _parser().parse_args(argv)
        if args.scenario is not None and not args.demo:
            raise CommandError("--scenario requires --demo.")
        if args.command is not None and args.demo:
            raise CommandError("--demo cannot be combined with account commands.")
        if args.command == "accounts":
            return _accounts(args)
        if args.demo:
            UsageApp(mode="demo", scenario=args.scenario or "healthy").run()
        else:
            store = AccountStore()
            accounts = store.load()
            credentials = CredentialStore()
            factory = LiveFactory(credentials)
            UsageApp(
                mode="live",
                accounts=accounts,
                scheduler_factory=factory,
                account_store=store,
                credential_store=credentials,
            ).run()
        return 0
    except SystemExit as error:
        return int(error.code or 0)
    except (Cancelled, KeyboardInterrupt, EOFError):
        print("Cancelled; no pending account changes were saved.")
        return 0
    except CommandError as error:
        print(str(error), file=sys.stderr)
        return error.code
    except AccountFlowError as error:
        # The reusable service distinguishes a committed write from rejection.
        # Its curated messages may be printed, but never its arbitrary context.
        print(str(error), file=sys.stderr)
        if isinstance(error.__context__, CredentialError):
            print(
                "CLI secrets require encrypted OS-keyring persistence. Unlock the keyring "
                "or use the TUI for explicit session-only mode.",
                file=sys.stderr,
            )
        return 2 if isinstance(error.__context__, (ConfigError, AccountFlowError)) else 3
    except ConfigError:
        print(
            "Cannot read/write config. Check private directory/file permissions and schema. "
            "For legacy ChatGPT profiles run usage accounts migrate-chatgpt-to-codex in a terminal; "
            "migration disables and detaches profiles and retains old secrets.",
            file=sys.stderr,
        )
        return 2
    except DomainError:
        print(
            "Invalid account or credential metadata; no pending changes were saved.",
            file=sys.stderr,
        )
        return 2
    except (CredentialError, CredentialResolutionError, TransportError):
        print(
            "Connection/credential failed. Check private import-file permissions, official login "
            "and source kind; unlock the encrypted OS keyring. CLI secrets require secure "
            "persistence; use the TUI for explicit session-only mode.",
            file=sys.stderr,
        )
        return 3
    except Exception:  # noqa: BLE001 - Never print arbitrary backend/provider/input exceptions.
        print(
            "Operation failed safely. Check configuration, secure keyring and reconnect guidance.",
            file=sys.stderr,
        )
        return 3
