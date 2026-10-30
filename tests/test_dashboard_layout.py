"""Grouped dashboard prompts: observable text of the actual headless OptionList."""

import re
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from rich.cells import cell_len

from cli_usage_api.app import InformationScreen, UsageApp, short_local_time
from cli_usage_api.domain import (
    Account,
    CredentialKind,
    Diagnostic,
    ExactMoney,
    FetchState,
    Metric,
    MetricId,
    MetricState,
    Money,
    ProviderId,
    QuotaValue,
    Snapshot,
    SourceKind,
    SourceRef,
)

BARS = ("█", "░", "▶")


@pytest.fixture(autouse=True)
def utc_timezone(monkeypatch):
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def prompt(app, row) -> str:
    return str(app.listing.get_option_at_index(app.option_index(row)).prompt)


def header(app, account) -> str:
    index = app.option_index(next(row for row in app.rows if row[0] == account)) - 1
    option = app.listing.get_option_at_index(index)
    assert option.disabled
    return str(option.prompt)


def row(app, metric_id, label=None):
    return next(
        (account, mid)
        for account, mid in app.rows
        if mid == metric_id and (label is None or label in account.label)
    )


async def test_headers_are_never_highlighted_and_enter_opens_metric():
    app = UsageApp(mode="demo")
    async with app.run_test(size=(110, 40)) as pilot:
        await pilot.pause()
        headers = [o for o in app.listing._options if o.id.startswith("h")]
        assert len(headers) == len(app.accounts) and all(o.disabled for o in headers)
        assert app.highlighted_row() is None
        assert app.listing.highlighted is None
        assert app.query_one("#account-selector").value == "all"
        app._tick()
        assert app.highlighted_row() is None
        selector = app.query_one("#account-selector")
        selector.value = app.accounts[0].id
        await pilot.pause()
        assert app.highlighted_row() is None
        selector.value = "all"
        await pilot.pause()
        assert app.highlighted_row() is None
        await pilot.press("enter")
        assert not isinstance(app.screen, InformationScreen)
        seen = []
        for _ in range(len(app.rows) + 2):
            await pilot.press("down")
            assert app.highlighted_row() is not None
            seen.append(app.highlighted_row())
        assert set(seen) == set(app.rows)
        for key in ("home", "up", "up", "end", "home"):
            await pilot.press(key)
            assert app.highlighted_row() is not None
        # The demo Claude account's prepaid credit row precedes the Console rows.
        await pilot.press("down", "down", "down", "down", "down")
        selected = app.highlighted_row()
        assert selected[1] == "claude.platform.promotional_balance"
        await pilot.press("enter")
        assert isinstance(app.screen, InformationScreen)
        assert app.screen.content.startswith(app._row_text(*selected).split("\n")[0])
        await pilot.press("escape", "q")


async def test_escape_clears_selection_through_refresh_and_filter_rebuilds():
    app = UsageApp(mode="demo")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("end")
        await pilot.pause()
        assert app.highlighted_row() == app.rows[-1]
        scroll = app.listing.scroll_offset
        await pilot.press("escape")
        assert app.listing.highlighted is None
        assert app.focused is app.listing
        assert app.listing.scroll_offset == scroll

        await pilot.press("escape", "enter", "r")
        assert len(app.screen_stack) == 1
        app._tick()
        assert app.highlighted_row() is None
        snapshot = app.snapshots[app.accounts[0].id]
        extra = replace(snapshot.metrics[0], id="claude.subscription.extra", label="Extra")
        app.publish_snapshot(replace(snapshot, metrics=(*snapshot.metrics, extra)))
        assert app.highlighted_row() is None
        app.selector.value = app.accounts[0].id
        await pilot.pause()
        assert app.highlighted_row() is None

        await pilot.press("down")
        assert app.highlighted_row() == app.rows[0]
        await pilot.press("enter")
        assert isinstance(app.screen, InformationScreen)
        await pilot.press("escape", "q")


async def test_escape_closes_account_dropdown_before_clearing_metric_selection():
    app = UsageApp(mode="demo")
    async with app.run_test() as pilot:
        await pilot.press("down")
        selected = app.highlighted_row()
        assert selected == app.rows[0]
        account_filter = app.selector.value
        await pilot.press("shift+tab", "enter")
        assert app.selector.expanded
        await pilot.press("escape")
        assert not app.selector.expanded
        assert app.highlighted_row() == selected
        await pilot.press("escape")
        assert app.highlighted_row() is None
        assert app.selector.value == account_filter
        assert app.focused is app.selector
        await pilot.press("q")


async def test_selection_survives_tick_and_earlier_extra_insertion():
    app = UsageApp(mode="demo")
    async with app.run_test(size=(110, 40)) as pilot:
        await pilot.pause()
        target = row(app, "codex.subscription.five_hour")
        app.listing.highlighted = app.option_index(target)
        app._tick()
        assert app.highlighted_row() == target
        claude = row(app, "claude.subscription.weekly")[0]
        snapshot = app.snapshots[claude.id]
        extra = replace(snapshot.metrics[0], id="claude.subscription.extra", label="Extra")
        app.publish_snapshot(replace(snapshot, metrics=(*snapshot.metrics, extra)))
        assert (claude, extra.id) in app.rows
        assert app.highlighted_row() == target
        await pilot.press("q")


