"""Dependency-injected Chinese terminal dashboard; demo stays completely offline."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
from collections.abc import Collection
from datetime import UTC, datetime
from decimal import Decimal

from rich.cells import cell_len
from rich.errors import StyleSyntaxError
from rich.style import Style
from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.geometry import Region
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Footer, Label, OptionList, Select, Static
from textual.widgets.option_list import Option

from cli_usage_api.accounts import GUIDANCE, AccountManagerScreen, credential_identity
from cli_usage_api.demo import DemoSource
from cli_usage_api.domain import (
    REQUIRED_METRIC_IDS,
    Account,
    Metric,
    MetricId,
    MetricState,
    ProviderId,
    Snapshot,
    sanitize_text,
)
from cli_usage_api.providers.grok import MISSING_DETAIL as GROK_MISSING
from cli_usage_api.scheduler import freshness
from cli_usage_api.storage import ConfigError, SettingsStore

METRIC_LABELS = {
    "claude.subscription.five_hour": "Claude 5h 用量",
    "claude.subscription.weekly": "Claude 每周用量",
    "claude.subscription.fable_weekly": "Claude Fable 每周用量",
    "claude.platform.purchased_balance": "Claude Platform 购买余额",
    "claude.platform.promotional_balance": "Claude Platform 赠送余额",
    "claude.platform.total_balance": "Claude Platform 总余额",
    "codex.subscription.weekly": "Codex weekly (7d)",
    "codex.subscription.five_hour": "Codex 5h",
    "codex.subscription.credits": "Codex credits",
    "claude.subscription.extra_usage": "Claude 额外用量",
    "grok.subscription.shared_pool": "Grok 共享池",
    "grok.product.build": "GrokBuild",
    "grok.product.chat": "GrokChat",
}

# Metrics a provider parses and publishes (snapshots, debug log, API JSON) that the
# dashboard deliberately does not display: no row, no details, no header, hoisting
# or stale-count effect. This is a user-requested exception to keeping every
# provider extra visible; see PLAN.md. The provider still emits the metric.
PARSE_ONLY_METRIC_IDS: frozenset[str] = frozenset({MetricId.CLAUDE_EXTRA_USAGE})


def displayed_metrics(snapshot: Snapshot) -> tuple[Metric, ...]:
    """The snapshot's metrics minus the parse-only ones the dashboard never shows."""
    return tuple(m for m in snapshot.metrics if m.id not in PARSE_ONLY_METRIC_IDS)


def credit_text(metric: Metric) -> str | None:
    """Non-currency credits as exact fixed-point text, or a positive unlimited report."""
    if metric.credits is not None:
        # Plain fixed-point: no exponent notation, no rounding, never currency.
        return f"{format(metric.credits, 'f')} credits"
    if metric.unlimited and metric.spent is None:
        return "不限量 / Unlimited"
    return None


def metric_label(metric_id: str, metric: Metric | None) -> str:
    # An aggregate without proven pool semantics is not labelled a shared pool.
    if metric_id == MetricId.GROK_SHARED_POOL and metric and metric.share_percent is not None:
        return "Grok 汇总"
    return METRIC_LABELS.get(metric_id) or sanitize_text(
        metric.label if metric else metric_id, max_length=120
    )


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
    if (credits := credit_text(metric)) is not None:
        return credits
    if metric.share_percent is not None:
        # A pool share has no remaining of its own.
        filled = int(min(Decimal(100), metric.share_percent) / 10)
        return f"已用 {metric.share_percent}% [" + "#" * filled + "-" * (10 - filled) + "]"
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
    return "— 未知 / no data"


WEEKDAYS = "一二三四五六日"
# Widest ordinary clock-driven strings ("23小时59分前", "等待刷新 / awaiting refresh").
AGE_RESERVE = cell_len("23小时59分前")
RETRY_RESERVE = cell_len("等待刷新 / awaiting refresh")
FALLBACK_COLORS = {
    "success": "green",
    "warning": "yellow",
    "error": "red",
    "secondary": "magenta",
    "accent": "cyan",
}
STATE_CHIPS = {"ok": ("●", "success"), "partial": ("◑", "warning")} | {
    state: ("▲", "warning") for state in ("rate_limited", "network_error")
}


def _span(seconds: int, *, precise: bool = False, coarse: bool = False) -> str:
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    if days:
        return f"{days}天{hours}小时" if hours and not coarse else f"{days}天"
    if hours:
        return f"{hours}小时{minutes}分" if minutes and not coarse else f"{hours}小时"
    if minutes:
        return f"{minutes}分{seconds:02}秒" if precise and seconds else f"{minutes}分钟"
    return f"{seconds}秒"


def relative_reset(
    value: datetime, now: datetime, *, precise: bool = False, coarse: bool = False
) -> str:
    """Relative countdown on the app clock; zero waits for refresh, never resets."""
    seconds = max(0, int((value - now).total_seconds()))
    if not seconds:
        return "等待刷新 / awaiting refresh"
    return _span(seconds, precise=precise, coarse=coarse) + "后"


