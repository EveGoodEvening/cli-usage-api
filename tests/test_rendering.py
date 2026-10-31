"""Text rendering preserves domain truth instead of deriving quota from timers."""

import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest

from cli_usage_api.app import METRIC_LABELS, UsageApp, local_time, metric_label, metric_value
from cli_usage_api.demo import DEMO_NOW
from cli_usage_api.domain import (
    Account,
    CredentialKind,
    ExactMoney,
    FetchState,
    Metric,
    MetricId,
    MetricState,
    ProviderId,
    QuotaValue,
    ResolvedCredential,
    SourceKind,
    SourceRef,
)
from cli_usage_api.providers.claude import ClaudeProvider
from cli_usage_api.providers.codex import CodexProvider
from cli_usage_api.providers.grok import MISSING_DETAIL as GROK_MISSING
from cli_usage_api.transport import Transport


def shown(app, row=None) -> str:
    """Text the dashboard actually displays: one metric prompt, or every option."""
    if row is not None:
        return str(app.listing.get_option_at_index(app.option_index(row)).prompt)
    return "\n".join(str(option.prompt) for option in app.listing._options)


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
            "Codex weekly (7d)",
            "Codex 5h",
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
        assert "属于共享池 fictional-grok-pool" in details
        products = [r for r in app.rows if r[1].startswith("grok.product.")]
        for product in products:
            # The structured share reads as used only: no derived remaining.
            assert "已用" in app._row_text(*product) and "剩余" not in app._row_text(*product)
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


async def test_live_codex_duration_rows_provenance_and_missing_weekly():
    account = Account(
        id="11111111-1111-4111-8111-111111111111",
        provider=ProviderId.CODEX_SUBSCRIPTION,
        label="Synthetic Codex",
        credential_kind=CredentialKind.CODEX_AUTH_FILE,
        credential_ref="synthetic-auth.json",
    )
    credential = ResolvedCredential(
        account.provider,
        CredentialKind.CODEX_AUTH_FILE,
        "synthetic-secret",
        "generation-1",
        codex_account_id="synthetic-account",
    )
    bodies = [
        {
            "rate_limit": {
                "primary_window": {"limit_window_seconds": 18000, "used_percent": 20},
                "secondary_window": {"limit_window_seconds": 604800, "used_percent": 35},
            }
        },
        {
            "rate_limit": {
                "primary_window": {"limit_window_seconds": 300, "used_percent": 8},
            }
        },
    ]
    http_transport = httpx.MockTransport(lambda _: httpx.Response(200, json=bodies.pop(0)))
    transport = Transport(http_transport=http_transport)
    provider = CodexProvider(transport)
    app = UsageApp(mode="live", accounts=(account,), scheduler_factory=lambda *a, **kw: None)
    try:
        async with app.run_test() as pilot:
            app.publish_snapshot(await provider.fetch(account, credential, DEMO_NOW))
            assert [metric_id for _, metric_id in app.rows] == [
                "codex.subscription.weekly",
                "codex.subscription.five_hour",
            ]
            weekly = app._row_text(account, "codex.subscription.weekly")
            five_hour = app._row_text(account, "codex.subscription.five_hour")
            assert "Codex weekly (7d)" in weekly and "35%" in weekly
            assert "Codex 5h" in five_hour and "20%" in five_hour
            visible_weekly = shown(app, (account, "codex.subscription.weekly"))
            assert "Codex weekly (7d)" in visible_weekly and "已用 35%" in visible_weekly
            assert "剩余 65%" in visible_weekly
            assert "已用 20%" in shown(app, (account, "codex.subscription.five_hour"))
            details = app.details(account, "codex.subscription.weekly")
            assert "private_http" in details and "codex.wham.usage.v1" in details
            app.publish_snapshot(await provider.fetch(account, credential, DEMO_NOW))
            assert [metric_id for _, metric_id in app.rows] == [
                "codex.subscription.weekly",
                "codex.subscription.window.300",
            ]
            weekly = app._row_text(account, "codex.subscription.weekly")
            assert "未知 / no data" in weekly and "已用 0" not in weekly
            assert "Codex 5m" in app._row_text(account, "codex.subscription.window.300")
            assert "8%" in app._row_text(account, "codex.subscription.window.300")
            visible_weekly = shown(app, (account, "codex.subscription.weekly"))
            assert "未知 / no data" in visible_weekly and "已用" not in visible_weekly
            window = shown(app, (account, "codex.subscription.window.300"))
            assert "Codex 5m" in window and "已用 8%" in window
            await pilot.press("q")
    finally:
        await http_transport.aclose()


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
        dashboard = shown(app) + str(app.status_line.content)
        assert "Unsafe" in dashboard and "NEVER_SHOW_THIS" not in dashboard
        assert "\x1b" not in dashboard and "\x07" not in dashboard and "[red]" not in dashboard
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
        assert "未知 / no data" in shown(app, (account, metric_id))
        assert "已用" not in shown(app, (account, metric_id))
        await pilot.press("q")