async def test_account_header_once_with_state_freshness_times_retry_diagnostic():
    app = UsageApp(mode="demo", scenario="errors")
    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.pause()
        rate = next(a for a in app.accounts if "rate limited" in a.label)
        text = header(app, rate)
        for token in ("限流", "rate_limited", "LAST KNOWN", "STALE 过期 3/3", "成功 11:50"):
            assert token in text
        assert "尝试 12:00" in text and "重试 / retry 12:01:30 · 1分30秒后" in text
        assert "到重试时间后再刷新" in text
        all_text = "\n".join(str(o.prompt) for o in app.listing._options)
        for account in app.accounts:
            assert all_text.count(account.label) == 1
        for account, metric_id in app.rows:
            metric_text = prompt(app, (account, metric_id))
            assert account.label not in metric_text and "尝试" not in metric_text
        await pilot.press("q")


async def test_overage_unknown_and_product_prompts():
    app = UsageApp(mode="demo", scenario="errors")
    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.pause()
        fable = prompt(app, row(app, "claude.subscription.fable_weekly", "network"))
        assert "已用 110.25%" in fable and "剩余 0%" in fable and "超额 +10.25%" in fable
        assert "▶" in fable
        unknown = prompt(app, row(app, "claude.subscription.five_hour", "auth required"))
        assert "未知 / no data" in unknown and "已用" not in unknown
        assert not any(glyph in unknown for glyph in BARS)
        pool = prompt(app, row(app, "grok.subscription.shared_pool", "rate limited"))
        assert "已用 45%" in pool and "剩余 55%" in pool
        for metric_id, share in (("grok.product.build", "30"), ("grok.product.chat", "15")):
            product = prompt(app, row(app, metric_id, "rate limited"))
            # One line: bar plus used share; never a derived remaining or a lecture.
            assert "\n" not in product.rstrip()
            assert f"已用 {share}%" in product and any(glyph in product for glyph in BARS)
            assert "剩余" not in product and "非独立额度" not in product
            assert "同共享池" not in product and "Synthetic" not in product
        missing = prompt(app, row(app, "grok.product.build", "missing products"))
        assert "未知 / no data" in missing and "剩余" not in missing.split("\n")[0]
        assert "never zero" in missing  # failure details remain visible
        await pilot.press("q")


@pytest.mark.parametrize("width", [120, 80, 60])
async def test_grok_rows_match_quota_style_in_every_tier(width):
    app = UsageApp(mode="demo")
    async with app.run_test(size=(width, 60)) as pilot:
        await pilot.pause()
        pool = prompt(app, row(app, "grok.subscription.shared_pool"))
        assert pool.startswith("  Grok 共享池 ") and "已用 45%" in pool and "剩余 55%" in pool
        assert "Synthetic" not in pool
        expected = (
            ("grok.product.build", "├ GrokBuild", "30"),
            ("grok.product.chat", "└ GrokChat", "15"),
        )
        for metric_id, label, share in expected:
            text = prompt(app, row(app, metric_id))
            first = text.split("\n")[0]
            # Narrow puts the value on the label line, like every other row.
            assert label in first and f"已用 {share}%" in first
            assert any(glyph in text for glyph in BARS)
            assert "剩余" not in text and "后" not in text
            assert "Synthetic" not in text and "共享池" not in text
            assert len(text.rstrip().split("\n")) == (2 if width == 60 else 1)
        await pilot.press("q")


async def test_grok_demo_card_hoists_synthetic_notice_like_other_cards():
    app = UsageApp(mode="demo")
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        grok = row(app, "grok.subscription.shared_pool")[0]
        claude = row(app, "claude.subscription.five_hour")[0]
        notice = "ⓘ Fictional synthetic demonstration; not live account data."
        assert notice in header(app, grok) and notice in header(app, claude)
        await pilot.press("q")


async def test_unproven_pool_is_a_flat_aggregate_without_remaining_or_lectures():
    app = UsageApp(mode="demo")
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        pool_row = row(app, "grok.subscription.shared_pool")
        snapshot = app.snapshots[pool_row[0].id]
        caveat = "与共享池关系未知。"
        metrics = tuple(
            replace(
                metric,
                quota=None,
                share_percent=metric.share_percent or Decimal(50),
                shared_pool_id=None,
                reset_at=None,
                detail=caveat,
            )
            for metric in snapshot.metrics
        )
        app.publish_snapshot(replace(snapshot, metrics=metrics))
        aggregate = prompt(app, pool_row)
        assert aggregate.startswith("  Grok 汇总 ") and "共享池" not in aggregate
        assert "已用 50%" in aggregate and "剩余" not in aggregate
        for metric_id, label, share in (
            ("grok.product.build", "  GrokBuild", "30"),
            ("grok.product.chat", "  GrokChat", "15"),
        ):
            text = prompt(app, row(app, metric_id))
            # Not nested under a pool that was never proven; still one line.
            assert text.startswith(label) and "├" not in text and "└" not in text
            assert f"已用 {share}%" in text and "剩余" not in text
            assert caveat not in text and "\n" not in text.rstrip()
        # The caveat remains available on request.
        assert caveat in app.details(*pool_row)
        assert "Grok 汇总" in app.details(*pool_row)
        await pilot.press("q")


