"""Account mutation for the HTTP API: one curated path into ``AccountService``.

``AccountOperations`` validates whitelisted JSON bodies (never ``Account.from_dict``
on client input), resolves file references, Grok scopes and discovered organizations (Console,
and the optional Claude subscription prepaid-credits organization) through
short-lived prepare records, and commits through the same ``AccountService`` the
TUI and CLI use. Every writer in the process holds the host's ``account_lock``
across the commit and the host notification, and the lock is taken inside a
shielded task, so a cancelled request still publishes in commit order.

Failures are ``OperationError(status, code)`` only: no message, no input and no
exception context. Secrets never reach a record, a log or a response; Console
secrets live between prepare and save only as an unreferenced ``session:`` entry.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import json
import math
import re
import secrets
import time
from collections import deque
from collections.abc import Awaitable, Callable, Collection, Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Protocol
from uuid import uuid4

from cli_usage_api.accounts import (
    FILE_KINDS,
    MAX_ACCOUNTS,
    MAX_HTTP_SECRET,
    AccountFlowError,
    AccountService,
    allowed_kinds,
    grok_scopes,
    storage_class,
    validate_reference,
    validate_secret,
)
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
    sanitize_text,
)
from cli_usage_api.providers.console import OrganizationChoice
from cli_usage_api.storage import AccountStore, ConfigError, CredentialStore

MAX_LABEL_LENGTH = 1024
# Canonical lowercase UUID text, as ``str(uuid.UUID(...))`` renders account IDs.
UUID_PATTERN = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_LEGACY_GROK_SCOPE = "https://accounts.x.ai/sign-in"
_HEX32 = frozenset("0123456789abcdef")
_SOURCE_KEYS = frozenset(
    {
        "credential_kind",
        "reference",
        "secret",
        "persist",
        "prepare_id",
        "choice_id",
        "organization",
    }
)
_KIND_KEYS = {
    CredentialKind.CLAUDE_CODE_FILE: frozenset({"credential_kind", "reference"}),
    CredentialKind.CODEX_AUTH_FILE: frozenset({"credential_kind", "reference"}),
    CredentialKind.GROK_AUTH_FILE: frozenset({"credential_kind", "prepare_id", "choice_id"}),
    CredentialKind.CONSOLE_SESSION: frozenset(
        {"credential_kind", "prepare_id", "choice_id", "persist"}
    ),
    CredentialKind.MANUAL_BEARER: frozenset({"credential_kind", "secret", "persist"}),
    CredentialKind.OPENAI_PLATFORM_SESSION: frozenset({"credential_kind", "secret", "persist"}),
    CredentialKind.API_KEY: frozenset({"credential_kind", "secret", "persist"}),
}
# Claude subscription read kinds may also carry the optional prepaid-credits
# organization: a prepare record and choice, or ``organization`` "none" / "keep".
_CREDITS_KEYS = frozenset({"prepare_id", "choice_id", "organization"})
_SECRET_KINDS = frozenset(
    {
        CredentialKind.MANUAL_BEARER,
        CredentialKind.OPENAI_PLATFORM_SESSION,
        CredentialKind.API_KEY,
    }
)
OrganizationDiscovery = Callable[[ResolvedCredential], Awaitable[tuple[OrganizationChoice, ...]]]
# Providers whose organization comes from an explicit, read-only discovery.
_DISCOVERY_PROVIDERS = frozenset({ProviderId.CLAUDE_PLATFORM, ProviderId.CLAUDE_SUBSCRIPTION})


def _credits_source(provider: ProviderId, kind: CredentialKind | None) -> bool:
    """Whether this source may select a Claude subscription prepaid-credits organization."""
    return (
        provider == ProviderId.CLAUDE_SUBSCRIPTION
        and kind in READ_CREDENTIAL_KINDS[ProviderId.CLAUDE_SUBSCRIPTION]
    )


# Uncommitted AccountFlowError codes -> (status, fixed error code).
_FLOW_ERRORS = {
    "conflict": (409, "conflict"),
    "secure_store_unavailable": (503, "secure_store_unavailable"),
    "config_unavailable": (503, "config_unavailable"),
    "too_many_accounts": (422, "too_many_accounts"),
    "credential_cleanup_failed": (500, "credential_cleanup_failed"),
}


class AccountHost(Protocol):
    """The process's account owner: ``SnapshotHub`` (standalone) or ``UsageApp``."""

    accounts: tuple[Account, ...]
    account_lock: asyncio.Lock

    async def accounts_changed(
        self, accounts: tuple[Account, ...], *, invalidate: Collection[str] | None = None
    ) -> None: ...

    async def reconnect(self, account_id: str) -> None: ...


class OperationError(Exception):
    """Curated: only (status, code, retry_after); never a message or input."""

    def __init__(self, status: int, code: str, *, retry_after: int | None = None) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.retry_after = retry_after


@dataclass(frozen=True, slots=True)
class MutationResult:
    account: Account | None
    accounts: tuple[Account, ...]
    warning: str | None


