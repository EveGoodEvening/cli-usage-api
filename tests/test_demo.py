"""Offline demonstration contracts; these samples never prove live support."""

import asyncio
import builtins
import io
import json
import socket
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from importlib.resources import files
from uuid import UUID

import httpx
import keyring
import pytest

from cli_usage_api import credentials, storage, transport
from cli_usage_api.demo import DEMO_NOW, DemoClock, DemoSource
from cli_usage_api.domain import (
    REQUIRED_METRIC_IDS,
    CredentialKind,
    DomainError,
    FetchState,
    MetricId,
    MetricState,
    ProviderId,
    Snapshot,
    SourceKind,
)
from cli_usage_api.scheduler import freshness

UNKNOWN_ALL_STATES = {
    FetchState.AUTH_REQUIRED,
    FetchState.PERMISSION_DENIED,
    FetchState.SCHEMA_ERROR,
}
DEMO_EXTRAS = {
    ProviderId.CLAUDE_SUBSCRIPTION: (MetricId.CLAUDE_CREDIT_BALANCE,),
    ProviderId.CODEX_SUBSCRIPTION: (MetricId.CODEX_FIVE_HOUR, MetricId.CODEX_CREDITS),
    ProviderId.OPENAI_PLATFORM: (MetricId.OPENAI_PAID_AVAILABLE_BALANCE,),
}
SYNTHETIC = "Fictional synthetic demonstration; not live account data."