@pytest.mark.parametrize("size", [(80, 24), (110, 40)])
async def test_balance_amount_whole_without_percent_and_expiry_is_not_reset(size):
    app = UsageApp(mode="demo")
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        purchased = row(app, "claude.platform.purchased_balance")
        text = prompt(app, purchased)
        assert "42.50 USD" in text and "%" not in text and "无周期重置" in text
        account = purchased[0]
        snapshot = app.snapshots[account.id]
        metric = replace(
            snapshot.metrics[0],
            balance=Money(123456789, "USD", 2),
            expires_at=app.now() + timedelta(days=30),
        )
        app.publish_snapshot(replace(snapshot, metrics=(metric, *snapshot.metrics[1:])))
        text = prompt(app, purchased)
        assert "1234567.89 USD" in text and "到期" in text
        # Grant expiry is not a reset: no reset text and no countdown.
        assert "重置" not in text and "后" not in text and "%" not in text
        await pilot.press("q")


async def test_console_explanations_stay_in_details_but_unknown_reasons_remain_visible():
    app = UsageApp(mode="demo")
    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.pause()
        account = row(app, "claude.platform.purchased_balance")[0]
        snapshot = app.snapshots[account.id]
        overview = flat(header(app, account))
        assert "组织" not in overview and "赠款" not in overview
        for metric in snapshot.metrics:
            target = (account, metric.id)
            text = flat(prompt(app, target))
            assert metric.balance.format() in text
            # Shared explanations must not reappear via header hoisting.
            assert flat(metric.detail) not in overview + text
            app.listing.highlighted = app.option_index(target)
            await pilot.press("enter")
            assert isinstance(app.screen, InformationScreen)
            assert metric.detail in app.screen.content
            assert snapshot.organization_id in app.screen.content
            for grant in snapshot.grants:
                assert grant.name in app.screen.content
                assert grant.remaining.format() in app.screen.content
            await pilot.press("escape")

        unknown = replace(
            snapshot.metrics[0],
            state=MetricState.UNKNOWN,
            balance=None,
            detail="Purchased grants unavailable; balance unknown, never zero.",
        )
        app.publish_snapshot(
            replace(
                snapshot,
                metrics=(unknown, *snapshot.metrics[1:]),
                fetch_state=FetchState.PARTIAL,
                diagnostic=Diagnostic("partial_data"),
            )
        )
        text = flat(prompt(app, (account, unknown.id)))
        assert "未知 / no data" in text and unknown.detail in text
        assert snapshot.metrics[0].balance.format() not in text
        for metric in snapshot.metrics[1:]:
            text = flat(prompt(app, (account, metric.id)))
            assert metric.balance.format() in text and flat(metric.detail) not in text
        overview = flat(header(app, account))
        assert "组织" not in overview and "赠款" not in overview
        assert Diagnostic("partial_data").message in overview
        await pilot.press("q")


async def test_passed_reset_marks_only_that_row_without_changing_quota():
    app = UsageApp(mode="demo")
    async with app.run_test(size=(110, 40)) as pilot:
        await pilot.pause()
        five = row(app, "claude.subscription.five_hour")
        metric = app._metric(*five)
        snapshot = app.snapshots[five[0].id]
        # Recent observation: only this row's reset elapsed since it was fetched.
        passed = replace(metric, reset_at=app.now() - timedelta(seconds=30))
        app.publish_snapshot(
            replace(
                snapshot,
                fetched_at=app.now() - timedelta(seconds=60),
                metrics=(passed, *snapshot.metrics[1:]),
            )
        )
        metric = passed
        assert "awaiting refresh" in prompt(app, five) and "STALE" in prompt(app, five)
        assert "已用 37.5%" in prompt(app, five)
        weekly = prompt(app, row(app, "claude.subscription.weekly"))
        assert "awaiting refresh" not in weekly and "STALE" not in weekly
        assert app._metric(*five).quota is metric.quota
        # Five-hour, weekly, Fable and the prepaid credit row; one passed reset.
        assert "STALE 过期 1/4" in header(app, five[0])
        await pilot.press("q")


async def test_shared_detail_is_hoisted_and_distinct_detail_stays_on_row():
    app = UsageApp(mode="demo", scenario="errors")
    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.pause()
        partial = next(a for a in app.accounts if "unknown Fable" in a.label)
        fable = prompt(app, row(app, "claude.subscription.fable_weekly", "unknown Fable"))
        assert "current value unknown, never zero" in fable
        auth = next(a for a in app.accounts if "auth required" in a.label)
        assert header(app, auth).count("never zero") == 1
        assert "never zero" not in prompt(app, row(app, "claude.subscription.weekly", "auth"))
        assert "ⓘ" not in header(app, partial)
        await pilot.press("q")