@pytest.fixture(params=[("Asia/Shanghai", datetime.max), ("America/Los_Angeles", datetime.min)])
def saturated_local_timezone(request, monkeypatch):
    timezone, boundary = request.param
    try:
        with monkeypatch.context() as patch:
            patch.setenv("TZ", timezone)
            time.tzset()
            yield boundary.replace(tzinfo=UTC)
    finally:
        time.tzset()


def test_local_time_preserves_utc_at_both_conversion_boundaries(saturated_local_timezone):
    boundary = saturated_local_timezone
    assert local_time(boundary) == boundary.isoformat() + " (UTC)"
    assert local_time(None) == "—"


async def test_saturated_retry_response_renders_without_local_overflow(saturated_local_timezone):
    account = Account(
        id="11111111-1111-4111-8111-111111111111",
        provider=ProviderId.CLAUDE_SUBSCRIPTION,
        label="Synthetic rate limit",
        credential_kind=CredentialKind.MANUAL_BEARER,
        credential_ref="session:synthetic",
    )
    transport = Transport(
        http_transport=httpx.MockTransport(
            lambda _: httpx.Response(429, headers={"Retry-After": "9" * 5000})
        ),
        clock=lambda: DEMO_NOW,
    )
    credential = ResolvedCredential(
        account.provider, CredentialKind.MANUAL_BEARER, "synthetic-secret", "generation-1"
    )
    snapshot = await ClaudeProvider(transport).fetch(account, credential, DEMO_NOW)
    assert snapshot.fetch_state == FetchState.RATE_LIMITED
    assert snapshot.retry_at == datetime.max.replace(tzinfo=UTC)
    app = UsageApp(mode="live", accounts=(account,), scheduler_factory=lambda *a, **kw: None)
    # Pin the countdown clock: the remaining days otherwise shrink as real time passes.
    app.now = lambda: DEMO_NOW
    days = (snapshot.retry_at - DEMO_NOW).days
    async with app.run_test() as pilot:
        app.publish_snapshot(snapshot)
        app._tick()
        row = app._row_text(account, snapshot.metrics[0].id)
        assert "rate_limited" in row and "重试 / retry" in row
        assert local_time(snapshot.retry_at) in row
        header = str(app.listing.get_option_at_index(0).prompt)
        assert "限流" in header and "重试 / retry 9999-12-31" in header and f"{days}天" in header
        assert snapshot.retry_at.isoformat() in app.details(account, snapshot.metrics[0].id)
        assert app.metric_option_count() == 3
        await pilot.press("q")