@pytest.fixture
def forbid_live(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Demo accessed a forbidden live dependency.")

    real_open = io.open
    fixture_path = str(files("cli_usage_api").joinpath("fixtures/demo.json"))

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
@pytest.mark.parametrize("scenario,count", [("healthy", 5), ("errors", 10)])
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
    assert files("cli_usage_api").joinpath("fixtures/demo.json").is_file()
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
            required = REQUIRED_METRIC_IDS[account.provider]
            metric_ids = tuple(row.id for row in snapshot.metrics)
            assert metric_ids[: len(required)] == required
            assert len(set(metric_ids)) == len(metric_ids)
            if snapshot.fetch_state in UNKNOWN_ALL_STATES:
                # A failed first fetch has only required rows; optional extras are absent.
                assert metric_ids == required
            elif account.provider in DEMO_EXTRAS:
                assert metric_ids == required + DEMO_EXTRAS[account.provider]
            else:
                assert metric_ids == required
            # Parse-only Claude extra usage never gets a demo row (user request).
            assert MetricId.CLAUDE_EXTRA_USAGE not in metric_ids
            assert all(row.source.kind == SourceKind.OFFLINE_DEMO for row in snapshot.metrics)
            assert all("SYNTHETIC" in row.label for row in snapshot.metrics)
            assert snapshot.attempted_at == DEMO_NOW
            assert Snapshot.from_dict(snapshot.to_dict()) == snapshot
    finally:
        await source.stop()


@pytest.mark.asyncio
async def test_healthy_values_balances_grants_and_fictional_codex_windows():
    published = []
    source = DemoSource(publish=published.append)
    await source.start()
    try:
        assert all(snapshot.fetch_state == FetchState.OK for snapshot in published)
        rows = {row.id: row for snapshot in published for row in snapshot.metrics}
        assert len(rows) == 15
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
        weekly = rows[MetricId.CODEX_WEEKLY]
        five_hour = rows[MetricId.CODEX_FIVE_HOUR]
        assert weekly.label == "Codex weekly (7d) · SYNTHETIC"
        assert weekly.quota.used_percent == Decimal(24)
        assert weekly.reset_at == DEMO_NOW + timedelta(days=4)
        assert five_hour.label == "Codex 5h · SYNTHETIC"
        assert five_hour.quota.used_percent == Decimal("12.5")
        assert five_hour.reset_at == DEMO_NOW + timedelta(hours=3)
        for row in (weekly, five_hour):
            assert row.source.kind == SourceKind.OFFLINE_DEMO
            assert row.detail == "Fictional synthetic demonstration; not live account data."
        credits = rows[MetricId.CODEX_CREDITS]
        assert credits.label == "Codex credits · SYNTHETIC"
        assert credits.credits == Decimal("137.5")
        assert str(credits.credits) == "137.5"
        assert credits.source.kind == SourceKind.OFFLINE_DEMO
        assert credits.detail == "Fictional synthetic demonstration; not live account data."
        # Credits are a non-currency balance: never a quota, money, spend or reset.
        assert credits.quota is None and credits.balance is None
        assert credits.spent is None and credits.spend_limit is None
        assert credits.unlimited is False
        assert credits.reset_at is None
        # Claude prepaid credits: an ordinary Money balance, distinct from Console.
        claude_credit = rows[MetricId.CLAUDE_CREDIT_BALANCE]
        assert claude_credit.label == "Claude 已购 credits 余额 · SYNTHETIC"
        assert claude_credit.balance.minor == 2500
        assert claude_credit.balance.currency == "USD"
        assert claude_credit.balance.exponent == 2
        assert claude_credit.quota is None and claude_credit.exact_balance is None
        assert claude_credit.reset_at is None
        assert claude_credit.detail == SYNTHETIC
        # Shown under the Claude subscription account, after its required rows.
        assert published[0].metrics[-1] == claude_credit
        # OpenAI Platform: any-scale exact money that keeps its float noise in data.
        openai = published[4]
        assert source.accounts[4].provider == ProviderId.OPENAI_PLATFORM
        assert openai.organization_id == source.accounts[4].organization_id
        available = rows[MetricId.OPENAI_AVAILABLE_BALANCE]
        paid = rows[MetricId.OPENAI_PAID_AVAILABLE_BALANCE]
        assert available.label == "OpenAI 可用余额 · SYNTHETIC"
        assert paid.label == "OpenAI 付费余额 · SYNTHETIC"
        assert str(available.exact_balance.amount) == "4.8999999999999995"
        assert available.exact_balance.currency == "USD"
        assert available.exact_balance.rounded_to_cents() == (Decimal("4.90"), True)
        assert available.exact_balance.format_cents() == "4.90 USD"
        assert paid.exact_balance.rounded_to_cents() == (Decimal("3.07"), False)
        assert paid.exact_balance.format_cents() == "3.07 USD"
        for row in (available, paid):
            assert row.state == MetricState.READY
            assert row.source.kind == SourceKind.OFFLINE_DEMO
            assert row.detail == SYNTHETIC
            assert row.balance is None and row.quota is None and row.credits is None
            assert row.reset_at is None
        assert openai.grants == ()
        assert openai.to_dict()["metrics"][0]["exact_balance"] == {
            "amount": "4.8999999999999995",
            "currency": "USD",
        }
        pool = rows[MetricId.GROK_SHARED_POOL]
        assert rows[MetricId.GROK_BUILD].share_percent == Decimal(30)
        assert rows[MetricId.GROK_CHAT].share_percent == Decimal(15)
        assert pool.share_percent is None
        for metric_id in (MetricId.GROK_SHARED_POOL, MetricId.GROK_BUILD, MetricId.GROK_CHAT):
            # Uniform synthetic provenance, hoisted to the header like other cards.
            assert rows[metric_id].detail == (
                "Fictional synthetic demonstration; not live account data."
            )
        for product in (MetricId.GROK_BUILD, MetricId.GROK_CHAT):
            assert rows[product].quota is None
            assert rows[product].reset_at is None
            assert rows[product].shared_pool_id == pool.shared_pool_id
            # A share is never a quota, so no independent remaining is derivable.
            assert rows[product].share_percent is not None
    finally:
        await source.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "inventory", ["weekly_only", "extra_duration", "missing_weekly", "duplicate"]
)
async def test_codex_fixture_preserves_required_weekly_and_optional_extras(
    inventory, tmp_path, monkeypatch
):
    fixture = json.loads(files("cli_usage_api").joinpath("fixtures/demo.json").read_text())
    metrics = fixture["providers"]["codex_subscription"]["metrics"]
    if inventory == "weekly_only":
        del metrics[1:]
    elif inventory == "extra_duration":
        metrics.append(
            {
                "id": "codex.subscription.window.300",
                "label": "Codex 300s · SYNTHETIC",
                "used_percent": "8",
                "reset_offset": 120,
            }
        )
    elif inventory == "missing_weekly":
        metrics.pop(0)
    else:
        metrics.append(dict(metrics[0]))
    fixture_dir = tmp_path / "fixtures"
    fixture_dir.mkdir()
    (fixture_dir / "demo.json").write_text(json.dumps(fixture))
    monkeypatch.setattr("cli_usage_api.demo.files", lambda package: tmp_path)
    published = []
    source = DemoSource(publish=published.append)
    try:
        if inventory in {"missing_weekly", "duplicate"}:
            with pytest.raises(ValueError, match="required metrics first, then unique extras"):
                await source.start()
        else:
            await source.start()
            snapshot = next(item for item in published if item.account_id == source.accounts[2].id)
            assert snapshot.fetch_state == FetchState.OK
            assert tuple(row.id for row in snapshot.metrics) == tuple(
                item["id"] for item in metrics
            )
            assert all(row.state == MetricState.READY for row in snapshot.metrics)
            assert all(row.source.kind == SourceKind.OFFLINE_DEMO for row in snapshot.metrics)
            if inventory == "weekly_only":
                assert tuple(row.id for row in snapshot.metrics) == (MetricId.CODEX_WEEKLY,)
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
        failed = [item for item in published if item.fetch_state in UNKNOWN_ALL_STATES]
        assert len(failed) == 4
        for snapshot in failed:
            assert snapshot.fetched_at is None
            assert snapshot.grants == ()
            assert all(row.state == MetricState.UNKNOWN for row in snapshot.metrics)
            assert all(
                row.quota is None and row.balance is None and row.exact_balance is None
                for row in snapshot.metrics
            )
        for state in (FetchState.RATE_LIMITED, FetchState.NETWORK_ERROR):
            snapshot = by_state[state]
            assert snapshot.fetched_at < snapshot.attempted_at
            assert snapshot.retry_at > source.clock.now()
            status = freshness(snapshot, source.clock.now())
            assert status.stale and status.last_known
            assert all("LAST KNOWN" in row.detail for row in snapshot.metrics)
        partials = [item for item in published if item.fetch_state == FetchState.PARTIAL]
        assert len(partials) == 3
        unknown = {
            row.id
            for snapshot in partials
            for row in snapshot.metrics
            if row.state == MetricState.UNKNOWN
        }
        assert unknown == {
            MetricId.CLAUDE_FABLE_WEEKLY,
            MetricId.CLAUDE_CREDIT_BALANCE,
            MetricId.GROK_BUILD,
            MetricId.GROK_CHAT,
        }
        for snapshot in partials:
            assert snapshot.fetched_at == DEMO_NOW
            for row in snapshot.metrics:
                if row.state == MetricState.UNKNOWN:
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
            (replace(original[0], provider=ProviderId.GROK_SUBSCRIPTION, organization_id=None),),
            (replace(original[0], organization_id=None),),
            (replace(original[0], organization_id=str(UUID(int=7))),),
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
        assert len(published) == 5
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

    monkeypatch.setattr("cli_usage_api.demo.files", forbidden)
    with pytest.raises(ValueError, match="scenario"):
        DemoSource(scenario="live-fallback", publish=lambda snapshot: None)


