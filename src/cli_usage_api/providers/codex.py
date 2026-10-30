"""Version-sensitive, read-only Codex quota windows from the private WHAM API."""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, DecimalException
from hashlib import sha256

from cli_usage_api.domain import (
    REQUIRED_METRIC_IDS,
    Account,
    Diagnostic,
    DomainError,
    FetchState,
    Metric,
    MetricId,
    MetricState,
    ProviderId,
    QuotaValue,
    ResolvedCredential,
    Snapshot,
    SourceKind,
    SourceRef,
    TransportError,
    credit_amount,
    percent,
    sanitize_text,
    utc_datetime,
    validate_credential_binding,
)
from cli_usage_api.transport import Transport

_PROVIDER = ProviderId.CODEX_SUBSCRIPTION
_SOURCE = SourceRef(SourceKind.PRIVATE_HTTP, "codex.wham.usage.v1", version_sensitive=True)
_WEEKLY_LABEL = "Codex weekly (7d)"
_MISSING = "本次未返回"
_CREDITS_LABEL = "Codex credits"


@dataclass(frozen=True, slots=True)
class _Window:
    used: Decimal | None
    reset: datetime | None


def _reset(value: object) -> datetime | None:
    # Absolute integer Unix seconds only: relative seconds are not an epoch,
    # and neither millisecond guessing nor numeric strings are part of this wire.
    if type(value) not in (int, float, Decimal):
        return None
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number != number.to_integral_value():
            return None
        if not Decimal(-62135596800) <= number <= Decimal(253402300799):
            return None
        return datetime.fromtimestamp(int(number), UTC)
    except (ValueError, OverflowError, OSError, DecimalException):
        return None


def _window(value: dict) -> _Window:
    try:
        raw = value.get("used_percent")
        used = percent(str(raw) if type(raw) is float else raw)
    except DomainError:
        used = None
    return _Window(used, _reset(value.get("reset_at")))


def _span(seconds: int) -> str:
    """A window length in its largest whole unit: 7d, 5h, 90m or 45s."""
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds % size == 0:
            return f"{seconds // size}{unit}"
    return f"{seconds}s"


def _identity(seconds: int, feature: str | None) -> tuple[str, str] | None:
    # Reject durations that cannot fit any metric identity before converting
    # an arbitrarily large injected integer to text.
    if seconds.bit_length() > 340:
        return None
    duration = str(seconds)
    if feature is not None:
        try:
            digest = sha256(feature.encode("utf-8")).hexdigest()
        except UnicodeEncodeError:
            return None
        metric_id = f"codex.pool.{digest}.window.{duration}"
        label = f"Codex pool ({_span(seconds)})"
    elif seconds == 604800:
        return MetricId.CODEX_WEEKLY, _WEEKLY_LABEL
    elif seconds == 18000:
        return MetricId.CODEX_FIVE_HOUR, "Codex 5h"
    else:
        metric_id = f"codex.subscription.window.{duration}"
        label = f"Codex {_span(seconds)}"
    return (metric_id, label) if len(metric_id) <= 128 else None


def _metric(metric_id: str, label: str, windows: list[_Window]) -> tuple[Metric, bool]:
    details = []
    usages = {window.used for window in windows if window.used is not None}
    resets = {window.reset for window in windows if window.reset is not None}
    used = next(iter(usages)) if len(usages) == 1 else None
    reset = next(iter(resets)) if len(resets) == 1 else None
    partial = not windows or any(window.used is None or window.reset is None for window in windows)
    if len(usages) > 1 or len(resets) > 1:
        partial = True
        details.append("重复窗口数值冲突")
    if used is None:
        partial = True
        details.append(_MISSING)
    if reset is None:
        partial = True
    return (
        Metric(
            id=metric_id,
            label=label,
            state=MetricState.READY if used is not None else MetricState.UNKNOWN,
            source=_SOURCE,
            quota=QuotaValue(used_percent=used) if used is not None else None,
            reset_at=reset,
            detail="; ".join(details) or None,
        ),
        partial,
    )