async def test_tier_reflow_keeps_every_number():
    app = UsageApp(mode="demo")
    async with app.run_test(size=(110, 40)) as pilot:
        await pilot.pause()
        fable = row(app, "claude.subscription.fable_weekly")
        balance = row(app, "claude.platform.total_balance")
        layouts = []
        for size in ((120, 40), (78, 24), (40, 12)):
            await pilot.resize_terminal(*size)
            await pilot.pause()
            text = prompt(app, fable)
            layouts.append(text)
            assert "已用 110.25%" in text and "剩余 0%" in text and "超额" in text
            assert "55.00 USD" in prompt(app, balance)
            assert "Claude 5h 用量" in prompt(app, row(app, "claude.subscription.five_hour"))
        assert "超额 +10.25%" in layouts[0] and "周六" in layouts[0]
        assert len(set(layouts)) == 3 and "\n" in layouts[2]
        await pilot.press("q")


def test_short_local_time_saturates_to_utc_without_raising(monkeypatch):
    now = datetime(2026, 10, 28, 12, tzinfo=UTC)
    assert short_local_time(now + timedelta(hours=2), now) == "今天 14:00"
    assert short_local_time(now + timedelta(days=1), now) == "明天 12:00"
    assert short_local_time(now + timedelta(days=3), now) == "周六 12:00"
    monkeypatch.setenv("TZ", "Asia/Shanghai")
    time.tzset()
    boundary = datetime.max.replace(tzinfo=UTC)
    assert short_local_time(boundary, now, "%H:%M:%S") == "9999-12-31 23:59:59 UTC"


class IdleScheduler:
    async def start(self):
        pass

    async def stop(self):
        pass


async def test_disabled_and_pending_accounts_keep_required_rows():
    disabled = Account(
        id="11111111-1111-4111-8111-111111111111",
        provider=ProviderId.CLAUDE_SUBSCRIPTION,
        label="My laptop Claude",
        enabled=False,
    )
    pending = Account(
        id="22222222-2222-4222-8222-222222222222",
        provider=ProviderId.CODEX_SUBSCRIPTION,
        label="New Codex",
    )
    app = UsageApp(
        mode="live",
        accounts=(disabled, pending),
        scheduler_factory=lambda *a, **kw: IdleScheduler(),
    )
    async with app.run_test(size=(110, 40)) as pilot:
        await pilot.pause()
        assert app.metric_option_count() == 4
        assert "已禁用 / disabled" in header(app, disabled)
        assert "等待首次观察 / pending" in header(app, pending)
        assert "已禁用 / disabled" in prompt(app, (disabled, "claude.subscription.five_hour"))
        assert "暂无数据 / no data" in prompt(app, (pending, "codex.subscription.weekly"))
        assert "已用" not in prompt(app, (pending, "codex.subscription.weekly"))
        await pilot.press("q")


@pytest.mark.parametrize("size", [(120, 40), (78, 24), (40, 12)])
async def test_blocked_not_applicable_counts_and_ready_zero_stay_distinct(size):
    app = UsageApp(mode="demo")
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        account = app.accounts[0]
        snapshot = app.snapshots[account.id]
        base = snapshot.metrics[0]
        extras = (
            replace(base, id="x.blocked", state=MetricState.BLOCKED, quota=None),
            replace(base, id="x.na", state=MetricState.NOT_APPLICABLE, quota=None),
            replace(
                base,
                id="x.count",
                quota=QuotaValue(used_count=120, limit_count=500, remaining_count=380),
            ),
            replace(base, id="x.zero", quota=QuotaValue(used_percent=Decimal(0), used_count=3)),
        )
        app.publish_snapshot(replace(snapshot, metrics=(*snapshot.metrics, *extras)))
        blocked, na, count, zero = (prompt(app, (account, m.id)) for m in extras)
        assert "阻塞 / blocked" in blocked and "已用" not in blocked
        assert "不适用 / not applicable" in na and "已用" not in na
        assert not any(glyph in blocked + na for glyph in BARS)
        assert "120 / 500 次" in count and "已用 120" in count and "剩余 380" in count
        assert "已用 0%" in zero and "剩余 100%" in zero and "░" in zero
        assert "次数 已用 3 / 上限 — / 剩余 —" in zero
        app.accounts = (replace(account, enabled=False), *app.accounts[1:])
        app._rebuild()
        disabled = prompt(app, (app.accounts[0], "claude.subscription.five_hour"))
        assert "已禁用 / disabled" in disabled and "后" not in disabled
        await pilot.press("q")


