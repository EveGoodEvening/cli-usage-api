"""Text rendering preserves domain truth instead of deriving quota from timers."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from usage_tui.app import UsageApp, metric_value
from usage_tui.demo import DEMO_NOW
from usage_tui.domain import (
    Account,
    CredentialKind,
    Metric,
    MetricState,
    ProviderId,
    QuotaValue,
    SourceKind,
    SourceRef,
)
from usage_tui.providers.chatgpt import ChatGPTProvider


async def test_all_required_provider_rows_values_and_details():
    app = UsageApp(mode="demo")
    async with app.run_test(size=(80, 24)) as pilot:
        text = "\n".join(app._row_text(*row) for row in app.rows)
        for label in (
            "Claude 5h",
            "Claude 每周",
            "Fable",
            "购买余额",
            "赠送余额",
            "ChatGPT",
            "GrokBuild",
            "GrokChat",
            "Grok 共享池",
        ):
            assert label in text
        assert "已用" in text and "剩余" in text and "USD" in text
        assert "重置" in text and "尝试 / attempt" in text
        details = "\n".join(app.details(*row) for row in app.rows)
        assert "offline_demo" in details and "synthetic-demo-v1" in details
        assert "grant" in details and "UTC" in details
        assert "不是可相加的独立额度" in details
        assert "不代表真实账号" in str(app.banner.content)
        await pilot.press("q")


async def test_errors_are_textual_and_keep_last_good_separate():
    app = UsageApp(mode="demo", scenario="errors")
    async with app.run_test() as pilot:
        text = "\n".join(app._row_text(*row) for row in app.rows)
        for state in (
            "auth_required",
            "permission_denied",
            "rate_limited",
            "network_error",
            "partial",
        ):
            assert state in text
        assert "LAST KNOWN" in text and "STALE" in text
        assert "retry" in text and "未知 / no data" in text
        await pilot.press("q")


async def test_countdown_passes_reset_without_changing_observation():
    app = UsageApp(mode="demo")
    async with app.run_test() as pilot:
        account, metric_id = next(
            row for row in app.rows if row[1] == "claude.subscription.five_hour"
        )
        snapshot = app.snapshots[account.id]
        metric = app._metric(account, metric_id)
        app.scheduler.tick((metric.reset_at - app.now()).total_seconds() + 1)
        app._render_rows()
        text = app._row_text(account, metric_id)
        assert "awaiting refresh" in text and "STALE" in text
        assert app.snapshots[account.id] is snapshot
        assert app._metric(account, metric_id).quota == metric.quota
        await pilot.press("q")


def test_numeric_overage_and_unknown_never_become_zero():
    metric = Metric(
        id="quota",
        label="Quota",
        state=MetricState.READY,
        source=SourceRef(SourceKind.OFFLINE_DEMO, "test"),
        quota=QuotaValue(used_percent=Decimal("125.5")),
    )
    text = metric_value(metric)
    assert "125.5%" in text and "剩余 0%" in text
    assert "[##########]" in text
    assert "未知" in metric_value(replace(metric, state=MetricState.UNKNOWN, quota=None))


async def test_live_blocked_chatgpt_is_not_synthetic_success():
    account = Account(
        id="11111111-1111-4111-8111-111111111111",
        provider=ProviderId.CHATGPT_SUBSCRIPTION,
        label="Blocked",
    )
    snapshot = await ChatGPTProvider().fetch(account, None, DEMO_NOW)
    # Rendering can be exercised before mounting; no scheduler or network needed.
    app = UsageApp(mode="live", accounts=(account,), scheduler_factory=lambda *args, **kwargs: None)
    app.snapshots[account.id] = snapshot
    text = app._row_text(account, snapshot.metrics[0].id)
    assert "blocked" in text and "upstream_contract_missing" in text
    assert "不使用 Codex/Work" in text
    assert "已用" not in text
    assert "unresolved" in app.details(account, snapshot.metrics[0].id)


async def test_untrusted_labels_remain_plain_and_no_credential_reference_rendered():
    app = UsageApp(mode="demo")
    async with app.run_test() as pilot:
        original = app.accounts[0]
        account = replace(
            original,
            label="\x1b[31m[red]Unsafe[/red]\x07",
            credential_ref="session:NEVER_SHOW_THIS",
            credential_kind=CredentialKind.MANUAL_BEARER,
        )
        app.accounts = (account,) + app.accounts[1:]
        app._rebuild()
        text = "\n".join(app._row_text(*row) for row in app.rows)
        assert "\x1b" not in text and "\x07" not in text and "[red]" not in text
        assert "NEVER_SHOW_THIS" not in text
        await pilot.press("q")


async def test_fresh_success_missing_metric_does_not_preserve_current_value():
    app = UsageApp(mode="demo")
    async with app.run_test() as pilot:
        account, metric_id = app.rows[0]
        snapshot = app.snapshots[account.id]
        app.publish_snapshot(
            replace(
                snapshot,
                metrics=tuple(m for m in snapshot.metrics if m.id != metric_id),
                attempted_at=DEMO_NOW + timedelta(seconds=1),
            )
        )
        assert "未知 / no data" in app._row_text(account, metric_id)
        assert "已用" not in app._row_text(account, metric_id)
        await pilot.press("q")