def age(value: datetime, now: datetime) -> str:
    seconds = max(0, int((now - value).total_seconds()))
    return "刚刚" if seconds < 60 else _span(seconds) + "前"


def short_local_time(value: datetime, now: datetime, fmt: str = "%H:%M") -> str:
    try:
        local, current = value.astimezone(), now.astimezone()
    except OverflowError:
        # Saturated deadlines keep their UTC value; nothing is clamped.
        return value.astimezone(UTC).strftime("%Y-%m-%d " + fmt) + " UTC"
    days = (local.date() - current.date()).days
    clock = local.strftime(fmt)
    if days in (-1, 0, 1):
        return ("昨天 ", "今天 ", "明天 ")[days + 1] + clock
    if 1 < days < 7:
        return f"周{WEEKDAYS[local.weekday()]} {clock}"
    return local.strftime("%m-%d " if local.year == current.year else "%Y-%m-%d ") + clock


def severity(used: Decimal) -> str:
    if used > 100:
        return "error"
    return "error" if used >= 90 else "warning" if used >= 70 else "success"


def overage(used: Decimal) -> str:
    return f"超额 +{used - Decimal(100)}%"


def bar(used: Decimal, width: int, *, style: str, dim: bool = False) -> Text:
    """Drawing alone is clamped at 100%; the numeric value is shown separately."""
    filled = int(min(used, Decimal(100)) * width / 100)
    text = Text("█" * filled, style=f"dim {style}" if dim else style)
    text.append("░" * (width - filled), style="dim")
    if used > 100:
        text.append("▶", style=f"bold {style}")
    return text


