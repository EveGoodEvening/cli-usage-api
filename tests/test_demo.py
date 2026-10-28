"""Offline demonstration contracts; these samples never prove live support."""

import asyncio
import builtins
import io
import socket
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from importlib.resources import files
from uuid import UUID

import httpx
import keyring
import pytest

from usage_tui import credentials, storage, transport
from usage_tui.demo import DEMO_NOW, DemoClock, DemoSource
from usage_tui.domain import (
    REQUIRED_METRIC_IDS,
    CredentialKind,
    FetchState,
    MetricId,
    MetricState,
    ProviderId,
    Snapshot,
    SourceKind,
)
from usage_tui.scheduler import freshness


@pytest.fixture
def forbid_live(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Demo accessed a forbidden live dependency.")

    real_open = io.open
    fixture_path = str(files("usage_tui").joinpath("fixtures/demo.json"))

    def fixture_only(path, mode="r", *args, **kwargs):
        if str(path) != fixture_path or mode not in {"r", "rb"}:
            forbidden()
        return real_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(io, "open", fixture_only)

    for owner, name in (
        (storage, "AccountStore"),
        (storage, "CredentialStore"),
        (credentials, "CredentialResolver"),
        (transport, "Transport"),
        (httpx, "Client"),
        (httpx, "AsyncClient"),
        (keyring, "get_keyring"),
        (keyring, "get_password"),
        (keyring, "set_password"),
        (builtins, "open"),
        (socket, "create_connection"),
    ):
        monkeypatch.setattr(owner, name, forbidden)


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario,count", [("healthy", 4), ("errors", 8)])
async def test_lifecycle_without_live_construction_or_reads(forbid_live, scenario, count):
    published = []
    source = DemoSource(scenario=scenario, publish=published.append)
    assert len(source.accounts) == count
    assert published == []
    await source.refresh()
    assert published == []
    await source.start()
    assert len(published) == count
    await source.start()
    assert len(published) == count
    await source.refresh(source.accounts[0].id)
    assert len(published) == count + 1
    assert published[-1] == published[0]
    await source.stop()
    await source.stop()
    source.tick(100)
    await source.refresh()
    await source.update_accounts(())
    assert len(published) == count + 1
    with pytest.raises(RuntimeError, match="stopped"):
        await source.start()


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", ["healthy", "errors"])
async def test_packaged_fixture_fictional_identity_and_required_rows(scenario):
    assert files("usage_tui").joinpath("fixtures/demo.json").is_file()
    published = []
    source = DemoSource(scenario=scenario, publish=published.append)
    await source.start()
    try:
        assert source.clock.now() == DEMO_NOW
        for account, snapshot in zip(source.accounts, published, strict=True):
            assert "FICTIONAL DEMO" in account.label
            assert str(UUID(account.id)) == account.id
            assert account.credential_ref is None
            assert account.credential_kind is None
            assert account.credential_selector is None
            assert snapshot.account_id == account.id
            assert (
                tuple(row.id for row in snapshot.metrics) == REQUIRED_METRIC_IDS[account.provider]
            )
            assert all(row.source.kind == SourceKind.OFFLINE_DEMO for row in snapshot.metrics)
            assert all("SYNTHETIC" in row.label for row in snapshot.metrics)
            assert snapshot.attempted_at == DEMO_NOW
            assert Snapshot.from_dict(snapshot.to_dict()) == snapshot
    finally:
        await source.stop()


@pytest.mark.asyncio
async def test_healthy_values_balances_grants_and_synthetic_gpt_warning():
    published = []
    source = DemoSource(publish=published.append)
    await source.start()
    try:
        assert all(snapshot.fetch_state == FetchState.OK for snapshot in published)
        rows = {row.id: row for snapshot in published for row in snapshot.metrics}
        assert len(rows) == 10
        assert all(row.state == MetricState.READY for row in rows.values())
        fable = rows[MetricId.CLAUDE_FABLE_WEEKLY]
        assert fable.quota.used_percent == Decimal("110.25")
        assert fable.quota.remaining_percent == 0
        assert rows[MetricId.CLAUDE_TOTAL_BALANCE].balance.minor == 5500
        console = published[1]
        assert console.organization_id == source.accounts[1].organization_id
        assert sum(grant.remaining.minor for grant in console.grants) == 5500
        assert console.grants[0].expires_at is None
        assert console.grants[1].expires_at == DEMO_NOW + timedelta(days=7)
        assert all(row.reset_at is None for row in console.metrics)
        gpt = rows[MetricId.CHATGPT_WEEKLY]
        assert "SYNTHETIC ONLY" in gpt.label
        assert "ordinary ChatGPT weekly live retrieval is unsupported" in gpt.detail
        assert "Not evidence of live support" in gpt.detail
        pool = rows[MetricId.GROK_SHARED_POOL]
        for product in (MetricId.GROK_BUILD, MetricId.GROK_CHAT):
            assert rows[product].quota is None
            assert rows[product].reset_at is None
            assert rows[product].shared_pool_id == pool.shared_pool_id
            assert "not an independent remaining allowance" in rows[product].detail
    finally:
        await source.stop()


@pytest.mark.asyncio
async def test_errors_cover_failures_partial_unknowns_and_stale_last_known():
    published = []
    source = DemoSource(scenario="errors", publish=published.append)
    await source.start()
    try:
        by_state = {snapshot.fetch_state: snapshot for snapshot in published}
        for state in (
            FetchState.AUTH_REQUIRED,
            FetchState.PERMISSION_DENIED,
            FetchState.RATE_LIMITED,
            FetchState.NETWORK_ERROR,
            FetchState.SCHEMA_ERROR,
            FetchState.PARTIAL,
        ):
            assert state in by_state
            assert by_state[state].diagnostic is not None
        for state in (
            FetchState.AUTH_REQUIRED,
            FetchState.PERMISSION_DENIED,
            FetchState.SCHEMA_ERROR,
        ):
            snapshot = by_state[state]
            assert snapshot.fetched_at is None
            assert snapshot.grants == ()
            assert all(row.state == MetricState.UNKNOWN for row in snapshot.metrics)
            assert all(row.quota is None and row.balance is None for row in snapshot.metrics)
        for state in (FetchState.RATE_LIMITED, FetchState.NETWORK_ERROR):
            snapshot = by_state[state]
            assert snapshot.fetched_at < snapshot.attempted_at
            assert snapshot.retry_at > source.clock.now()
            status = freshness(snapshot, source.clock.now())
            assert status.stale and status.last_known
            assert all("LAST KNOWN" in row.detail for row in snapshot.metrics)
        partials = [item for item in published if item.fetch_state == FetchState.PARTIAL]
        assert len(partials) == 2
        unknown = {
            row.id
            for snapshot in partials
            for row in snapshot.metrics
            if row.state == MetricState.UNKNOWN
        }
        assert unknown == {
            MetricId.CLAUDE_FABLE_WEEKLY,
            MetricId.GROK_BUILD,
            MetricId.GROK_CHAT,
        }
        for snapshot in partials:
            assert snapshot.fetched_at == DEMO_NOW
            for row in snapshot.metrics:
                if row.id in unknown:
                    assert row.quota is None and row.balance is None
                    assert row.reset_at is None
                    assert "current value unknown, never zero" in row.detail
    finally:
        await source.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", ["healthy", "errors"])
async def test_tick_only_moves_clock_and_refresh_keeps_fixed_deadlines(scenario):
    first, second = [], []
    source = DemoSource(scenario=scenario, publish=first.append)
    twin = DemoSource(scenario=scenario, publish=second.append)
    await source.start()
    await twin.start()
    try:
        assert first == second
        count = len(first)
        original = tuple(first)
        assert source.tick(7201) == DEMO_NOW + timedelta(seconds=7201)
        twin.tick(7201)
        assert len(first) == count
        assert source.clock.monotonic() == 7201
        await source.refresh()
        await twin.refresh()
        assert first == second
        for before, after in zip(original, first[count:], strict=True):
            assert after.metrics == before.metrics
            assert after.retry_at == before.retry_at
            assert after.attempted_at == source.clock.now()
            if before.fetch_state not in {FetchState.OK, FetchState.PARTIAL}:
                assert after.fetched_at == before.fetched_at
    finally:
        await source.stop()
        await twin.stop()


@pytest.mark.asyncio
async def test_account_selection_replacement_disable_removal_and_atomic_rejection():
    published = []
    source = DemoSource(publish=published.append)
    original = source.accounts
    selected = replace(original[0], label="FICTIONAL DEMO · edited")
    disabled = replace(original[1], enabled=False)
    await source.update_accounts((selected, disabled))
    assert not published
    await source.start()
    try:
        assert [item.account_id for item in published] == [selected.id]
        await source.update_accounts((original[2],))
        assert published[-1].account_id == original[2].id
        await source.refresh(selected.id)
        assert len(published) == 2
        for invalid in (
            (original[0], original[0]),
            (replace(original[0], id=str(UUID(int=999))),),
            (replace(original[0], provider=ProviderId.GROK_SUBSCRIPTION),),
            (
                replace(
                    original[0],
                    credential_ref="synthetic-rejected-reference",
                    credential_kind=CredentialKind.MANUAL_BEARER,
                ),
            ),
            (replace(original[3], credential_selector="synthetic-rejected-profile"),),
            (replace(original[1], organization_id="other-fictional-organization"),),
        ):
            with pytest.raises(ValueError, match="fictional"):
                await source.update_accounts(invalid)
            assert source.accounts == (original[2],)
            assert len(published) == 2
        await source.update_accounts(())
        await source.refresh()
        assert len(published) == 2
    finally:
        await source.stop()


@pytest.mark.asyncio
async def test_injected_clock_and_sleep_use_only_explicit_time():
    now = datetime(2030, 1, 1, tzinfo=UTC)
    clock = DemoClock(now)
    published = []
    source = DemoSource(clock=clock, publish=published.append)
    await source.start()
    try:
        assert source.clock is clock
        assert published[0].fetched_at == now
        assert published[0].metrics[0].reset_at == now + timedelta(hours=2)
        sleeper = asyncio.create_task(clock.sleep(2))
        await asyncio.sleep(0)
        clock.advance(1)
        assert not sleeper.done()
        clock.advance(1)
        await asyncio.wait_for(sleeper, 1)
        cancelled = asyncio.create_task(clock.sleep(10))
        await asyncio.sleep(0)
        cancelled.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancelled
        clock.advance(10)
        await clock.sleep(0)
        assert len(published) == 4
    finally:
        await source.stop()


@pytest.mark.parametrize(
    ("seconds", "error"),
    [
        (-1, ValueError),
        (True, TypeError),
        (float("inf"), ValueError),
        (float("nan"), ValueError),
        ("1", TypeError),
    ],
)
def test_invalid_clock_ticks_are_atomic(seconds, error):
    clock = DemoClock()
    with pytest.raises(error):
        clock.advance(seconds)
    assert clock.now() == DEMO_NOW
    assert clock.monotonic() == 0


def test_unknown_scenario_is_rejected_before_fixture_access(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Unknown scenario read a fixture.")

    monkeypatch.setattr("usage_tui.demo.files", forbidden)
    with pytest.raises(ValueError, match="scenario"):
        DemoSource(scenario="live-fallback", publish=lambda snapshot: None)
