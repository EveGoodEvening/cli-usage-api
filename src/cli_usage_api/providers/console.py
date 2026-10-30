"""Read-only, version-sensitive Claude Platform prepaid credit contract."""

import re
from dataclasses import dataclass
from datetime import datetime

from cli_usage_api.domain import (
    REQUIRED_METRIC_IDS,
    Account,
    Diagnostic,
    DomainError,
    FetchState,
    Grant,
    GrantCategory,
    Metric,
    MetricState,
    Money,
    ProviderId,
    ResolvedCredential,
    Snapshot,
    SourceKind,
    SourceRef,
    TransportError,
    parse_timestamp,
    sanitize_text,
    utc_datetime,
    validate_credential_binding,
)
from cli_usage_api.transport import Transport

_PROVIDER = ProviderId.CLAUDE_PLATFORM
_SOURCE = SourceRef(
    SourceKind.PRIVATE_HTTP, "claude.platform.prepaid.credits", version_sensitive=True
)
_LABELS = ("Claude Platform 购买余额", "Claude Platform 赠送余额", "Claude Platform 总余额")
_ORGANIZATION = re.compile(r"[A-Za-z0-9-]{1,64}")
_COOKIE = re.compile(r"[\x21\x23-\x2b\x2d-\x3a\x3c-\x5b\x5d-\x7e]+")


@dataclass(frozen=True, slots=True)
class OrganizationChoice:
    """An explicit connection-screen choice, never an automatically saved selection."""

    id: str
    label: str

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or _ORGANIZATION.fullmatch(self.id) is None:
            raise DomainError("Invalid organization identifier.")
        object.__setattr__(self, "label", sanitize_text(self.label, max_length=120))


def _credential_error(credential: ResolvedCredential | None) -> str | None:
    if credential is None:
        return "credential_unavailable"
    try:
        validate_credential_binding(_PROVIDER, credential)
    except DomainError:
        return "credential_mismatch"
    if _COOKIE.fullmatch(credential.secret) is None:
        return "credential_mismatch"
    return None


def _units(payload: dict) -> tuple[str, int]:
    currency = payload.get("currency", "USD")
    balance = payload.get("balance", {})
    if not isinstance(balance, dict):
        raise DomainError("Invalid money units.")
    credits = balance.get("credits", {})
    if not isinstance(credits, dict):
        raise DomainError("Invalid money units.")
    exponent = credits.get("exponent", 2)
    # Money is the single source of currency/exponent validation.
    validated = Money(0, currency, exponent)
    return validated.currency, validated.exponent


def _category(
    raw: object, category: GrantCategory, currency: str, exponent: int, now: datetime
) -> tuple[Money | None, tuple[Grant, ...], datetime | None, str | None, bool]:
    if not isinstance(raw, list):
        return None, (), None, "Grant array missing or invalid; category balance is unknown.", True
    grants = []
    uncertain = False
    total = 0
    expiries = []
    for entry in raw:
        if not isinstance(entry, dict):
            return None, (), None, "Invalid grant; category balance is unknown.", True
        try:
            granted = Money(entry.get("granted_amount_minor_units"), currency, exponent)
            remaining = Money(entry.get("remaining_amount_minor_units"), currency, exponent)
        except DomainError:
            return None, (), None, "Invalid grant amounts; category balance is unknown.", True
        expiry = None
        try:
            expiry = parse_timestamp(entry.get("expires_at"))
        except DomainError:
            uncertain = True
        grant = Grant(
            category,
            granted,
            remaining,
            name=entry.get("name") if isinstance(entry.get("name"), str) else None,
            program_id=entry.get("program_id")
            if isinstance(entry.get("program_id"), str)
            else None,
            expires_at=expiry,
        )
        grants.append(grant)
        if expiry is None or expiry > now:
            total += remaining.minor
            if expiry is not None:
                expiries.append(expiry)
    details = []
    if uncertain:
        details.append("部分赠款到期时间未知，已计入。")
    if any(grant.program_id == "subscription_api_credit" for grant in grants):
        details.append("含订阅赠送的 API credits。")
    return (
        Money(total, currency, exponent),
        tuple(grants),
        min(expiries, default=None),
        " ".join(details) or None,
        uncertain,
    )


