"""Read-only, version-sensitive OpenAI Platform prepaid credit balance.

Contract (official platform.openai.com dashboard bundle, static inspection):
``GET https://api.openai.com/v1/dashboard/billing/credit_grants`` with the
dashboard session key as Bearer and ``OpenAI-Organization``. The client reads only
``total_available``; ``total_paid_available``, ``total_granted``, ``total_used``
and ``grants.data[]`` are community-sampled and therefore optional. The payload
has no currency: USD is a documented contract assumption. Amounts stay exact
(Transport decodes JSON numbers as ``Decimal``); presentation rounds to cents.
Available balance is reported, never derived from granted minus used.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cli_usage_api.domain import (
    REQUIRED_METRIC_IDS,
    Account,
    Diagnostic,
    DomainError,
    ExactMoney,
    FetchState,
    Metric,
    MetricId,
    MetricState,
    ProviderId,
    ResolvedCredential,
    Snapshot,
    SourceKind,
    SourceRef,
    TransportError,
    credit_amount,
    format_timestamp,
    openai_session_key,
    utc_datetime,
    validate_credential_binding,
)
from cli_usage_api.transport import OPENAI_CREDIT_GRANTS_PATH, Transport

_PROVIDER = ProviderId.OPENAI_PLATFORM
_SOURCE = SourceRef(
    SourceKind.PRIVATE_HTTP, "openai.platform.billing.credit_grants", version_sensitive=True
)
# The dashboard bills in USD and hard-codes USD formatting; the payload names none.
_CURRENCY = "USD"
_AVAILABLE_LABEL = "OpenAI 可用余额"
_PAID_LABEL = "OpenAI 付费余额"
_MISSING = "Available balance is missing or invalid; missing does not mean zero"
_MAX_EPOCH = Decimal(253402300799)  # 9999-12-31T23:59:59Z
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_FAILURE_DETAILS = {
    "credential_unavailable": "No session key available; reconnect by pasting a new session key.",
    "credential_expired": "Dashboard session expired; reconnect by pasting a new session key.",
    "auth_required": "Session rejected; reconnect by pasting a new dashboard session key.",
    "credential_mismatch": (
        "Only a platform.openai.com dashboard session key works here; API keys (sk-...) do not."
    ),
    "permission_denied": (
        "Access denied: needs billing permission on this organization, and the"
        " organization must use prepaid billing."
    ),
    "rate_limited": "Rate limited; waiting for the retry deadline before reading again.",
}
_DEFAULT_FAILURE = "Balance unavailable; inspect the safe diagnostic."


def _amount(value: object) -> Decimal | None:
    """An exact JSON number (int or Decimal); strings, bools and hostile forms are invalid."""
    if type(value) not in (int, Decimal):
        return None
    try:
        return credit_amount(value)
    except DomainError:
        return None


def _epoch(value: object) -> datetime | None:
    """Absolute epoch seconds, integral or fractional; nothing else is guessed."""
    number = _amount(value)
    if number is None or not 0 <= number <= _MAX_EPOCH:
        return None
    seconds = int(number)
    microseconds = int((number - seconds) * 1_000_000)
    return _EPOCH + timedelta(seconds=seconds, microseconds=microseconds)


def _money_text(amount: Decimal) -> str:
    """A detail amount rounded half-even to cents, marked when rounding changed it.

    Detail text is shown verbatim on the TUI and web dashboards, so it follows
    the cents display rule; the structured ``exact_balance`` stays exact.
    """
    value = ExactMoney(amount, _CURRENCY)
    _, changed = value.rounded_to_cents()
    suffix = " (服务端金额已舍入到分 / rounded to cents)" if changed else ""
    return f"{value.format_cents()}{suffix}"


def _grants_summary(raw: object, now: datetime) -> tuple[str | None, bool]:
    """Detail-only grant summary; returns (text, partial). Never Grant objects.

    Grant amounts carry no minor-unit scale, and an expiry is a grant expiry,
    never a reset or renewal of the balance.
    """
    if raw is None:
        return None, False
    data = raw.get("data") if isinstance(raw, dict) else None
    if not isinstance(data, list):
        return "Grant list is invalid; grant summary unavailable.", True
    valid = 0
    invalid = 0
    expired = 0
    expiries = []
    for entry in data:
        if not isinstance(entry, dict):
            invalid += 1
            continue
        granted = _amount(entry.get("grant_amount"))
        used = _amount(entry.get("used_amount"))
        expires = _epoch(entry.get("expires_at"))
        effective = entry.get("effective_at")
        if (
            granted is None
            or used is None
            or expires is None
            or (effective is not None and _epoch(effective) is None)
        ):
            invalid += 1
            continue
        valid += 1
        if expires <= now:
            expired += 1
        else:
            expiries.append(expires)
    parts = [f"{valid} 笔授予"]
    if expired:
        parts.append(f"{expired} 笔已过期")
    if expiries:
        parts.append(f"最早 {format_timestamp(min(expiries))[:10]} 到期")
    text = "，".join(parts)
    if invalid:
        text += f"，{invalid} 笔无效"
    return text, bool(invalid)


class OpenAIPlatformProvider:
    """Fetch the saved organization's prepaid balance; no discovery, no writes."""

    requires_credential = True
    metric_ids = REQUIRED_METRIC_IDS[_PROVIDER]

    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    async def fetch(
        self, account: Account, credential: ResolvedCredential | None, now: datetime
    ) -> Snapshot:
        now = utc_datetime(now)
        failure = self._credential_error(account, credential, now)
        if failure is not None:
            return self._failure(account, now, FetchState.AUTH_REQUIRED, failure)
        try:
            payload = await self._transport.get_json(
                _PROVIDER, OPENAI_CREDIT_GRANTS_PATH, credential=credential
            )
        except TransportError as error:
            return self._failure(
                account, now, error.fetch_state, error.code, retry_at=error.retry_at
            )
        if not isinstance(payload, dict):
            return self._failure(account, now, FetchState.SCHEMA_ERROR, "schema_error")
        return self._snapshot(account, payload, now)

    @staticmethod
    def _credential_error(
        account: Account, credential: ResolvedCredential | None, now: datetime
    ) -> str | None:
        if account.provider != _PROVIDER:
            return "credential_mismatch"
        if credential is None:
            return "credential_unavailable"
        try:
            validate_credential_binding(_PROVIDER, credential)
            bare = openai_session_key(credential.secret) == credential.secret
        except DomainError:
            return "credential_mismatch"
        if (
            not bare
            or account.credential_kind != credential.credential_kind
            or credential.organization_id != account.organization_id
        ):
            return "credential_mismatch"
        if credential.expires_at is not None and credential.expires_at <= now:
            return "credential_expired"
        return None

    def _snapshot(self, account: Account, payload: dict, now: datetime) -> Snapshot:
        available = _amount(payload.get("total_available"))
        partial = available is None
        notes = []
        granted = _amount(payload.get("total_granted"))
        used = _amount(payload.get("total_used"))
        if granted is not None:
            notes.append(f"已授予 {_money_text(granted)}")
        if used is not None:
            notes.append(f"已用 {_money_text(used)}")
        grants, grants_partial = _grants_summary(payload.get("grants"), now)
        if grants is not None:
            notes.append(grants)
        partial = partial or grants_partial
        paid_raw = payload.get("total_paid_available")
        paid = _amount(paid_raw)
        if paid_raw is not None and paid is None:
            partial = True
            notes.append("付费余额格式不受支持")
        if available is None:
            notes.insert(0, _MISSING)
        detail = " · ".join(notes) or None
        metrics = [
            Metric(
                MetricId.OPENAI_AVAILABLE_BALANCE,
                _AVAILABLE_LABEL,
                MetricState.UNKNOWN if available is None else MetricState.READY,
                _SOURCE,
                detail=detail,
                exact_balance=None if available is None else ExactMoney(available, _CURRENCY),
            )
        ]
        if paid is not None:
            metrics.append(
                Metric(
                    MetricId.OPENAI_PAID_AVAILABLE_BALANCE,
                    _PAID_LABEL,
                    MetricState.READY,
                    _SOURCE,
                    exact_balance=ExactMoney(paid, _CURRENCY),
                )
            )
        usable = available is not None or paid is not None
        state = (
            FetchState.SCHEMA_ERROR
            if not usable
            else FetchState.PARTIAL
            if partial
            else FetchState.OK
        )
        return Snapshot(
            account.id,
            tuple(metrics),
            (),
            state,
            now,
            fetched_at=now if usable else None,
            diagnostic=None
            if state == FetchState.OK
            else Diagnostic("partial_data" if usable else "schema_error"),
            organization_id=account.organization_id,
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
            account.id,
            (
                Metric(
                    MetricId.OPENAI_AVAILABLE_BALANCE,
                    _AVAILABLE_LABEL,
                    MetricState.UNKNOWN,
                    _SOURCE,
                    detail=_FAILURE_DETAILS.get(code, _DEFAULT_FAILURE),
                ),
            ),
            (),
            state,
            now,
            retry_at=retry_at,
            diagnostic=Diagnostic(code),
            organization_id=account.organization_id if account.provider == _PROVIDER else None,
        )