@dataclass(slots=True)
class _Prepare:
    """A discovery result awaiting an explicit choice; never stores an exception."""

    id: str
    expires: float
    account_id: str
    original_revision: str | None
    provider: ProviderId
    kind: CredentialKind
    reference: str | None
    choices: dict[str, str] = field(default_factory=dict)
    temp_ref: str | None = None
    timer: asyncio.TimerHandle | None = None
    # Claude credits discovery with a typed bearer: a keyed digest binds the choice
    # to that exact bearer; the bearer itself is not kept after discovery.
    secret_digest: bytes | None = None


@dataclass(slots=True)
class _Source:
    """A validated source submission, before file checks and commit."""

    kind: CredentialKind | None
    ref: str | None
    selector: str | None = None
    organization: str | None = None
    secret: str | None = None
    persist: bool = False
    record: _Prepare | None = None


def _invalid() -> OperationError:
    return OperationError(400, "invalid_request")


def _has_surrogate(value: str) -> bool:
    return any("\ud800" <= char <= "\udfff" for char in value)


def _string(value: object) -> str:
    if type(value) is not str or _has_surrogate(value):
        raise _invalid()
    return value


def _keys(body: object, allowed: Collection[str], required: Collection[str] = ()) -> dict:
    if type(body) is not dict or not set(body) <= set(allowed) or not set(required) <= set(body):
        raise _invalid()
    return body


def _uuid(value: object) -> str:
    text = _string(value)
    if not UUID_PATTERN.fullmatch(text):
        raise _invalid()
    return text


def _revision(value: object) -> str:
    text = _string(value)
    if len(text) != 32 or not set(text) <= _HEX32:
        raise _invalid()
    return text


def _provider(value: object) -> ProviderId:
    try:
        return ProviderId(_string(value))
    except ValueError:
        raise _invalid() from None


def _label(value: object) -> str:
    text = _string(value)
    if len(text) > MAX_LABEL_LENGTH or not sanitize_text(text, max_length=80):
        raise OperationError(422, "invalid_label")
    return text


def _interval(value: object) -> int:
    if type(value) is not int:
        raise _invalid()
    if not 30 <= value <= 3600:
        raise OperationError(422, "invalid_poll_interval")
    return value


def _bool(value: object) -> bool:
    if type(value) is not bool:
        raise _invalid()
    return value


def _kind(value: object, provider: ProviderId) -> CredentialKind:
    try:
        kind = CredentialKind(_string(value))
    except ValueError:
        raise OperationError(422, "invalid_kind") from None
    if kind not in allowed_kinds(provider):
        raise OperationError(422, "invalid_kind")
    return kind


def _secret(kind: CredentialKind, value: object) -> str:
    text = _string(value)
    try:
        return validate_secret(kind, text, maximum=MAX_HTTP_SECRET)
    except AccountFlowError:
        raise OperationError(422, "invalid_secret") from None


def _reference(kind: CredentialKind, value: object) -> str:
    text = _string(value)
    try:
        return validate_reference(kind, text)
    except AccountFlowError:
        raise OperationError(422, "invalid_reference") from None


def _openai_organization(provider: ProviderId, body: dict, current: str | None) -> str | None:
    """The user-entered OpenAI organization (required for that provider only).

    No discovery endpoint is evidenced, so it is typed by the user; it is nonsecret
    but, like every organization ID, never echoed by the API.
    """
    if provider != ProviderId.OPENAI_PLATFORM:
        if "organization_id" in body:
            raise _invalid()
        return None
    if "organization_id" not in body:
        if current is None:
            raise OperationError(422, "organization_required")
        return current
    try:
        return openai_organization_id(_string(body["organization_id"]))
    except DomainError:
        raise OperationError(422, "invalid_organization") from None


def config_view(
    account: Account, *, revision: str | None = None, session_present: bool | None = None
) -> dict[str, Any]:
    """Nonsecret account configuration; never a path, selector, org ID or credential ref."""
    kind = account.credential_kind
    storage = storage_class(account)
    reference = None
    if kind in FILE_KINDS:
        reference = "default" if account.credential_ref == "default" else "custom"
    return {
        "id": account.id,
        "provider": account.provider.value,
        "label": account.label,
        "enabled": account.enabled,
        "poll_interval_seconds": account.poll_interval_seconds,
        "effective_poll_interval_seconds": account.effective_poll_interval_seconds,
        "credential_kind": None if kind is None else kind.value,
        "storage": storage,
        "reference": reference,
        "session_available": session_present if storage == "session" else None,
        "scope_selected": account.credential_selector is not None,
        "organization_selected": account.organization_id is not None,
        "revision": revision,
    }