def middle(value: str, width: int) -> str:
    """Ellipsize inside a label so distinguishing tails ("购买余额") stay visible."""
    if cell_len(value) <= width:
        return value
    tail = ""
    for char in reversed(value):
        if cell_len(char + tail) > max(1, (width - 1) // 2):
            break
        tail = char + tail
    word = tail.rsplit(" ", 1)[-1]
    tail = word if cell_len(word) >= 4 else tail
    head = ""
    for char in value:
        if cell_len(head + char) > width - 1 - cell_len(tail):
            break
        head += char
    return head.rstrip() + "…" + tail.lstrip()


def cell(value: Text | str, width: int, *, justify: str = "left", truncate: bool = True) -> Text:
    """Pad by terminal cells; values that must stay whole are never ellipsized."""
    text = Text(value) if isinstance(value, str) else value.copy()
    text.no_wrap = True
    if truncate and text.cell_len > width:
        text.truncate(width, overflow="ellipsis")
    gap = max(0, width - text.cell_len)
    if justify == "right":
        text.pad_left(gap)
    else:
        text.pad_right(gap)
    return text


class MetricList(OptionList):
    """Option list whose scroll keeps an account header above its first metric."""

    class Resized(Message):
        pass

    def on_resize(self) -> None:
        self.post_message(self.Resized())

    def _move_page(self, direction) -> None:
        # A page can land on a disabled header with no metric beyond it; keep a
        # metric selected (the nearest one at that end) rather than clearing it.
        super()._move_page(direction)
        if self.highlighted is None and self.option_count:
            (self.action_first if direction < 0 else self.action_last)()

    def keep_highlight_in_view(self, before: tuple[int, int] | None) -> None:
        """After prompts change height, keep a previously visible selection visible."""
        span = self.highlight_span()
        if before is not None and span is not None and span != before:
            top = self.scroll_offset.y
            if not (top <= span[0] and span[1] <= top + self.scrollable_content_region.height):
                self.scroll_to_highlight()

    def highlight_span(self) -> tuple[int, int] | None:
        highlighted = self.highlighted
        if highlighted is None or not self.is_mounted:
            return None
        self._update_lines()
        try:
            start = self._index_to_line[highlighted]
            return start, start + self._heights[highlighted]
        except KeyError:
            return None

    def scroll_to_highlight(self, top: bool = False) -> None:
        highlighted = self.highlighted
        if highlighted and self.is_mounted and self.get_option_at_index(highlighted - 1).disabled:
            self._update_lines()
            try:
                start = self._index_to_line[highlighted - 1]
                end = self._index_to_line[highlighted] + self._heights[highlighted]
            except KeyError:
                pass
            else:
                if end - start <= self.scrollable_content_region.height:
                    self.scroll_to_region(
                        Region(0, start, self.scrollable_content_region.width, end - start),
                        force=True,
                        animate=False,
                        top=top,
                        immediate=True,
                    )
                    return
        super().scroll_to_highlight(top)


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

    Observers (``add_observer``) mirror accepted snapshots and account changes, e.g.
    the embedded API hub; they never own or drive the scheduler. Every account
    writer (the account manager, the embedded API) holds ``account_lock`` across
    its commit and ``accounts_changed`` so publication order matches commit order;
    ``accounts_changed`` itself never takes it. Services
    (``add_service``: ``async start(app)``, ``async stop()``, optional ``note``)
    start after the scheduler on mount and stop before it on unmount.
    """

    CSS_PATH = "app.tcss"
    BINDINGS = (
        Binding("q", "quit", "退出"),
        Binding("ctrl+c", "quit", "退出", priority=True),
        Binding("r", "refresh", "刷新"),
        Binding("a", "accounts", "账号"),
        Binding("escape", "clear_selection", "取消选择"),
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
        settings_store: SettingsStore | None = None,
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
        self.theme = "nord"
        self._settings_store = settings_store
        self._theme_notice = ""
        if settings_store is not None:
            try:
                saved_theme = settings_store.load_theme()
            except ConfigError:
                self._theme_notice = (
                    "无法读取主题设置，已使用 nord；请检查 settings.json 的格式和权限。"
                )
            else:
                if saved_theme is not None:
                    if saved_theme in self.available_themes:
                        self.theme = saved_theme
                    else:
                        self._theme_notice = "已保存的主题不可用，已使用 nord；可重新选择主题。"
        self.mode = mode
        self.accounts = tuple(accounts)
        self.scheduler_factory = scheduler_factory
        self.account_store = account_store
        self.credential_store = credential_store
        self.snapshots: dict[str, Snapshot] = {}
        self.selected_account: str | None = None
        self.rows: list[tuple[Account, str]] = []
        self._row_option: list[int] = []
        self._usage_closed = False
        self._refreshing = False
        self._notice = ""
        self._observers: list = []
        self.account_lock = asyncio.Lock()
        # The manager reporting a change reloads itself; others reload from the tuple.
        self._account_origin = None
        self.services: list = []
        self._services_started: list = []
        self.scheduler = None
        if mode == "demo":
            self.scheduler = DemoSource(scenario=scenario, publish=self.publish_snapshot)
            self.accounts = self.scheduler.accounts
        self.banner = Static(id="banner", markup=False)
        self.selector = Select(
            self._account_options(), value="all", allow_blank=False, id="account-selector"
        )
        self.status_line = Static(id="dashboard-status", markup=False)
        self.listing = MetricList(id="metrics")
        self.hint = Static(id="resize-hint", markup=False)

    def add_observer(self, observer) -> None:
        """Register ``observer.publish(snapshot)`` / ``observer.accounts_changed(accounts)``."""
        self._observers.append(observer)

    def add_service(self, service) -> None:
        if self.is_running:
            raise RuntimeError("Add services before the app starts.")
        self.services.append(service)

    def _notify_observers(self, method: str, value) -> None:
        for observer in self._observers:
            # A mirror must never break the dashboard it observes.
            with contextlib.suppress(Exception):
                getattr(observer, method)(value)

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
        for service in self.services:
            try:
                await service.start(self)
            except Exception:  # noqa: BLE001 - Curated notice; never echo exception text.
                self.notify(
                    "后台服务启动失败；仪表盘继续运行。", title="服务", severity="error", timeout=15
                )
            else:
                self._services_started.append(service)
        self.set_interval(1, self._tick)
        self.listing.focus()
        self.watch(self, "theme", self._save_theme, init=False)
        if self._theme_notice:
            self.notify(self._theme_notice, title="主题设置", severity="warning", timeout=10)

    def _save_theme(self, theme: str) -> None:
        if self._settings_store is None:
            return
        try:
            self._settings_store.save_theme(theme)
        except ConfigError:
            self.notify(
                "本次主题已应用，但无法确认保存；请检查 settings.json 的格式和权限。",
                title="主题设置",
                severity="warning",
                timeout=10,
            )

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
        self._notify_observers("publish", snapshot)
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
            self._render_rows()

    @on(MetricList.Resized)
    def _reflow(self) -> None:
        # The list's own size settles after the screen resize: re-flow tiers then.
        self._render_rows()

    def _render_header(self) -> None:
        demo = self.mode == "demo"
        compact = self.size.width < 80 or self.size.height < 24
        if self.screen_stack:
            self.screen_stack[0].set_class(compact, "compact")
        banner = (
            "DEMO 离线合成演示 — 不代表真实账号或已验证的 Codex 实时额度"
            if demo
            else "LIVE 实时账号用量（有界轮询）"
        )
        # Service notes (e.g. "API 127.0.0.1:8787") follow the mode banner.
        notes = [note for service in self.services if (note := getattr(service, "note", None))]
        self.banner.update(" · ".join([banner, *notes]))
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
                freshness(snapshot, self.now(), account.effective_poll_interval_seconds).stale
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
            upcoming = [
                (metric.reset_at, account, metric)
                for account, snapshot in observed
                for metric in displayed_metrics(snapshot)
                if metric.state == MetricState.READY
                and metric.reset_at is not None
                and metric.reset_at > self.now()
            ]
            if upcoming and not compact:
                reset_at, account, metric = min(upcoming, key=lambda item: item[0])
                soonest = f" · 最近重置 {self._label(account, metric.id)} {relative_reset(reset_at, self.now())}"
                if cell_len(message + soonest) <= self.size.width - 2:
                    message += soonest
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
                for metric in displayed_metrics(snapshot):
                    if metric.id not in seen:
                        rows.append((account, metric.id))
                        seen.add(metric.id)
        return rows

    def option_index(self, row: tuple[Account, str]) -> int:
        return self._row_option[self.rows.index(row)]

    def metric_option_count(self) -> int:
        return len(self.rows)

    def _row_index(self, option_index: int | None) -> int | None:
        if option_index is None or not 0 <= option_index < self.listing.option_count:
            return None
        option_id = self.listing.get_option_at_index(option_index).id or ""
        return int(option_id[1:]) if option_id.startswith("m") else None

    def highlighted_row(self) -> tuple[Account, str] | None:
        index = self._row_index(self.listing.highlighted)
        return None if index is None or index >= len(self.rows) else self.rows[index]

    def _groups(self) -> list[tuple[Account, list[int]]]:
        groups: list[tuple[Account, list[int]]] = []
        for index, (account, _) in enumerate(self.rows):
            if not groups or groups[-1][0] != account:
                groups.append((account, []))
            groups[-1][1].append(index)
        return groups

    def _rebuild(self, rows: list[tuple[Account, str]] | None = None) -> None:
        selected = self.highlighted_row()
        previous = self._row_index(self.listing.highlighted)
        self.rows = self._visible_rows() if rows is None else rows
        if selected is not None:
            # Row identity is the account ID and metric: a rename or reorder keeps it.
            selected = next(
                (row for row in self.rows if row[0].id == selected[0].id and row[1] == selected[1]),
                selected,
            )
        self._row_option = []
        self.listing.clear_options()
        options = []
        for number, (account, indexes) in enumerate(self._groups()):
            options.append(Option(self._account_header(account), id=f"h{number}", disabled=True))
            for index in indexes:
                self._row_option.append(len(options))
                options.append(Option(self._metric_prompt(*self.rows[index]), id=f"m{index}"))
        self.listing.add_options(options)
        if selected in self.rows:
            self.listing.highlighted = self._row_option[self.rows.index(selected)]
        elif previous is not None and self.rows:
            # If a selected row disappeared, keep the nearest surviving metric.
            self.listing.highlighted = self._row_option[min(previous, len(self.rows) - 1)]
        else:
            # Startup and later unselected states stay unselected through rebuilds.
            self.listing.highlighted = None
        self._render_header()

    def _metric(self, account: Account, metric_id: str) -> Metric | None:
        snapshot = self.snapshots.get(account.id)
        return (
            next((metric for metric in displayed_metrics(snapshot) if metric.id == metric_id), None)
            if snapshot
            else None
        )

    def _row_text(self, account: Account, metric_id: str) -> str:
        snapshot = self.snapshots.get(account.id)
        metric = self._metric(account, metric_id)
        label = metric_label(metric_id, metric)
        heading = f"{sanitize_text(account.label, max_length=80)} · {label}"
        if not account.enabled:
            return heading + "\n  — 已禁用 / disabled"
        if snapshot is None:
            return heading + "\n  — 暂无数据 / no data · 等待首次观察 / pending"
        state = freshness(
            snapshot, self.now(), account.effective_poll_interval_seconds, metric=metric
        )
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
        before = self.listing.highlight_span()
        for number, (account, indexes) in enumerate(self._groups()):
            self.listing.replace_option_prompt(f"h{number}", self._account_header(account))
            for index in indexes:
                self.listing.replace_option_prompt(
                    f"m{index}", self._metric_prompt(*self.rows[index])
                )
        self.listing.keep_highlight_in_view(before)
        self._render_header()

    def _layout(self) -> tuple[str, int, bool]:
        compact = self.size.width < 80 or self.size.height < 24
        mounted = self.listing.is_mounted and self.listing.size.width > 0
        outer = self.listing.size.width - 2 if mounted else self.size.width - 4
        region = self.listing.scrollable_content_region.width if mounted else 0
        width = region - 2 if region > 2 else outer - 3
        tier = "wide" if outer >= 100 else "medium" if outer >= 72 else "narrow"
        return tier, max(20, width), compact

    def _color(self, name: str) -> str:
        if getattr(self, "_palette", (None,))[0] != self.theme:
            variables = self.get_css_variables()
            palette = {}
            for key, fallback in FALLBACK_COLORS.items():
                try:
                    palette[key] = str(Style.parse(variables.get(key, fallback)).color.name)
                except (StyleSyntaxError, AttributeError):
                    palette[key] = fallback
            self._palette = (self.theme, palette)
        return self._palette[1][name]

    def _label(self, account: Account, metric_id: str) -> str:
        return metric_label(metric_id, self._metric(account, metric_id))

    def _wrapped(self, text: str, width: int, indent: str, style: str) -> Text:
        result = Text()
        for line in Text(text).wrap(self.console, max(10, width - cell_len(indent))):
            result.append("\n" + indent, style="dim")
            result.append(line.plain, style=style)
        return result

    def _account_header(self, account: Account) -> Text:
        tier, width, compact = self._layout()
        chips_first = compact or tier == "narrow"
        label = sanitize_text(account.label, max_length=80)
        snapshot = self.snapshots.get(account.id)
        now = self.now()
        chips = self._chips(account, tier, now)
        times, later = Text(), Text()
        reserves = [0, 0]
        lines: list[Text] = []
        hoisted: str | None = None
        if account.enabled and snapshot is not None:
            code = str(snapshot.fetch_state)

            def clock(value: datetime) -> str:
                return short_local_time(value, now).removeprefix("今天 ")

            times.style = "dim"
            elapsed = "" if snapshot.fetched_at is None else age(snapshot.fetched_at, now)
            times.append(
                "成功 "
                + (
                    "—"
                    if snapshot.fetched_at is None
                    else f"{clock(snapshot.fetched_at)} ({elapsed})"
                )
            )
            times.append(f" · 尝试 {clock(snapshot.attempted_at)}")
            reserves[0] = times.cell_len + max(0, AGE_RESERVE - cell_len(elapsed))
            if snapshot.retry_at:
                remaining = relative_reset(snapshot.retry_at, now, precise=True)
                later.append(
                    f"重试 / retry {short_local_time(snapshot.retry_at, now, '%H:%M:%S').removeprefix('今天 ')} · "
                    + remaining,
                    style=self._color("warning"),
                )
                reserves[1] = later.cell_len + max(0, RETRY_RESERVE - cell_len(remaining))
            if snapshot.diagnostic:
                lines.append(
                    Text(
                        "⚠ " + sanitize_text(snapshot.diagnostic.message, max_length=256),
                        style=self._color("error" if code not in STATE_CHIPS else "warning"),
                    )
                )
            if self._hoisted(account):
                hoisted = sanitize_text(displayed_metrics(snapshot)[0].detail, max_length=1024)
        name = Text(label, style="bold")
        # One chip column across accounts: pad to the longest visible label,
        # capped so every account's chips still fit beside the padded label.
        pad = max(30, min(self._longest_label(), width - 4 - self._widest_chips(tier, now)))
        if not chips_first and 1 + pad + 3 + chips.cell_len <= width:
            name = cell(name, max(pad, name.cell_len))
        segments = [chips, name] if chips_first else [name, chips]
        packed: list[Text] = []
        footprint = 0
        for segment, reserve in [
            *((s, 0) for s in segments),
            (times, reserves[0]),
            (later, reserves[1]),
        ]:
            if not segment.plain:
                continue
            # Clock-driven text packs at its widest form so ticks never reflow lines.
            size = max(segment.cell_len, reserve)
            if not packed:
                packed.append(Text("▌", style="bold").append_text(segment))
                footprint = 1 + size
            elif footprint + 3 + size <= width:
                packed[-1].append("   ").append_text(segment)
                footprint += 3 + size
            else:
                packed.append(Text("  ").append_text(segment))
                footprint = 2 + size
        result = Text(no_wrap=True, overflow="ellipsis")
        for index, line in enumerate(packed):
            result.append("\n" if index else "")
            result.append_text(cell(line, width))
        # Diagnostics and unknown-value notes wrap whole in every tier.
        for line in lines:
            result.append_text(self._wrapped(line.plain, width, "  ", str(line.style)))
        if hoisted:
            result.append_text(self._wrapped("ⓘ " + hoisted, width, "  ", "dim"))
        return result

    def _chips(self, account: Account, tier: str, now: datetime) -> Text:
        chips = Text()
        snapshot = self.snapshots.get(account.id)
        if not account.enabled:
            chips.append("⏸ 已禁用 / disabled — 不轮询（a 账号管理）", style="dim")
            return chips
        if snapshot is None:
            chips.append("… 等待首次观察 / pending", style="dim italic")
            return chips
        code = str(snapshot.fetch_state)
        icon, color = STATE_CHIPS.get(code, ("✖", "error"))
        chips.append(
            f"{icon} {STATE_LABELS[code]}" + (f" ({code})" if tier == "wide" else ""),
            style=f"bold {self._color(color)}",
        )
        state = freshness(snapshot, now, account.effective_poll_interval_seconds)
        if state.last_known:
            chips.append(" · ")
            chips.append("LAST KNOWN 上次已知", style=f"bold {self._color('warning')}")
        shown = displayed_metrics(snapshot)
        stale = (
            sum(
                freshness(
                    snapshot, now, account.effective_poll_interval_seconds, metric=metric
                ).stale
                for metric in shown
            )
            if shown
            else int(state.stale)
        )
        chips.append(" · ")
        if stale:
            count = f" {stale}/{len(shown)}" if shown else ""
            chips.append(f"STALE 过期{count}", style=f"bold {self._color('warning')}")
        else:
            chips.append("fresh 新鲜", style=self._color("success"))
        return chips

    def _widest_chips(self, tier: str, now: datetime) -> int:
        return max(
            (self._chips(account, tier, now).cell_len for account, _ in self._groups()),
            default=0,
        )

    def _longest_label(self) -> int:
        return max(
            (
                cell_len(sanitize_text(account.label, max_length=80))
                for account, _ in self._groups()
            ),
            default=0,
        )

    def _metric_prompt(self, account: Account, metric_id: str) -> Text:
        tier, width, _ = self._layout()
        now = self.now()
        snapshot = self.snapshots.get(account.id)
        metric = self._metric(account, metric_id)
        state = (
            freshness(snapshot, now, account.effective_poll_interval_seconds, metric=metric)
            if snapshot is not None
            else None
        )
        dim = bool(state and state.last_known)
        nest, last = self._nesting(account).get(metric_id, ("", False))
        prefix = "  " + (nest + " " if nest else "")
        name = self._label(account, metric_id) + (" ⟲" if dim else "")
        used_w, rest_w = 12, 11
        values_w = 1 + used_w + 1 + rest_w + 1
        # Labels shrink only when the row (minimal bar plus a short reset) cannot fit.
        label_w = min(26, max(20, width - 1 - (6 + 1) - values_w - 10))
        spare = width - label_w - 2 - values_w
        # Spare width grows the bar while the absolute reset time still fits.
        bar_w = (
            24
            if tier == "wide"
            else 8
            if tier == "narrow"
            else max(6, min(24, max(spare - 22, min(8, spare - 10))))
        )
        extra: list[str] = []
        reset = Text()
        amount: Text | None = None
        heads = [Text()]
        cells: list[Text] = []
        if not account.enabled or snapshot is None:
            cells = [
                Text(
                    "— 已禁用 / disabled" if not account.enabled else "— 暂无数据 / no data",
                    style="dim",
                )
            ]
        elif (
            metric is None
            or metric.state != MetricState.READY
            or (
                metric.quota is None
                and metric.balance is None
                and metric.share_percent is None
                and credit_text(metric) is None
            )
            or (
                metric.quota is not None
                and all(
                    value is None
                    for value in (
                        metric.quota.used_percent,
                        metric.quota.remaining_percent,
                        metric.quota.used_count,
                        metric.quota.limit_count,
                        metric.quota.remaining_count,
                    )
                )
            )
        ):
            kind = MetricState.UNKNOWN if metric is None else metric.state
            if kind == MetricState.BLOCKED:
                placeholder = Text("✖ 阻塞 / blocked", style=f"bold {self._color('secondary')}")
            elif kind == MetricState.NOT_APPLICABLE:
                placeholder = Text("不适用 / not applicable", style="dim italic")
            else:
                text = " 未知 / no data "
                fill = max(2, (bar_w + 1 - cell_len(text)) // 2)
                placeholder = Text("┄" * fill + text + "┄" * fill, style="dim")
            if cell_len(placeholder.plain) <= bar_w + 1:
                cells = [cell(placeholder, bar_w + 1), cell(Text("—", style="dim"), used_w)]
            else:
                cells = [cell(placeholder, bar_w + 1 + 1 + used_w, truncate=False)]
            cells.append(cell(Text("—", style="dim"), rest_w))
            reset = Text("—", style="dim")
        elif metric.balance is not None:
            amount = Text(
                metric.balance.format(),
                style=f"bold {self._color('accent')}"
                if metric_id == "claude.platform.total_balance"
                else "bold",
            )
            cells = [
                cell(Text("余额", style="dim"), bar_w + 1),
                cell(amount, used_w + 1 + rest_w, justify="right", truncate=False),
            ]
            reset = Text("无周期重置", style="dim")
        elif metric.quota is None and (credits := credit_text(metric)) is not None:
            # Credits are not money and carry no inferred expiry or reset.
            amount = Text(credits, style="bold")
            cells = [
                cell(
                    Text("余额" if metric.credits is not None else "credits", style="dim"),
                    bar_w + 1,
                ),
                cell(amount, used_w + 1 + rest_w, justify="right", truncate=False),
            ]
        elif metric.share_percent is not None:
            # A pool share draws bar + used only: no derived remaining, no reset.
            share = metric.share_percent
            color = self._color(severity(share))
            cells = [
                cell(bar(share, bar_w, style=color, dim=dim), bar_w + 1),
                cell(
                    Text(f"已用 {share}%", style=f"{'dim ' if dim else ''}bold {color}"),
                    used_w,
                    truncate=False,
                ),
                cell("", rest_w),
            ]
        else:
            quota = metric.quota
            parts = [quota.used_count, quota.limit_count, quota.remaining_count]
            parts = ["—" if value is None else str(value) for value in parts]
            if quota.used_percent is not None or quota.remaining_percent is not None:
                used = quota.used_percent
                color = self._color(severity(used)) if used is not None else "default"
                style = f"{'dim ' if dim else ''}bold {color}"
                cells = [
                    cell(bar(used, bar_w, style=color, dim=dim), bar_w + 1)
                    if used is not None
                    else cell(Text("—", style="dim"), bar_w + 1),
                    cell(
                        Text(f"已用 {'—' if used is None else str(used) + '%'}", style=style),
                        used_w,
                        truncate=False,
                    ),
                    cell(
                        Text(
                            f"剩余 {'—' if quota.remaining_percent is None else str(quota.remaining_percent) + '%'}",
                            style=("dim bold" if dim else "bold"),
                        ),
                        rest_w,
                        truncate=False,
                    ),
                ]
                if used is not None and used > 100:
                    heads = [
                        Text(f"{overage(used)} · ", style=f"bold {self._color('error')}"),
                        Text("超额 ", style=f"bold {self._color('error')}"),
                    ]
                    reset = heads[0][:-3]
                if any(
                    value is not None
                    for value in (quota.used_count, quota.limit_count, quota.remaining_count)
                ):
                    extra.append(f"次数 已用 {parts[0]} / 上限 {parts[1]} / 剩余 {parts[2]}")
            else:
                cells = [
                    cell(
                        Text(f"{parts[0]} / {parts[1]} 次", style="bold"), bar_w + 1, truncate=False
                    ),
                    cell(Text(f"已用 {parts[0]}", style="bold"), used_w, truncate=False),
                    cell(Text(f"剩余 {parts[2]}", style="bold"), rest_w, truncate=False),
                ]
        resets = [reset]
        if (
            metric is not None
            and account.enabled
            and snapshot is not None
            and cells
            and reset.plain != "—"
            and metric.state == MetricState.READY
        ):
            if metric.reset_at is None and metric.quota is not None and metric.expires_at is None:
                # A missing or invalid reset is unknown, never blank.
                unknown = Text("重置 — 未知", style="dim")
                resets = [head + unknown for head in heads] + [Text("重置 —", style="dim")]
            elif metric.reset_at is not None and metric.quota is not None:
                if state is not None and state.reset_passed:
                    passed = ("⟳ 等待刷新 / awaiting refresh · STALE", "⟳ awaiting refresh · STALE")
                    bodies = [Text(text, style=self._color("warning")) for text in passed]
                else:
                    style = "dim" if dim else ""
                    full = Text(relative_reset(metric.reset_at, now), style=style)
                    coarse = Text(relative_reset(metric.reset_at, now, coarse=True), style=style)
                    bodies = [full, coarse]
                    if metric.reset_at > now:
                        absolute = " · " + short_local_time(metric.reset_at, now)
                        bodies.insert(0, full + Text(absolute, style="dim"))
                resets = [head + body for head in heads for body in bodies]
            if metric.expires_at is not None:
                expiry = f"到期 {short_local_time(metric.expires_at, now)}（非周期重置）"
                resets = [Text(expiry, style=f"italic {self._color('secondary')}")]
        # Numeric Grok/Console rows need no explanation; failure details stay visible.
        numeric = (
            account.enabled
            and snapshot is not None
            and metric is not None
            and metric.state == MetricState.READY
            and reset.plain != "—"
        )
        detail = (
            sanitize_text(metric.detail, max_length=1024)
            if metric is not None
            and metric.detail
            and not self._hoisted(account)
            and not (
                numeric
                and account.provider in (ProviderId.GROK_SUBSCRIPTION, ProviderId.CLAUDE_PLATFORM)
            )
            else None
        )
        if detail and account.provider == ProviderId.GROK_SUBSCRIPTION:
            # The `未知 / no data` placeholder already says this; Enter details keeps it.
            detail = detail.replace(GROK_MISSING, "").strip() or None
        indent = "  " + ("│   " if nest and not last else "    ")
        prompt = Text()
        if tier == "narrow":
            body = list(cells)
            value = None
            if amount is not None:
                # The bare amount (not its wide padded cell) sits on the label line.
                body.pop(1)
                value = amount
            elif len(body) > 1 and body[1].plain.startswith(("已用", "—")):
                value = body.pop(1)
            value_w = max(used_w, value.cell_len) if value is not None else 0
            room = width - (value_w + 1) if value is not None else width
            prompt.append_text(cell(prefix + middle(name, room - cell_len(prefix)), room))
            if value is not None:
                prompt.append(" ").append_text(
                    cell(value, value_w, justify="right", truncate=False)
                )
            line = Text("  ")
            line.append(("│ " if not last else "  ") if nest else "", style="dim")
            for part in body:
                line.append_text(part).append(" ")
            prompt.append("\n").append_text(line)
            self._append_reset(prompt, resets, width, indent)
        else:
            prompt.append_text(cell(prefix + middle(name, label_w - cell_len(prefix)), label_w))
            prompt.append(" ")
            for part in cells:
                prompt.append_text(part).append(" ")
            self._append_reset(prompt, resets, width, indent)
        for line in extra:
            prompt.append("\n" + indent, style="dim").append(line, style="dim")
        if detail:
            prompt.append_text(self._wrapped(detail, width, indent, "dim"))
        return prompt

    @staticmethod
    def _append_reset(prompt: Text, resets: list[Text], width: int, indent: str) -> None:
        """Prefer a variant that fits; otherwise continue whole on the next line."""
        if not resets[0].plain:
            return
        line = prompt.plain.rsplit("\n", 1)[-1]
        room = width - cell_len(line)
        choice = next((text for text in resets if text.cell_len <= room), None)
        if choice is not None:
            prompt.append_text(choice)
        else:
            prompt.rstrip()
            prompt.append("\n" + indent).append_text(resets[0])

    def _hoisted(self, account: Account) -> bool:
        snapshot = self.snapshots.get(account.id)
        metrics = displayed_metrics(snapshot) if snapshot is not None else ()
        if snapshot is None or not metrics:
            return False
        if account.provider == ProviderId.CLAUDE_PLATFORM and any(
            metric.state == MetricState.READY and metric.balance is not None for metric in metrics
        ):
            # Do not move hidden balance explanations back into the account header.
            return False
        details = {metric.detail for metric in metrics}
        return len(details) == 1 and bool(details.pop())

    def _nesting(self, account: Account) -> dict[str, tuple[str, bool]]:
        pools: set[str] = set()
        nested: list[str] = []
        for row_account, metric_id in self.rows:
            metric = self._metric(account, metric_id) if row_account == account else None
            if metric is None:
                continue
            if metric.quota is not None:
                # A product may name its pool by metric id or by a shared pool id.
                pools.update(filter(None, (metric.id, metric.shared_pool_id)))
            elif metric.shared_pool_id and metric.shared_pool_id in pools:
                nested.append(metric_id)
        return {
            metric_id: ("└" if index == len(nested) - 1 else "├", index == len(nested) - 1)
            for index, metric_id in enumerate(nested)
        }

    @on(Select.Changed, "#account-selector")
    def select_account(self, event: Select.Changed) -> None:
        self.selected_account = None if event.value == "all" else str(event.value)
        self._rebuild()

    @on(OptionList.OptionSelected, "#metrics")
    def show_details(self, event: OptionList.OptionSelected) -> None:
        option_id = event.option.id or ""
        if option_id.startswith("m") and int(option_id[1:]) < len(self.rows):
            account, metric_id = self.rows[int(option_id[1:])]
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
                lines.append(f"属于共享池 {metric.shared_pool_id}")
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

    def action_clear_selection(self) -> None:
        if self.screen is self.listing.screen:
            self.listing.highlighted = None

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

    async def accounts_changed(
        self, accounts: tuple[Account, ...], *, invalidate: Collection[str] | None = None
    ) -> None:
        """Publish a committed account tuple; the caller holds ``account_lock``.

        ``invalidate=None`` discards every observation (legacy). With a set, a
        snapshot survives when its account remains, is not named in the set, and
        keeps its credential identity, so a rename, toggle or reorder keeps data.
        """
        old = {account.id: account for account in self.accounts}
        self.accounts = tuple(accounts)
        if invalidate is None:
            self.snapshots.clear()
        else:
            keep = {
                account.id
                for account in self.accounts
                if account.id not in invalidate
                and account.id in old
                and credential_identity(old[account.id]) == credential_identity(account)
            }
            for account_id in tuple(self.snapshots):
                if account_id not in keep:
                    del self.snapshots[account_id]
        # Observers (the embedded API hub) mirror the already-filtered snapshots.
        self._notify_observers("accounts_changed", self.accounts)
        if self.selected_account not in {account.id for account in self.accounts}:
            self.selected_account = None
        self.selector.set_options(self._account_options())
        self.selector.value = self.selected_account or "all"
        self._rebuild()
        if self.scheduler is not None:
            await self.scheduler.update_accounts(self.accounts, invalidate=invalidate)
        for screen in tuple(self.screen_stack):
            if isinstance(screen, AccountManagerScreen) and screen is not self._account_origin:
                # Another writer (e.g. the web) changed accounts: render without disk I/O.
                with contextlib.suppress(Exception):
                    await screen.reload(self.accounts)

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
        from cli_usage_api.credentials import CredentialResolver

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
                "q / Ctrl-C 退出（包括对话框）\nr 请求刷新；调度器合并并遵守重试期限\na 账号管理（Shift+↑↓ 或拖动调整账号顺序）；DEMO 只读\nTab / Shift-Tab 切换控件；↑↓ 选择并滚动；Enter 查看详情\nEscape 主界面取消选择；弹窗返回\n\n已用 / 剩余为数值，条形图仅绘图限制在 100%。\nSTALE / LAST KNOWN 为旧观察，不是当前实时额度。倒计时结束等待刷新，不会清零。\n余额有币种；赠款到期不等于周期重置。GrokBuild / GrokChat 消耗同一共享池。\nCodex weekly (7d) 为七天窗口，不表示日历周；缺失时显示未知。Codex 5h 及其他时长/独立池仅在上游报告时显示，不相加。DEMO 是合成样例，不是实时额度证据。\n\n凭据过期请在官方客户端重新登录或在账号管理中替换；本程序不刷新上游令牌。",
            )
        )

    async def on_unmount(self) -> None:
        if self._usage_closed:
            return
        self._usage_closed = True
        try:
            # Services (embedded API, keepalive) stop before the scheduler and factory.
            while self._services_started:
                service = self._services_started.pop()
                with contextlib.suppress(Exception):
                    await service.stop()
            if self.scheduler is not None:
                await self.scheduler.stop()
        finally:
            if self.mode == "live":
                close = getattr(self.scheduler_factory, "aclose", None)
                if close is not None:
                    result = close()
                    if inspect.isawaitable(result):
                        await result