def _credits(value: object) -> Metric | None:
    """Optional credit-balance row from the same response's ``credits`` object.

    Mirrors the official client's CreditStatusDetails handling: ``unlimited``
    is checked first, ``has_credits == false`` shows nothing, otherwise the
    balance amount is exact text. Absence is no row, never a zero balance.
    """
    if value is None:
        return None

    def unknown(detail: str) -> Metric:
        return Metric(
            MetricId.CODEX_CREDITS,
            _CREDITS_LABEL,
            MetricState.UNKNOWN,
            _SOURCE,
            detail=detail + "；缺失不代表为零。",
        )

    if not isinstance(value, dict):
        return unknown("credits 格式无效")
    if value.get("unlimited") is True:
        return Metric(
            MetricId.CODEX_CREDITS,
            _CREDITS_LABEL,
            MetricState.READY,
            _SOURCE,
            unlimited=True,
        )
    has_credits = value.get("has_credits")
    if has_credits is False:
        return None
    if has_credits is not True:
        return unknown("credits 格式无效")
    balance = value.get("balance")
    if type(balance) in (str, int, Decimal):
        try:
            amount = credit_amount(balance)
        except DomainError:
            amount = None
        if amount is not None:
            return Metric(
                MetricId.CODEX_CREDITS,
                _CREDITS_LABEL,
                MetricState.READY,
                _SOURCE,
                credits=amount,
            )
    return unknown("有可用 credits，但数量未知")


class CodexProvider:
    """Fetch main and independently identified additional windows in one read."""

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
                _PROVIDER, "/backend-api/wham/usage", credential=credential
            )
        except TransportError as error:
            return self._failure(
                account, now, error.fetch_state, error.code, retry_at=error.retry_at
            )
        if not isinstance(payload, dict):
            return self._failure(account, now, FetchState.SCHEMA_ERROR, "schema_error")

        grouped: dict[str, tuple[str, list[_Window]]] = {MetricId.CODEX_WEEKLY: (_WEEKLY_LABEL, [])}
        partial = False
        recognized = False

        def collect(limit: object, feature: str | None = None, name: str = "") -> None:
            nonlocal partial, recognized
            if not isinstance(limit, dict):
                partial = True
                return
            for slot in ("primary_window", "secondary_window"):
                value = limit.get(slot)
                if value is None:
                    continue
                if not isinstance(value, dict):
                    partial = True
                    continue
                seconds = value.get("limit_window_seconds")
                if type(seconds) is not int or seconds <= 0:
                    partial = True
                    continue
                identity = _identity(seconds, feature)
                if identity is None:
                    partial = True
                    continue
                metric_id, label = identity
                recognized = True
                if feature is not None:
                    label = f"Codex {name} ({_span(seconds)})" if name else label
                if metric_id not in grouped:
                    grouped[metric_id] = (label, [])
                grouped[metric_id][1].append(_window(value))

        collect(payload.get("rate_limit"))
        if not grouped[MetricId.CODEX_WEEKLY][1]:
            grouped[MetricId.CODEX_WEEKLY][1].append(_Window(None, None))
        additional = payload.get("additional_rate_limits")
        if additional is not None:
            if not isinstance(additional, list):
                partial = True
            else:
                for entry in additional:
                    if not isinstance(entry, dict):
                        partial = True
                        continue
                    feature = entry.get("metered_feature")
                    if not isinstance(feature, str) or not feature.strip():
                        partial = True
                        continue
                    limit_name = entry.get("limit_name")
                    name = sanitize_text(
                        limit_name
                        if isinstance(limit_name, str) and limit_name.strip()
                        else feature,
                        max_length=80,
                    )
                    collect(entry.get("rate_limit"), feature, name)
        metrics = []
        for metric_id, (label, windows) in grouped.items():
            metric, incomplete = _metric(metric_id, label, windows)
            metrics.append(metric)
            partial |= incomplete
        # Recognized identities remain partial even when reconciliation leaves
        # no usable quota; only an unrecognizable response is a schema error.
        state = FetchState.PARTIAL if partial else FetchState.OK
        if not recognized:
            state = FetchState.SCHEMA_ERROR
        else:
            # Optional extra: never affects fetch state, diagnostic or partiality,
            # and an unrecognized (schema-error) response is not an observation.
            credits = _credits(payload.get("credits"))
            if credits is not None:
                metrics.append(credits)
        return Snapshot(
            account_id=account.id,
            metrics=tuple(metrics),
            grants=(),
            fetch_state=state,
            attempted_at=now,
            fetched_at=now if recognized else None,
            diagnostic=Diagnostic("schema_error" if not recognized else "partial_data")
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
            metrics=(
                Metric(
                    MetricId.CODEX_WEEKLY,
                    _WEEKLY_LABEL,
                    MetricState.UNKNOWN,
                    _SOURCE,
                    detail=_MISSING,
                ),
            ),
            grants=(),
            fetch_state=state,
            attempted_at=now,
            retry_at=retry_at,
            diagnostic=Diagnostic(code),
        )
