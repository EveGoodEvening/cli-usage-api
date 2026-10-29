"""Version-sensitive, read-only Claude subscription usage normalization."""

from datetime import UTC, datetime
from decimal import Decimal, DecimalException

from cli_usage_api.domain import (
    REQUIRED_METRIC_IDS,
    Account,
    Diagnostic,
    DomainError,
    FetchState,
    Metric,
    MetricState,
    ProviderId,
    QuotaValue,
    ResolvedCredential,
    Snapshot,
    SourceKind,
    SourceRef,
    TransportError,
    parse_timestamp,
    percent,
    utc_datetime,
    validate_credential_binding,
)
from cli_usage_api.transport import Transport

_PROVIDER = ProviderId.CLAUDE_SUBSCRIPTION
_SOURCE = SourceRef(SourceKind.PRIVATE_HTTP, "claude.oauth.usage", version_sensitive=True)
_LABELS = ("Claude 5 小时", "Claude 每周", "Fable 每周（模型范围，非额外额度）")
_MISSING = "Usage is unavailable in this response; absence does not establish eligibility."


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


class ClaudeProvider:
    """Fetch all three subscription rows in one fixed-origin Transport read."""

    requires_credential = True
    metric_ids = REQUIRED_METRIC_IDS[_PROVIDER]

    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    async def fetch(
        self, account: Account, credential: ResolvedCredential | None, now: datetime
    ) -> Snapshot:
        now = utc_datetime(now)
        failure = None
        if account.provider != _PROVIDER:
            failure = "credential_mismatch"
        elif credential is None:
            failure = "credential_unavailable"
        else:
            try:
                validate_credential_binding(_PROVIDER, credential)
                if account.credential_kind != credential.credential_kind:
                    failure = "credential_mismatch"
                elif credential.expires_at is not None and credential.expires_at <= now:
                    failure = "credential_expired"
            except DomainError:
                failure = "credential_mismatch"
        if failure is not None:
            return self._failure(account, now, FetchState.AUTH_REQUIRED, failure)
        try:
            payload = await self._transport.get_json(
                _PROVIDER, "/api/oauth/usage", credential=credential
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
                    "Conflicting scoped Fable windows; usage is unknown."
                    if metric_id == self.metric_ids[2] and conflict
                    else _MISSING
                )
            elif window[2]:
                partial = True
                detail = "Usage is valid, but the reported reset timestamp is invalid."
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
        if not usable:
            state = FetchState.SCHEMA_ERROR
        return Snapshot(
            account_id=account.id,
            metrics=tuple(metrics),
            grants=(),
            fetch_state=state,
            attempted_at=now,
            fetched_at=now if usable else None,
            diagnostic=Diagnostic("schema_error" if not usable else "partial_data")
            if partial
            else None,
        )

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
        )