@pytest.mark.asyncio
async def test_update_accounts_accepts_and_ignores_invalidate():
    published = []
    source = DemoSource(publish=published.append)
    original = source.accounts
    await source.start()
    try:
        await source.update_accounts(original[::-1], invalidate=frozenset())
        assert source.accounts == original[::-1]
        await source.update_accounts((original[0],), invalidate={original[0].id})
        assert source.accounts == (original[0],)
        with pytest.raises(ValueError, match="fictional"):
            await source.update_accounts((original[0], original[0]), invalidate=frozenset())
    finally:
        await source.stop()


def _codex_fixture(tmp_path, monkeypatch, extra):
    fixture = json.loads(files("cli_usage_api").joinpath("fixtures/demo.json").read_text())
    metrics = fixture["providers"]["codex_subscription"]["metrics"]
    metrics[:] = [item for item in metrics if item["id"] != MetricId.CODEX_CREDITS]
    metrics.append({"id": MetricId.CODEX_CREDITS.value, "label": "Codex credits · SYNTHETIC"})
    metrics[-1].update(extra)
    fixture_dir = tmp_path / "fixtures"
    fixture_dir.mkdir()
    (fixture_dir / "demo.json").write_text(json.dumps(fixture))
    monkeypatch.setattr("cli_usage_api.demo.files", lambda package: tmp_path)


async def _codex_credits_row(scenario="healthy"):
    published = []
    source = DemoSource(scenario=scenario, publish=published.append)
    try:
        await source.start()
        codex = [
            snapshot
            for snapshot, account in zip(published, source.accounts, strict=True)
            if account.provider == ProviderId.CODEX_SUBSCRIPTION
        ]
        for snapshot in codex:
            assert Snapshot.from_dict(snapshot.to_dict()) == snapshot
        return [
            row
            for snapshot in codex
            for row in snapshot.metrics
            if row.id == MetricId.CODEX_CREDITS
        ]
    finally:
        await source.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("extra", "credits", "unlimited"),
    [
        ({"unlimited": True}, None, True),
        ({"credits": "0"}, Decimal(0), False),
        ({"credits": "-2.50"}, Decimal("-2.50"), False),
    ],
)
async def test_codex_credit_loader_supports_unlimited_zero_and_negative(
    tmp_path, monkeypatch, extra, credits, unlimited
):
    _codex_fixture(tmp_path, monkeypatch, extra)
    (row,) = await _codex_credits_row()
    assert row.state == MetricState.READY
    assert row.source.kind == SourceKind.OFFLINE_DEMO
    assert row.unlimited is unlimited
    assert row.credits == credits
    if credits is not None:
        assert str(row.credits) == str(credits)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "extra",
    [
        {"credits": 1.5},
        {"credits": True},
        {"credits": "1e999999999"},
        {"credits": "x" * 65},
        {"unlimited": "yes"},
        {"unlimited": True, "credits": "5"},
    ],
)
async def test_codex_credit_loader_rejects_unbounded_or_inconsistent_fixture(
    tmp_path, monkeypatch, extra
):
    _codex_fixture(tmp_path, monkeypatch, extra)
    with pytest.raises(DomainError):
        await _codex_credits_row()