class AccountOperations:
    """HTTP account writes through ``AccountService`` under the host's ``account_lock``."""

    PREPARE_TTL = 300.0
    MAX_PREPARES = 4
    DISCOVERY_SECONDS = 30.0
    DISCOVERY_COOLDOWN = 10.0
    DISCOVERY_BUDGET = (6, 600.0)
    RECONNECT_SPACING = 30.0
    FILE_READ_CONCURRENCY = 2
    CLOSE_SECONDS = 5.0

    def __init__(
        self,
        *,
        host: AccountHost,
        account_store: AccountStore,
        credential_store: CredentialStore,
        resolver: CredentialResolver,
        console_discovery: (
            OrganizationDiscovery | Mapping[ProviderId, OrganizationDiscovery] | None
        ),
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.host = host
        self.accounts = account_store
        self.credentials = credential_store
        self.resolver = resolver
        self.console_discovery = console_discovery
        self.service = AccountService(account_store, credential_store)
        self._monotonic = monotonic
        self.revision_key = secrets.token_bytes(32)
        self._digest_key = secrets.token_bytes(32)
        self.secure_store_available = False
        self._records: dict[str, _Prepare] = {}
        self._commits: set[asyncio.Future] = set()
        self._discovery = asyncio.Lock()
        self._discovery_starts: deque[float] = deque()
        self._reconnects: dict[str, float] = {}
        self._file_slots = asyncio.Semaphore(self.FILE_READ_CONCURRENCY)

    def discovery_for(self, provider: ProviderId) -> OrganizationDiscovery | None:
        """The explicit organization discovery for ``provider``, if the host supplies one.

        ``console_discovery`` is ``{ProviderId: async callable}`` (Claude Platform and
        Claude subscription), or, for older hosts, the Console callable alone.
        """
        discovery = self.console_discovery
        if isinstance(discovery, Mapping):
            return discovery.get(provider) if provider in _DISCOVERY_PROVIDERS else None
        return discovery if provider == ProviderId.CLAUDE_PLATFORM else None

    def _digest(self, secret: str) -> bytes:
        return hmac.new(self._digest_key, secret.encode("utf-8"), hashlib.sha256).digest()

    async def start(self) -> None:
        """Probe the secure backend type once, off the loop; GET polling never re-probes."""
        await self._refresh_secure()

    async def _refresh_secure(self) -> None:
        self.secure_store_available = bool(
            await asyncio.to_thread(self.credentials.secure_available)
        )

    # --- views ------------------------------------------------------------------

    def revision(self, account: Account) -> str:
        canonical = json.dumps(
            account.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        return hmac.new(self.revision_key, canonical, hashlib.sha256).hexdigest()[:32]

    def config_view(self, account: Account) -> dict[str, Any]:
        present = None
        if storage_class(account) == "session":
            present = self.credentials.session_present(account.credential_ref)
        return config_view(account, revision=self.revision(account), session_present=present)

    # --- infrastructure -----------------------------------------------------------

    async def _file_read(self, fn: Callable[..., Any], *args: Any) -> Any:
        """Run a blocking file probe; a slot is held until its thread returns.

        A cancelled request does not free the slot early, so probes against a hung
        mount stay bounded and cannot exhaust the executor the scheduler shares.
        """
        await self._file_slots.acquire()
        try:
            future = asyncio.ensure_future(asyncio.to_thread(fn, *args))
        except BaseException:
            self._file_slots.release()
            raise

        def done(task: asyncio.Future) -> None:
            self._file_slots.release()
            if not task.cancelled():
                task.exception()

        future.add_done_callback(done)
        return await asyncio.shield(future)

    async def _load(self) -> tuple[Account, ...]:
        try:
            return await asyncio.to_thread(self.accounts.load)
        except ConfigError:
            raise OperationError(503, "config_unavailable") from None

    async def _resync_locked(self) -> None:
        """Publish the stored tuple when it differs; the caller holds ``account_lock``."""
        try:
            current = await asyncio.to_thread(self.accounts.load)
        except Exception:  # noqa: BLE001 - A failed resync still reports the conflict.
            return
        if current != tuple(self.host.accounts):
            with contextlib.suppress(Exception):
                await self.host.accounts_changed(current, invalidate=frozenset())

    async def _conflict(self) -> OperationError:
        async with self.host.account_lock:
            await self._resync_locked()
        return OperationError(409, "conflict")

    async def _existing(self, account_id: str, revision: str) -> Account:
        current = await self._load()
        existing = next((item for item in current if item.id == account_id), None)
        if existing is None:
            raise OperationError(404, "not_found")
        if not hmac.compare_digest(self.revision(existing), revision):
            raise await self._conflict()
        return existing

    async def _commit(
        self,
        work: Callable[[], tuple[Account, ...]],
        invalidate: Collection[str],
        on_commit: Callable[[], None],
        release: Callable[[], None] | None = None,
    ) -> tuple[tuple[Account, ...], str | None]:
        """Commit in a shielded task that owns everything ``work`` needs.

        ``release`` runs only when that task ends, never when the request is
        cancelled, so a secret the commit still has to store stays available to it.
        """
        task = asyncio.ensure_future(self._commit_locked(work, invalidate, on_commit))
        self._commits.add(task)

        def done(future: asyncio.Future) -> None:
            self._commits.discard(future)
            if release is not None:
                release()
            if not future.cancelled():
                future.exception()

        task.add_done_callback(done)
        return await asyncio.shield(task)

    async def _commit_locked(
        self,
        work: Callable[[], tuple[Account, ...]],
        invalidate: Collection[str],
        on_commit: Callable[[], None],
    ) -> tuple[tuple[Account, ...], str | None]:
        # Acquired inside the shielded task: a cancelled request still publishes,
        # and no writer can publish an older tuple after a newer one.
        async with self.host.account_lock:
            try:
                updated = await asyncio.to_thread(work)
                warning = None
            except AccountFlowError as error:
                if error.updated is None:
                    code = error.code
                    if code == "conflict":
                        await self._resync_locked()
                    status, public = _FLOW_ERRORS.get(code, (500, "save_failed"))
                    raise OperationError(status, public) from None
                updated, warning = error.updated, error.code
            on_commit()
            try:
                await self.host.accounts_changed(updated, invalidate=invalidate)
            except Exception:  # noqa: BLE001 - Committed; report, never undo.
                warning = warning or "host_refresh_failed"
            return updated, warning

    def _sweep(self) -> None:
        now = self._monotonic()
        for record in tuple(self._records.values()):
            if record.expires <= now:
                self._discard(record)

    def _discard(self, record: _Prepare) -> None:
        self._records.pop(record.id, None)
        if record.timer is not None:
            record.timer.cancel()
            record.timer = None
        if record.temp_ref is not None:
            # Temporary refs are always in-memory session entries.
            with contextlib.suppress(Exception):
                self.credentials.delete(record.temp_ref)
            record.temp_ref = None

    def _record(self, prepare_id: object) -> _Prepare:
        presented = _string(prepare_id).encode("utf-8")
        found = None
        for key, record in self._records.items():
            if hmac.compare_digest(presented, key.encode("utf-8")):
                found = record
        if found is None:
            raise OperationError(410, "prepare_expired")
        if found.expires <= self._monotonic():
            self._discard(found)
            raise OperationError(410, "prepare_expired")
        return found

    # --- source validation ----------------------------------------------------------

    def _source(
        self,
        source: object,
        provider: ProviderId,
        *,
        account_id: str | None,
        existing: Account | None,
        revision: str | None,
    ) -> _Source:
        if source is None:
            return _Source(kind=None, ref=None)
        _keys(source, _SOURCE_KEYS, required=("credential_kind",))
        kind = _kind(source["credential_kind"], provider)
        credits = _credits_source(provider, kind)
        if not set(source) <= (_KIND_KEYS[kind] | _CREDITS_KEYS if credits else _KIND_KEYS[kind]):
            raise _invalid()
        if kind in (CredentialKind.CLAUDE_CODE_FILE, CredentialKind.CODEX_AUTH_FILE):
            if "reference" in source:
                reference = _reference(kind, source["reference"])
            elif credits and existing is not None and existing.credential_kind == kind:
                # The saved login file (its path is never sent to the page), so a
                # prepaid-credits organization can change without naming the path.
                reference = existing.credential_ref
            else:
                raise OperationError(422, "invalid_reference")
            result = _Source(kind=kind, ref=reference)
        elif kind in _SECRET_KINDS:
            result = self._secret_source(source, kind, existing)
            if provider == ProviderId.CLAUDE_SUBSCRIPTION and not credits:
                # Prepaid credits are read only through a Claude login, never an API key.
                result.organization = None
        else:
            return self._choice_source(source, kind, provider, account_id, existing, revision)
        if credits:
            try:
                self._credits_organization(source, result, provider, account_id, existing, revision)
            except BaseException:
                result.secret = None
                raise
        return result

    @staticmethod
    def _secret_source(source: dict, kind: CredentialKind, existing: Account | None) -> _Source:
        organization = existing.organization_id if existing is not None else None
        if "secret" not in source and "persist" not in source:
            if existing is not None and existing.credential_kind == kind:
                # Same kind without a new secret keeps the saved reference.
                return _Source(
                    kind=kind,
                    ref=existing.credential_ref,
                    selector=existing.credential_selector,
                    organization=organization,
                )
            raise OperationError(422, "secret_required")
        if "secret" not in source:
            raise OperationError(422, "secret_required")
        if "persist" not in source:
            raise OperationError(422, "persist_required")
        persist = _bool(source["persist"])
        secret = _secret(kind, source["secret"])
        # A valid placeholder; AccountService.save replaces it with a fresh ref.
        return _Source(
            kind=kind,
            ref=f"session:{uuid4()}",
            organization=organization,
            secret=secret,
            persist=persist,
        )

    def _credits_organization(
        self,
        source: dict,
        result: _Source,
        provider: ProviderId,
        account_id: str | None,
        existing: Account | None,
        revision: str | None,
    ) -> None:
        """Set the optional Claude subscription prepaid-credits organization.

        Only an explicit choice from a prepare record made for this same login sets
        one; ``"keep"`` (or omission) keeps the saved one only while the login is
        unchanged, and ``"none"`` clears it. Nothing is ever selected implicitly.
        """
        saved = existing.organization_id if existing is not None else None
        unchanged = (
            existing is not None
            and existing.credential_kind == result.kind
            and existing.credential_ref == result.ref
            and result.secret is None
        )
        if "prepare_id" in source or "choice_id" in source:
            if "organization" in source:
                raise _invalid()
            if "prepare_id" not in source or "choice_id" not in source:
                raise OperationError(422, "selection_required")
            record = self._record(source["prepare_id"])
            choice = _string(source["choice_id"])
            if (
                record.provider != provider
                or record.kind != result.kind
                or record.original_revision != revision
                or (account_id is not None and record.account_id != account_id)
            ):
                raise OperationError(410, "prepare_expired")
            # The choice is bound to the exact login that was read.
            if result.secret is not None:
                if record.secret_digest is None or not hmac.compare_digest(
                    record.secret_digest, self._digest(result.secret)
                ):
                    raise OperationError(410, "prepare_expired")
            elif record.secret_digest is not None or record.reference != result.ref:
                raise OperationError(410, "prepare_expired")
            if choice not in record.choices:
                raise OperationError(422, "invalid_choice")
            result.organization = record.choices[choice]
            result.record = record
            return
        if "organization" in source:
            mode = _string(source["organization"])
            if mode == "none":
                result.organization = None
                return
            if mode != "keep":
                raise _invalid()
            if saved is None or not unchanged:
                raise OperationError(422, "organization_reselect_required")
            result.organization = saved
            return
        if saved is not None and not unchanged:
            # A changed login must re-select (or explicitly clear) the organization.
            raise OperationError(422, "organization_reselect_required")
        result.organization = saved

    def _choice_source(
        self,
        source: dict,
        kind: CredentialKind,
        provider: ProviderId,
        account_id: str | None,
        existing: Account | None,
        revision: str | None,
    ) -> _Source:
        if "prepare_id" not in source or "choice_id" not in source:
            raise OperationError(422, "selection_required")
        record = self._record(source["prepare_id"])
        choice = _string(source["choice_id"])
        if (
            record.provider != provider
            or record.kind != kind
            or record.original_revision != revision
            or (account_id is not None and record.account_id != account_id)
        ):
            raise OperationError(410, "prepare_expired")
        if choice not in record.choices:
            raise OperationError(422, "invalid_choice")
        value = record.choices[choice]
        if kind == CredentialKind.GROK_AUTH_FILE:
            return _Source(kind=kind, ref=record.reference, selector=value, record=record)
        if record.temp_ref is None:
            # Organization-only change: the record was made for this account at this
            # revision from its saved Console session, which is kept.
            if "persist" in source or existing is None or existing.credential_ref is None:
                raise _invalid()
            return _Source(
                kind=kind, ref=existing.credential_ref, organization=value, record=record
            )
        if "persist" not in source:
            raise OperationError(422, "persist_required")
        persist = _bool(source["persist"])
        return _Source(
            kind=kind, ref=f"session:{uuid4()}", organization=value, persist=persist, record=record
        )

    async def _check_file(self, draft: Account, source: _Source) -> str | None:
        """Resolve a file source now; only an expired token passes (as a warning)."""
        if draft.credential_kind not in FILE_KINDS:
            return None
        if draft.credential_kind == CredentialKind.GROK_AUTH_FILE:
            try:
                raw = await self._file_read(_read_file, self.resolver._path(draft))
                scopes = grok_scopes(raw)
            except (CredentialResolutionError, AccountFlowError):
                raise OperationError(422, "credential_unavailable") from None
            del raw
            if source.selector not in scopes:
                raise OperationError(410, "prepare_expired")
        try:
            await self._file_read(self.resolver.resolve, draft)
        except CredentialResolutionError as error:
            if error.code == "credential_expired":
                return "credential_expired"
            raise OperationError(422, "credential_unavailable") from None
        return None

    async def _console_secret(self, source: _Source) -> None:
        record = source.record
        if (
            record is None
            or record.temp_ref is None
            or source.kind != CredentialKind.CONSOLE_SESSION
        ):
            return
        try:
            source.secret = await asyncio.to_thread(self.credentials.get, record.temp_ref)
        except Exception:  # noqa: BLE001 - The temporary entry is gone.
            raise OperationError(410, "prepare_expired") from None

    def _consume(self, source: _Source) -> Callable[[], None]:
        record = source.record

        def consume() -> None:
            if record is not None:
                self._discard(record)

        return consume

    async def _write(
        self,
        draft: Account,
        original: Account | None,
        source: _Source | None,
        invalidate: Collection[str],
    ) -> MutationResult:
        expired = None
        held: dict[str, str] = {}
        persist = False

        def on_commit() -> None:
            return None

        if source is not None:
            expired = await self._check_file(draft, source)
            await self._console_secret(source)
            if source.secret is not None:
                held["secret"] = source.secret
            persist = source.persist
            source.secret = None
            on_commit = self._consume(source)
        expects_secret = "secret" in held
        storing = expects_secret and persist

        def work() -> tuple[Account, ...]:
            # The secret leaves this holder exactly once, inside the commit thread.
            # The commit task, not the cancellable request, owns the holder.
            secret = held.pop("secret", None)
            if expects_secret and secret is None:
                # Never commit a placeholder ref with no stored secret behind it.
                raise OperationError(500, "save_failed")
            return self.service.save(draft, original=original, secret=secret, persist=persist)

        try:
            updated, warning = await self._commit(work, invalidate, on_commit, held.clear)
        except OperationError as error:
            if storing and error.code == "secure_store_unavailable":
                await self._refresh_secure()
            raise
        if storing:
            await self._refresh_secure()
        account = next((item for item in updated if item.id == draft.id), None)
        return MutationResult(account=account, accounts=updated, warning=warning or expired)

    # --- operations -------------------------------------------------------------

    async def create(self, body: dict) -> MutationResult:
        self._sweep()
        _keys(
            body,
            {"provider", "label", "poll_interval_seconds", "enabled", "source", "organization_id"},
            required=("provider", "label", "source"),
        )
        provider = _provider(body["provider"])
        label = _label(body["label"])
        interval = _interval(
            body.get("poll_interval_seconds", default_poll_interval_seconds(provider))
        )
        enabled = _bool(body.get("enabled", True))
        openai_organization = _openai_organization(provider, body, None)
        source = self._source(
            body["source"], provider, account_id=None, existing=None, revision=None
        )
        account_id = source.record.account_id if source.record is not None else str(uuid4())
        try:
            draft = Account(
                id=account_id,
                provider=provider,
                label=label,
                credential_kind=source.kind,
                credential_ref=source.ref,
                credential_selector=source.selector,
                organization_id=(
                    openai_organization
                    if provider == ProviderId.OPENAI_PLATFORM
                    else source.organization
                ),
                poll_interval_seconds=interval,
                enabled=enabled,
            )
        except DomainError:
            source.secret = None
            raise _invalid() from None
        return await self._write(draft, None, source, frozenset({account_id}))

    async def update(self, account_id: str, revision: str, body: dict) -> MutationResult:
        self._sweep()
        _keys(body, {"label", "poll_interval_seconds", "enabled", "source", "organization_id"})
        account_id = _uuid(account_id)
        revision = _revision(revision)
        fields: dict[str, Any] = {}
        if "label" in body:
            fields["label"] = _label(body["label"])
        if "poll_interval_seconds" in body:
            fields["poll_interval_seconds"] = _interval(body["poll_interval_seconds"])
        if "enabled" in body:
            fields["enabled"] = _bool(body["enabled"])
        existing = await self._existing(account_id, revision)
        openai_organization = _openai_organization(
            existing.provider, body, existing.organization_id
        )
        source = None
        if "source" in body:
            source = self._source(
                body["source"],
                existing.provider,
                account_id=account_id,
                existing=existing,
                revision=revision,
            )
            fields.update(
                credential_kind=source.kind,
                credential_ref=source.ref,
                credential_selector=source.selector,
                organization_id=source.organization,
            )
        if existing.provider == ProviderId.OPENAI_PLATFORM:
            # Account metadata, required with or without a credential.
            fields["organization_id"] = openai_organization
        try:
            draft = replace(existing, **fields)
        except DomainError:
            if source is not None:
                source.secret = None
            raise _invalid() from None
        # A rename or toggle keeps scheduler state; any source submission (or a new
        # OpenAI organization, which the read is bound to) does not.
        rebind = source is not None or draft.organization_id != existing.organization_id
        invalidate = frozenset({account_id}) if rebind else frozenset()
        return await self._write(draft, existing, source, invalidate)

    async def remove(self, account_id: str, revision: str) -> MutationResult:
        account_id = _uuid(account_id)
        existing = await self._existing(account_id, _revision(revision))
        updated, warning = await self._commit(
            lambda: self.service.remove(existing), frozenset({account_id}), lambda: None
        )
        return MutationResult(account=None, accounts=updated, warning=warning)

    async def reorder(self, body: dict) -> MutationResult:
        _keys(body, {"ids"}, required=("ids",))
        ids = body["ids"]
        if type(ids) is not list or len(ids) > MAX_ACCOUNTS:
            raise _invalid()
        ids = [_uuid(item) for item in ids]
        updated, warning = await self._commit(
            lambda: self.service.reorder(ids), frozenset(), lambda: None
        )
        return MutationResult(account=None, accounts=updated, warning=warning)

    async def reconnect(self, account_id: str) -> None:
        """Explicit re-poll; coalesced per account, never bypassing scheduler embargoes."""
        account = next((item for item in self.host.accounts if item.id == account_id), None)
        if account is None:
            raise OperationError(404, "not_found")
        ids = {item.id for item in self.host.accounts}
        self._reconnects = {key: value for key, value in self._reconnects.items() if key in ids}
        now = self._monotonic()
        last = self._reconnects.get(account_id)
        spacing = max(self.RECONNECT_SPACING, account.effective_poll_interval_seconds)
        if last is not None and now - last < spacing:
            return
        # Reserve before awaiting, so concurrent requests coalesce into one refresh.
        self._reconnects[account_id] = now
        if account.credential_kind is not None:
            try:
                await self._file_read(self.resolver.resolve, account)
            except CredentialResolutionError as error:
                if error.code != "credential_expired":
                    self._unreserve(account_id, now)
                    raise OperationError(422, "credential_unavailable") from None
            except BaseException:
                self._unreserve(account_id, now)
                raise
        await self.host.reconnect(account_id)

    def _unreserve(self, account_id: str, reserved: float) -> None:
        # Nothing was refreshed: a later request may try again at once.
        if self._reconnects.get(account_id) == reserved:
            del self._reconnects[account_id]

    async def prepare(self, body: dict) -> dict[str, Any]:
        """Read Grok scopes or discover organizations; never auto-selects.

        Organizations are discovered for Claude Platform (Console session) and for
        the optional Claude subscription prepaid-credits read (its Claude login).
        """
        self._sweep()
        _keys(
            body,
            {"account_id", "revision", "provider", "credential_kind", "reference", "secret"},
            required=("credential_kind",),
        )
        account_id = body.get("account_id")
        existing = None
        revision = None
        if account_id is not None:
            account_id = _uuid(account_id)
            if "revision" not in body:
                raise _invalid()
            revision = _revision(body["revision"])
        elif body.get("revision") is not None:
            raise _invalid()
        if "provider" in body:
            provider = _provider(body["provider"])
        elif account_id is None:
            raise _invalid()
        kind_value = body["credential_kind"]
        if account_id is not None:
            existing = await self._existing(account_id, revision)
            if "provider" in body and provider != existing.provider:
                raise _invalid()
            provider = existing.provider
        kind = _kind(kind_value, provider)
        if kind == CredentialKind.GROK_AUTH_FILE:
            if "secret" in body:
                raise _invalid()
            return await self._prepare_grok(body, provider, account_id, existing, revision)
        if kind == CredentialKind.CONSOLE_SESSION:
            if "reference" in body:
                raise _invalid()
            return await self._prepare_console(body, provider, account_id, existing, revision)
        if _credits_source(provider, kind):
            return await self._prepare_credits(body, provider, kind, account_id, existing, revision)
        raise OperationError(422, "invalid_kind")

    def _store_record(self, record: _Prepare) -> dict[str, Any]:
        while len(self._records) >= self.MAX_PREPARES:
            self._discard(next(iter(self._records.values())))
        self._records[record.id] = record

        def expire() -> None:
            # Expiry deletes the temporary secret itself, not only at the next write.
            record.timer = None
            if self._records.get(record.id) is record:
                self._discard(record)

        record.timer = asyncio.get_running_loop().call_later(self.PREPARE_TTL, expire)
        return {"prepare_id": record.id, "expires_in": int(self.PREPARE_TTL)}

    def _new_record(
        self,
        provider: ProviderId,
        kind: CredentialKind,
        account_id: str | None,
        revision: str | None,
    ) -> _Prepare:
        return _Prepare(
            id=secrets.token_urlsafe(32),
            expires=self._monotonic() + self.PREPARE_TTL,
            account_id=account_id if account_id is not None else str(uuid4()),
            original_revision=revision,
            provider=provider,
            kind=kind,
            reference=None,
        )

    async def _prepare_grok(
        self,
        body: dict,
        provider: ProviderId,
        account_id: str | None,
        existing: Account | None,
        revision: str | None,
    ) -> dict[str, Any]:
        kind = CredentialKind.GROK_AUTH_FILE
        if "reference" in body:
            reference = _reference(kind, body["reference"])
        elif existing is not None and existing.credential_kind == kind:
            reference = existing.credential_ref
        else:
            raise OperationError(422, "invalid_reference")
        record = self._new_record(provider, kind, account_id, revision)
        record.reference = reference
        draft = Account(
            id=record.account_id,
            provider=provider,
            label="prepare",
            credential_kind=kind,
            credential_ref=reference,
        )
        try:
            raw = await self._file_read(_read_file, self.resolver._path(draft))
            scopes = grok_scopes(raw)
        except (CredentialResolutionError, AccountFlowError):
            # Every resolution and parse failure collapses to one code over HTTP.
            raise OperationError(422, "credential_unavailable") from None
        del raw
        if not scopes:
            raise OperationError(422, "credential_unavailable")
        current = (
            existing.credential_selector
            if existing is not None
            and existing.credential_kind == kind
            and existing.credential_ref == reference
            else None
        )
        choices = []
        for index, scope in enumerate(scopes, 1):
            choice_id = f"c{index}"
            record.choices[choice_id] = scope
            choices.append(
                {
                    "id": choice_id,
                    "label": None,
                    "legacy": scope == _LEGACY_GROK_SCOPE,
                    "current": current is not None and scope == current,
                }
            )
        return {**self._store_record(record), "kind": "grok_scope", "choices": choices}

    def _discovery_retry(self) -> int | None:
        now = self._monotonic()
        limit, window = self.DISCOVERY_BUDGET
        starts = self._discovery_starts
        while starts and starts[0] <= now - window:
            starts.popleft()
        retry = 0.0
        if self._discovery.locked() and starts:
            retry = max(retry, starts[-1] + self.DISCOVERY_SECONDS - now)
        if starts and now - starts[-1] < self.DISCOVERY_COOLDOWN:
            retry = max(retry, starts[-1] + self.DISCOVERY_COOLDOWN - now)
        if len(starts) >= limit:
            retry = max(retry, starts[0] + window - now)
        if self._discovery.locked() or retry > 0:
            return max(1, math.ceil(retry))
        return None

    async def _prepare_console(
        self,
        body: dict,
        provider: ProviderId,
        account_id: str | None,
        existing: Account | None,
        revision: str | None,
    ) -> dict[str, Any]:
        kind = CredentialKind.CONSOLE_SESSION
        secret = None
        if "secret" in body:
            secret = _secret(kind, body["secret"])
        elif existing is None or existing.credential_kind != kind or not existing.credential_ref:
            raise OperationError(422, "secret_required")
        record = self._new_record(provider, kind, account_id, revision)
        if secret is None:
            base = existing
        else:
            base = Account(
                id=record.account_id,
                provider=provider,
                label="prepare",
                credential_kind=kind,
                credential_ref=f"session:{uuid4()}",
            )
        # The Console save does not resend the key: the record keeps it as an
        # unreferenced session entry until save, expiry or eviction.
        return await self._discover(
            record, base, existing, secret, keep_secret=True, result_kind="console_organization"
        )

    async def _prepare_credits(
        self,
        body: dict,
        provider: ProviderId,
        kind: CredentialKind,
        account_id: str | None,
        existing: Account | None,
        revision: str | None,
    ) -> dict[str, Any]:
        """Discover the Claude profile's organization for the optional credits read.

        A typed bearer is resolved through a temporary session entry deleted right
        after resolution; the record keeps only a keyed digest, so the save must
        resend the same bearer. The draft carries no organization: the profile read
        is unscoped.
        """
        record = self._new_record(provider, kind, account_id, revision)
        secret = None
        same_kind = existing is not None and existing.credential_kind == kind
        if kind in FILE_KINDS:
            if "secret" in body:
                raise _invalid()
            if "reference" in body:
                reference = _reference(kind, body["reference"])
            elif same_kind:
                reference = existing.credential_ref
            else:
                raise OperationError(422, "invalid_reference")
        else:
            if "reference" in body:
                raise _invalid()
            if "secret" in body:
                secret = _secret(kind, body["secret"])
                record.secret_digest = self._digest(secret)
                reference = None
            elif same_kind and existing.credential_ref:
                reference = existing.credential_ref
            else:
                raise OperationError(422, "secret_required")
        record.reference = reference
        if same_kind and reference is not None and reference == existing.credential_ref:
            base = replace(existing, organization_id=None)
        else:
            base = Account(
                id=record.account_id,
                provider=provider,
                label="prepare",
                credential_kind=kind,
                credential_ref=reference if reference is not None else f"session:{uuid4()}",
            )
        return await self._discover(
            record, base, existing, secret, keep_secret=False, result_kind="claude_organization"
        )

    async def _discover(
        self,
        record: _Prepare,
        base: Account,
        existing: Account | None,
        secret: str | None,
        *,
        keep_secret: bool,
        result_kind: str,
    ) -> dict[str, Any]:
        """One throttled, explicit discovery; every failure is a curated code."""
        discovery = self.discovery_for(record.provider)
        if discovery is None:
            raise OperationError(502, "discovery_failed")
        retry = self._discovery_retry()
        if retry is not None:
            raise OperationError(409, "discovery_busy", retry_after=retry)
        stored = False
        async with self._discovery:
            self._discovery_starts.append(self._monotonic())
            temporary = None
            try:
                draft = base
                if secret is not None:
                    try:
                        # A session put is an in-memory insert with no I/O. Run it on
                        # the loop: a cancelled thread could store the secret after
                        # the ref was lost, leaving it unreachable by cleanup.
                        temporary = self.credentials.put(record.account_id, secret, persist=False)
                    except Exception:  # noqa: BLE001 - Session puts never contact a keyring.
                        raise OperationError(500, "internal_error") from None
                    finally:
                        secret = None
                    draft = replace(base, credential_ref=temporary)
                    if keep_secret:
                        # Deleted by ``_discard`` together with the record.
                        record.temp_ref = temporary
                        temporary = None
                try:
                    if draft.credential_kind in FILE_KINDS:
                        credential = await self._file_read(self.resolver.resolve, draft)
                    else:
                        credential = await asyncio.to_thread(self.resolver.resolve, draft)
                except CredentialResolutionError:
                    raise OperationError(422, "credential_unavailable") from None
                finally:
                    if temporary is not None:
                        # Claude credits: the bearer is needed only for this one read.
                        with contextlib.suppress(Exception):
                            self.credentials.delete(temporary)
                        temporary = None
                try:
                    async with asyncio.timeout(self.DISCOVERY_SECONDS):
                        organizations = tuple(await discovery(credential))
                except Exception:  # noqa: BLE001 - Redact network/auth/schema errors and timeouts.
                    raise OperationError(502, "discovery_failed") from None
                finally:
                    del credential
                if not organizations:
                    raise OperationError(422, "no_choices")
                choices = []
                for index, choice in enumerate(organizations, 1):
                    choice_id = f"c{index}"
                    record.choices[choice_id] = choice.id
                    label = sanitize_text(choice.label, max_length=120)
                    choices.append(
                        {
                            "id": choice_id,
                            # Discovery falls back to the org UUID for a nameless org;
                            # never send that ID, even as a label.
                            "label": None if not label or choice.label == choice.id else label,
                            "legacy": False,
                            "current": existing is not None
                            and existing.organization_id == choice.id,
                        }
                    )
                result = {**self._store_record(record), "kind": result_kind, "choices": choices}
                stored = True
                return result
            finally:
                if temporary is not None:
                    with contextlib.suppress(Exception):
                        self.credentials.delete(temporary)
                if not stored:
                    self._discard(record)

    async def aclose(self) -> None:
        """Await outstanding commits (bounded) and delete temporary refs; idempotent."""
        pending = {task for task in self._commits if not task.done()}
        if pending:
            with contextlib.suppress(Exception):
                await asyncio.wait(pending, timeout=self.CLOSE_SECONDS)
        for record in tuple(self._records.values()):
            self._discard(record)
