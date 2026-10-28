"""Dependency-injected Chinese terminal dashboard; demo stays completely offline."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from decimal import Decimal

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Label, OptionList, Select, Static
from textual.widgets.option_list import Option

from usage_tui.accounts import GUIDANCE, AccountManagerScreen
from usage_tui.demo import DemoSource
from usage_tui.domain import (
    REQUIRED_METRIC_IDS,
    Account,
    Metric,
    MetricState,
    Snapshot,
    sanitize_text,
)
from usage_tui.scheduler import freshness

METRIC_LABELS = {
    "claude.subscription.five_hour": "Claude 5h 用量",
    "claude.subscription.weekly": "Claude 每周用量",
    "claude.subscription.fable_weekly": "Claude Fable 每周用量",
    "claude.platform.purchased_balance": "Claude Platform 购买余额",
    "claude.platform.promotional_balance": "Claude Platform 赠送余额",
    "claude.platform.total_balance": "Claude Platform 总余额",
    "chatgpt.subscription.weekly": "ChatGPT 每周用量",
    "grok.subscription.shared_pool": "Grok 共享池用量",
    "grok.product.build": "GrokBuild 共享池消耗",
    "grok.product.chat": "GrokChat 共享池消耗",
}
STATE_LABELS = {
    "ok": "正常",
    "partial": "部分数据",
    "unconfigured": "未配置",
    "auth_required": "需要重新连接",
    "permission_denied": "权限不足",
    "rate_limited": "限流",
    "network_error": "网络错误",
    "provider_error": "服务错误",
    "schema_error": "数据格式错误",
    "upstream_contract_missing": "阻塞：上游契约缺失",
}


def local_time(value: datetime | None) -> str:
    if value is None:
        return "—"
    try:
        return value.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    except OverflowError:
        # Saturated UTC deadlines may be outside the local timezone's range.
        return utc_time(value) + " (UTC)"


def utc_time(value: datetime | None) -> str:
    return "—" if value is None else value.astimezone(UTC).isoformat()


def countdown(value: datetime, now: datetime) -> str:
    seconds = max(0, int((value - now).total_seconds()))
    if not seconds:
        return "等待刷新 / awaiting refresh"
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return f"{days}天 {hours:02}:{minutes:02}:{seconds:02}"


def metric_value(metric: Metric) -> str:
    if metric.state != MetricState.READY:
        return {
            MetricState.UNKNOWN: "— 未知 / no data",
            MetricState.BLOCKED: "— 阻塞 / blocked",
            MetricState.NOT_APPLICABLE: "— 不适用 / not applicable",
        }[metric.state]
    if metric.balance is not None:
        return metric.balance.format()
    if metric.quota is not None:
        quota = metric.quota
        parts = []
        if quota.used_percent is not None:
            used = quota.used_percent
            filled = int(min(Decimal(100), used) / 10)
            parts.append(
                f"已用 {used}% 剩余 {quota.remaining_percent if quota.remaining_percent is not None else '—'}%"
            )
            parts.append("[" + "#" * filled + "-" * (10 - filled) + "]")
        if any(
            value is not None
            for value in (quota.used_count, quota.limit_count, quota.remaining_count)
        ):
            parts.append(
                f"已用 {quota.used_count if quota.used_count is not None else '—'} / 上限 {quota.limit_count if quota.limit_count is not None else '—'} / 剩余 {quota.remaining_count if quota.remaining_count is not None else '—'}"
            )
        return " ".join(parts) or "— 未知 / no data"
    # Product percentages are detail-only: they are not independent allowances.
    return "共享池消耗明细（非独立额度）" if metric.shared_pool_id else "— 未知 / no data"


class InformationScreen(Screen[None]):
    BINDINGS = (("escape", "back", "返回"), ("?", "back", "返回"))

    def __init__(self, title: str, content: str) -> None:
        super().__init__()
        self.heading = title
        self.content = content

    def compose(self) -> ComposeResult:
        yield Label(self.heading, markup=False)
        with VerticalScroll():
            yield Static(self.content, markup=False)
        yield Static("Esc 返回 · ↑↓ / PgUp PgDn 滚动", markup=False)

    def action_back(self) -> None:
        self.dismiss(None)


class UsageApp(App[None]):
    """Live factory signature: factory(accounts, *, publish) -> scheduler.

    The callable may expose resolver, console_discovery (the bound
    ConsoleProvider.discover_organizations method), and async aclose(). The app
    owns the returned scheduler lifecycle and closes factory-owned clients after
    stopping it. A configured live dashboard requires this explicit factory.
    """

    CSS_PATH = "app.tcss"
    BINDINGS = (
        Binding("q", "quit", "退出"),
        Binding("ctrl+c", "quit", "退出", priority=True),
        Binding("r", "refresh", "刷新"),
        Binding("a", "accounts", "账号"),
        Binding("?", "help", "帮助"),
    )

    def __init__(
        self,
        *,
        mode: str,
        accounts=(),
        scheduler_factory=None,
        account_store=None,
        credential_store=None,
        scenario: str = "healthy",
    ) -> None:
        if mode not in {"live", "demo"}:
            raise ValueError("Mode must be live or demo.")
        if (
            mode == "live"
            and scheduler_factory is None
            and (accounts or account_store is not None or credential_store is not None)
        ):
            raise ValueError("Configured live mode requires a scheduler factory.")
        super().__init__()
        self.mode = mode
        self.accounts = tuple(accounts)
        self.scheduler_factory = scheduler_factory
        self.account_store = account_store
        self.credential_store = credential_store
        self.snapshots: dict[str, Snapshot] = {}
        self.selected_account: str | None = None
        self.rows: list[tuple[Account, str]] = []
        self._usage_closed = False
        self._refreshing = False
        self._notice = ""
        self.scheduler = None
        if mode == "demo":
            self.scheduler = DemoSource(scenario=scenario, publish=self.publish_snapshot)
            self.accounts = self.scheduler.accounts
        self.banner = Static(id="banner", markup=False)
        self.selector = Select(
            self._account_options(), value="all", allow_blank=False, id="account-selector"
        )
        self.status_line = Static(id="dashboard-status", markup=False)
        self.listing = OptionList(id="metrics")
        self.hint = Static(id="resize-hint", markup=False)

    def _account_options(self):
        return [("全部账号", "all")] + [
            (sanitize_text(account.label, max_length=80), account.id) for account in self.accounts
        ]

    def compose(self) -> ComposeResult:
        yield self.banner
        yield self.selector
        yield self.status_line
        yield self.listing
        yield self.hint
        yield Footer()

    async def on_mount(self) -> None:
        if self.mode == "live" and self.scheduler_factory is not None:
            self.scheduler = self.scheduler_factory(self.accounts, publish=self.publish_snapshot)
        self._rebuild()
        if self.scheduler is not None:
            await self.scheduler.start()
        self.set_interval(1, self._tick)
        self.listing.focus()

    def now(self) -> datetime:
        if self.mode == "demo":
            return self.scheduler.clock.now()
        return datetime.now(UTC)

    def publish_snapshot(self, snapshot: Snapshot) -> None:
        if self._usage_closed or snapshot.account_id not in {
            account.id for account in self.accounts
        }:
            return
        self.snapshots[snapshot.account_id] = snapshot
        if self.listing.is_mounted:
            self._render_rows()

    def _tick(self) -> None:
        if self._usage_closed:
            return
        if self.mode == "demo":
            self.scheduler.tick()
        self._render_rows()

    def on_resize(self) -> None:
        if self.listing.is_mounted:
            self._render_header()

    def _render_header(self) -> None:
        demo = self.mode == "demo"
        compact = self.size.width < 80 or self.size.height < 24
        if self.screen_stack:
            self.screen_stack[0].set_class(compact, "compact")
        self.banner.update(
            "DEMO 离线合成演示 — 不代表真实账号或 ChatGPT 已支持"
            if demo
            else "LIVE 实时账号用量（有界轮询）"
        )
        self.hint.update(
            "窗口较小：↑↓ 滚动，Enter 详情；建议放大终端"
            if self.size.width < 80 or self.size.height < 24
            else "Tab 切换 · ↑↓ 选择/滚动 · Enter 详情 · ? 帮助"
        )
        if not self.accounts:
            message = "暂无账号 / No accounts — 按 a 打开账号管理并添加连接。"
        else:
            visible = [
                account
                for account in self.accounts
                if account.enabled
                and (self.selected_account is None or account.id == self.selected_account)
            ]
            observed = [
                (account, self.snapshots[account.id])
                for account in visible
                if account.id in self.snapshots
            ]
            stale = sum(
                freshness(snapshot, self.now(), account.poll_interval_seconds).stale
                for account, snapshot in observed
            )
            retries = [
                snapshot.retry_at
                for _, snapshot in observed
                if snapshot.retry_at is not None and snapshot.retry_at > self.now()
            ]
            message = f"fresh {len(observed) - stale} · STALE {stale} · pending {len(visible) - len(observed)}"
            if retries:
                message += f" · retry {countdown(min(retries), self.now())}"
        self.status_line.update(message + ("\n" + self._notice if self._notice else ""))

    def _visible_rows(self) -> list[tuple[Account, str]]:
        rows = []
        for account in self.accounts:
            if self.selected_account is not None and account.id != self.selected_account:
                continue
            seen = set(REQUIRED_METRIC_IDS[account.provider])
            rows.extend((account, metric_id) for metric_id in REQUIRED_METRIC_IDS[account.provider])
            snapshot = self.snapshots.get(account.id)
            if snapshot is not None:
                for metric in snapshot.metrics:
                    if metric.id not in seen:
                        rows.append((account, metric.id))
                        seen.add(metric.id)
        return rows

    def _rebuild(self, rows: list[tuple[Account, str]] | None = None) -> None:
        highlighted = self.listing.highlighted
        selected = (
            self.rows[highlighted]
            if highlighted is not None and highlighted < len(self.rows)
            else None
        )
        self.rows = self._visible_rows() if rows is None else rows
        self.listing.clear_options()
        for index, (account, metric_id) in enumerate(self.rows):
            self.listing.add_option(Option(Text(self._row_text(account, metric_id)), id=str(index)))
        if self.rows:
            self.listing.highlighted = (
                self.rows.index(selected)
                if selected in self.rows
                else min(highlighted or 0, len(self.rows) - 1)
            )
        self._render_header()

    def _metric(self, account: Account, metric_id: str) -> Metric | None:
        snapshot = self.snapshots.get(account.id)
        return (
            next((metric for metric in snapshot.metrics if metric.id == metric_id), None)
            if snapshot
            else None
        )

    def _row_text(self, account: Account, metric_id: str) -> str:
        snapshot = self.snapshots.get(account.id)
        metric = self._metric(account, metric_id)
        label = METRIC_LABELS.get(metric_id, metric.label if metric else metric_id)
        heading = f"{sanitize_text(account.label, max_length=80)} · {label}"
        if not account.enabled:
            return heading + "\n  — 已禁用 / disabled"
        if snapshot is None:
            return heading + "\n  — 暂无数据 / no data · 等待首次观察 / pending"
        state = freshness(snapshot, self.now(), account.poll_interval_seconds, metric=metric)
        flags = (" LAST KNOWN 上次已知" if state.last_known else "") + (
            " STALE 过期" if state.stale else " fresh 新鲜"
        )
        value = metric_value(metric) if metric else "— 未知 / no data"
        lines = [
            heading,
            f"  {value}",
            f"  {STATE_LABELS[snapshot.fetch_state]} ({snapshot.fetch_state}){flags}",
        ]
        if metric and metric.detail:
            lines.append("  " + sanitize_text(metric.detail, max_length=1024))
        if metric and metric.reset_at:
            lines.append(
                f"  重置 {local_time(metric.reset_at)} · {countdown(metric.reset_at, self.now())}"
            )
        if metric and metric.expires_at:
            lines.append(f"  到期 {local_time(metric.expires_at)}（非周期重置）")
        lines.append(
            f"  成功 / fresh {local_time(snapshot.fetched_at)} · 尝试 / attempt {local_time(snapshot.attempted_at)}"
        )
        if snapshot.retry_at:
            lines.append(
                f"  重试 / retry {local_time(snapshot.retry_at)} · {countdown(snapshot.retry_at, self.now())}"
            )
        if snapshot.diagnostic:
            lines.append("  " + snapshot.diagnostic.message)
        return "\n".join(lines)

    def _render_rows(self) -> None:
        rows = self._visible_rows()
        if rows != self.rows:
            self._rebuild(rows)
            return
        for index, (account, metric_id) in enumerate(self.rows):
            self.listing.replace_option_prompt(str(index), Text(self._row_text(account, metric_id)))
        self._render_header()

    @on(Select.Changed, "#account-selector")
    def select_account(self, event: Select.Changed) -> None:
        self.selected_account = None if event.value == "all" else str(event.value)
        self._rebuild()

    @on(OptionList.OptionSelected, "#metrics")
    def show_details(self, event: OptionList.OptionSelected) -> None:
        if event.option_index < len(self.rows):
            account, metric_id = self.rows[event.option_index]
            self.push_screen(
                InformationScreen("用量详情 / Details", self.details(account, metric_id))
            )

    def details(self, account: Account, metric_id: str) -> str:
        lines = [self._row_text(account, metric_id), "", GUIDANCE[account.provider]]
        snapshot = self.snapshots.get(account.id)
        metric = self._metric(account, metric_id)
        if metric:
            lines.extend(
                [
                    f"来源 / provenance: {metric.source.kind}",
                    f"契约: {metric.source.contract}",
                    f"版本敏感: {metric.source.version_sensitive}",
                    f"重置 UTC: {utc_time(metric.reset_at)}",
                    f"到期 UTC: {utc_time(metric.expires_at)}",
                ]
            )
            if metric.shared_pool_id:
                lines.append(
                    f"共享池 {metric.shared_pool_id}：产品消耗占同一个池，不是可相加的独立额度；不推算产品剩余。"
                )
        if snapshot:
            lines.extend(
                [
                    f"成功 UTC: {utc_time(snapshot.fetched_at)}",
                    f"尝试 UTC: {utc_time(snapshot.attempted_at)}",
                    f"重试 UTC: {utc_time(snapshot.retry_at)}",
                ]
            )
            if snapshot.organization_id:
                lines.append("组织: " + snapshot.organization_id)
            for grant in snapshot.grants:
                lines.append(
                    f"\n赠款 / grant {grant.category}: {grant.name or '—'} / {grant.program_id or '—'} / {grant.id or '—'}\n  授予 {grant.granted.format()} · 剩余 {grant.remaining.format()}\n  到期 {local_time(grant.expires_at)} · UTC {utc_time(grant.expires_at)}"
                )
        return "\n".join(lines)

    async def action_refresh(self) -> None:
        if self.scheduler is None or self._refreshing:
            return
        self._refreshing = True
        try:
            await self.scheduler.refresh(self.selected_account)
            self._notice = "刷新请求已合并 / refresh pending；仍遵守限流重试期限。"
            self._render_header()
        finally:
            self._refreshing = False

    async def accounts_changed(self, accounts: tuple[Account, ...]) -> None:
        self.accounts = tuple(accounts)
        # A mutation may replace credentials under the same reference: discard UI
        # observations and let Scheduler invalidate all supplied generations.
        self.snapshots.clear()
        if self.selected_account not in {account.id for account in self.accounts}:
            self.selected_account = None
        self.selector.set_options(self._account_options())
        self.selector.value = self.selected_account or "all"
        self._rebuild()
        if self.scheduler is not None:
            await self.scheduler.update_accounts(self.accounts)

    async def reconnect(self, account_id: str) -> None:
        if self.scheduler is not None:
            await self.scheduler.refresh(account_id)

    def action_accounts(self) -> None:
        if self.mode == "demo":
            self.push_screen(AccountManagerScreen(readonly=True, accounts=self.accounts))
            return
        if self.account_store is None or self.credential_store is None:
            self.push_screen(
                InformationScreen(
                    "账号管理", "暂无账号。需要注入账号与凭据存储后添加连接；不读取隐式配置。"
                )
            )
            return
        from usage_tui.credentials import CredentialResolver

        resolver = getattr(self.scheduler_factory, "resolver", None)
        if resolver is None:
            resolver = CredentialResolver(self.credential_store)
        self.push_screen(
            AccountManagerScreen(
                self.account_store,
                self.credential_store,
                resolver,
                getattr(self.scheduler_factory, "console_discovery", None),
                on_changed=self.accounts_changed,
                on_reconnect=self.reconnect,
            )
        )

    def action_help(self) -> None:
        self.push_screen(
            InformationScreen(
                "帮助 / Help",
                "q / Ctrl-C 退出（包括对话框）\nr 请求刷新；调度器合并并遵守重试期限\na 账号管理；DEMO 只读\nTab / Shift-Tab 切换控件；↑↓ 选择并滚动；Enter 查看详情\nEscape 返回\n\n已用 / 剩余为数值，条形图仅绘图限制在 100%。\nSTALE / LAST KNOWN 为旧观察，不是当前实时额度。倒计时结束等待刷新，不会清零。\n余额有币种；赠款到期不等于周期重置。GrokBuild / GrokChat 消耗同一共享池。\nLIVE ChatGPT 每周契约仍阻塞；DEMO ChatGPT 是合成样例，不是支持证据。\n\n凭据过期请在官方客户端重新登录或在账号管理中替换；本程序不刷新上游令牌。",
            )
        )

    async def on_unmount(self) -> None:
        if self._usage_closed:
            return
        self._usage_closed = True
        try:
            if self.scheduler is not None:
                await self.scheduler.stop()
        finally:
            if self.mode == "live":
                close = getattr(self.scheduler_factory, "aclose", None)
                if close is not None:
                    result = close()
                    if inspect.isawaitable(result):
                        await result
