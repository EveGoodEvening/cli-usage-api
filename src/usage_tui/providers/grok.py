"""Version-sensitive Grok billing read; product consumption is not a quota."""

from datetime import datetime
from decimal import Decimal
from hashlib import sha256

from usage_tui.domain import (
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
    sanitize_text,
    utc_datetime,
    validate_credential_binding,
)
from usage_tui.transport import Transport

_PROVIDER = ProviderId.GROK_SUBSCRIPTION
_SOURCE = SourceRef(SourceKind.PRIVATE_HTTP, "grok.cli.billing.credits", version_sensitive=True)
_LABELS = ("Grok 共享池", "GrokBuild", "GrokChat")
_MISSING = "Usage is unavailable in this response; missing does not mean zero."


def _percent(value: object) -> Decimal:
    return percent(str(value) if type(value) is float else value)


def _period(config: dict) -> tuple[str, datetime | None, bool]:
    period = config.get("currentPeriod", {})
    if not isinstance(period, dict):
        return "period", None, True
    label = {
        "USAGE_PERIOD_TYPE_WEEKLY": "weekly",
        "USAGE_PERIOD_TYPE_MONTHLY": "monthly",
    }.get(period.get("type") if isinstance(period.get("type"), str) else None, "period")
    end = period["end"] if "end" in period else config.get("billingPeriodEnd")
    try:
        reset = parse_timestamp(end)
        if "start" in period:
            start = parse_timestamp(period["start"])
            if start > reset:
                return label, None, True
    except DomainError:
        return label, None, True
    return label, reset, False


def _products(
    config: dict, aggregate: Decimal | None, *, omitted_zero: bool
) -> dict[str, Decimal] | None:
    entries = config.get("productUsage")
    if not isinstance(entries, list) or aggregate is None:
        return None
    products = {}
    for entry in entries:
        if not isinstance(entry, dict):
            return None
        name = entry.get("product")
        if not isinstance(name, str) or not name.strip() or name in products:
            return None
        try:
            value = entry.get("usagePercent", 0) if omitted_zero else entry.get("usagePercent")
            products[name] = _percent(value)
        except DomainError:
            return None
    return products


def _product_id(name: str) -> str:
    encoded = name.encode("utf-8", errors="surrogatepass")
    return "grok.product.other." + sha256(encoded).hexdigest()


class GrokProvider:
    """Normalize one billing payload without inventing per-product allowances."""

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
                if (
                    account.credential_kind != credential.credential_kind
                    or credential.secret.startswith("xai-")
                ):
                    failure = "credential_mismatch"
                elif credential.expires_at is not None and credential.expires_at <= now:
                    failure = "credential_expired"
            except DomainError:
                failure = "credential_mismatch"
        if failure is not None:
            return self._failure(account, now, FetchState.AUTH_REQUIRED, failure)
        try:
            payload = await self._transport.get_json(
                _PROVIDER, "/v1/billing?format=credits", credential=credential
            )
        except TransportError as error:
            return self._failure(
                account, now, error.fetch_state, error.code, retry_at=error.retry_at
            )
        if not isinstance(payload, dict) or not isinstance(payload.get("config"), dict):
            return self._failure(account, now, FetchState.SCHEMA_ERROR, "schema_error")
        config = payload["config"]
        period, reset, bad_period = _period(config)
        # BYOS's weekly billing parser and ProtoJSON omit default-valued
        # scalars. Require explicit, valid weekly context; an arbitrary empty
        # config, malformed present value, or missing product is not zero.
        omitted_zero = period == "weekly" and not bad_period
        try:
            value = (
                config.get("creditUsagePercent", 0)
                if omitted_zero
                else config.get("creditUsagePercent")
            )
            aggregate = _percent(value)
        except DomainError:
            aggregate = None
        unified = config.get("isUnifiedBillingUser") is True
        # The informational breakdown has no documented sum-to-total invariant.
        products = _products(config, aggregate, omitted_zero=omitted_zero)
        detail = [
            f"Reported aggregate consumption: {aggregate}%." if aggregate is not None else _MISSING
        ]
        detail.append(f"Server period: {period}.")
        if not unified:
            detail.append("Pool relationship unknown; remaining/reset unavailable.")
        elif bad_period:
            detail.append("Period reset is missing, invalid, or has reversed bounds.")
        tier = config.get("subscriptionTier", config.get("subscription_tier"))
        if tier is None:
            tier = payload.get("subscriptionTier", payload.get("subscription_tier"))
        if isinstance(tier, str):
            detail.append(
                f"Reported plan: {sanitize_text(tier, max_length=120)}; no assumed quota."
            )
        metrics = [
            Metric(
                self.metric_ids[0],
                _LABELS[0] if unified else "Grok reported aggregate",
                MetricState.READY if aggregate is not None else MetricState.UNKNOWN,
                _SOURCE,
                quota=QuotaValue(used_percent=aggregate)
                if unified and aggregate is not None
                else None,
                # Without proven pool semantics the aggregate is consumption only.
                share_percent=aggregate if not unified else None,
                reset_at=reset if unified and aggregate is not None else None,
                detail=" ".join(detail),
            )
        ]
        names = [("GrokBuild", self.metric_ids[1]), ("GrokChat", self.metric_ids[2])]
        if products is not None:
            names.extend(
                (name, _product_id(name))
                for name in products
                if name not in ("GrokBuild", "GrokChat")
            )
        for name, metric_id in names:
            used = None if products is None else products.get(name)
            linked = unified and aggregate is not None and used is not None
            product_detail = _MISSING
            if used is not None:
                product_detail = f"Reported consumption share: {used}%. Not an independent quota. "
                product_detail += (
                    "剩余/重置：共享池 (remaining/reset: shared pool)."
                    if linked
                    else "Pool relationship unknown; remaining/reset unavailable."
                )
            metrics.append(
                Metric(
                    metric_id,
                    sanitize_text(name, max_length=120) or metric_id,
                    MetricState.READY if used is not None else MetricState.UNKNOWN,
                    _SOURCE,
                    # QuotaValue derives 100-used: product consumption is a share,
                    # never a quota exposing an independent remaining allowance.
                    share_percent=used,
                    shared_pool_id=self.metric_ids[0] if linked else None,
                    reset_at=reset if linked else None,
                    detail=product_detail,
                )
            )
        usable = aggregate is not None
        partial = (
            bad_period or not unified or any(row.state == MetricState.UNKNOWN for row in metrics)
        )
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
