"""Bounded event-loop polling and presentation-only freshness calculations.

Clock.sleep uses monotonic elapsed time. Wall time is used only for observations
and converting a server retry deadline once, never to schedule periodic work.
Periodic jitter adds a bounded offset to the interval so exact endpoint deadlines
remain predictable without tolerances that could start a provider early.
Providers/transports are borrowed; their owner remains responsible for closing them.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Protocol

from cli_usage_api import debuglog
from cli_usage_api.accounts import credential_identity
from cli_usage_api.credentials import CredentialResolutionError, CredentialResolver
from cli_usage_api.domain import (
    POLL_FLOOR_SECONDS,
    Account,
    Diagnostic,
    FetchState,
    Metric,
    MetricState,
    ProviderId,
    Snapshot,
    SourceKind,
    SourceRef,
    TransportError,
    utc_datetime,
)
from cli_usage_api.providers.base import Provider

_SUCCESS = frozenset({FetchState.OK, FetchState.PARTIAL})
_SUSPEND = frozenset(
    {FetchState.AUTH_REQUIRED, FetchState.PERMISSION_DENIED, FetchState.UNCONFIGURED}
)


class Clock(Protocol):
    def now(self) -> datetime: ...

    def monotonic(self) -> float: ...

    async def sleep(self, seconds: float) -> None: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic(self) -> float:
        return time.monotonic()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


@dataclass(frozen=True, slots=True)
class Freshness:
    age_seconds: float | None
    attempted_age_seconds: float
    stale: bool
    reset_passed: bool
    last_known: bool


def freshness(
    snapshot: Snapshot,
    now: datetime,
    poll_interval_seconds: int = 60,
    *,
    metric: Metric | None = None,
) -> Freshness:
    """Describe observed age without changing values or inventing a reset.

    With a metric, only that row's reset is considered. Otherwise any elapsed
    reset marks the account stale. A reset already passed at observation time
    does not imply that a *later* observation has been missed.
    """
    now = utc_datetime(now)
    fetched = snapshot.fetched_at
    age = None if fetched is None else max(0.0, (now - fetched).total_seconds())
    metrics = snapshot.metrics if metric is None else (metric,)
    passed = fetched is not None and any(
        row.reset_at is not None and fetched < row.reset_at <= now for row in metrics
    )
    return Freshness(
        age_seconds=age,
        attempted_age_seconds=max(0.0, (now - snapshot.attempted_at).total_seconds()),
        stale=age is None or age > max(2 * poll_interval_seconds, 120) or passed,
        reset_passed=passed,
        last_known=fetched is not None and snapshot.fetch_state not in _SUCCESS,
    )


@dataclass(slots=True)
class _AccountState:
    account: Account
    due: float
    retry_deadline: float = 0.0
    failures: int = 0
    # Consecutive partial observations carrying a secondary request's embargo
    # (e.g. Claude prepaid credits 429); drives a conservative escalating floor.
    embargoes: int = 0
    suspended: bool = False
    pending: bool = False
    snapshot: Snapshot | None = None
    capability_done: bool = False


class Scheduler:
    """Two global fetches, one per account, and five-second provider start spacing.

    refresh() is an explicit reconnect attempt for suspended accounts and may
    bypass the normal polling interval, including Claude's three-minute floor.
    Requests during a fetch coalesce into one follow-up, still subject to retry
    embargoes and provider start spacing.
    update_accounts() without ``invalidate`` replaces every supplied generation,
    even when a secret was replaced behind an unchanged reference. With an
    ``invalidate`` set it keeps the generation of each account outside that set
    whose credential identity is unchanged (a rename, interval, enable or order
    change). That is sound because keyring and session secrets never change
    behind an unchanged reference (each put mints a new one); file contents can,
    so an explicit source submission must name the account in ``invalidate``.
    Same-provider retry embargoes survive replacement. Removed/replaced
    generations can never publish.
    Eligible accounts run oldest account deadline first, before origin spacing is
    applied, so periodic polls cannot overtake an account's initial observation.
    """

    def __init__(
        self,
        accounts: Iterable[Account],
        providers: Mapping[ProviderId, Provider],
        resolver: CredentialResolver,
        *,
        clock: Clock | None = None,
        rng: random.Random | None = None,
        publish: Callable[[Snapshot], None],
    ) -> None:
        self._clock = clock if clock is not None else SystemClock()
        self._rng = rng if rng is not None else random.Random()
        self._providers = providers
        self._resolver = resolver
        self._publish = publish
        self._states = self._make_states(accounts)
        self._origin_next: dict[ProviderId, float] = {}
        self._active: dict[asyncio.Task, str] = {}
        self._wake = asyncio.Event()
        self._runner: asyncio.Task | None = None
        self._running = False
        self._closed = False

    def _make_states(self, accounts: Iterable[Account]) -> dict[str, _AccountState]:
        states = {}
        for account in accounts:
            if account.id in states:
                raise ValueError("Duplicate account ID.")
            if account.provider not in self._providers:
                raise ValueError("Missing provider.")
            states[account.id] = _AccountState(account, self._clock.monotonic())
        return states

    async def start(self) -> None:
        if self._closed:
            raise RuntimeError("Scheduler is stopped.")
        if not self._running:
            self._running = True
            self._runner = asyncio.create_task(self._run())

    async def refresh(self, account_id: str | None = None) -> None:
        if self._closed:
            return
        for key, state in self._states.items():
            provider = self._providers[state.account.provider]
            if (account_id is not None and key != account_id) or not state.account.enabled:
                continue
            if not provider.requires_credential:
                continue
            state.suspended = False
            state.pending = True
            state.due = self._clock.monotonic()
        self._wake.set()

    async def update_accounts(
        self, accounts: Iterable[Account], *, invalidate: Collection[str] | None = None
    ) -> None:
        if self._closed:
            return
        states = self._make_states(accounts)
        kept = set()
        for key, state in states.items():
            old = self._states.get(key)
            if old is None:
                continue
            if (
                invalidate is not None
                and key not in invalidate
                and credential_identity(old.account) == credential_identity(state.account)
            ):
                # Same generation: due, embargo, suspension and in-flight work stay.
                if state.account.enabled and not old.account.enabled:
                    old.pending = True
                    old.suspended = False
                seconds = state.account.effective_poll_interval_seconds
                if seconds < old.account.effective_poll_interval_seconds:
                    # A shorter interval applies now; the retry embargo is separate
                    # and never shortened.
                    old.due = min(old.due, self._clock.monotonic() + seconds)
                old.account = state.account
                states[key] = old
                kept.add(key)
                continue
            if old.account.provider == state.account.provider:
                state.retry_deadline = old.retry_deadline
                state.failures = old.failures
                state.embargoes = old.embargoes
                if old.account == state.account:
                    state.snapshot = old.snapshot
        self._states = states
        for task, key in tuple(self._active.items()):
            if key not in kept:
                task.cancel()
        self._wake.set()

    async def stop(self) -> None:
        """Cancel promptly, with bounded loop turns even for a broken adapter.

        Cancellation-resistant providers remain tracked until they finish; their
        results are discarded. We never await an unbounded adapter cancellation.
        """
        self._closed = True
        self._running = False
        tasks = tuple(self._active) + ((self._runner,) if self._runner else ())
        for task in tasks:
            task.cancel()
        self._wake.set()
        for _ in range(3):
            if all(task.done() for task in tasks):
                break
            await asyncio.sleep(0)

    def _deadline(self, state: _AccountState) -> float:
        account = state.account
        return max(
            state.due,
            state.retry_deadline,
            self._origin_next.get(account.provider, 0.0),
        )

    async def _run(self) -> None:
        try:
            while self._running:
                self._wake.clear()
                active_ids = set(self._active.values())
                deadlines = []
                # Origin deadlines are shared: sorting by them would hide which
                # account has waited longest when several are already overdue.
                states = sorted(
                    self._states.items(),
                    key=lambda item: max(item[1].due, item[1].retry_deadline),
                )
                dispatched = False
                for key, state in states:
                    if (
                        not state.account.enabled
                        or state.suspended
                        or state.capability_done
                        or key in active_ids
                    ):
                        continue
                    deadline = self._deadline(state)
                    if len(self._active) < 2 and deadline <= self._clock.monotonic():
                        state.pending = False
                        dispatched = True
                        task = asyncio.create_task(self._fetch(state))
                        self._active[task] = key
                        task.add_done_callback(self._finished)
                        break
                    deadlines.append(deadline)
                if dispatched:
                    # Let credential resolution and the actual start gate run
                    # before choosing another account from the same origin.
                    await asyncio.sleep(0)
                    continue
                if len(self._active) >= 2 or not deadlines:
                    await self._wake.wait()
                else:
                    await self._wait_until(min(deadlines))
        except asyncio.CancelledError:
            pass

    async def _wait_until(self, deadline: float) -> None:
        sleeper = asyncio.create_task(
            self._clock.sleep(max(0.0, deadline - self._clock.monotonic()))
        )
        wake = asyncio.create_task(self._wake.wait())
        try:
            await asyncio.wait((sleeper, wake), return_when=asyncio.FIRST_COMPLETED)
        finally:
            sleeper.cancel()
            wake.cancel()
            await asyncio.gather(sleeper, wake, return_exceptions=True)

    def _finished(self, task: asyncio.Task) -> None:
        self._active.pop(task, None)
        if not task.cancelled():
            task.exception()  # Retrieve exceptions without logging unsafe adapter text.
        self._wake.set()

    def _unknown_metrics(self, state: _AccountState) -> tuple[Metric, ...]:
        previous = {row.id: row for row in state.snapshot.metrics} if state.snapshot else {}
        source = SourceRef(SourceKind.UNRESOLVED, "scheduler.unobserved")
        return tuple(
            replace(
                previous[key],
                state=MetricState.UNKNOWN,
                quota=None,
                balance=None,
                reset_at=None,
                expires_at=None,
                shared_pool_id=None,
                detail=None,
                share_percent=None,
                spent=None,
                spend_limit=None,
                credits=None,
                unlimited=False,
                exact_balance=None,
            )
            if key in previous
            else Metric(key, key, MetricState.UNKNOWN, source)
            for key in self._providers[state.account.provider].metric_ids
        )

    def _failure(self, state: _AccountState, now: datetime, error: Exception) -> Snapshot:
        if isinstance(error, (TransportError, CredentialResolutionError)):
            fetch_state, code = error.fetch_state, error.code
            retry_at = getattr(error, "retry_at", None)
        else:
            fetch_state, code, retry_at = FetchState.PROVIDER_ERROR, "provider_error", None
        return Snapshot(
            state.account.id,
            self._unknown_metrics(state),
            (),
            fetch_state,
            now,
            retry_at=retry_at,
            diagnostic=Diagnostic(code),
            organization_id=state.account.organization_id,
        )

    async def _start_origin(self, provider: ProviderId) -> None:
        """Reserve spacing at the actual start, not before credential lookup.

        Recheck after every monotonic wait. No await separates checking and
        updating the deadline, serializing concurrent starters on this loop.
        """
        while True:
            current = self._clock.monotonic()
            remaining = self._origin_next.get(provider, 0.0) - current
            if remaining <= 0:
                self._origin_next[provider] = current + 5.0
                return
            await self._clock.sleep(remaining)

    async def _fetch(self, state: _AccountState) -> None:
        account = state.account
        provider = self._providers[account.provider]
        now = self._clock.now()
        try:
            credential = self._resolver.resolve(account) if provider.requires_credential else None
            if not self._running or self._states.get(account.id) is not state:
                return
            await self._start_origin(account.provider)
            now = self._clock.now()
            result = await provider.fetch(account, credential, now)
            if not isinstance(result, Snapshot) or result.account_id != account.id:
                raise TransportError(FetchState.SCHEMA_ERROR, "schema_error")
        except asyncio.CancelledError:
            return
        except Exception as error:  # noqa: BLE001 - Adapter failures must never expose secrets.
            result = self._failure(state, now, error)
        if not self._running or self._states.get(account.id) is not state:
            return
        # The adapter's own observation, before retained/unknown rows are merged.
        debuglog.snapshot(account.provider, result)
        current = self._clock.monotonic()
        if result.fetch_state in _SUCCESS:
            present = {metric.id for metric in result.metrics}
            missing = tuple(row for row in self._unknown_metrics(state) if row.id not in present)
            # A partial observation may carry a secondary request's server retry
            # deadline (e.g. Claude prepaid credits 429): keep the fresh rows but
            # honour it as an embargo for the whole refresh, never shortened.
            embargo = result.retry_at if result.fetch_state == FetchState.PARTIAL else None
            result = replace(
                result, metrics=result.metrics + missing, fetched_at=now, retry_at=embargo
            )
            state.failures = 0
            state.retry_deadline = 0.0
            if embargo is None:
                state.embargoes = 0
            else:
                # Repeated secondary rate limits escalate like a primary 429
                # (Claude 180, 360, 720, 900 s); a longer server deadline wins.
                base = 180 if account.provider == ProviderId.CLAUDE_SUBSCRIPTION else 60
                local = min(base * 2 ** min(state.embargoes, 3), 900)
                state.embargoes += 1
                wall = self._clock.now()
                delay = max(float(local), (embargo - wall).total_seconds())
                state.retry_deadline = current + delay
                try:
                    shown = wall + timedelta(seconds=delay)
                except OverflowError:
                    shown = datetime.max.replace(tzinfo=UTC)
                result = replace(result, retry_at=max(embargo, shown))
            # The current account: an interval edit may have landed mid-fetch.
            seconds = state.account.effective_poll_interval_seconds
            offset = self._rng.uniform(-seconds * 0.1, seconds * 0.1)
            floor = seconds if account.provider in POLL_FLOOR_SECONDS else 30
            interval = max(float(floor), seconds + offset)
            state.due = current if state.pending else current + interval
            state.due = max(state.due, state.retry_deadline)
        elif result.fetch_state == FetchState.UPSTREAM_CONTRACT_MISSING:
            state.capability_done = True
        else:
            previous = state.snapshot
            if previous is not None and previous.fetched_at is not None:
                result = replace(
                    result,
                    metrics=previous.metrics,
                    grants=previous.grants,
                    fetched_at=previous.fetched_at,
                )
            if result.fetch_state in _SUSPEND:
                state.suspended = True
                state.pending = False
                result = replace(result, retry_at=None)
            else:
                base = min(60 * 2 ** min(state.failures, 4), 900)
                if (
                    account.provider == ProviderId.CLAUDE_SUBSCRIPTION
                    and result.fetch_state == FetchState.RATE_LIMITED
                ):
                    base = min(180 * 2 ** min(state.failures, 3), 900)
                if account.provider in POLL_FLOOR_SECONDS:
                    base = max(base, account.effective_poll_interval_seconds)
                state.failures += 1
                delay = base + self._rng.uniform(0.0, base * 0.1)
                if result.retry_at is not None:
                    delay = max(delay, (result.retry_at - self._clock.now()).total_seconds())
                state.retry_deadline = max(state.retry_deadline, current + delay)
                state.due = state.retry_deadline
                wall = self._clock.now()
                try:
                    retry_at = wall + timedelta(seconds=state.retry_deadline - current)
                except OverflowError:
                    # Float conversion may round datetime.max into year 10000.
                    # Only presentation saturates; the monotonic embargo stays.
                    retry_at = datetime.max.replace(tzinfo=UTC)
                result = replace(result, retry_at=retry_at)
        if not provider.requires_credential:
            state.capability_done = True
        state.snapshot = result
        self._publish(result)
