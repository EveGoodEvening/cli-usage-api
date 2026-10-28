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
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Protocol

from usage_tui.credentials import CredentialResolutionError, CredentialResolver
from usage_tui.domain import (
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
from usage_tui.providers.base import Provider

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
    suspended: bool = False
    pending: bool = False
    snapshot: Snapshot | None = None
    capability_done: bool = False


class Scheduler:
    """Two global fetches, one per account, and five-second provider spacing.

    refresh() is an explicit reconnect attempt for suspended accounts. Requests
    during a fetch coalesce into one follow-up, still subject to retry embargoes.
    update_accounts() invalidates every supplied generation, even when a secret
    was replaced behind an unchanged reference. Same-provider retry embargoes
    survive that operation. Removed/replaced generations can never publish.
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

    async def update_accounts(self, accounts: Iterable[Account]) -> None:
        if self._closed:
            return
        states = self._make_states(accounts)
        for key, state in states.items():
            old = self._states.get(key)
            if old is not None and old.account.provider == state.account.provider:
                state.retry_deadline = old.retry_deadline
                state.failures = old.failures
                if old.account == state.account:
                    state.snapshot = old.snapshot
        self._states = states
        for task in tuple(self._active):
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
                for key, state in self._states.items():
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
                        provider = state.account.provider
                        self._origin_next[provider] = self._clock.monotonic() + 5.0
                        task = asyncio.create_task(self._fetch(state))
                        self._active[task] = key
                        task.add_done_callback(self._finished)
                        active_ids.add(key)
                    else:
                        deadlines.append(deadline)
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

    async def _fetch(self, state: _AccountState) -> None:
        account = state.account
        provider = self._providers[account.provider]
        now = self._clock.now()
        try:
            credential = self._resolver.resolve(account) if provider.requires_credential else None
            result = await provider.fetch(account, credential, now)
            if not isinstance(result, Snapshot) or result.account_id != account.id:
                raise TransportError(FetchState.SCHEMA_ERROR, "schema_error")
        except asyncio.CancelledError:
            return
        except Exception as error:  # noqa: BLE001 - Adapter failures must never expose secrets.
            result = self._failure(state, now, error)
        if not self._running or self._states.get(account.id) is not state:
            return
        current = self._clock.monotonic()
        if result.fetch_state in _SUCCESS:
            present = {metric.id for metric in result.metrics}
            missing = tuple(row for row in self._unknown_metrics(state) if row.id not in present)
            result = replace(
                result, metrics=result.metrics + missing, fetched_at=now, retry_at=None
            )
            state.failures = 0
            state.retry_deadline = 0.0
            seconds = account.poll_interval_seconds
            offset = self._rng.uniform(-seconds * 0.1, seconds * 0.1)
            interval = max(30.0, seconds + offset)
            state.due = current if state.pending else current + interval
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
                state.failures += 1
                delay = base + self._rng.uniform(0.0, base * 0.1)
                if result.retry_at is not None:
                    delay = max(delay, (result.retry_at - self._clock.now()).total_seconds())
                state.retry_deadline = max(state.retry_deadline, current + delay)
                state.due = state.retry_deadline
                result = replace(
                    result,
                    retry_at=self._clock.now() + timedelta(seconds=state.retry_deadline - current),
                )
        if not provider.requires_credential:
            state.capability_done = True
        state.snapshot = result
        self._publish(result)
