"""Grouped dashboard prompts: observable text of the actual headless OptionList."""

import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from rich.cells import cell_len

from usage_tui.app import InformationScreen, UsageApp, short_local_time
from usage_tui.domain import (
    Account,
    Diagnostic,
    FetchState,
    MetricState,
    Money,
    ProviderId,
    QuotaValue,
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
        assert app.highlighted_row() == app.rows[0]
        seen = []
        for _ in range(len(app.rows) + 2):
            await pilot.press("down")
            assert app.highlighted_row() is not None
            seen.append(app.highlighted_row())
        assert set(seen) == set(app.rows)
        for key in ("home", "up", "up", "end", "home"):
            await pilot.press(key)
            assert app.highlighted_row() is not None
        await pilot.press("down", "down", "down", "down")
        selected = app.highlighted_row()
        assert selected[1] == "claude.platform.promotional_balance"
        await pilot.press("enter")
        assert isinstance(app.screen, InformationScreen)
        assert app.screen.content.startswith(app._row_text(*selected).split("\n")[0])
        await pilot.press("escape", "q")


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
        assert "Wait until the retry deadline" in text
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
        for metric_id in ("grok.product.build", "grok.product.chat"):
            product = prompt(app, row(app, metric_id, "rate limited"))
            assert "非独立额度" in product and "同共享池" in product
            assert "剩余" not in product.split("\n")[0]
            assert not any(glyph in product for glyph in BARS)
        missing = prompt(app, row(app, "grok.product.build", "missing products"))
        assert "未知 / no data" in missing and "剩余" not in missing.split("\n")[0]
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
        assert "1234567.89 USD" in text and "非周期重置" in text and "到期" in text
        assert "后" not in text and "%" not in text
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
        assert "STALE 过期 1/3" in header(app, five[0])
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


@pytest.mark.parametrize("size", [(120, 50), (80, 24), (56, 40)])
async def test_incomplete_console_fetch_never_shows_a_zero_grant_count(size):
    app = UsageApp(mode="demo")
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        account = row(app, "claude.platform.purchased_balance")[0]
        snapshot = app.snapshots[account.id]
        assert snapshot.grants and "赠款 2 项" in flat(header(app, account))
        unknown = replace(snapshot.metrics[0], state=MetricState.UNKNOWN, balance=None)
        partial = replace(
            snapshot,
            metrics=(unknown, *snapshot.metrics[1:]),
            fetch_state=FetchState.PARTIAL,
            diagnostic=Diagnostic("partial_data"),
        )
        app.publish_snapshot(replace(partial, grants=()))
        text = flat(header(app, account))
        assert "赠款 0" not in text and "赠款 — 项（未知）" in text
        app.publish_snapshot(partial)
        text = flat(header(app, account))
        assert "赠款 ≥2 项（部分未知）" in text and "赠款 2 项" not in text
        await pilot.press("q")


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
        for keys in (("home", "pageup"), ("pagedown", "pagedown", "pageup", "pageup")):
            for key in keys:
                await pilot.press(key)
                assert app.highlighted_row() is not None
        app._tick()
        assert app.highlighted_row() == app.rows[0]
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