@pytest.mark.asyncio
async def test_unknown_codex_credits_clear_amount_and_unlimited(tmp_path, monkeypatch):
    fixture = json.loads(files("cli_usage_api").joinpath("fixtures/demo.json").read_text())
    metrics = fixture["providers"]["codex_subscription"]["metrics"]
    next(item for item in metrics if item["id"] == MetricId.CODEX_CREDITS)["unlimited"] = False
    profile = next(
        item for item in fixture["scenarios"]["errors"] if item["provider"] == "codex_subscription"
    )
    profile.update(
        fetch_state="partial",
        diagnostic="partial_data",
        unknown_metrics=[MetricId.CODEX_CREDITS.value],
    )
    fixture_dir = tmp_path / "fixtures"
    fixture_dir.mkdir()
    (fixture_dir / "demo.json").write_text(json.dumps(fixture))
    monkeypatch.setattr("cli_usage_api.demo.files", lambda package: tmp_path)
    (row,) = await _codex_credits_row("errors")
    assert row.state == MetricState.UNKNOWN
    assert row.credits is None and row.unlimited is False
    assert "current value unknown, never zero" in row.detail


@pytest.mark.asyncio
async def test_errors_cover_failed_claude_credits_and_expired_openai_session():
    published = []
    source = DemoSource(scenario="errors", publish=published.append)
    await source.start()
    try:
        views = dict(zip((a.label for a in source.accounts), published, strict=True))
        credits_failed = views["FICTIONAL DEMO · credits request failed"]
        # A failed second request leaves the usage rows fresh and only the credit row unknown.
        assert credits_failed.fetch_state == FetchState.PARTIAL
        assert credits_failed.fetched_at == DEMO_NOW
        by_id = {row.id: row for row in credits_failed.metrics}
        assert all(
            by_id[metric_id].state == MetricState.READY
            for metric_id in REQUIRED_METRIC_IDS[ProviderId.CLAUDE_SUBSCRIPTION]
        )
        credit = by_id[MetricId.CLAUDE_CREDIT_BALANCE]
        assert credit.state == MetricState.UNKNOWN
        assert credit.balance is None
        assert "never zero" in credit.detail
        expired = views["FICTIONAL DEMO · OpenAI session expired"]
        assert expired.fetch_state == FetchState.AUTH_REQUIRED
        assert expired.fetched_at is None
        assert tuple(row.id for row in expired.metrics) == (MetricId.OPENAI_AVAILABLE_BALANCE,)
        assert expired.metrics[0].exact_balance is None
    finally:
        await source.stop()


def test_demo_accounts_carry_only_fictional_well_formed_organizations():
    source = DemoSource(publish=lambda snapshot: None)
    organizations = {account.provider: account.organization_id for account in source.accounts}
    claude = organizations[ProviderId.CLAUDE_SUBSCRIPTION]
    assert str(UUID(claude)) == claude
    assert organizations[ProviderId.OPENAI_PLATFORM].startswith("org-Fictional")
    assert organizations[ProviderId.CODEX_SUBSCRIPTION] is None
    assert all(account.credential_kind is None for account in source.accounts)


def _openai_fixture(tmp_path, monkeypatch, value):
    fixture = json.loads(files("cli_usage_api").joinpath("fixtures/demo.json").read_text())
    fixture["providers"]["openai_platform"]["metrics"][0]["exact_balance"] = value
    fixture_dir = tmp_path / "fixtures"
    fixture_dir.mkdir()
    (fixture_dir / "demo.json").write_text(json.dumps(fixture))
    monkeypatch.setattr("cli_usage_api.demo.files", lambda package: tmp_path)


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [4.9, True, "1e999999999", "NaN", "x" * 65])
async def test_exact_balance_loader_rejects_binary_float_and_hostile_amounts(
    tmp_path, monkeypatch, value
):
    _openai_fixture(tmp_path, monkeypatch, value)
    source = DemoSource(publish=lambda snapshot: None)
    try:
        with pytest.raises(DomainError):
            await source.start()
    finally:
        await source.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(("value", "cents"), [("-0.005", "-0.00"), ("0", "0.00")])
async def test_exact_balance_loader_keeps_zero_and_negative(tmp_path, monkeypatch, value, cents):
    _openai_fixture(tmp_path, monkeypatch, value)
    published = []
    source = DemoSource(publish=published.append)
    try:
        await source.start()
        row = published[4].metrics[0]
        assert row.state == MetricState.READY
        assert row.exact_balance.amount == Decimal(value)
        assert row.exact_balance.format_cents() == f"{cents} USD"
    finally:
        await source.stop()
