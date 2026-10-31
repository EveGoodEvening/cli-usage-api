"""Version-sensitive, read-only Claude subscription usage normalization."""

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal, DecimalException
from types import MappingProxyType

from cli_usage_api.domain import (
    REQUIRED_METRIC_IDS,
    Account,
    Diagnostic,
    DomainError,
    FetchState,
    Metric,
    MetricId,
    MetricState,
    Money,
    ProviderId,
    QuotaValue,
    ResolvedCredential,
    Snapshot,
    SourceKind,
    SourceRef,
    TransportError,
    claude_organization_id,
    format_timestamp,
    parse_timestamp,
    percent,
    utc_datetime,
    validate_credential_binding,
)
from cli_usage_api.providers.console import OrganizationChoice
from cli_usage_api.transport import (
    CLAUDE_PROFILE_PATH,
    CLAUDE_USAGE_PATH,
    Transport,
    claude_credits_path,
)

_PROVIDER = ProviderId.CLAUDE_SUBSCRIPTION
_SOURCE = SourceRef(SourceKind.PRIVATE_HTTP, "claude.oauth.usage", version_sensitive=True)
_LABELS = ("Claude 5 小时", "Claude 每周", "Claude Fable 每周")
_MISSING = "本次未返回。"


def _reset(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        return parse_timestamp(value)
    if type(value) not in (Decimal, int, float):
        raise DomainError("Invalid reset timestamp.")
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number <= 0:
            raise DomainError("Invalid reset timestamp.")
        if number >= 100_000_000_000:
            number /= 1000
        return datetime.fromtimestamp(float(number), UTC)
    except (ValueError, OverflowError, OSError, DecimalException):
        raise DomainError("Invalid reset timestamp.") from None


def _window(
    value: object, *, scoped: bool = False
) -> tuple[QuotaValue, datetime | None, bool] | None:
    if not isinstance(value, dict):
        return None
    raw = value.get("percent") if scoped else value.get("utilization")
    if not scoped and raw is None:
        raw = value.get("used_percentage")
    try:
        # Transport preserves fractional JSON numbers as exact Decimals.
        used = percent(str(raw) if type(raw) is float else raw)
    except DomainError:
        return None
    try:
        return QuotaValue(used_percent=used), _reset(value.get("resets_at")), False
    except DomainError:
        return QuotaValue(used_percent=used), None, True


def _fable(payload: dict) -> tuple[tuple[QuotaValue, datetime | None, bool] | None, bool]:
    candidates = []
    limits = payload.get("limits")
    if isinstance(limits, list):
        for entry in limits:
            if not isinstance(entry, dict) or entry.get("kind") != "weekly_scoped":
                continue
            scope = entry.get("scope")
            model = scope.get("model") if isinstance(scope, dict) else None
            name = model.get("display_name") if isinstance(model, dict) else None
            if not isinstance(name, str) or name.strip().casefold() != "fable":
                continue
            parsed = _window(entry, scoped=True)
            if parsed is not None:
                candidates.append(parsed)
    if candidates:
        first = candidates[0]
        if any(candidate[0] != first[0] for candidate in candidates[1:]):
            return None, True
        valid_resets = [candidate[1] for candidate in candidates if not candidate[2]]
        if valid_resets and any(reset != valid_resets[0] for reset in valid_resets[1:]):
            return None, True
        invalid_reset = any(candidate[2] for candidate in candidates)
        # Malformed resets cannot contradict valid usage, but leave the reset unknown.
        reset = None if invalid_reset else first[1]
        return (first[0], reset, invalid_reset), False
    for alias in ("fable_weekly", "fable_seven_day", "seven_day_fable"):
        parsed = _window(payload.get(alias))
        if parsed is not None:
            return parsed, False
    return None, False


_EXTRA_LABEL = "Claude 额外用量"
# Explicit ISO 4217 minor-unit exponents; unknown codes leave amounts unknown
# rather than guessing a scale (and absent currency never defaults to USD).
_CURRENCY_EXPONENTS = MappingProxyType(
    {
        **dict.fromkeys(
            (
                "USD", "EUR", "GBP", "CAD", "AUD", "NZD", "SGD", "HKD",
                "CHF", "SEK", "NOK", "DKK", "MXN", "BRL", "INR", "CNY",
            ),
            2,
        ),
        "JPY": 0,
        "KRW": 0,
    }
)  # fmt: skip
_MAX_MINOR_UNITS = 10**15
_EXTRA_PERIOD_NOTE = (
    "Extra usage spend in the current billing period; the server provides no reset time."
)


def _currency(value: object) -> tuple[str | None, int | None]:
    """Uppercase a 3-letter code and look up its explicit ISO exponent.

    Absent, malformed or unmapped codes yield ``(None, None)``: amounts stay
    unknown rather than defaulting to USD or guessing a scale.
    """
    if isinstance(value, str) and re.fullmatch(r"[A-Za-z]{3}", value):
        code = value.upper()
        exponent = _CURRENCY_EXPONENTS.get(code)
        if exponent is not None:
            return code, exponent
    return None, None


def _minor_units(value: object) -> int | None:
    """Read a nonnegative integral minor-unit amount, bounded before arithmetic."""
    if type(value) is int:
        return value if 0 <= value <= _MAX_MINOR_UNITS else None
    if type(value) is not Decimal or not value.is_finite():
        return None
    # Compare magnitude first: a compact exponent must not force a large expansion.
    if value < 0 or value > _MAX_MINOR_UNITS or value != value.to_integral_value():
        return None
    return int(value)


def _extra_usage(payload: dict) -> Metric | None:
    """Parse the optional extra-usage spend row from the same usage response.

    Amounts are minor currency units against an optional monthly spending cap;
    this is consumption, never a balance or a subscription allowance.
    """
    raw = payload.get("extra_usage")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        return Metric(
            MetricId.CLAUDE_EXTRA_USAGE,
            _EXTRA_LABEL,
            MetricState.UNKNOWN,
            _SOURCE,
            detail="Extra usage format is invalid; values are unknown.",
        )
    enabled = raw.get("is_enabled")
    if type(enabled) is not bool:
        return Metric(
            MetricId.CLAUDE_EXTRA_USAGE,
            _EXTRA_LABEL,
            MetricState.UNKNOWN,
            _SOURCE,
            detail="Extra usage status is missing or invalid; values are unknown.",
        )
    notes = []
    if not enabled:
        notes.append("Extra usage is currently unavailable.")
        reason = raw.get("disabled_reason")
        if isinstance(reason, str) and re.fullmatch(r"[a-z0-9_]{1,64}", reason):
            notes.append(f"Reason: {reason}.")
    notes.append(_EXTRA_PERIOD_NOTE)

    currency, exponent = _currency(raw.get("currency"))

    def money(key: str, label: str) -> Money | None:
        value = raw.get(key)
        if value is None:
            return None
        minor = _minor_units(value)
        if minor is None:
            notes.append(f"Reported {label} is invalid; amount unknown.")
            return None
        if exponent is None:
            return None
        return Money(minor, currency, exponent)

    spent = money("used_credits", "spend")
    has_cap = "monthly_limit" in raw and raw["monthly_limit"] is not None
    spend_limit = money("monthly_limit", "monthly limit")
    unlimited = enabled and "monthly_limit" in raw and raw["monthly_limit"] is None
    if unlimited:
        notes.append("No monthly spending cap.")
    elif "monthly_limit" not in raw:
        notes.append("Monthly spending cap is not reported; cap is unknown.")
    has_amount = raw.get("used_credits") is not None or has_cap
    if exponent is None and has_amount:
        notes.append("Currency is missing or unsupported; amounts are unknown.")

    quota = None
    utilization = raw.get("utilization")
    if has_cap and utilization is not None:
        try:
            quota = QuotaValue(
                used_percent=percent(
                    str(utilization) if type(utilization) is float else utilization
                )
            )
        except DomainError:
            notes.append("Reported cap utilization is invalid; utilization unknown.")
    return Metric(
        MetricId.CLAUDE_EXTRA_USAGE,
        _EXTRA_LABEL,
        MetricState.READY,
        _SOURCE,
        quota=quota,
        detail=" ".join(notes),
        spent=spent,
        spend_limit=spend_limit,
        unlimited=unlimited,
    )


_CREDITS_SOURCE = SourceRef(
    SourceKind.PRIVATE_HTTP, "claude.oauth.prepaid.credits", version_sensitive=True
)
_CREDITS_LABEL = "Claude credits 余额"
_CREDITS_RATE_LIMIT_COOLDOWN = timedelta(seconds=180)
_CREDITS_FAILURES = MappingProxyType(
    {
        "auth_required": "未授权：请重新连接账号。",
        "permission_denied": "无计费权限，或此方案不支持预付 credits。",
        "organization_not_found": "找不到组织：请在账号设置中重新选择。",
        "rate_limited": "限流：到重试时间后再读取。",
        "schema_error": "响应格式无效。",
    }
)
_CREDITS_FALLBACK = "读取失败。"


def _credits_unknown(detail: str) -> Metric:
    return Metric(
        MetricId.CLAUDE_CREDIT_BALANCE,
        _CREDITS_LABEL,
        MetricState.UNKNOWN,
        _CREDITS_SOURCE,
        detail=detail,
    )


def _promo_summary(raw: object, currency: str, exponent: int, now: datetime) -> str | None:
    """Summarize promotional tranches as detail only; never Grants or a balance.

    Remaining promo amounts are already included in the reported balance, and
    the granted amounts are unknown. Expiry is a credit expiry, never a reset.
    """
    if raw is None:
        return None
    if not isinstance(raw, list):
        return "促销信息格式无效。"
    active = 0
    total = 0
    expired = 0
    nearest = None
    invalid = False
    for entry in raw:
        if not isinstance(entry, dict):
            invalid = True
            continue
        remaining = _minor_units(entry.get("remaining_amount_minor_units"))
        code, _ = _currency(entry.get("currency"))
        try:
            expiry = parse_timestamp(entry.get("expires_at"))
        except DomainError:
            expiry = None
        if remaining is None or expiry is None or code != currency:
            invalid = True
            continue
        if expiry <= now:
            expired += 1
            continue
        if remaining == 0:
            continue
        active += 1
        total += remaining
        nearest = expiry if nearest is None else min(nearest, expiry)
    notes = []
    if active:
        notes.append(
            f"含促销 {Money(total, currency, exponent).format()}（{active} 笔），"
            f"最早 {format_timestamp(nearest)[:10]} 到期。"
        )
    if expired:
        notes.append(f"{expired} 笔促销已过期。")
    if invalid:
        notes.append("部分促销条目无效。")
    return "".join(notes)


def _credit_balance(payload: object, now: datetime) -> Metric:
    """Parse the prepaid credits balance; invalid amount/currency is unknown, never zero."""
    if not isinstance(payload, dict):
        return _credits_unknown(_CREDITS_FAILURES["schema_error"])
    currency, exponent = _currency(payload.get("currency"))
    raw_amount = payload.get("amount")
    amount = _minor_units(raw_amount)
    notes = []
    if amount is None:
        notes.append("金额无效。" if raw_amount is not None else "未返回金额。")
    if currency is None:
        notes.append("币种缺失或不受支持。")
    if amount is None or currency is None:
        return _credits_unknown("".join(notes))
    reload = payload.get("auto_reload_settings")
    enabled = reload.get("enabled") if isinstance(reload, dict) else None
    if type(enabled) is bool:
        notes.append(f"自动充值{'开' if enabled else '关'}。")
    months = payload.get("expiry_policy_months")
    if type(months) is int and 0 < months <= 1200:
        notes.append(f"有效期 {months} 个月。")
    promo = _promo_summary(payload.get("promo_tranches"), currency, exponent, now)
    if promo:
        notes.append(promo)
    return Metric(
        MetricId.CLAUDE_CREDIT_BALANCE,
        _CREDITS_LABEL,
        MetricState.READY,
        _CREDITS_SOURCE,
        balance=Money(amount, currency, exponent),
        detail="".join(notes) or None,
    )


def _credential_error(credential: ResolvedCredential | None, now: datetime) -> str | None:
    if credential is None:
        return "credential_unavailable"
    try:
        validate_credential_binding(_PROVIDER, credential)
    except DomainError:
        return "credential_mismatch"
    if credential.expires_at is not None and credential.expires_at <= now:
        return "credential_expired"
    return None


class ClaudeProvider:
    """Fetch subscription rows, plus an explicitly selected organization's credits.

    Without a saved organization this is exactly one usage read. With one, a
    second read of that organization's prepaid credits follows a usable usage
    response; organization discovery is a separate explicit connection action.
    """

    requires_credential = True
    metric_ids = REQUIRED_METRIC_IDS[_PROVIDER]

    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    async def discover_organizations(
        self, credential: ResolvedCredential, *, now: datetime | None = None
    ) -> tuple[OrganizationChoice, ...]:
        """Read the signed-in profile's organization as an explicit choice.

        The profile reports a single organization, so this yields at most one
        choice; the caller must still ask the user to confirm it. Never polled.
        """
        failure = _credential_error(
            credential, utc_datetime(now) if now is not None else datetime.now(UTC)
        )
        if failure is not None:
            raise TransportError(FetchState.AUTH_REQUIRED, failure)
        payload = await self._transport.get_json(
            _PROVIDER, CLAUDE_PROFILE_PATH, credential=credential
        )
        organization = payload.get("organization") if isinstance(payload, dict) else None
        if organization is None and isinstance(payload, dict) and "organization" in payload:
            return ()
        if not isinstance(organization, dict):
            raise TransportError(FetchState.SCHEMA_ERROR, "schema_error")
        try:
            organization_id = claude_organization_id(organization.get("uuid"))
        except DomainError:
            raise TransportError(FetchState.SCHEMA_ERROR, "schema_error") from None
        name = organization.get("name")
        label = name if isinstance(name, str) and name.strip() else organization_id
        try:
            choice = OrganizationChoice(organization_id, label)
        except DomainError:
            choice = None
        if choice is None or not choice.label:
            # An unusable display name falls back to the identifier itself.
            choice = OrganizationChoice(organization_id, organization_id)
        return (choice,)

    async def fetch(
        self, account: Account, credential: ResolvedCredential | None, now: datetime
    ) -> Snapshot:
        now = utc_datetime(now)
        failure = _credential_error(credential, now)
        if account.provider != _PROVIDER or (
            failure is None
            and (
                account.credential_kind != credential.credential_kind
                # The credits read is bound to the account's saved organization.
                or credential.organization_id != account.organization_id
            )
        ):
            failure = "credential_mismatch"
        if failure is not None:
            return self._failure(account, now, FetchState.AUTH_REQUIRED, failure)
        try:
            payload = await self._transport.get_json(
                _PROVIDER, CLAUDE_USAGE_PATH, credential=credential
            )
        except TransportError as error:
            return self._failure(
                account, now, error.fetch_state, error.code, retry_at=error.retry_at
            )
        if not isinstance(payload, dict):
            return self._failure(account, now, FetchState.SCHEMA_ERROR, "schema_error")
        fable, conflict = _fable(payload)
        windows = (_window(payload.get("five_hour")), _window(payload.get("seven_day")), fable)
        metrics = []
        partial = False
        for metric_id, label, window in zip(self.metric_ids, _LABELS, windows, strict=True):
            detail = None
            if window is None:
                partial = True
                detail = (
                    "Fable 窗口数值冲突。"
                    if metric_id == self.metric_ids[2] and conflict
                    else _MISSING
                )
            elif window[2]:
                # The row already reads "重置 — 未知"; partial_data covers the rest.
                partial = True
            metrics.append(
                Metric(
                    id=metric_id,
                    label=label,
                    state=MetricState.UNKNOWN if window is None else MetricState.READY,
                    source=_SOURCE,
                    quota=None if window is None else window[0],
                    reset_at=None if window is None else window[1],
                    detail=detail,
                )
            )
        usable = any(window is not None for window in windows)
        state = FetchState.PARTIAL if partial else FetchState.OK
        retry_at = None
        if not usable:
            state = FetchState.SCHEMA_ERROR
        else:
            # Optional extra: never affects fetch_state, diagnostic or usability.
            extra = _extra_usage(payload)
            if extra is not None:
                metrics.append(extra)
            if account.organization_id is not None:
                # Only after a usable 2xx usage payload; never after a failure.
                credits, retry_at = await self._credits(account, credential, now)
                metrics.append(credits)
                if credits.state != MetricState.READY:
                    partial = True
                    state = FetchState.PARTIAL
        return Snapshot(
            account_id=account.id,
            metrics=tuple(metrics),
            grants=(),
            fetch_state=state,
            attempted_at=now,
            fetched_at=now if usable else None,
            retry_at=retry_at,
            diagnostic=Diagnostic("schema_error" if not usable else "partial_data")
            if partial
            else None,
            organization_id=account.organization_id,
        )

    async def _credits(
        self, account: Account, credential: ResolvedCredential, now: datetime
    ) -> tuple[Metric, datetime | None]:
        try:
            payload = await self._transport.get_json(
                _PROVIDER, claude_credits_path(account.organization_id), credential=credential
            )
        except TransportError as error:
            code = "organization_not_found" if error.status == 404 else error.code
            detail = _CREDITS_FAILURES.get(code, _CREDITS_FALLBACK)
            retry_at = error.retry_at
            if retry_at is None and error.code == "rate_limited":
                # No usable Retry-After: a conservative local embargo (the Claude
                # 429 base) that the scheduler escalates on repeats.
                retry_at = now + _CREDITS_RATE_LIMIT_COOLDOWN
            return _credits_unknown(detail), retry_at
        return _credit_balance(payload, now), None

    def _failure(
        self,
        account: Account,
        now: datetime,
        state: FetchState,
        code: str,
        *,
        retry_at: datetime | None = None,
    ) -> Snapshot:
        return Snapshot(
            account_id=account.id,
            metrics=tuple(
                Metric(metric_id, label, MetricState.UNKNOWN, _SOURCE, detail=_MISSING)
                for metric_id, label in zip(self.metric_ids, _LABELS, strict=True)
            ),
            grants=(),
            fetch_state=state,
            attempted_at=now,
            retry_at=retry_at,
            diagnostic=Diagnostic(code),
            organization_id=account.organization_id if account.provider == _PROVIDER else None,
        )
