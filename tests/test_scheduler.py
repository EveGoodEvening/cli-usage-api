"""All scheduling tests use virtual time and in-memory providers, never sockets."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from math import nextafter
from uuid import UUID

import pytest

from usage_tui.domain import (
    Account,
    CredentialKind,
    Diagnostic,
    FetchState,
    Metric,
    MetricState,
    ProviderId,
    QuotaValue,
    ResolvedCredential,
    Snapshot,
    SourceKind,
    SourceRef,
    TransportError,
)
from usage_tui.providers.chatgpt import ChatGPTProvider
from usage_tui.scheduler import Scheduler


class FakeClock:
    def __init__(self):
        self.elapsed = 0.0
        self.wall = datetime(2026, 1, 1, tzinfo=UTC)
        self.sleepers = []

    def now(self):
        return self.wall + timedelta(seconds=self.elapsed)

    def monotonic(self):
        return self.elapsed

    async def sleep(self, seconds):
        if seconds <= 0:
            return
        future = asyncio.get_running_loop().create_future()
        self.sleepers.append((self.elapsed + seconds, future))
        try:
            await future
        finally:
            self.sleepers = [(when, f) for when, f in self.sleepers if f is not future]

    async def advance(self, seconds):
        self.elapsed += seconds
        for when, future in tuple(self.sleepers):
            if when <= self.elapsed and not future.done():
                future.set_result(None)
        await settle()


class FixedRng:
    def __init__(self, fraction=0.5):
        self.fraction = fraction

    def uniform(self, low, high):
        # Midpoint periodic offset and zero retry jitter at the default fraction.
        fraction = self.fraction if low < 0 or self.fraction != 0.5 else 0
        return low + (high - low) * fraction


async def settle():
    # Scheduler has a bounded number of event/wake/task hand-offs, not a timer.
    for _ in range(30):
        await asyncio.sleep(0)


def account(number=1, provider=ProviderId.CLAUDE_SUBSCRIPTION, **kwargs):
    return Account(
        id=str(UUID(int=number)),
        provider=provider,
        label=f"Account {number}",
        credential_ref="synthetic",
        credential_kind=CredentialKind.MANUAL_BEARER,
        **kwargs,
    )


class Resolver:
    def __init__(self):
        self.calls = []

    def resolve(self, item):
        self.calls.append(item)
        return ResolvedCredential(
            item.provider, item.credential_kind, "synthetic-secret", "generation.one"
        )


class FakeProvider:
    requires_credential = True
    metric_ids = ("test.usage", "test.optional")

    def __init__(self, clock):
        self.clock = clock
        self.calls = []
        self.results = []
        self.gate = None
        self.active = 0
        self.maximum = 0
        self.cancellations = 0

    async def fetch(self, item, credential, now):
        self.calls.append((item, credential, self.clock.monotonic()))
        self.active += 1
        self.maximum = max(self.maximum, self.active)
        try:
            if self.gate is not None:
                await self.gate.wait()
            result = self.results.pop(0) if self.results else None
            if isinstance(result, Exception):
                raise result
            if callable(result):
                return result(item, now)
            return observation(item, now)
        except asyncio.CancelledError:
            self.cancellations += 1
            raise
        finally:
            self.active -= 1


def observation(item, now, *, optional=True, state=FetchState.OK):
    source = SourceRef(SourceKind.OFFLINE_DEMO, "scheduler.test")
    metrics = (
        Metric(
            "test.usage",
            "Usage",
            MetricState.READY,
            source,
            quota=QuotaValue(used_percent=Decimal("23.5")),
            reset_at=now + timedelta(seconds=100),
        ),
    )
    if optional:
        metrics += (Metric("test.optional", "Optional", MetricState.READY, source),)
    return Snapshot(item.id, metrics, (), state, now, fetched_at=now)


def setup(items=None, rng=None):
    clock = FakeClock()
    provider = FakeProvider(clock)
    resolver = Resolver()
    published = []
    items = items if items is not None else (account(),)
    providers = {item.provider: provider for item in items}
    scheduler = Scheduler(
        items,
        providers,
        resolver,
        clock=clock,
        rng=rng or FixedRng(),
        publish=published.append,
    )
    return scheduler, clock, provider, resolver, published


async def test_initial_poll_periodic_monotonic_and_stop():
    scheduler, clock, provider, resolver, published = setup()
    await scheduler.start()
    await settle()
    assert len(published) == len(resolver.calls) == 1
    clock.wall += timedelta(days=10)
    await clock.advance(59)
    assert len(provider.calls) == 1
    await clock.advance(1)
    assert len(provider.calls) == 2
    await scheduler.stop()
    await clock.advance(1000)
    assert len(published) == 2
    assert not scheduler._active
    assert scheduler._runner.done()
    assert not clock.sleepers


async def test_same_origin_spacing_and_no_account_overlap():
    scheduler, clock, provider, _, published = setup((account(1), account(2)))
    provider.gate = asyncio.Event()
    await scheduler.start()
    await settle()
    assert len(provider.calls) == 1
    await scheduler.refresh()
    await scheduler.refresh()
    await clock.advance(4.9)
    assert len(provider.calls) == 1
    await clock.advance(0.1)
    assert len(provider.calls) == 2
    assert provider.maximum == 2
    assert {call[0].id for call in provider.calls} == {account(1).id, account(2).id}
    provider.gate.set()
    await settle()
    await clock.advance(5)
    assert len(published) == 3  # One coalesced follow-up for the in-flight first account.
    await scheduler.stop()


async def test_global_two_across_providers():
    items = (
        account(1),
        account(2, ProviderId.GROK_SUBSCRIPTION),
        Account(
            str(UUID(int=3)),
            ProviderId.CLAUDE_PLATFORM,
            "Console",
            "session",
            CredentialKind.CONSOLE_SESSION,
        ),
    )
    scheduler, _, provider, _, _ = setup(items)
    provider.gate = asyncio.Event()
    await scheduler.start()
    await settle()
    assert len(provider.calls) == provider.active == 2
    provider.gate.set()
    await settle()
    assert len(provider.calls) == 3
    assert provider.maximum == 2
    await scheduler.stop()


async def test_refresh_burst_one_followup_and_five_second_spacing():
    scheduler, clock, provider, _, _ = setup()
    provider.gate = asyncio.Event()
    await scheduler.start()
    await settle()
    for _ in range(10):
        await scheduler.refresh(account().id)
    provider.gate.set()
    await settle()
    assert len(provider.calls) == 1
    await clock.advance(5)
    assert len(provider.calls) == 2
    await settle()
    assert len(provider.calls) == 2
    await scheduler.stop()


async def test_long_rate_limit_survives_manual_and_same_reference_replacement():
    scheduler, clock, provider, _, published = setup()
    deadline = clock.now() + timedelta(hours=3)
    provider.results = [TransportError(FetchState.RATE_LIMITED, "rate_limited", retry_at=deadline)]
    await scheduler.start()
    await settle()
    assert published[-1].retry_at == deadline
    await scheduler.refresh()
    await scheduler.update_accounts((account(),))
    await settle()
    await clock.advance(10799)
    assert len(provider.calls) == 1
    await clock.advance(1)
    assert len(provider.calls) == 2
    await scheduler.stop()


@pytest.mark.parametrize(
    "state",
    [
        FetchState.NETWORK_ERROR,
        FetchState.SCHEMA_ERROR,
        FetchState.PROVIDER_ERROR,
        FetchState.RATE_LIMITED,
    ],
)
async def test_exponential_backoff_cap_and_success_reset(state):
    scheduler, clock, provider, _, published = setup()
    provider.results = [TransportError(state, state.value) for _ in range(7)]
    await scheduler.start()
    await settle()
    for delay in (60, 120, 240, 480, 900, 900, 900):
        assert (published[-1].retry_at - clock.now()).total_seconds() == delay
        await scheduler.refresh()
        await clock.advance(delay - 1)
        count = len(provider.calls)
        await clock.advance(1)
        assert len(provider.calls) == count + 1
    assert published[-1].fetch_state == FetchState.OK
    provider.results = [TransportError(state, state.value)]
    await scheduler.refresh()
    await clock.advance(5)
    assert (published[-1].retry_at - clock.now()).total_seconds() == 60
    await scheduler.stop()


@pytest.mark.parametrize(
    "state", [FetchState.AUTH_REQUIRED, FetchState.PERMISSION_DENIED, FetchState.UNCONFIGURED]
)
async def test_auth_suspends_until_explicit_reconnect_or_update(state):
    scheduler, clock, provider, _, _ = setup()
    provider.results = [TransportError(state, state.value), TransportError(state, state.value)]
    await scheduler.start()
    await settle()
    await clock.advance(10000)
    assert len(provider.calls) == 1
    await scheduler.refresh()
    await settle()
    assert len(provider.calls) == 2
    await clock.advance(10000)
    assert len(provider.calls) == 2
    await scheduler.update_accounts((account(),))
    await settle()
    assert len(provider.calls) == 3
    await scheduler.stop()


async def test_errors_preserve_last_good_but_partial_disappearance_does_not():
    scheduler, clock, provider, _, published = setup()
    await scheduler.start()
    await settle()
    good = published[-1]
    provider.results = [RuntimeError("SECRET /private/credential/path")]
    await scheduler.refresh()
    await clock.advance(5)
    failed = published[-1]
    assert failed.metrics == good.metrics
    assert failed.fetched_at == good.fetched_at
    assert failed.attempted_at > good.attempted_at
    assert failed.diagnostic == Diagnostic("provider_error")
    assert "SECRET" not in repr(failed)
    provider.results = [
        lambda item, now: observation(item, now, optional=False, state=FetchState.PARTIAL)
    ]
    await clock.advance(60)
    partial = published[-1]
    assert partial.fetch_state == FetchState.PARTIAL
    assert partial.metrics[-1].id == "test.optional"
    assert partial.metrics[-1].state == MetricState.UNKNOWN
    assert partial.metrics[-1].quota is None
    assert partial.fetched_at > good.fetched_at
    await scheduler.stop()


async def test_replacement_cancels_old_generation_and_removal_stops_publication():
    scheduler, clock, provider, _, published = setup()
    provider.gate = asyncio.Event()
    await scheduler.start()
    await settle()
    replacement = replace(account(), credential_ref="replacement")
    await scheduler.update_accounts((replacement,))
    await settle()
    assert provider.cancellations == 1
    await clock.advance(5)
    assert provider.calls[-1][0] == replacement
    await scheduler.update_accounts(())
    await settle()
    provider.gate.set()
    await clock.advance(1000)
    assert not published
    await scheduler.stop()
    assert not scheduler._active


async def test_disabled_and_missing_provider_and_duplicate_accounts():
    with pytest.raises(ValueError, match="Duplicate"):
        setup((account(), account()))
    with pytest.raises(ValueError, match="Missing"):
        Scheduler((account(),), {}, Resolver(), publish=lambda snapshot: None)
    scheduler, clock, provider, _, _ = setup((replace(account(), enabled=False),))
    await scheduler.start()
    await scheduler.refresh()
    await clock.advance(100)
    assert not provider.calls
    await scheduler.update_accounts((account(),))
    await settle()
    assert len(provider.calls) == 1
    await scheduler.stop()


async def test_chatgpt_never_resolves_or_repolls():
    clock = FakeClock()
    item = Account(str(UUID(int=1)), ProviderId.CHATGPT_SUBSCRIPTION, "ChatGPT", None)

    class ForbiddenResolver:
        def resolve(self, account):
            raise AssertionError("Credential-free capability must never resolve.")

    published = []
    scheduler = Scheduler(
        (item,),
        {item.provider: ChatGPTProvider()},
        ForbiddenResolver(),
        clock=clock,
        rng=FixedRng(),
        publish=published.append,
    )
    await scheduler.start()
    await settle()
    assert published[0].fetch_state == FetchState.UPSTREAM_CONTRACT_MISSING
    assert published[0].metrics[0].state == MetricState.BLOCKED
    await scheduler.refresh()
    await clock.advance(100000)
    assert len(published) == 1
    await scheduler.update_accounts((item,))
    await settle()
    assert len(published) == 2
    await scheduler.stop()


@pytest.mark.parametrize("fraction, deadline", ((0, 54), (0.5, 60), (1, 66)))
async def test_periodic_poll_never_starts_before_exact_jitter_deadline(fraction, deadline):
    scheduler, clock, provider, _, _ = setup(rng=FixedRng(fraction))
    await scheduler.start()
    try:
        await settle()
        just_before = nextafter(deadline, float("-inf"))
        await clock.advance(just_before)
        assert len(provider.calls) == 1
        await clock.advance(deadline - just_before)
        assert [call[2] for call in provider.calls] == [0, deadline]
    finally:
        await scheduler.stop()


async def test_unexpected_provider_exception_is_not_rendered_and_polling_recovers():
    class UnsafeProviderError(Exception):
        def __str__(self):
            raise AssertionError("Unsafe exception text must not be rendered.")

        def __repr__(self):
            raise AssertionError("Unsafe exception representation must not be rendered.")

    scheduler, clock, provider, _, published = setup()
    provider.results = [UnsafeProviderError("SECRET /private/credential/path")]
    await scheduler.start()
    try:
        await settle()
        failed = published[-1]
        assert failed.fetch_state == FetchState.PROVIDER_ERROR
        assert failed.diagnostic == Diagnostic("provider_error")
        assert "SECRET" not in repr(failed)
        await clock.advance(60)
        assert len(provider.calls) == 2
        assert published[-1].fetch_state == FetchState.OK
    finally:
        await scheduler.stop()


async def test_interval_jitter_floor_and_bounds():
    for interval, fraction, expected in (
        (30, 0, 30),
        (30, 1, 33),
        (60, 0, 54),
        (60, 0.5, 60),
        (60, 1, 66),
        (3600, 1, 3960),
    ):
        scheduler, clock, provider, _, _ = setup(
            (account(poll_interval_seconds=interval),), FixedRng(fraction)
        )
        await scheduler.start()
        await settle()
        await clock.advance(expected - 0.5)
        assert len(provider.calls) == 1
        await clock.advance(0.5)
        assert len(provider.calls) == 2
        await scheduler.stop()


async def test_retry_jitter_is_positive_bounded_and_server_deadline_not_capped():
    scheduler, clock, provider, _, published = setup(rng=FixedRng(1))
    provider.results = [TransportError(FetchState.NETWORK_ERROR, "network_error")]
    await scheduler.start()
    await settle()
    assert (published[-1].retry_at - clock.now()).total_seconds() == 66
    await scheduler.stop()


async def test_cancellation_resistant_generation_cannot_publish_or_overlap():
    scheduler, clock, provider, _, published = setup()
    release = asyncio.Event()
    entered = asyncio.Event()

    async def resistant(item, credential, now):
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            await release.wait()
        return observation(item, now)

    provider.fetch = resistant
    await scheduler.start()
    await settle()
    assert entered.is_set()
    await scheduler.update_accounts((replace(account(), label="Replaced"),))
    await clock.advance(5)
    assert len(scheduler._active) == 1
    await scheduler.stop()
    assert not published
    release.set()
    await settle()
    assert not published
    assert not scheduler._active


async def scheduler_smoke():
    """Executable offline integration smoke used by the orchestrator."""
    scheduler, clock, provider, _, published = setup()
    await scheduler.start()
    await settle()
    assert len(published) == 1
    first = published[-1]
    provider.results = [RuntimeError("synthetic unsafe failure text")]
    await scheduler.refresh()
    await clock.advance(5)
    assert published[-1].fetch_state == FetchState.PROVIDER_ERROR
    assert published[-1].metrics == first.metrics
    assert published[-1].fetched_at == first.fetched_at
    assert published[-1].attempted_at > first.attempted_at
    assert published[-1].diagnostic.code == "provider_error"
    replacement = replace(account(), credential_ref="new-synthetic-reference")
    await scheduler.update_accounts((replacement,))
    await clock.advance(60)
    assert provider.calls[-1][0] == replacement
    assert published[-1].fetch_state == FetchState.OK
    await scheduler.update_accounts(())
    count = len(published)
    await clock.advance(1000)
    assert len(published) == count
    await scheduler.stop()
    await settle()
    assert not scheduler._active and scheduler._runner.done() and not clock.sleepers
    await clock.advance(1000)
    assert len(published) == count
    print(
        "Scheduler smoke: actual tasks, success, refresh, safe last-good failure, "
        "replacement, removal, bounded stop; no late publication"
    )


async def test_actual_scheduler_smoke():
    await scheduler_smoke()


async def test_late_old_generation_is_discarded_before_replacement_fetch():
    scheduler, clock, provider, _, published = setup()
    release = asyncio.Event()
    calls = []

    async def resistant_once(item, credential, now):
        calls.append(item)
        if len(calls) == 1:
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()
        return observation(item, now)

    provider.fetch = resistant_once
    await scheduler.start()
    await settle()
    replacement = replace(account(), credential_ref="replacement")
    await scheduler.update_accounts((replacement,))
    await clock.advance(5)
    assert len(calls) == 1
    release.set()
    await settle()
    assert calls == [account(), replacement]
    assert len(published) == 1
    await scheduler.stop()


async def test_resolution_failure_is_safe_and_does_not_call_provider():
    from usage_tui.credentials import CredentialResolutionError

    scheduler, clock, provider, resolver, published = setup()

    def unavailable(item):
        raise CredentialResolutionError(FetchState.AUTH_REQUIRED, "credential_expired")

    resolver.resolve = unavailable
    await scheduler.start()
    await settle()
    assert not provider.calls
    assert published[-1].diagnostic.code == "credential_expired"
    assert all(row.state == MetricState.UNKNOWN for row in published[-1].metrics)
    await clock.advance(10000)
    assert len(published) == 1
    await scheduler.stop()


async def test_successful_missing_row_is_unknown_not_last_good():
    scheduler, clock, provider, _, published = setup()
    await scheduler.start()
    await settle()
    provider.results = [lambda item, now: observation(item, now, optional=False)]
    await scheduler.refresh()
    await clock.advance(5)
    assert published[-1].fetch_state == FetchState.OK
    assert published[-1].metrics[-1].state == MetricState.UNKNOWN
    await scheduler.stop()