class ConsoleProvider:
    """Fetch selected-organization balances; discovery is a separate explicit action."""

    requires_credential = True
    metric_ids = REQUIRED_METRIC_IDS[_PROVIDER]

    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    async def discover_organizations(
        self, credential: ResolvedCredential
    ) -> tuple[OrganizationChoice, ...]:
        failure = _credential_error(credential)
        if failure is not None:
            raise TransportError(FetchState.AUTH_REQUIRED, failure)
        payload = await self._transport.get_json(
            _PROVIDER, "/api/organizations", credential=credential
        )
        if not isinstance(payload, list):
            raise TransportError(FetchState.SCHEMA_ERROR, "schema_error")
        choices = []
        seen = set()
        for entry in payload:
            if not isinstance(entry, dict) or not isinstance(entry.get("capabilities"), list):
                raise TransportError(FetchState.SCHEMA_ERROR, "schema_error")
            if "api" not in entry["capabilities"]:
                continue
            organization_id = entry.get("uuid")
            if (
                not isinstance(organization_id, str)
                or _ORGANIZATION.fullmatch(organization_id) is None
                or organization_id in seen
            ):
                raise TransportError(FetchState.SCHEMA_ERROR, "schema_error")
            seen.add(organization_id)
            label = entry.get("name")
            choices.append(
                OrganizationChoice(
                    organization_id, label if isinstance(label, str) else organization_id
                )
            )
        return tuple(choices)

    async def fetch(
        self, account: Account, credential: ResolvedCredential | None, now: datetime
    ) -> Snapshot:
        now = utc_datetime(now)
        failure = _credential_error(credential)
        if account.provider != _PROVIDER:
            failure = "credential_mismatch"
        if failure is None:
            if account.credential_kind != credential.credential_kind:
                failure = "credential_mismatch"
            elif credential.expires_at is not None and credential.expires_at <= now:
                failure = "credential_expired"
            elif (
                credential.organization_id is not None
                and credential.organization_id != account.organization_id
            ):
                failure = "credential_mismatch"
        if failure is not None:
            return self._failure(account, now, FetchState.AUTH_REQUIRED, failure)
        organization_id = account.organization_id
        if not isinstance(organization_id, str) or _ORGANIZATION.fullmatch(organization_id) is None:
            return self._failure(
                account, now, FetchState.UNCONFIGURED, "organization_selection_required"
            )
        try:
            payload = await self._transport.get_json(
                _PROVIDER,
                f"/api/organizations/{organization_id}/prepaid/credits",
                credential=credential,
            )
        except TransportError as error:
            if error.status == 404:
                return self._failure(
                    account, now, FetchState.PERMISSION_DENIED, "organization_selection_required"
                )
            return self._failure(
                account, now, error.fetch_state, error.code, retry_at=error.retry_at
            )
        if not isinstance(payload, dict):
            return self._failure(account, now, FetchState.SCHEMA_ERROR, "schema_error")
        try:
            currency, exponent = _units(payload)
        except DomainError:
            return self._failure(account, now, FetchState.SCHEMA_ERROR, "schema_error")
        categories = (
            _category(payload.get("tranches"), GrantCategory.PURCHASED, currency, exponent, now),
            _category(
                payload.get("promo_tranches"), GrantCategory.PROMOTIONAL, currency, exponent, now
            ),
        )
        try:
            total = Money(payload.get("amount"), currency, exponent)
        except DomainError:
            total = None
        total_detail = None
        difference = (
            total.minor - sum(category[0].minor for category in categories)
            if total is not None and all(category[0] is not None for category in categories)
            else None
        )
        if difference:
            difference_text = Money(difference, currency, exponent).format()
            total_detail = f"总额 − 明细合计 = {difference_text}"
        if total is None:
            total_detail = (
                "Authoritative total is missing or invalid; category values remain independent."
            )
        metrics = tuple(
            Metric(
                metric_id,
                label,
                MetricState.UNKNOWN if category[0] is None else MetricState.READY,
                _SOURCE,
                balance=category[0],
                expires_at=category[2],
                detail=category[3],
            )
            for metric_id, label, category in zip(
                self.metric_ids[:2], _LABELS[:2], categories, strict=True
            )
        ) + (
            Metric(
                self.metric_ids[2],
                _LABELS[2],
                MetricState.UNKNOWN if total is None else MetricState.READY,
                _SOURCE,
                balance=total,
                detail=total_detail,
            ),
        )
        usable = any(row.balance is not None for row in metrics)
        partial = total is None or any(category[4] for category in categories)
        state = (
            FetchState.SCHEMA_ERROR
            if not usable
            else FetchState.PARTIAL
            if partial
            else FetchState.OK
        )
        return Snapshot(
            account.id,
            metrics,
            tuple(grant for category in categories for grant in category[1]),
            state,
            now,
            fetched_at=now if usable else None,
            diagnostic=Diagnostic("schema_error" if not usable else "partial_data")
            if partial
            else Diagnostic("balance_mismatch")
            if difference
            else None,
            organization_id=organization_id,
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
            tuple(
                Metric(
                    metric_id,
                    label,
                    MetricState.UNKNOWN,
                    _SOURCE,
                    detail="Balance unavailable; reconnect or inspect the safe diagnostic.",
                )
                for metric_id, label in zip(self.metric_ids, _LABELS, strict=True)
            ),
            (),
            state,
            now,
            retry_at=retry_at,
            diagnostic=Diagnostic(code),
            organization_id=account.organization_id if account.provider == _PROVIDER else None,
        )