async def test_snapshot_extras_follow_emission_order_and_preserve_unknown_truth():
    app = UsageApp(mode="demo")
    async with app.run_test() as pilot:
        account = next(a for a in app.accounts if a.provider == ProviderId.GROK_SUBSCRIPTION)
        snapshot = app.snapshots[account.id]
        product = snapshot.metrics[-1]
        first = replace(
            product,
            id="grok.product.other.first",
            label="First other product",
            detail="Reported consumption share: 10%. Not an independent quota.",
            quota=None,
            share_percent=Decimal(10),
        )
        unknown = replace(
            first,
            id="grok.product.other.unknown",
            label="Unknown other product",
            state=MetricState.UNKNOWN,
            detail=GROK_MISSING,
            shared_pool_id=None,
            reset_at=None,
            share_percent=None,
        )
        app.publish_snapshot(replace(snapshot, metrics=(first, *snapshot.metrics, unknown)))
        required = [metric.id for metric in snapshot.metrics]
        ids = [metric_id for row_account, metric_id in app.rows if row_account == account]
        assert ids == [*required, first.id, unknown.id]
        assert len(ids) == len(set(ids))
        index = app.option_index((account, first.id))
        app.listing.highlighted = index
        shown_first = str(app.listing.get_option_at_index(index).prompt)
        assert "已用 10%" in shown_first and "剩余" not in shown_first
        details = app.details(account, first.id)
        assert "provenance" in details and "consumption share: 10%" in details
        assert "剩余 90%" not in details
        unknown_text = app._row_text(account, unknown.id)
        assert "未知 / no data" in unknown_text and "missing does not mean zero" in unknown_text
        # The dashboard placeholder already says unknown; only details keep the caveat.
        shown_unknown = str(
            app.listing.get_option_at_index(app.option_index((account, unknown.id))).prompt
        )
        assert (
            "未知 / no data" in shown_unknown and "missing does not mean zero" not in shown_unknown
        )
        assert "已用 0" not in unknown_text and "剩余 100" not in unknown_text
        # A new extra before the highlighted one must not change the selection.
        earlier = replace(first, id="grok.product.other.earlier", label="Earlier product")
        app.publish_snapshot(
            replace(snapshot, metrics=(*snapshot.metrics, earlier, first, unknown))
        )
        assert app.highlighted_row() == (account, first.id)
        assert [metric_id for a, metric_id in app.rows if a == account] == [
            *required,
            earlier.id,
            first.id,
            unknown.id,
        ]
        app.publish_snapshot(replace(snapshot, metrics=()))
        assert [metric_id for a, metric_id in app.rows if a == account] == required
        assert all("未知 / no data" in app._row_text(account, metric_id) for metric_id in required)
        await pilot.press("q")


def test_exact_money_and_credits_text_round_half_even_for_display_only():
    source = SourceRef(SourceKind.PRIVATE_HTTP, "synthetic", True)
    exact = Metric(
        MetricId.OPENAI_AVAILABLE_BALANCE,
        "x",
        MetricState.READY,
        source,
        exact_balance=ExactMoney(Decimal("17.3715455"), "USD"),
    )
    assert metric_value(exact) == "17.37 USD"
    assert exact.exact_balance.amount == Decimal("17.3715455")
    half = replace(exact, exact_balance=ExactMoney(Decimal("2.665"), "USD"))
    assert metric_value(half) == "2.66 USD"
    credits = Metric(
        MetricId.CODEX_CREDITS, "x", MetricState.READY, source, credits=Decimal("137.5")
    )
    assert metric_value(credits) == "137.50 credits"
    assert metric_value(replace(credits, credits=Decimal("1E+3"))) == "1,000.00 credits"
    assert metric_value(replace(credits, credits=Decimal("0.005"))) == "0.00 credits"
    grouped = replace(credits, credits=Decimal("12345.5"))
    assert metric_value(grouped) == "12,345.50 credits" and grouped.credits == Decimal("12345.5")
    assert metric_value(
        replace(exact, exact_balance=ExactMoney(Decimal("-1234567.891"), "USD"))
    ) == ("-1,234,567.89 USD")
    # Unknown never renders a number.
    unknown = replace(exact, state=MetricState.UNKNOWN, exact_balance=None)
    assert metric_value(unknown) == "— 未知 / no data"


def test_new_metric_ids_have_dashboard_labels():
    for metric_id, label in (
        (MetricId.CLAUDE_CREDIT_BALANCE, "Claude credits 余额"),
        (MetricId.OPENAI_AVAILABLE_BALANCE, "OpenAI 可用余额"),
        (MetricId.OPENAI_PAID_AVAILABLE_BALANCE, "OpenAI 付费余额"),
    ):
        assert METRIC_LABELS[metric_id] == label
        assert metric_label(metric_id, None) == label