async def test_untrusted_text_in_prompts_is_plain():
    app = UsageApp(mode="demo")
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        account = replace(app.accounts[0], label="\x1b[31m[bold]Unsafe[/bold]\x07")
        app.accounts = (account, *app.accounts[1:])
        snapshot = app.snapshots[account.id]
        metric = replace(snapshot.metrics[0], id="x.unsafe", label="[red]Odd\x1b[0m", detail="[b]x")
        app.publish_snapshot(replace(snapshot, metrics=(*snapshot.metrics, metric)))
        text = header(app, account) + prompt(app, (account, metric.id))
        assert "\x1b" not in text and "\x07" not in text and "[" not in text
        assert "Unsafe" in text and "Odd" in text
        await pilot.press("q")


def flat(text: str) -> str:
    return " ".join(text.split())


def lines_fit(app, text: str) -> bool:
    _, width, _ = app._layout()
    return all(cell_len(line) <= width for line in text.split("\n"))


@pytest.mark.parametrize("size", [(120, 30), (80, 24), (78, 24), (56, 40)])
async def test_header_diagnostic_and_hoisted_detail_wrap_whole_in_every_tier(size):
    app = UsageApp(mode="demo", scenario="errors")
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        for account in app.accounts:
            snapshot = app.snapshots[account.id]
            text = header(app, account)
            assert lines_fit(app, text)
            notes = [line for line in text.split("\n") if line.startswith(("  ⚠", "  ⓘ"))]
            assert notes and not any("…" in line for line in notes)
            if snapshot.diagnostic:
                assert snapshot.diagnostic.message in flat(text)
        auth = next(a for a in app.accounts if "auth required" in a.label)
        assert "current value unknown, never zero." in flat(header(app, auth))
        await pilot.press("q")


@pytest.mark.parametrize("size", [(120, 40), (80, 24), (56, 40)])
async def test_ready_quota_without_reset_reads_unknown_reset(size):
    app = UsageApp(mode="demo")
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        weekly = row(app, "codex.subscription.weekly")
        snapshot = app.snapshots[weekly[0].id]
        metric = replace(app._metric(*weekly), reset_at=None)
        app.publish_snapshot(replace(snapshot, metrics=(metric, *snapshot.metrics[1:])))
        text = prompt(app, weekly)
        assert "已用 24%" in text and "剩余 76%" in text and "重置 —" in text
        assert "后" not in text
        await pilot.press("q")


@pytest.mark.parametrize("size", [(72, 40), (60, 40), (56, 40)])
async def test_narrow_balance_amount_sits_on_its_label_line(size):
    app = UsageApp(mode="demo")
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        for metric_id, amount in (
            ("claude.platform.purchased_balance", "42.50 USD"),
            ("claude.platform.total_balance", "55.00 USD"),
        ):
            text = prompt(app, row(app, metric_id))
            first, second = text.split("\n")
            assert first.startswith("  Claude") and first.rstrip().endswith(amount)
            assert second.startswith("  余额") and "无周期重置" in second
            assert lines_fit(app, text)
        await pilot.press("q")


@pytest.mark.parametrize("size", [(78, 24), (80, 24)])
async def test_compact_medium_keeps_full_distinguishing_labels(size):
    app = UsageApp(mode="demo")
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        for metric_id, label in (
            ("claude.subscription.fable_weekly", "Claude Fable 每周用量"),
            ("claude.platform.purchased_balance", "Claude Platform 购买余额"),
        ):
            text = prompt(app, row(app, metric_id))
            assert label in text and "…" not in text and lines_fit(app, text)
        await pilot.press("q")


async def test_narrow_nesting_keeps_one_indent_and_tree_connector():
    app = UsageApp(mode="demo")
    async with app.run_test(size=(60, 90)) as pilot:
        await pilot.pause()
        five = prompt(app, row(app, "claude.subscription.five_hour")).split("\n")
        assert five[0].startswith("  Claude") and five[1].startswith("  █")
        build = prompt(app, row(app, "grok.product.build")).split("\n")
        assert build[0].startswith("  ├ GrokBuild")
        assert all(line.startswith("  │ ") for line in build[1:])
        chat = prompt(app, row(app, "grok.product.chat")).split("\n")
        assert chat[0].startswith("  └ GrokChat") and "│" not in "".join(chat[1:])
        await pilot.press("q")


async def test_hundred_columns_show_absolute_reset_time():
    app = UsageApp(mode="demo")
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        text = prompt(app, row(app, "claude.subscription.five_hour"))
        assert "2小时后 · 今天 14:00" in text and lines_fit(app, text)
        await pilot.press("q")


async def test_header_chips_form_one_column_for_long_labels():
    app = UsageApp(mode="demo", scenario="errors")
    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.pause()
        columns = set()
        for account in app.accounts:
            first = header(app, account).split("\n")[0]
            if account.label in first and any(c in first for c in "●◑▲✖"):
                chip = next(i for i, c in enumerate(first) if c in "●◑▲✖")
                columns.add(cell_len(first[:chip]))
        assert len(columns) == 1
        await pilot.press("q")


