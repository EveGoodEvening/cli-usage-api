"""Explicitly synthetic published snapshots, independent of all live services.

Only the packaged fixture is read. This source is never a live-fetch fallback.
The app's one-second countdown calls tick(); refresh() republishes the selected
scenario without changing its fixed resets, retry deadlines, or last-known data.
"""

from __future__ import annotations

import asyncio
import json
import math
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from importlib.resources import files

from usage_tui.domain import (
    REQUIRED_METRIC_IDS,
    Account,
    Diagnostic,
    FetchState,
    Grant,
    GrantCategory,
    Metric,
    MetricState,
    Money,
    ProviderId,
    QuotaValue,
    Snapshot,
    SourceKind,
    SourceRef,
    parse_timestamp,
    utc_datetime,
)

DEMO_NOW = parse_timestamp("2026-10-28T12:00:00Z")
_SOURCE = SourceRef(SourceKind.OFFLINE_DEMO, "synthetic-demo-v1")


def _seconds(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("Demo time must be finite and nonnegative.")
    if not math.isfinite(value) or value < 0:
        raise ValueError("Demo time must be finite and nonnegative.")
    return float(value)


class DemoClock:
    """Manually advanced UTC/monotonic clock; never consults machine time.

    advance() wakes eligible sleep() calls on the owning event loop. Neither
    advancing time nor sleeping fabricates new provider observations.
    """

    def __init__(self, now: datetime = DEMO_NOW) -> None:
        self._now = utc_datetime(now)
        self._elapsed = 0.0
        self._sleepers: dict[asyncio.Future, float] = {}

    def now(self) -> datetime:
        return self._now

    def monotonic(self) -> float:
        return self._elapsed

    def advance(self, seconds: float = 1) -> datetime:
        seconds = _seconds(seconds)
        now = self._now + timedelta(seconds=seconds)
        self._elapsed += seconds
        self._now = now
        for future, deadline in tuple(self._sleepers.items()):
            if deadline <= self._elapsed and not future.done():
                future.set_result(None)
        return self._now

    async def sleep(self, seconds: float) -> None:
        seconds = _seconds(seconds)
        if seconds == 0:
            await asyncio.sleep(0)
            return
        future = asyncio.get_running_loop().create_future()
        self._sleepers[future] = self._elapsed + seconds
        try:
            await future
        finally:
            del self._sleepers[future]


class DemoSource:
    """Scheduler-compatible lifecycle with immediate, deterministic publication.

    No worker tasks or live dependencies are created. start(), refresh(), and
    update_accounts() publish synchronously on the caller's event loop; repeated
    start() is idempotent and stop() permanently prevents further publication.
    Account updates may select, disable, or edit only this scenario's fictional
    profiles, never supply live credentials or introduce a live account.
    """

    def __init__(
        self,
        *,
        scenario: str = "healthy",
        publish: Callable[[Snapshot], None],
        clock: DemoClock | None = None,
    ) -> None:
        if scenario not in {"healthy", "errors"}:
            raise ValueError("Unknown demo scenario; choose healthy or errors.")
        fixture = json.loads(
            files("usage_tui").joinpath("fixtures/demo.json").read_text(encoding="utf-8")
        )
        self.clock = clock if clock is not None else DemoClock(parse_timestamp(fixture["now"]))
        self._epoch = self.clock.now()
        self._publish = publish
        self._running = False
        self._closed = False
        self._profiles = {item["id"]: item for item in fixture["scenarios"][scenario]}
        self._templates = fixture["providers"]
        self._fixture_accounts = {
            item["id"]: Account(
                id=item["id"],
                provider=ProviderId(item["provider"]),
                label=item["label"],
                organization_id=self._templates[item["provider"]].get("organization_id"),
            )
            for item in self._profiles.values()
        }
        self.accounts = tuple(self._fixture_accounts.values())

    def tick(self, seconds: float = 1) -> datetime:
        """Advance countdown time only: no refresh or automatic quota reset."""
        return self.clock.advance(seconds)

    async def start(self) -> None:
        if self._closed:
            raise RuntimeError("Demo source is stopped.")
        if not self._running:
            self._running = True
            self._emit()

    async def refresh(self, account_id: str | None = None) -> None:
        if self._running and not self._closed:
            self._emit(account_id)

    async def update_accounts(self, accounts: Iterable[Account]) -> None:
        if self._closed:
            return
        accounts = tuple(accounts)
        seen = set()
        for account in accounts:
            original = self._fixture_accounts.get(account.id)
            if (
                original is None
                or account.id in seen
                or account.provider != original.provider
                or account.credential_ref is not None
                or account.credential_selector is not None
                or account.organization_id != original.organization_id
            ):
                raise ValueError("Demo accepts only its fictional credential-free profiles.")
            seen.add(account.id)
        self.accounts = accounts
        if self._running:
            self._emit()

    async def stop(self) -> None:
        self._closed = True
        self._running = False

    def _emit(self, account_id: str | None = None) -> None:
        for account in self.accounts:
            if self._closed:
                break
            if account.enabled and (account_id is None or account.id == account_id):
                self._publish(self._snapshot(account))

    def _snapshot(self, account: Account) -> Snapshot:
        profile = self._profiles[account.id]
        template = self._templates[account.provider.value]
        state = FetchState(profile.get("fetch_state", "ok"))
        unknown_all = profile.get("unknown_all", False)
        unknown_ids = profile.get("unknown_metrics", ())
        metrics = []
        for item in template["metrics"]:
            unknown = unknown_all or item["id"] in unknown_ids
            detail = item.get("detail", "Fictional synthetic demonstration; not live account data.")
            if unknown:
                detail = "Synthetic missing or malformed field; current value unknown, never zero."
            elif "fetched_offset" in profile:
                detail = "Synthetic stale LAST KNOWN observation; latest attempt failed. " + detail
            metrics.append(
                Metric(
                    id=item["id"],
                    label=item["label"],
                    state=MetricState.UNKNOWN if unknown else MetricState.READY,
                    source=_SOURCE,
                    quota=(
                        QuotaValue(used_percent=item["used_percent"])
                        if not unknown and "used_percent" in item
                        else None
                    ),
                    balance=(
                        Money(item["balance_minor"], "USD", 2)
                        if not unknown and "balance_minor" in item
                        else None
                    ),
                    reset_at=(
                        self._epoch + timedelta(seconds=item["reset_offset"])
                        if not unknown and "reset_offset" in item
                        else None
                    ),
                    shared_pool_id=item.get("shared_pool_id"),
                    share_percent=(
                        item["share_percent"] if not unknown and "share_percent" in item else None
                    ),
                    detail=detail,
                )
            )
        required = REQUIRED_METRIC_IDS[account.provider]
        metric_ids = tuple(metric.id for metric in metrics)
        if metric_ids[: len(required)] != required or len(set(metric_ids)) != len(metric_ids):
            raise ValueError(
                "Demo fixture must contain required metrics first, then unique extras."
            )
        grants = tuple(
            Grant(
                category=GrantCategory(item["category"]),
                granted=Money(item["granted_minor"], "USD", 2),
                remaining=Money(item["remaining_minor"], "USD", 2),
                name=item["name"],
                expires_at=(
                    self._epoch + timedelta(seconds=item["expiry_offset"])
                    if "expiry_offset" in item
                    else None
                ),
            )
            for item in template.get("grants", ())
            if not unknown_all
        )
        return Snapshot(
            account_id=account.id,
            metrics=tuple(metrics),
            grants=grants,
            fetch_state=state,
            attempted_at=self.clock.now(),
            fetched_at=(
                None
                if unknown_all
                else self._epoch + timedelta(seconds=profile["fetched_offset"])
                if "fetched_offset" in profile
                else self.clock.now()
            ),
            retry_at=(
                self._epoch + timedelta(seconds=profile["retry_offset"])
                if "retry_offset" in profile
                else None
            ),
            diagnostic=Diagnostic(profile["diagnostic"]) if "diagnostic" in profile else None,
            organization_id=account.organization_id,
        )
