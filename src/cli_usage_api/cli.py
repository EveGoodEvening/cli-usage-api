"""Production entry point and interactive, secret-safe local account commands."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import getpass
import sys
import warnings
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from cli_usage_api import api as api_server
from cli_usage_api import debuglog, keepalive
from cli_usage_api.accounts import (
    CONSOLE_SESSION_WARNING,
    FILE_KINDS,
    GUIDANCE,
    KINDS,
    AccountFlowError,
    AccountService,
    allowed_kinds,
    grok_scopes,
    validate_reference,
    validate_secret,
)
from cli_usage_api.api import DEFAULT_HOST, DEFAULT_PORT, OriginError, is_loopback_host
from cli_usage_api.app import UsageApp
from cli_usage_api.credentials import (
    CredentialResolutionError,
    CredentialResolver,
    _read_file,
)
from cli_usage_api.domain import (
    Account,
    CredentialKind,
    DomainError,
    ProviderId,
    sanitize_text,
)
from cli_usage_api.operations import AccountOperations
from cli_usage_api.providers.base import build_providers
from cli_usage_api.scheduler import Scheduler
from cli_usage_api.storage import (
    MAX_API_TOKENS,
    AccountStore,
    ApiTokenLimitError,
    ApiTokenStore,
    ConfigCommittedError,
    ConfigError,
    CredentialError,
    CredentialStore,
    SettingsStore,
)
from cli_usage_api.transport import Transport, TransportError

PROVIDER_NAMES = {
    "claude-subscription": ProviderId.CLAUDE_SUBSCRIPTION,
    "claude-platform": ProviderId.CLAUDE_PLATFORM,
    "codex-subscription": ProviderId.CODEX_SUBSCRIPTION,
    "grok-subscription": ProviderId.GROK_SUBSCRIPTION,
}


# AccountFlowError codes: exit 2 (config/conflict) and the keyring hint set match
# the earlier context-based mapping, so CLI messages and exit codes are unchanged.
_CONFIG_EXIT_CODES = frozenset({"conflict", "config_unavailable", "committed_uncertain"})
_KEYRING_HINT_CODES = frozenset(
    {"secure_store_unavailable", "cleanup_failed", "credential_cleanup_failed"}
)


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


def _keepalive_arguments(parser: argparse.ArgumentParser, *, prefix: str) -> None:
    # Subcommand destinations are prefixed: a subparser's defaults would otherwise
    # overwrite the same-named dashboard options in the shared namespace.
    parser.add_argument(
        "--keepalive",
        dest=prefix + "keepalive",
        action="store_true",
        help="Live only: run usage-keepalive in this process so official CLIs renew their "
        "own file-backed logins (log: ~/.local/state/usage-keepalive/keepalive.log).",
    )
    parser.add_argument(
        "--keepalive-cli",
        dest=prefix + "keepalive_cli",
        action="append",
        choices=tuple(keepalive.LOGIN_PATHS),
        metavar="NAME",
        default=None,
        help="With --keepalive: login to keep alive (repeatable; default: every CLI with a "
        f"login file). One of: {', '.join(keepalive.LOGIN_PATHS)}.",
    )
    parser.add_argument(
        "--keepalive-claude-mode",
        dest=prefix + "keepalive_claude_mode",
        choices=tuple(keepalive.CLAUDE_MODES),
        default=None,
        help="With --keepalive: hybrid (default; auth status, then a minimal Haiku request "
        "only if needed), status or model.",
    )


def _parser() -> Parser:
    parser = Parser(prog="usage", description="Read-only terminal account usage dashboard.")
    parser.add_argument(
        "--demo", action="store_true", help="Offline synthetic demo; no live files."
    )
    parser.add_argument("--scenario", choices=("healthy", "errors"), default=None)
    parser.add_argument(
        "--debug-log",
        metavar="PATH",
        default=None,
        help="Live dashboard only: append JSON-lines provider responses/snapshots to a "
        "private file. Contains raw response bodies; secrets are redacted best-effort.",
    )
    parser.add_argument(
        "--debug-provider",
        action="append",
        choices=tuple(PROVIDER_NAMES),
        metavar="PROVIDER",
        default=None,
        help="Limit --debug-log to this provider (repeatable; default: all). "
        f"One of: {', '.join(PROVIDER_NAMES)}.",
    )
    parser.add_argument(
        "--api",
        action="store_true",
        help="Also serve the HTTP API from this dashboard process; it reads the same "
        "snapshots the TUI shows (including session-only credentials entered here), and "
        "accounts can be managed over HTTP unless --read-only.",
    )
    parser.add_argument(
        "--api-host", default=None, help=f"With --api: bind host (default {DEFAULT_HOST})"
    )
    parser.add_argument(
        "--api-port", default=None, help=f"With --api: bind port 1..65535 (default {DEFAULT_PORT})"
    )
    parser.add_argument(
        "--allow-origin",
        dest="dashboard_allow_origins",
        action="append",
        default=None,
        metavar="ORIGIN",
        help="With --api: exact browser origin allowed by CORS (repeatable).",
    )
    parser.add_argument(
        "--trust-proxy",
        dest="dashboard_trust_proxy",
        action="store_true",
        help="With --api: use the right-most X-Forwarded-For entry for failed-auth limiting.",
    )
    parser.add_argument(
        "--read-only",
        dest="dashboard_read_only",
        action="store_true",
        help="With --api: disable account changes over HTTP.",
    )
    _keepalive_arguments(parser, prefix="")
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
    api = commands.add_parser("api", help="HTTP API for usage data and account management")
    api_actions = api.add_subparsers(dest="api_action", required=True)
    serve = api_actions.add_parser(
        "serve",
        help="Serve usage JSON (headless). Account changes made over the API apply "
        "immediately; changes from `usage accounts` in another process apply on the next "
        "API write or restart.",
    )
    serve.add_argument("--host", default=DEFAULT_HOST, help=f"Bind host (default {DEFAULT_HOST})")
    serve.add_argument(
        "--port", default=str(DEFAULT_PORT), help=f"Bind port 1..65535 (default {DEFAULT_PORT})"
    )
    serve.add_argument(
        "--allow-origin",
        dest="allow_origins",
        action="append",
        default=None,
        metavar="ORIGIN",
        help="Exact browser origin scheme://host[:port] allowed by CORS (repeatable).",
    )
    serve.add_argument(
        "--demo", dest="serve_demo", action="store_true", help="Offline synthetic data only."
    )
    serve.add_argument(
        "--scenario", dest="serve_scenario", choices=("healthy", "errors"), default=None
    )
    serve.add_argument(
        "--trust-proxy",
        action="store_true",
        help="Use the right-most X-Forwarded-For entry as the client address for "
        "failed-auth limiting (only behind a trusted reverse proxy).",
    )
    serve.add_argument(
        "--read-only",
        dest="serve_read_only",
        action="store_true",
        help="Disable account changes over HTTP (demo is always read-only).",
    )
    serve.add_argument("--debug-log", dest="serve_debug_log", metavar="PATH", default=None)
    serve.add_argument(
        "--debug-provider",
        dest="serve_debug_provider",
        action="append",
        choices=tuple(PROVIDER_NAMES),
        metavar="PROVIDER",
        default=None,
    )
    _keepalive_arguments(serve, prefix="serve_")
    token = api_actions.add_parser("token", help="Manage API bearer tokens")
    token_actions = token.add_subparsers(dest="token_action", required=True)
    create = token_actions.add_parser("create", help="Create a token; it is shown only once")
    create.add_argument("--label", default=None)
    token_actions.add_parser("list", help="List token IDs, labels and creation times")
    revoke = token_actions.add_parser("revoke", help="Revoke a token by ID")
    revoke.add_argument("token_id")
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
    try:
        return validate_secret(kind, value)
    except AccountFlowError as error:
        raise CommandError(str(error)) from None


def _source(account: Account, credentials: CredentialStore) -> tuple[Account, str | None]:
    kind = _choose(
        "Credential source number",
        [("No credential / local profile", None)]
        + [(KINDS[kind], kind) for kind in allowed_kinds(account.provider)],
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
            try:
                reference = validate_reference(kind, reference)
            except AccountFlowError as error:
                raise CommandError(str(error)) from None
            draft = replace(draft, credential_ref=reference)
            if kind == CredentialKind.GROK_AUTH_FILE:
                try:
                    scopes = grok_scopes(_read_file(resolver._path(draft)))
                except AccountFlowError:
                    raise CommandError(
                        "Invalid Grok auth file; sign in with Grok again.", 3
                    ) from None
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
        print(
            "Removes only cli-usage-api config/owned secrets. External login files are not deleted."
        )
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


def _configure_debug(path: str, providers: list[str] | None) -> None:
    try:
        debuglog.configure(
            path,
            None if providers is None else {PROVIDER_NAMES[name] for name in providers},
        )
    except debuglog.DebugLogError:
        raise CommandError(
            "Cannot open debug log. Its directory must exist; the file must be "
            "your own regular file (not a symlink) without group/other access."
        ) from None


def _api_tokens(args) -> int:
    store = ApiTokenStore()
    if args.token_action == "list":
        tokens = store.load()
        if not tokens:
            print("No API tokens. Create one in a terminal with usage api token create.")
        for item in tokens:
            print(f"{item.id}  {item.label}  created={item.created_at}")
        return 0
    _tty()
    if args.token_action == "create":
        try:
            token, record = store.create(args.label)
        except ApiTokenLimitError:
            raise CommandError(
                f"At most {MAX_API_TOKENS} API tokens are supported; no token was created. "
                "Revoke unused tokens with usage api token revoke ID "
                "(see usage api token list)."
            ) from None
        print(f"API token created: id={record.id}  label={record.label}")
        print("Copy it now; it is shown only once and only its SHA-256 digest is stored.")
        print(token)
        print("Use it as: Authorization: Bearer <token>. Revoke with usage api token revoke ID.")
        print(
            "This token can add, edit and remove accounts unless the server runs with --read-only."
        )
        return 0
    token_id = args.token_id
    if not any(item.id == token_id for item in store.load()):
        raise CommandError("API token not found. Use usage api token list for a token ID.")
    if not _confirm("Revoke this API token? Running servers stop accepting it within seconds."):
        raise Cancelled
    if not store.revoke(token_id):
        raise CommandError("API token not found. Use usage api token list for a token ID.")
    print("API token revoked.")
    return 0


class ApiPlan:
    """Validated API endpoint and authentication policy, shared by both API modes."""

    def __init__(
        self,
        host: str,
        port_text: str,
        allow_origins: Sequence[str] | None,
        *,
        demo: bool,
        trust_proxy: bool,
        read_only: bool = False,
        options: tuple[str, str] = ("--host", "--port"),
    ) -> None:
        host_option, port_option = options
        if (
            not host
            or len(host) > 253
            or any(ord(char) <= 32 or ord(char) == 127 for char in host)
            or "/" in host
        ):
            raise CommandError(f"{host_option} must be a hostname or IP address.")
        if not port_text.isascii() or not port_text.isdigit() or not 1 <= int(port_text) <= 65535:
            raise CommandError(f"{port_option} must be an integer from 1 to 65535.")
        try:
            self.origins = tuple(
                dict.fromkeys(api_server.normalize_origin(item) for item in allow_origins or ())
            )
        except OriginError:
            raise CommandError(
                "--allow-origin must be an exact http(s) origin like https://app.example.com "
                "(scheme://host[:port]; no path, query, fragment or wildcard)."
            ) from None
        self.host = host
        self.port = int(port_text)
        self.port_option = port_option
        self.host_option = host_option
        self.demo = demo
        self.trust_proxy = trust_proxy
        # Demo is always read-only; live writes are on unless --read-only.
        self.read_only = read_only or demo
        self.loopback = is_loopback_host(host)
        self.token_store: ApiTokenStore | None = None
        self.allow_unauthenticated = False

    def authorize(self) -> None:
        """Apply the token policy; live mode always requires at least one token."""
        token_store = ApiTokenStore()
        has_tokens = bool(token_store.load())
        # An unauthenticated loopback demo stays open only while zero tokens exist.
        self.allow_unauthenticated = self.demo and self.loopback
        if not has_tokens and not self.allow_unauthenticated:
            raise CommandError(
                "No API tokens configured; refusing to serve unauthenticated data. "
                "Create one in a terminal with usage api token create."
            )
        self.token_store = token_store

    def create_app(self, hub, operations: AccountOperations | None = None) -> api_server.UsageApi:
        return api_server.create_app(
            hub,
            self.token_store,
            self.origins,
            trust_proxy=self.trust_proxy,
            allow_unauthenticated=self.allow_unauthenticated,
            operations=None if self.read_only or self.demo else operations,
        )

    def bind(self):
        try:
            return api_server.bind_socket(self.host, self.port)
        except api_server.BindError as error:
            if isinstance(error, api_server.AddressInUseError):
                raise CommandError(
                    "Cannot listen: the requested host/port is already in use. "
                    f"Stop the other server or choose another {self.port_option}.",
                    3,
                ) from None
            raise CommandError(
                f"Cannot listen on the requested host/port. Check that {self.host_option} is "
                "a local address of this machine (localhost binds 127.0.0.1).",
                3,
            ) from None

    @property
    def address(self) -> str:
        shown = "127.0.0.1" if self.host.casefold() == "localhost" else self.host
        shown = f"[{shown}]" if ":" in shown and not shown.startswith("[") else shown
        return f"{shown}:{self.port}"


def _stamp(message: str) -> str:
    return f"{datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')} {message}"


class KeepaliveService:
    """usage-keepalive in the host event loop; logs to its private file only.

    ``echo`` (headless api serve) also prints log lines to stdout. In the dashboard,
    an ``ALERT`` line raises a warning notification instead; nothing is written to
    the terminal the TUI owns. As a ``UsageApp`` observer, account changes replace
    the protected Grok scopes. ``stop`` requests a cooperative stop (no new target
    or command; the in-flight official CLI's process group is killed) and waits for
    the worker thread; ``join`` waits without a bound, so the instance lock is
    released only after the worker has returned.
    """

    STOP_SECONDS = 10.0

    def __init__(
        self,
        names: Sequence[str] | None,
        claude_mode: str | None,
        accounts: Sequence[Account],
        *,
        echo: bool,
        log_file: Callable[[str], None] | None = None,
    ) -> None:
        self._file = log_file if log_file is not None else keepalive.file_logger()
        self._echo = echo
        self._alert: Callable[[str], None] | None = None
        # Resolved once here: later account changes are matched lexically, so
        # token-supplied references never cause filesystem lookups on the loop.
        self._grok_defaults = keepalive.grok_default_forms()
        # References already saved at startup are resolved now, before the loop runs,
        # so a symlinked or unnormalized saved path keeps its protection.
        self._grok_resolved = keepalive.resolve_grok_references(accounts)
        try:
            self.keepalive = keepalive.build(
                names,
                claude_mode or "hybrid",
                log=self.log,
                grok_protected_scopes=keepalive.grok_protected_scopes(
                    accounts, default_forms=self._grok_defaults, resolved=self._grok_resolved
                ),
            )
        except keepalive.KeepaliveError as error:
            raise CommandError(str(error)) from None
        self.names = tuple(target.name for target in self.keepalive.targets)
        self._stop: asyncio.Event | None = None
        self._task: asyncio.Task | None = None
        self._stopped_logged = False

    def publish(self, snapshot) -> None:
        """Observer hook; snapshots are irrelevant to keepalive."""

    def accounts_changed(self, accounts: Sequence[Account]) -> None:
        """Observer hook: protect the selectors the changed accounts now read."""
        self.keepalive.set_protected(
            "grok",
            keepalive.grok_protected_scopes(
                tuple(accounts), default_forms=self._grok_defaults, resolved=self._grok_resolved
            ),
        )

    @property
    def note(self) -> str:
        if self._task is None:
            return ""
        return "keepalive " + ",".join(self.names)

    def log(self, message: str) -> None:
        # Called from keepalive's worker thread as well as the loop thread.
        self._file(message)
        if self._echo:
            print(_stamp(message), flush=True)
        alert = self._alert
        if alert is not None and "ALERT" in message:
            alert(message)

    async def start(self, host=None) -> None:
        if host is not None:
            loop = asyncio.get_running_loop()
            text = sanitize_text

            def alert(message: str) -> None:
                with contextlib.suppress(RuntimeError):
                    loop.call_soon_threadsafe(
                        lambda: host.notify(
                            text(message, max_length=200),
                            title="keepalive",
                            severity="warning",
                            timeout=60,
                        )
                    )

            self._alert = alert
        self._stop = asyncio.Event()
        self.log("keepalive started for " + ", ".join(self.names))
        self._task = asyncio.create_task(
            keepalive.run_async(self.keepalive, self._stop), name="usage-keepalive"
        )

    async def stop(self) -> None:
        self._alert = None
        # Cancelling the to_thread await would not stop the worker thread: ask it
        # to stop (killing the in-flight CLI) and wait for it to actually return.
        self.keepalive.request_stop()
        if self._task is None:
            return
        self._stop.set()
        try:
            await asyncio.wait_for(asyncio.shield(self._task), self.STOP_SECONDS)
        except TimeoutError:
            self._task.cancel()
            with contextlib.suppress(BaseException):
                await self._task
        except Exception:  # noqa: BLE001, S110 - Shutdown continues; no detail is printed.
            pass
        if self.keepalive.wait_idle(0):
            self._log_stopped()
        else:
            self.log("keepalive stopping; waiting for the running command to end")

    def join(self) -> None:
        """Block until the worker has returned (called before releasing the lock)."""
        self.keepalive.request_stop()
        self.keepalive.wait_idle()
        if self._task is not None:
            self._log_stopped()

    def _log_stopped(self) -> None:
        if not self._stopped_logged:
            self._stopped_logged = True
            self.log("keepalive stopped")


@contextlib.contextmanager
def _keepalive_lock(service: KeepaliveService):
    """Hold the instance lock until ``service``'s worker thread has returned."""
    try:
        lock = keepalive.InstanceLock().__enter__()
    except keepalive.KeepaliveError as error:
        raise CommandError(str(error)) from None
    try:
        yield
    finally:
        try:
            service.join()
        finally:
            lock.__exit__(None, None, None)


def _serve(args) -> int:
    plan = ApiPlan(
        args.host,
        args.port,
        args.allow_origins,
        demo=args.serve_demo,
        trust_proxy=args.trust_proxy,
        read_only=args.serve_read_only,
    )
    if args.serve_scenario is not None and not args.serve_demo:
        raise CommandError("--scenario requires --demo.")
    if args.serve_debug_provider is not None and args.serve_debug_log is None:
        raise CommandError("--debug-provider requires --debug-log.")
    if args.serve_debug_log is not None and args.serve_demo:
        raise CommandError("--debug-log cannot be combined with --demo.")
    _check_keepalive_options(
        args.serve_keepalive,
        args.serve_keepalive_cli,
        args.serve_keepalive_claude_mode,
        demo=args.serve_demo,
    )
    plan.authorize()
    with contextlib.ExitStack() as stack:
        services = []
        operations = None
        # Branch demo before constructing any live store, resolver, provider or transport.
        if args.serve_demo:
            hub = api_server.demo_hub(args.serve_scenario or "healthy")
        else:
            if args.serve_debug_log is not None:
                _configure_debug(args.serve_debug_log, args.serve_debug_provider)
            store = AccountStore()
            accounts = store.load()
            keepalive_service = None
            if args.serve_keepalive:
                keepalive_service = KeepaliveService(
                    args.serve_keepalive_cli,
                    args.serve_keepalive_claude_mode,
                    accounts,
                    echo=True,
                )
                stack.enter_context(_keepalive_lock(keepalive_service))
                services.append(keepalive_service)
            # One credential store: the resolver reads session secrets the API stores.
            credentials = CredentialStore()
            factory = LiveFactory(credentials)
            hub = api_server.live_hub(accounts, factory)
            if keepalive_service is not None:
                # API account writes update the protected Grok scopes.
                hub.add_observer(keepalive_service)
            if not plan.read_only:
                operations = AccountOperations(
                    host=hub,
                    account_store=store,
                    credential_store=credentials,
                    resolver=factory.resolver,
                    console_discovery=factory.console_discovery,
                )
        app = plan.create_app(hub, operations)
        try:
            sock = plan.bind()
        except CommandError:
            if hub.mode == "live":
                asyncio.run(hub.stop())
            raise
        return _serve_bound(args, plan, hub, app, sock, services)


def _serve_bound(args, plan: ApiPlan, hub, app, sock, services) -> int:
    origins, loopback = plan.origins, plan.loopback
    print(f"usage api serving {hub.mode} data on http://{plan.address} (Ctrl-C to stop).")
    if app.auth_mode == "none":
        print(
            "NOTICE: no API tokens configured; demo data is readable without authentication "
            "on this loopback address only until a token is created (then a bearer token "
            "is required within seconds)."
        )
    else:
        print("Bearer token required. Token revocation applies within seconds.")
    if hub.mode == "live":
        writable = app.operations is not None
        if writable:
            print(
                f"{len(hub.accounts)} account(s) loaded. Account changes over the API are "
                "ENABLED for every API token (use --read-only to disable)."
            )
        else:
            print(f"{len(hub.accounts)} account(s) loaded. API is read-only (--read-only).")
        print("Credentials are resolved by the server process only.")
        if not hub.accounts:
            if writable:
                print(
                    "No accounts configured. Add accounts in the web UI or with usage accounts "
                    "add --provider ..."
                )
            else:
                print(
                    "No accounts configured. Add accounts with usage accounts add --provider "
                    "..., then restart serve."
                )
    if origins:
        print("Allowed browser origins: " + ", ".join(origins))
    elif not loopback:
        print(
            "NOTICE: no --allow-origin configured; browsers on other origins are blocked by "
            "CORS (curl and same-origin clients still work with a token)."
        )
    if services:
        print(
            "keepalive running for "
            + ", ".join(services[0].names)
            + "; log ~/.local/state/usage-keepalive/keepalive.log"
        )
    try:
        api_server.run(app, sock, services)
    except api_server.ServeError:
        raise CommandError("API server failed to start its usage source.", 3) from None
    print("usage api stopped.")
    return 0


def _check_keepalive_options(
    enabled: bool, names: list[str] | None, claude_mode: str | None, *, demo: bool
) -> None:
    if (names is not None or claude_mode is not None) and not enabled:
        raise CommandError("--keepalive-cli and --keepalive-claude-mode require --keepalive.")
    if enabled and demo:
        raise CommandError("--keepalive cannot be combined with --demo; it is live only.")


def _dashboard(args) -> int:
    """The TUI, optionally hosting the API and keepalive in the same event loop.

    Every refusal (validation, tokens, keepalive lock/logins, bind) happens before
    the TUI takes the terminal, so errors print normally and exit 2/3.
    """
    _check_keepalive_options(
        args.keepalive, args.keepalive_cli, args.keepalive_claude_mode, demo=args.demo
    )
    plan = None
    if args.api:
        plan = ApiPlan(
            args.api_host if args.api_host is not None else DEFAULT_HOST,
            args.api_port if args.api_port is not None else str(DEFAULT_PORT),
            args.dashboard_allow_origins,
            demo=args.demo,
            trust_proxy=args.dashboard_trust_proxy,
            read_only=args.dashboard_read_only,
            options=("--api-host", "--api-port"),
        )
        plan.authorize()
    settings = SettingsStore()
    with contextlib.ExitStack() as stack:
        services = []
        operations = None
        if args.demo:
            app = UsageApp(
                mode="demo", scenario=args.scenario or "healthy", settings_store=settings
            )
        else:
            if args.debug_log is not None:
                _configure_debug(args.debug_log, args.debug_provider)
            store = AccountStore()
            accounts = store.load()
            keepalive_service = None
            if args.keepalive:
                keepalive_service = KeepaliveService(
                    args.keepalive_cli, args.keepalive_claude_mode, accounts, echo=False
                )
                services.append(keepalive_service)
                stack.enter_context(_keepalive_lock(keepalive_service))
            credentials = CredentialStore()
            factory = LiveFactory(credentials)
            app = UsageApp(
                mode="live",
                accounts=accounts,
                scheduler_factory=factory,
                account_store=store,
                credential_store=credentials,
                settings_store=settings,
            )
            if keepalive_service is not None:
                # Account edits in the TUI update the protected Grok scopes.
                app.add_observer(keepalive_service)
            if plan is not None and not plan.read_only:
                # Web writes go through the app (its lock, scheduler and manager).
                operations = AccountOperations(
                    host=app,
                    account_store=store,
                    credential_store=credentials,
                    resolver=factory.resolver,
                    console_discovery=factory.console_discovery,
                )
        if plan is not None:
            api_server.harden_process()
            # One app hub mirrors what the TUI shows: same scheduler, same credentials.
            usage_api = plan.create_app(api_server.AppHub.attach(app), operations)
            sock = plan.bind()
            stack.callback(sock.close)
            services.append(api_server.EmbeddedServer(usage_api, sock, address=plan.address))
        for service in services:
            app.add_service(service)
        app.run()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the actual CLI. Errors use fixed safe messages and exit codes 2/3."""
    try:
        args = _parser().parse_args(argv)
        if args.scenario is not None and not args.demo:
            raise CommandError("--scenario requires --demo.")
        if args.command is not None and args.demo:
            raise CommandError("--demo cannot be combined with account commands.")
        if args.debug_provider is not None and args.debug_log is None:
            raise CommandError("--debug-provider requires --debug-log.")
        if args.debug_log is not None and args.demo:
            raise CommandError("--debug-log cannot be combined with --demo.")
        if args.debug_log is not None and args.command is not None:
            raise CommandError(
                "--debug-log applies only to the live dashboard; use usage api serve --debug-log."
            )
        dashboard_api_options = (
            args.api_host is not None
            or args.api_port is not None
            or args.dashboard_allow_origins is not None
            or args.dashboard_trust_proxy
            or args.dashboard_read_only
        )
        keepalive_options = (
            args.keepalive
            or args.keepalive_cli is not None
            or args.keepalive_claude_mode is not None
        )
        if args.command is not None and (args.api or dashboard_api_options or keepalive_options):
            raise CommandError(
                "--api, --allow-origin, --trust-proxy, --read-only and --keepalive options "
                "before a command apply only to the dashboard; use usage api serve options "
                "instead."
            )
        if dashboard_api_options and not args.api:
            raise CommandError(
                "--api-host, --api-port, --allow-origin, --trust-proxy and --read-only "
                "require --api."
            )
        if args.command == "accounts":
            return _accounts(args)
        if args.command == "api":
            return _serve(args) if args.api_action == "serve" else _api_tokens(args)
        return _dashboard(args)
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
        if error.code == "failed":
            # Unclassified host errors keep the original context-based mapping.
            keyring_hint = isinstance(error.__context__, CredentialError)
            config = isinstance(error.__context__, (ConfigError, AccountFlowError))
        else:
            keyring_hint = error.code in _KEYRING_HINT_CODES
            config = error.code in _CONFIG_EXIT_CODES
        if keyring_hint:
            print(
                "CLI secrets require encrypted OS-keyring persistence. Unlock the keyring "
                "or use the TUI for explicit session-only mode.",
                file=sys.stderr,
            )
        return 2 if config else 3
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
    finally:
        debuglog.close()