@pytest.mark.parametrize("size", [(120, 50), (80, 24), (40, 12)])
async def test_page_keys_never_clear_the_metric_selection(size):
    app = UsageApp(mode="demo")
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        assert app.highlighted_row() is None
        for keys in (("home", "pageup"), ("pagedown", "pagedown", "pageup", "pageup")):
            for key in keys:
                await pilot.press(key)
                assert app.highlighted_row() is not None
        selected = app.highlighted_row()
        app._tick()
        assert app.highlighted_row() == selected
        await pilot.press("end", "pagedown")
        assert app.highlighted_row() == app.rows[-1]
        await pilot.press("pageup", "enter")
        assert isinstance(app.screen, InformationScreen)
        await pilot.press("escape", "q")


@pytest.mark.parametrize(("scenario", "size"), [("healthy", (100, 30)), ("errors", (80, 24))])
async def test_clock_ticks_never_change_header_heights(scenario, size):
    app = UsageApp(mode="demo", scenario=scenario)
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        base = app.now()
        heights = []
        for seconds in (0, 56, 63, 602, 3_700, 7_203):
            app.now = lambda seconds=seconds: base + timedelta(seconds=seconds)
            app._render_rows()
            heights.append([str(o.prompt).count("\n") for o in app.listing._options if o.disabled])
        assert all(item == heights[0] for item in heights)
        await pilot.press("q")


async def test_selection_stays_visible_when_a_row_grows_on_tick():
    app = UsageApp(mode="demo", scenario="errors")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        listing = app.listing
        target = row(app, "claude.subscription.five_hour", "network")
        listing.highlighted = app.option_index(target)
        await pilot.pause()
        start, end = listing.highlight_span()
        listing.scroll_to(y=end - listing.scrollable_content_region.height, animate=False)
        await pilot.pause()
        snapshot = app.snapshots[target[0].id]
        grown = replace(snapshot.metrics[1], detail="A much longer synthetic note. " * 6)
        index = app.option_index(target)
        app.snapshots[target[0].id] = replace(
            snapshot, metrics=(snapshot.metrics[0], grown, *snapshot.metrics[2:])
        )
        app._render_rows()
        await pilot.pause()
        start, end = listing.highlight_span()
        top = listing.scroll_offset.y
        assert listing.highlighted == index
        assert top <= start and end <= top + listing.scrollable_content_region.height
        await pilot.press("q")


def header_heights(app) -> dict[str, int]:
    return {account.id: header(app, account).count("\n") for account, _ in app._groups()}


@pytest.mark.parametrize("size", [(110, 40), (80, 24)])
async def test_reorder_moves_headers_and_keeps_selection_state(size):
    app = UsageApp(mode="demo")
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        heights = header_heights(app)
        reordered = tuple(reversed(app.accounts))
        snapshots = dict(app.snapshots)
        async with app.account_lock:
            await app.accounts_changed(reordered, invalidate=frozenset())
        await pilot.pause()
        # An unselected dashboard stays unselected through a reorder.
        assert app.listing.highlighted is None and app.highlighted_row() is None
        assert [account for account, _ in app._groups()] == list(reordered)
        headers = [str(o.prompt) for o in app.listing._options if o.disabled]
        assert len(headers) == len(reordered)
        assert all(account.label in text for account, text in zip(reordered, headers, strict=True))
        assert set(app.snapshots) == set(snapshots)
        assert header_heights(app) == heights
        target = row(app, "codex.subscription.weekly")
        app.listing.highlighted = app.option_index(target)
        await pilot.pause()
        async with app.account_lock:
            await app.accounts_changed(tuple(reversed(reordered)), invalidate=frozenset())
        await pilot.pause()
        # The selected row keeps its account and metric, not its old position.
        assert app.highlighted_row() == target
        assert [account for account, _ in app._groups()] == list(reversed(reordered))
        assert header_heights(app) == heights
        await pilot.press("q")


def codex_extra(app, **fields):
    """Append a Codex credits row built from the demo weekly row (same provenance)."""
    weekly = row(app, "codex.subscription.weekly")
    snapshot = app.snapshots[weekly[0].id]
    metric = replace(
        app._metric(*weekly),
        id=MetricId.CODEX_CREDITS,
        label="Codex credits",
        quota=None,
        reset_at=None,
        **fields,
    )
    kept = tuple(m for m in snapshot.metrics if m.id != MetricId.CODEX_CREDITS)
    app.publish_snapshot(replace(snapshot, metrics=(*kept, metric)))
    return weekly[0], MetricId.CODEX_CREDITS


