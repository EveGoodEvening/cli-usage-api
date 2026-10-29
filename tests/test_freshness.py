"""Freshness is presentation metadata, never a quota reset or state mutation."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from usage_tui.app import UsageApp
from usage_tui.domain import (
    Account,
    Diagnostic,
    FetchState,
    Metric,
    MetricState,
    ProviderId,
    QuotaValue,
    Snapshot,
    SourceKind,
    SourceRef,
)
from usage_tui.scheduler import freshness

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def snapshot(*, fetched_at=NOW, reset_at=None, state=FetchState.OK):
    row = Metric(
        "test.usage",
        "Usage",
        MetricState.READY,
        SourceRef(SourceKind.OFFLINE_DEMO, "freshness.test"),
        quota=QuotaValue(used_percent=Decimal("127.25")),
        reset_at=reset_at,
    )
    return Snapshot(
        str(UUID(int=1)),
        (row,),
        (),
        state,
        NOW,
        fetched_at=fetched_at,
        diagnostic=Diagnostic("network_error") if state == FetchState.NETWORK_ERROR else None,
    )


@pytest.mark.parametrize(
    "interval,age,stale",
    [
        (30, 119, False),
        (30, 120, False),
        (30, 120.1, True),
        (60, 120, False),
        (60, 121, True),
        (100, 200, False),
        (100, 201, True),
        (3600, 7200, False),
        (3600, 7201, True),
    ],
)
def test_stale_threshold_is_strict_and_interval_sensitive(interval, age, stale):
    result = freshness(snapshot(), NOW + timedelta(seconds=age), interval)
    assert result.age_seconds == age
    assert result.stale is stale
    assert not result.reset_passed
    assert not result.last_known


def test_failed_attempt_does_not_refresh_observation_age():
    failed = replace(
        snapshot(state=FetchState.NETWORK_ERROR), attempted_at=NOW + timedelta(seconds=300)
    )
    result = freshness(failed, NOW + timedelta(seconds=301))
    assert result.age_seconds == 301
    assert result.last_known and result.stale
    assert failed.fetched_at == NOW
    assert failed.attempted_at == NOW + timedelta(seconds=300)
    assert result.attempted_age_seconds == 1


def test_reset_passed_is_stale_without_changing_values_or_fabricating_next_reset():
    reset = NOW + timedelta(seconds=10)
    value = snapshot(reset_at=reset)
    original = value.to_dict()
    assert not freshness(value, reset - timedelta(microseconds=1)).stale
    result = freshness(value, reset)
    assert result.stale and result.reset_passed
    assert value.to_dict() == original
    assert value.metrics[0].quota.used_percent == Decimal("127.25")
    assert value.metrics[0].quota.remaining_percent == 0
    assert value.metrics[0].reset_at == reset
    assert value.metrics[0].state == MetricState.READY


def test_new_observation_after_reset_clears_missed_observation_flag():
    value = snapshot(reset_at=NOW - timedelta(seconds=1))
    result = freshness(value, NOW + timedelta(seconds=1))
    assert not result.reset_passed
    assert not result.stale


def test_unknown_reset_never_invents_a_period():
    value = snapshot()
    assert not freshness(value, NOW + timedelta(seconds=100)).reset_passed
    assert value.metrics[0].reset_at is None
    assert freshness(value, NOW + timedelta(seconds=200)).stale


def test_no_successful_observation_has_no_age_and_is_not_last_known():
    value = snapshot(fetched_at=None, state=FetchState.NETWORK_ERROR)
    result = freshness(value, NOW)
    assert result.age_seconds is None
    assert result.stale
    assert not result.last_known
    assert not result.reset_passed


def test_metric_specific_reset_does_not_stale_independent_sibling():
    value = snapshot(reset_at=NOW + timedelta(seconds=10))
    sibling = replace(value.metrics[0], id="test.sibling", reset_at=None)
    value = replace(value, metrics=value.metrics + (sibling,))
    assert freshness(value, NOW + timedelta(seconds=10)).stale
    assert not freshness(value, NOW + timedelta(seconds=10), metric=sibling).stale


def test_unknown_state_and_freshness_are_orthogonal():
    value = snapshot()
    row = replace(value.metrics[0], state=MetricState.UNKNOWN, quota=None)
    value = replace(value, metrics=(row,), fetch_state=FetchState.PARTIAL)
    result = freshness(value, NOW)
    assert not result.stale
    assert not result.last_known
    assert value.metrics[0].state == MetricState.UNKNOWN


def test_wall_clock_reversal_does_not_show_negative_age():
    assert freshness(snapshot(), NOW - timedelta(seconds=60)).age_seconds == 0


@pytest.mark.parametrize("last_good", [False, True])
def test_maximum_retry_timestamp_does_not_change_observation_freshness(last_good):
    value = replace(
        snapshot(fetched_at=NOW if last_good else None, state=FetchState.RATE_LIMITED),
        attempted_at=NOW + timedelta(seconds=300),
        retry_at=datetime.max.replace(tzinfo=UTC),
    )
    original = value.to_dict()
    result = freshness(value, NOW + timedelta(seconds=301))
    assert result.stale
    assert result.last_known is last_good
    assert result.age_seconds == (301 if last_good else None)
    assert result.attempted_age_seconds == 1
    assert value.to_dict() == original


@pytest.mark.parametrize(
    "provider,interval,threshold",
    [
        (ProviderId.CLAUDE_SUBSCRIPTION, 60, 600),
        (ProviderId.CLAUDE_SUBSCRIPTION, 900, 1800),
        (ProviderId.GROK_SUBSCRIPTION, 60, 120),
        (ProviderId.CODEX_SUBSCRIPTION, 60, 120),
        (ProviderId.CLAUDE_PLATFORM, 60, 120),
    ],
)
async def test_dashboard_freshness_uses_effective_poll_interval(
    monkeypatch, provider, interval, threshold
):
    item = Account(str(UUID(int=1)), provider, "Synthetic", poll_interval_seconds=interval)
    app = UsageApp(
        mode="live", accounts=(item,), scheduler_factory=lambda accounts, *, publish: None
    )
    value = snapshot()
    async with app.run_test(size=(120, 40)) as pilot:
        for age, stale in ((121, threshold < 121), (threshold, False), (threshold + 1, True)):
            now = NOW + timedelta(seconds=age)
            monkeypatch.setattr(app, "now", lambda now=now: now)
            app.publish_snapshot(value)
            await pilot.pause()
            prompts = "\n".join(
                str(app.listing.get_option_at_index(index).prompt)
                for index in range(app.listing.option_count)
            )
            assert ("STALE" in prompts) is stale
            app.listing.highlighted = app.option_index((item, "test.usage"))
            await pilot.press("enter")
            assert ("STALE" in app.screen.content) is stale
            await pilot.press("escape")
        assert app.snapshots[item.id] is value
        assert item.poll_interval_seconds == interval
