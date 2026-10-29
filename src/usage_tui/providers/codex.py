"""Version-sensitive, read-only Codex quota windows from the private WHAM API."""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, DecimalException
from hashlib import sha256

from usage_tui.domain import (
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
    percent,
    sanitize_text,
    utc_datetime,
    validate_credential_binding,
)
from usage_tui.transport import Transport

_PROVIDER = ProviderId.CODEX_SUBSCRIPTION
_SOURCE = SourceRef(SourceKind.PRIVATE_HTTP, "codex.wham.usage.v1", version_sensitive=True)
_WEEKLY_LABEL = "Codex weekly (7d)"
_MISSING = "Usage is unavailable; missing does not mean zero or establish eligibility."


@dataclass(frozen=True, slots=True)
class _Window:
    used: Decimal | None
    reset: datetime | None
    detail: str


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


def _window(value: dict, detail: str) -> _Window:
    try:
        raw = value.get("used_percent")
        used = percent(str(raw) if type(raw) is float else raw)
    except DomainError:
        used = None
    return _Window(used, _reset(value.get("reset_at")), detail)


def _enforcement(value: dict) -> str:
    parts = []
    reached_type = value.get("rate_limit_reached_type")
    if isinstance(reached_type, dict):
        reached_type = reached_type.get("type")
    if isinstance(reached_type, str):
        parts.append("rate_limit_reached_type=" + sanitize_text(reached_type, max_length=128))
    return "; ".join(parts)


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
        label = f"Codex pool ({duration}s)"
    elif seconds == 604800:
        return MetricId.CODEX_WEEKLY, _WEEKLY_LABEL
    elif seconds == 18000:
        return MetricId.CODEX_FIVE_HOUR, "Codex 5h"
    else:
        metric_id = f"codex.subscription.window.{duration}"
        label = f"Codex window ({duration}s)"
    return (metric_id, label) if len(metric_id) <= 128 else None


def _metric(metric_id: str, label: str, windows: list[_Window]) -> tuple[Metric, bool]:
    details = list(dict.fromkeys(window.detail for window in windows if window.detail))
    usages = {window.used for window in windows if window.used is not None}
    resets = {window.reset for window in windows if window.reset is not None}
    used = next(iter(usages)) if len(usages) == 1 else None
    reset = next(iter(resets)) if len(resets) == 1 else None
    partial = not windows or any(window.used is None or window.reset is None for window in windows)
    if len(usages) > 1 or len(resets) > 1:
        partial = True
        details.append("Conflicting duplicate window values; conflicting fields are unknown.")
    if used is None:
        partial = True
        details.append(_MISSING)
    if reset is None:
        partial = True
        details.append("Absolute reset is unavailable; relative reset is not used as a timestamp.")
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
        response_detail = _enforcement(payload)

        def collect(limit: object, feature: str | None = None, name: str = "") -> None:
            nonlocal partial, recognized
            if not isinstance(limit, dict):
                partial = True
                return
            feature_detail = (
                "metered_feature=" + sanitize_text(feature, max_length=128)
                if feature is not None
                else ""
            )
            detail = "; ".join(
                part
                for part in (response_detail, name, feature_detail, _enforcement(limit))
                if part
            )
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
                    label = f"{label}: {name}" if name else label
                if metric_id not in grouped:
                    grouped[metric_id] = (label, [])
                grouped[metric_id][1].append(_window(value, detail))

        collect(payload.get("rate_limit"))
        if not grouped[MetricId.CODEX_WEEKLY][1]:
            main = payload.get("rate_limit")
            detail = "; ".join(
                part
                for part in (response_detail, _enforcement(main) if isinstance(main, dict) else "")
                if part
            )
            grouped[MetricId.CODEX_WEEKLY][1].append(_Window(None, None, detail))
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
        if partial:
            # A malformed unclassifiable sibling has no invented identity/row.
            # Preserve its existence safely on the always-present weekly row.
            weekly = metrics[0]
            metrics[0] = Metric(
                id=weekly.id,
                label=weekly.label,
                state=weekly.state,
                source=weekly.source,
                quota=weekly.quota,
                reset_at=weekly.reset_at,
                detail=(weekly.detail + "; " if weekly.detail else "")
                + "Response is partial; some windows or fields are unavailable or malformed.",
            )
        # Recognized identities remain partial even when reconciliation leaves
        # no usable quota; only an unrecognizable response is a schema error.
        state = FetchState.PARTIAL if partial else FetchState.OK
        if not recognized:
            state = FetchState.SCHEMA_ERROR
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