@pytest.mark.parametrize("size", [(120, 40), (80, 24), (56, 40)])
async def test_codex_credits_and_unlimited_are_whole_values_not_unknown(size):
    app = UsageApp(mode="demo")
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        for value, shown in (
            # Display rounds half-even to exactly two decimals; data stays exact.
            (Decimal("1234567.0000001"), "1234567.00 credits"),
            (Decimal("1E+5"), "100000.00 credits"),
            (Decimal(0), "0.00 credits"),
            (Decimal("-2.50"), "-2.50 credits"),
            (Decimal("137.5"), "137.50 credits"),
            (Decimal("0.125"), "0.12 credits"),
            (Decimal("0.135"), "0.14 credits"),
        ):
            target = codex_extra(app, credits=value)
            # Extras follow the required rows of their account.
            account_rows = [r for r in app.rows if r[0] == target[0]]
            assert account_rows[-1] == target and len(account_rows) == 3
            text = prompt(app, target)
            assert "Codex credits" in text and shown in text
            assert "未知" not in text and "no data" not in text
            assert "%" not in text and "USD" not in text and "重置" not in text
            assert "E+" not in text and lines_fit(app, text)
            assert shown in app.details(*target)
            # The snapshot (and so API JSON) keeps the exact wire value.
            assert app.snapshots[target[0].id].metrics[-1].credits == value
            if size[0] < 72:
                # Narrow: the bare amount sits on the label line.
                first, second = text.split("\n")[:2]
                assert first.rstrip().endswith(shown) and second.startswith("  余额")

        target = codex_extra(app, unlimited=True)
        text = prompt(app, target)
        assert "不限量 / Unlimited" in text and "未知" not in text and "credits" in text
        assert "不限量 / Unlimited" in app.details(*target)
        assert lines_fit(app, text)

        target = codex_extra(app, state=MetricState.UNKNOWN, detail="有可用 credits，但数量未知")
        text = prompt(app, target)
        assert "未知 / no data" in text and "数量未知" in text and "Unlimited" not in text
        assert not re.search(r"\d credits", text)
        assert "— 未知 / no data" in app.details(*target)
        await pilot.press("q")


@pytest.mark.parametrize("size", [(120, 40), (80, 24), (56, 40)])
async def test_claude_extra_usage_is_parse_only_and_never_displayed(size):
    app = UsageApp(mode="demo")
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        weekly = row(app, "claude.subscription.weekly")
        account = weekly[0]
        snapshot = app.snapshots[account.id]
        before_rows = list(app.rows)
        before_header = header(app, account)
        before_prompts = [prompt(app, r) for r in app.rows]
        assert "ⓘ" in before_header
        extra = replace(
            app._metric(*weekly),
            id=MetricId.CLAUDE_EXTRA_USAGE,
            label="Claude 额外用量",
            quota=QuotaValue(used_percent=Decimal("24.68")),
            reset_at=None,
            spent=Money(1234, "USD", 2),
            spend_limit=Money(5000, "USD", 2),
            detail="Extra usage spend this billing period; no reset time.",
        )
        app.publish_snapshot(replace(snapshot, metrics=(*snapshot.metrics, extra)))
        # The snapshot carries the parsed metric, but no consumer surface shows it.
        assert extra in app.snapshots[account.id].metrics
        assert app.rows == before_rows
        assert all(metric_id != MetricId.CLAUDE_EXTRA_USAGE for _, metric_id in app.rows)
        # Its distinct detail does not break the hoisted card note or stale count.
        assert header(app, account) == before_header
        assert [prompt(app, r) for r in app.rows] == before_prompts
        everything = "\n".join(
            [str(o.prompt) for o in app.listing._options]
            + [app.details(*r) for r in app.rows if r[0] == account]
        )
        for hidden in ("额外用量", "12.34", "50.00", "24.68", "no reset time"):
            assert hidden not in everything
        assert app._metric(account, MetricId.CLAUDE_EXTRA_USAGE) is None
        # A stale-only extra must not add a stale count either.
        app.publish_snapshot(
            replace(
                app.snapshots[account.id],
                metrics=(*snapshot.metrics, replace(extra, state=MetricState.UNKNOWN)),
            )
        )
        assert header(app, account) == before_header
        await pilot.press("q")


ROUNDED = "已舍入到分"
OPENAI = Account(
    id="77777777-7777-4777-8777-777777777777",
    provider=ProviderId.OPENAI_PLATFORM,
    label="Synthetic OpenAI",
    credential_kind=CredentialKind.OPENAI_PLATFORM_SESSION,
    credential_ref="memory:synthetic",
    organization_id="org-SyntheticOrg1234",
)
OPENAI_SOURCE = SourceRef(SourceKind.PRIVATE_HTTP, "openai.platform.billing.credit_grants", True)


def openai_snapshot(available, paid=None, *, state=MetricState.READY, detail=None):
    now = datetime.now(UTC)
    metrics = [
        Metric(
            MetricId.OPENAI_AVAILABLE_BALANCE,
            "OpenAI 可用余额",
            state,
            OPENAI_SOURCE,
            exact_balance=None if available is None else ExactMoney(available, "USD"),
            detail=detail,
        )
    ]
    if paid is not None:
        metrics.append(
            Metric(
                MetricId.OPENAI_PAID_AVAILABLE_BALANCE,
                "OpenAI 付费余额",
                MetricState.READY,
                OPENAI_SOURCE,
                exact_balance=ExactMoney(paid, "USD"),
            )
        )
    return Snapshot(
        OPENAI.id,
        tuple(metrics),
        (),
        FetchState.OK if state == MetricState.READY else FetchState.SCHEMA_ERROR,
        now,
        fetched_at=now if state == MetricState.READY else None,
    )


@pytest.mark.parametrize("size", [(140, 40), (120, 40), (80, 24), (56, 40)])
async def test_openai_exact_balance_rounds_to_cents_with_note_in_every_tier(size):
    app = UsageApp(mode="live", accounts=(OPENAI,), scheduler_factory=lambda *a, **kw: None)
    async with app.run_test(size=size) as pilot:
        for available, shown, rounded in (
            (Decimal("17.3715455"), "17.37 USD", True),
            (Decimal("4.9"), "4.90 USD", False),
            (Decimal("0.125"), "0.12 USD", True),  # half-even, not half-up
            (Decimal("0.135"), "0.14 USD", True),
            (Decimal("-3.07"), "-3.07 USD", False),
            (Decimal(0), "0.00 USD", False),
            (Decimal("1234567890.005"), "1234567890.00 USD", True),
        ):
            app.publish_snapshot(openai_snapshot(available, Decimal("4.9")))
            await pilot.pause()
            target = (OPENAI, MetricId.OPENAI_AVAILABLE_BALANCE)
            text = prompt(app, target)
            assert "OpenAI 可用余额" in text and shown in text, text
            assert "未知" not in text and "%" not in text
            # The note wraps whole (never truncated) and appears only when rounding changed it.
            assert (ROUNDED in flat(text)) == rounded and "舍入" not in text.split("\n")[0]
            assert lines_fit(app, text)
            details = app.details(*target)
            assert shown in details and (ROUNDED in details) == rounded
            assert f"精确金额 / exact: {available:f} USD" in details
            # The snapshot keeps the exact amount; display alone rounds.
            assert app.snapshots[OPENAI.id].metrics[0].exact_balance.amount == available
            if size[0] < 72:
                first, second = text.split("\n")[:2]
                assert first.rstrip().endswith(shown) and second.startswith("  余额")
            paid = prompt(app, (OPENAI, MetricId.OPENAI_PAID_AVAILABLE_BALANCE))
            assert "4.90 USD" in paid and "舍入" not in paid and lines_fit(app, paid)
            if size[0] >= 100:
                # Wide rows keep the whole distinguishing label.
                assert "OpenAI 付费余额" in paid
        await pilot.press("q")


async def test_openai_unknown_balance_is_unknown_not_zero():
    app = UsageApp(mode="live", accounts=(OPENAI,), scheduler_factory=lambda *a, **kw: None)
    async with app.run_test(size=(120, 30)) as pilot:
        app.publish_snapshot(
            openai_snapshot(
                None,
                state=MetricState.UNKNOWN,
                detail="Available balance is missing or invalid; missing does not mean zero.",
            )
        )
        await pilot.pause()
        target = (OPENAI, MetricId.OPENAI_AVAILABLE_BALANCE)
        text = prompt(app, target) + header(app, OPENAI)
        assert "未知 / no data" in text and "missing does not mean zero" in text
        assert "0.00" not in text and "USD" not in text and "舍入" not in text
        assert [m for _, m in app.rows] == [MetricId.OPENAI_AVAILABLE_BALANCE]
        assert "精确金额" not in app.details(*target)
        await pilot.press("q")


@pytest.mark.parametrize("size", [(120, 40), (80, 24), (56, 40)])
async def test_claude_credit_balance_row_follows_required_rows(size):
    app = UsageApp(mode="demo")
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        weekly = row(app, "claude.subscription.weekly")
        account = weekly[0]
        snapshot = app.snapshots[account.id]
        credit = replace(
            app._metric(*weekly),
            id=MetricId.CLAUDE_CREDIT_BALANCE,
            label="Claude 已购 credits 余额",
            quota=None,
            reset_at=None,
            balance=Money(123456789, "USD", 2),
        )
        others = tuple(m for m in snapshot.metrics if m.id != MetricId.CLAUDE_CREDIT_BALANCE)
        app.publish_snapshot(replace(snapshot, metrics=(*others, credit)))
        await pilot.pause()
        account_rows = [m for a, m in app.rows if a == account]
        assert account_rows[-1] == MetricId.CLAUDE_CREDIT_BALANCE
        target = (account, MetricId.CLAUDE_CREDIT_BALANCE)
        text = prompt(app, target)
        assert "1234567.89 USD" in text and "未知" not in text and "%" not in text
        assert "舍入" not in text and lines_fit(app, text)
        assert "1234567.89 USD" in app.details(*target)
        unknown = replace(
            credit, state=MetricState.UNKNOWN, balance=None, detail="Org not found; re-select."
        )
        app.publish_snapshot(replace(snapshot, metrics=(*others, unknown)))
        await pilot.pause()
        text = prompt(app, target)
        assert "未知 / no data" in text and "USD" not in text
        await pilot.press("q")
