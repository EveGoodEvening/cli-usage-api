"""Immutable, secret-safe values shared by storage, providers and presentation.

JSON codecs are explicit: secrets are never serializable, Decimal percentages are
strings, money remains integer minor units, and timestamps are UTC RFC3339.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field, fields
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation, localcontext
from enum import StrEnum
from types import MappingProxyType
from typing import Any
from uuid import UUID, uuid4


class DomainError(ValueError):
    """Invalid local value, with no offending input in its message."""


class ProviderId(StrEnum):
    CLAUDE_SUBSCRIPTION = "claude_subscription"
    CLAUDE_PLATFORM = "claude_platform"
    CODEX_SUBSCRIPTION = "codex_subscription"
    GROK_SUBSCRIPTION = "grok_subscription"
    OPENAI_PLATFORM = "openai_platform"


class CredentialKind(StrEnum):
    CLAUDE_CODE_FILE = "claude_code_file"
    GROK_AUTH_FILE = "grok_auth_file"
    CODEX_AUTH_FILE = "codex_auth_file"
    CONSOLE_SESSION = "console_session"
    # platform.openai.com dashboard session key (``session.sensitive_id``).
    OPENAI_PLATFORM_SESSION = "openai_platform_session"
    MANUAL_BEARER = "manual_bearer"
    API_KEY = "api_key"


class MetricId(StrEnum):
    CLAUDE_FIVE_HOUR = "claude.subscription.five_hour"
    CLAUDE_WEEKLY = "claude.subscription.weekly"
    CLAUDE_FABLE_WEEKLY = "claude.subscription.fable_weekly"
    CLAUDE_PURCHASED_BALANCE = "claude.platform.purchased_balance"
    CLAUDE_PROMOTIONAL_BALANCE = "claude.platform.promotional_balance"
    CLAUDE_TOTAL_BALANCE = "claude.platform.total_balance"
    CODEX_WEEKLY = "codex.subscription.weekly"
    CODEX_FIVE_HOUR = "codex.subscription.five_hour"
    OPENAI_AVAILABLE_BALANCE = "openai.platform.available_balance"
    # Optional extras, never required rows.
    CLAUDE_EXTRA_USAGE = "claude.subscription.extra_usage"
    # Emitted only when the subscription account has an explicitly selected org.
    CLAUDE_CREDIT_BALANCE = "claude.subscription.credit_balance"
    OPENAI_PAID_AVAILABLE_BALANCE = "openai.platform.paid_available_balance"
    CODEX_CREDITS = "codex.subscription.credits"
    GROK_SHARED_POOL = "grok.subscription.shared_pool"
    GROK_BUILD = "grok.product.build"
    GROK_CHAT = "grok.product.chat"


REQUIRED_METRIC_IDS = MappingProxyType(
    {
        ProviderId.CLAUDE_SUBSCRIPTION: (
            MetricId.CLAUDE_FIVE_HOUR,
            MetricId.CLAUDE_WEEKLY,
            MetricId.CLAUDE_FABLE_WEEKLY,
        ),
        ProviderId.CLAUDE_PLATFORM: (
            MetricId.CLAUDE_PURCHASED_BALANCE,
            MetricId.CLAUDE_PROMOTIONAL_BALANCE,
            MetricId.CLAUDE_TOTAL_BALANCE,
        ),
        ProviderId.CODEX_SUBSCRIPTION: (MetricId.CODEX_WEEKLY,),
        ProviderId.GROK_SUBSCRIPTION: (
            MetricId.GROK_SHARED_POOL,
            MetricId.GROK_BUILD,
            MetricId.GROK_CHAT,
        ),
        ProviderId.OPENAI_PLATFORM: (MetricId.OPENAI_AVAILABLE_BALANCE,),
    }
)

READ_CREDENTIAL_KINDS = MappingProxyType(
    {
        ProviderId.CLAUDE_SUBSCRIPTION: frozenset(
            {
                CredentialKind.CLAUDE_CODE_FILE,
                CredentialKind.MANUAL_BEARER,
            }
        ),
        ProviderId.CLAUDE_PLATFORM: frozenset({CredentialKind.CONSOLE_SESSION}),
        ProviderId.CODEX_SUBSCRIPTION: frozenset({CredentialKind.CODEX_AUTH_FILE}),
        ProviderId.GROK_SUBSCRIPTION: frozenset(
            {
                CredentialKind.GROK_AUTH_FILE,
                CredentialKind.MANUAL_BEARER,
            }
        ),
        ProviderId.OPENAI_PLATFORM: frozenset({CredentialKind.OPENAI_PLATFORM_SESSION}),
    }
)

# Providers whose only management kinds are their read kinds (no API-key records).
_NO_API_KEY_PROVIDERS = frozenset({ProviderId.CODEX_SUBSCRIPTION, ProviderId.OPENAI_PLATFORM})

# Provider polling floors apply to saved accounts at runtime; the default is the
# initial interval for a newly added account.
POLL_FLOOR_SECONDS = MappingProxyType(
    {ProviderId.CLAUDE_SUBSCRIPTION: 180, ProviderId.OPENAI_PLATFORM: 300}
)
DEFAULT_POLL_INTERVAL_SECONDS = 60


def default_poll_interval_seconds(provider: ProviderId) -> int:
    """The initial interval for a new account: the provider floor, else 60 seconds."""
    return max(DEFAULT_POLL_INTERVAL_SECONDS, POLL_FLOOR_SECONDS.get(provider, 0))


class MetricState(StrEnum):
    READY = "ready"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"
    BLOCKED = "blocked"


class FetchState(StrEnum):
    OK = "ok"
    PARTIAL = "partial"
    UNCONFIGURED = "unconfigured"
    AUTH_REQUIRED = "auth_required"
    PERMISSION_DENIED = "permission_denied"
    RATE_LIMITED = "rate_limited"
    NETWORK_ERROR = "network_error"
    PROVIDER_ERROR = "provider_error"
    SCHEMA_ERROR = "schema_error"
    UPSTREAM_CONTRACT_MISSING = "upstream_contract_missing"


class SourceKind(StrEnum):
    PRIVATE_HTTP = "private_http"
    OFFLINE_DEMO = "offline_demo"
    UNRESOLVED = "unresolved"


class GrantCategory(StrEnum):
    PURCHASED = "purchased"
    PROMOTIONAL = "promotional"


# Only these curated strings cross the diagnostic/exception boundary. Extend the
# catalog with reviewed messages, never with upstream text or exception reprs.
DIAGNOSTIC_MESSAGES = MappingProxyType(
    {
        "invalid_config": "配置无效：请修正后再保存。",
        "credential_unavailable": "凭据不可用：请重新连接账号。",
        "credential_expired": "凭据已过期：请在官方应用中重新登录。",
        "credential_mismatch": "凭据类型不匹配：请选择此服务支持的凭据。",
        "unsafe_credential_file": "凭据文件不安全：需为本人所有的私有普通文件。",
        "credential_selection_required": "需要选择凭据：请选择要使用的登录配置。",
        "secure_store_unavailable": "安全存储不可用：请解锁，或改用仅本次会话保存。",
        "organization_selection_required": "需要选择组织：请选择可访问的计费组织。",
        "forbidden_request": "请求不在允许范围。",
        "auth_required": "需要重新连接：请用支持的凭据重新连接。",
        "permission_denied": "权限不足：请检查所选组织和账号权限。",
        "rate_limited": "限流：到重试时间后再刷新。",
        "network_error": "网络错误：请检查网络后重试。",
        "provider_error": "服务错误：请稍后重试。",
        "schema_error": "数据格式错误：响应不符合支持的格式。",
        "response_too_large": "响应过大。",
        "partial_data": "部分数据缺失。",
        "balance_mismatch": "余额明细与总额不一致；差额见总余额详情。",
        "unconfigured": "未配置：连接账号后开始读取。",
        "upstream_contract_missing": "上游契约缺失：暂无可用的读取接口。",
    }
)


def _fail() -> None:
    raise DomainError("Invalid domain value.")


def _integer(value: Any, *, minimum: int | None = None, maximum: int | None = None) -> int:
    if type(value) is not int:
        _fail()
    if minimum is not None and value < minimum:
        _fail()
    if maximum is not None and value > maximum:
        _fail()
    return value


def _enum(cls: type[StrEnum], value: Any) -> StrEnum:
    try:
        return cls(value)
    except (ValueError, TypeError):
        raise DomainError("Invalid domain value.") from None


def _text(value: Any, *, maximum: int = 256, empty: bool = False) -> str:
    if not isinstance(value, str) or len(value) > maximum or (not empty and not value):
        _fail()
    return value


def sanitize_text(value: str, *, max_length: int = 256) -> str:
    """Remove terminal escapes, controls and Rich markup delimiters for display."""
    _text(value, maximum=1_048_576, empty=True)
    _integer(max_length, minimum=1, maximum=4096)
    value = re.sub(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)", "", value)
    value = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", value)
    return "".join(
        char
        for char in value
        if not unicodedata.category(char).startswith("C") and char not in "[]"
    ).strip()[:max_length]


def _display(value: str | None, maximum: int = 256) -> str | None:
    return None if value is None else sanitize_text(value, max_length=maximum)


def _identifier(value: Any) -> str:
    _text(value, maximum=128)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*", value):
        _fail()
    return value


def _account_id(value: Any) -> str:
    _text(value, maximum=36)
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError):
        raise DomainError("Invalid account ID.") from None
    if str(parsed) != value:
        _fail()
    return value


def new_account_id() -> str:
    return str(uuid4())


_CANONICAL_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
# Local format assumption (no sourced regex): ``org-`` plus an alphanumeric ID.
_OPENAI_ORGANIZATION = re.compile(r"org-[A-Za-z0-9]{8,64}")


def _organization(value: str | None) -> str | None:
    if value is not None and (
        not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,68}", value)
    ):
        _fail()
    return value


def _provider_organization(provider: ProviderId, value: str | None) -> None:
    """Organization rules per provider: optional, required or forbidden."""
    if provider == ProviderId.OPENAI_PLATFORM:
        if not isinstance(value, str) or not _OPENAI_ORGANIZATION.fullmatch(value):
            _fail()
    elif value is None:
        return
    elif provider == ProviderId.CLAUDE_PLATFORM:
        if not re.fullmatch(r"[A-Za-z0-9-]{1,64}", value):
            _fail()
    elif provider == ProviderId.CLAUDE_SUBSCRIPTION:
        if not _CANONICAL_UUID.fullmatch(value):
            _fail()
    else:
        _fail()


def claude_organization_id(value: object) -> str:
    """A Claude subscription organization: a lowercase canonical UUID."""
    if not isinstance(value, str) or not _CANONICAL_UUID.fullmatch(value):
        raise DomainError("Invalid organization ID.")
    return value


def openai_organization_id(value: object) -> str:
    """An OpenAI Platform organization ID, ``org-`` plus 8..64 ASCII letters/digits.

    Surrounding whitespace is removed; nothing else is altered.
    """
    if isinstance(value, str):
        value = value.strip()
    if not isinstance(value, str) or not _OPENAI_ORGANIZATION.fullmatch(value):
        raise DomainError("Invalid organization ID.")
    return value


OPENAI_SESSION_MIN_LENGTH = 20
OPENAI_SESSION_MAX_LENGTH = 4096


def openai_session_key(value: object) -> str:
    """Accept only a bare dashboard session token value.

    Surrounding whitespace is removed; internal whitespace/controls, a ``Bearer``
    prefix, header text (``Cookie:``/``Authorization:``), a cookie ``name=value``
    pair, JSON/HAR-looking input and out-of-range lengths are rejected. No ``sess-`` prefix is required.
    """
    if not isinstance(value, str) or len(value) > 2 * OPENAI_SESSION_MAX_LENGTH:
        raise DomainError("Invalid session key.")
    value = value.strip()
    lowered = value.lower()
    if (
        not OPENAI_SESSION_MIN_LENGTH <= len(value) <= OPENAI_SESSION_MAX_LENGTH
        or any(not 0x21 <= ord(char) <= 0x7E for char in value)
        or lowered.startswith(("bearer", "cookie:", "authorization:"))
        or any(char in '{}[]"\\,;:<>=' for char in value)
    ):
        raise DomainError("Invalid session key.")
    return value


def utc_datetime(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        _fail()
    try:
        return value.astimezone(UTC)
    except (ValueError, OverflowError):
        raise DomainError("Invalid timestamp.") from None


def parse_timestamp(value: str) -> datetime:
    """Parse timezone-required RFC3339, never guess a numeric epoch unit."""
    if not isinstance(value, str) or not re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt][0-9]{2}:[0-9]{2}:[0-9]{2}"
        r"(?:\.[0-9]{1,6})?(?:[Zz]|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])",
        value,
    ):
        _fail()
    try:
        parsed = datetime.fromisoformat(value.upper())
    except ValueError:
        raise DomainError("Invalid timestamp.") from None
    return utc_datetime(parsed)


def format_timestamp(value: datetime) -> str:
    return utc_datetime(value).isoformat().replace("+00:00", "Z")


def _optional_time(value: datetime | None) -> datetime | None:
    return None if value is None else utc_datetime(value)


# Bound coefficient precision and stored scale before any exact arithmetic.
# These generous limits preserve provider decimals without letting a compact
# exponent force gigabytes of zero padding during subtraction or presentation.
_MAX_PERCENT_DIGITS = 1024
_MAX_PERCENT_EXPONENT = 1000
_MAX_PERCENT_TEXT_LENGTH = 4096


def percent(value: Decimal | int | str) -> Decimal:
    """Read exact nonnegative percentages within bounded precision and scale."""
    if type(value) not in (Decimal, int, str):
        _fail()
    if type(value) is str and len(value) > _MAX_PERCENT_TEXT_LENGTH:
        _fail()
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError):
        raise DomainError("Invalid percentage.") from None
    if not result.is_finite() or result < 0:
        _fail()
    parts = result.as_tuple()
    if len(parts.digits) > _MAX_PERCENT_DIGITS or abs(parts.exponent) > _MAX_PERCENT_EXPONENT:
        _fail()
    return result


# Credit balances are non-currency counts; bound them tightly before any use.
_MAX_CREDIT_DIGITS = 40
_MAX_CREDIT_EXPONENT = 40
_MAX_CREDIT_TEXT_LENGTH = 64


def credit_amount(value: Decimal | int | str) -> Decimal:
    """Read an exact credit balance (zero/negative allowed) within bounded representation."""
    if type(value) not in (Decimal, int, str):
        _fail()
    if type(value) is str and len(value) > _MAX_CREDIT_TEXT_LENGTH:
        _fail()
    if type(value) is int and abs(value) >= 10**_MAX_CREDIT_DIGITS:
        _fail()
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError):
        raise DomainError("Invalid credit amount.") from None
    if not result.is_finite():
        _fail()
    parts = result.as_tuple()
    if len(parts.digits) > _MAX_CREDIT_DIGITS or abs(parts.exponent) > _MAX_CREDIT_EXPONENT:
        _fail()
    return result


def remaining_percent(used: Decimal | int | str) -> Decimal:
    used = percent(used)
    if used >= 100:
        return Decimal(0)
    with localcontext() as context:
        context.prec = max(28, len(used.as_tuple().digits) + abs(used.as_tuple().exponent) + 3)
        return Decimal(100) - used


def validate_credential_kind(
    provider: ProviderId, kind: CredentialKind, *, for_read: bool = False
) -> None:
    provider = _enum(ProviderId, provider)
    kind = _enum(CredentialKind, kind)
    allowed = READ_CREDENTIAL_KINDS[provider]
    if not for_read and provider not in _NO_API_KEY_PROVIDERS:
        allowed = allowed | {CredentialKind.API_KEY}
    if kind not in allowed:
        raise DomainError("Credential kind is not supported by this provider.")


@dataclass(frozen=True, slots=True)
class Account:
    id: str
    provider: ProviderId
    label: str
    credential_ref: str | None = None
    credential_kind: CredentialKind | None = None
    credential_selector: str | None = None
    organization_id: str | None = None
    poll_interval_seconds: int = 60
    enabled: bool = True

    def __post_init__(self) -> None:
        _account_id(self.id)
        object.__setattr__(self, "provider", _enum(ProviderId, self.provider))
        object.__setattr__(self, "label", sanitize_text(self.label, max_length=80))
        if not self.label:
            _fail()
        _integer(self.poll_interval_seconds, minimum=30, maximum=3600)
        if type(self.enabled) is not bool:
            _fail()
        if (self.credential_ref is None) != (self.credential_kind is None):
            _fail()
        if self.credential_kind is not None:
            object.__setattr__(self, "credential_kind", _enum(CredentialKind, self.credential_kind))
            validate_credential_kind(self.provider, self.credential_kind)
            _text(self.credential_ref, maximum=4096)
        if self.credential_selector is not None:
            _text(self.credential_selector, maximum=1024)
            if self.provider != ProviderId.GROK_SUBSCRIPTION:
                _fail()
        _provider_organization(self.provider, self.organization_id)

    @property
    def effective_poll_interval_seconds(self) -> int:
        """Runtime cadence; preserve saved preferences without rewriting config."""
        return max(POLL_FLOOR_SECONDS.get(self.provider, 0), self.poll_interval_seconds)

    def to_dict(self) -> dict[str, Any]:
        return _encode(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Account:
        return _construct(cls, value)


@dataclass(frozen=True, slots=True)
class Money:
    minor: int
    currency: str
    exponent: int

    def __post_init__(self) -> None:
        _integer(self.minor)
        _integer(self.exponent, minimum=0, maximum=4)
        if not isinstance(self.currency, str) or not re.fullmatch(r"[A-Z]{3}", self.currency):
            _fail()

    def __add__(self, other: Money) -> Money:
        if not isinstance(other, Money):
            return NotImplemented
        if (self.currency, self.exponent) != (other.currency, other.exponent):
            raise DomainError("Money units must match.")
        return Money(self.minor + other.minor, self.currency, self.exponent)

    def format(self) -> str:
        digits = str(abs(self.minor)).zfill(self.exponent + 1)
        if self.exponent:
            digits = digits[: -self.exponent] + "." + digits[-self.exponent :]
        return f"{'-' if self.minor < 0 else ''}{digits} {self.currency}"


_CENT = Decimal("0.01")


def round_to_cents(value: Decimal) -> Decimal:
    """Round an exact bounded amount half-even to two decimal places (display only)."""
    value = credit_amount(value)
    with localcontext() as context:
        # credit_amount bounds digits and exponent, so this precision is exact.
        context.prec = 2 * (_MAX_CREDIT_DIGITS + _MAX_CREDIT_EXPONENT) + 4
        return value.quantize(_CENT, rounding=ROUND_HALF_EVEN)


def format_two_decimals(value: Decimal) -> str:
    """Half-even rounded, always two decimals, plain notation (e.g. ``137.50``)."""
    return f"{round_to_cents(value):f}"


@dataclass(frozen=True, slots=True)
class ExactMoney:
    """An exact provider money amount whose minor-unit scale is not reported.

    ``amount`` keeps the wire value (bounded like ``credit_amount``; zero and
    negative allowed). Presentation rounds to cents; data never does.
    """

    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        if type(self.amount) not in (Decimal, int, str):
            _fail()
        object.__setattr__(self, "amount", credit_amount(self.amount))
        if not isinstance(self.currency, str) or not re.fullmatch(r"[A-Z]{3}", self.currency):
            _fail()

    def rounded_to_cents(self) -> tuple[Decimal, bool]:
        """The half-even cents value and whether rounding changed the amount."""
        rounded = round_to_cents(self.amount)
        return rounded, rounded != self.amount

    def format_cents(self) -> str:
        return f"{format_two_decimals(self.amount)} {self.currency}"


@dataclass(frozen=True, slots=True)
class QuotaValue:
    used_percent: Decimal | None = None
    remaining_percent: Decimal | None = None
    used_count: int | None = None
    limit_count: int | None = None
    remaining_count: int | None = None

    def __post_init__(self) -> None:
        for name in ("used_percent", "remaining_percent"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, percent(value))
        if self.used_percent is not None:
            expected = remaining_percent(self.used_percent)
            if self.remaining_percent is not None and self.remaining_percent != expected:
                _fail()
            object.__setattr__(self, "remaining_percent", expected)
        if self.remaining_percent is not None and self.remaining_percent > 100:
            _fail()
        for name in ("used_count", "limit_count", "remaining_count"):
            value = getattr(self, name)
            if value is not None:
                _integer(value, minimum=0)


@dataclass(frozen=True, slots=True)
class SourceRef:
    kind: SourceKind
    contract: str
    version_sensitive: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _enum(SourceKind, self.kind))
        _identifier(self.contract)
        if type(self.version_sensitive) is not bool:
            _fail()


@dataclass(frozen=True, slots=True)
class Grant:
    category: GrantCategory
    granted: Money
    remaining: Money
    id: str | None = None
    program_id: str | None = None
    name: str | None = None
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "category", _enum(GrantCategory, self.category))
        if not isinstance(self.granted, Money) or not isinstance(self.remaining, Money):
            _fail()
        if (self.granted.currency, self.granted.exponent) != (
            self.remaining.currency,
            self.remaining.exponent,
        ):
            _fail()
        for name in ("id", "program_id", "name"):
            object.__setattr__(self, name, _display(getattr(self, name)))
        object.__setattr__(self, "expires_at", _optional_time(self.expires_at))


@dataclass(frozen=True, slots=True)
class Metric:
    id: str
    label: str
    state: MetricState
    source: SourceRef
    quota: QuotaValue | None = None
    balance: Money | None = None
    reset_at: datetime | None = None
    expires_at: datetime | None = None
    shared_pool_id: str | None = None
    detail: str | None = None
    # Reported consumption (a product's pool share, or an aggregate without proven
    # pool semantics); never an allowance or a source for a derived remaining.
    share_percent: Decimal | None = None
    # Reported consumption against a spending cap; never a balance or allowance.
    spent: Money | None = None
    # The spending cap; same currency/exponent as ``spent`` when both are present.
    spend_limit: Money | None = None
    # Non-currency credit balance (unit "credits"); never converted to money.
    credits: Decimal | None = None
    # The source positively reported "no cap / unlimited".
    unlimited: bool = False
    # Exact money without a reported minor-unit scale; exclusive with every other value.
    exact_balance: ExactMoney | None = None

    def __post_init__(self) -> None:
        _identifier(self.id)
        object.__setattr__(self, "label", sanitize_text(self.label, max_length=120))
        object.__setattr__(self, "state", _enum(MetricState, self.state))
        if not isinstance(self.source, SourceRef):
            _fail()
        if self.quota is not None and not isinstance(self.quota, QuotaValue):
            _fail()
        if self.balance is not None and not isinstance(self.balance, Money):
            _fail()
        if self.balance is not None and self.quota is not None:
            _fail()
        if self.share_percent is not None:
            if self.quota is not None or self.balance is not None:
                _fail()
            object.__setattr__(self, "share_percent", percent(self.share_percent))
        for name in ("spent", "spend_limit"):
            value = getattr(self, name)
            if value is None:
                continue
            if not isinstance(value, Money):
                _fail()
            if (
                self.balance is not None
                or self.share_percent is not None
                or self.credits is not None
            ):
                _fail()
        if (
            self.spent is not None
            and self.spend_limit is not None
            and (self.spent.currency, self.spent.exponent)
            != (self.spend_limit.currency, self.spend_limit.exponent)
        ):
            _fail()
        if self.credits is not None:
            if any(
                item is not None
                for item in (
                    self.quota,
                    self.balance,
                    self.share_percent,
                    self.spent,
                    self.spend_limit,
                )
            ):
                _fail()
            object.__setattr__(self, "credits", credit_amount(self.credits))
        if type(self.unlimited) is not bool:
            _fail()
        if self.unlimited and (self.spend_limit is not None or self.credits is not None):
            _fail()
        if self.exact_balance is not None and (
            not isinstance(self.exact_balance, ExactMoney)
            or self.unlimited
            or any(
                item is not None
                for item in (
                    self.quota,
                    self.balance,
                    self.share_percent,
                    self.spent,
                    self.spend_limit,
                    self.credits,
                )
            )
        ):
            _fail()
        object.__setattr__(self, "reset_at", _optional_time(self.reset_at))
        object.__setattr__(self, "expires_at", _optional_time(self.expires_at))
        if self.shared_pool_id is not None:
            _identifier(self.shared_pool_id)
        object.__setattr__(self, "detail", _display(self.detail, 1024))


@dataclass(frozen=True, slots=True)
class Diagnostic:
    code: str
    message: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or self.code not in DIAGNOSTIC_MESSAGES:
            raise DomainError("Unknown safe diagnostic code.")
        object.__setattr__(self, "message", DIAGNOSTIC_MESSAGES[self.code])


class TransportError(Exception):
    """Safe structured transport failure; no arbitrary message/body is accepted."""

    def __init__(
        self,
        fetch_state: FetchState,
        code: str,
        *,
        status: int | None = None,
        retry_at: datetime | None = None,
    ) -> None:
        self.fetch_state = _enum(FetchState, fetch_state)
        self.code = Diagnostic(code).code
        if self.fetch_state in (FetchState.OK, FetchState.PARTIAL):
            _fail()
        self.status = None if status is None else _integer(status, minimum=100, maximum=599)
        self.retry_at = _optional_time(retry_at)
        super().__init__(DIAGNOSTIC_MESSAGES[self.code])


@dataclass(frozen=True, slots=True)
class ResolvedCredential:
    provider: ProviderId
    credential_kind: CredentialKind
    secret: str = field(repr=False)
    generation_fingerprint: str = field(repr=False)
    user_id: str | None = field(default=None, repr=False)
    expires_at: datetime | None = None
    organization_id: str | None = None
    codex_account_id: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", _enum(ProviderId, self.provider))
        object.__setattr__(self, "credential_kind", _enum(CredentialKind, self.credential_kind))
        validate_credential_kind(self.provider, self.credential_kind)
        _text(self.secret, maximum=1_048_576)
        _identifier(self.generation_fingerprint)
        if self.user_id is not None:
            if self.provider != ProviderId.GROK_SUBSCRIPTION:
                _fail()
            _text(self.user_id)
        if self.provider == ProviderId.CODEX_SUBSCRIPTION:
            _text(self.codex_account_id)
            if any(not 33 <= ord(char) <= 126 for char in self.codex_account_id):
                _fail()
        elif self.codex_account_id is not None:
            _fail()
        object.__setattr__(self, "expires_at", _optional_time(self.expires_at))
        _provider_organization(self.provider, self.organization_id)


def validate_credential_binding(provider: ProviderId, credential: ResolvedCredential) -> None:
    provider = _enum(ProviderId, provider)
    if not isinstance(credential, ResolvedCredential) or credential.provider != provider:
        raise DomainError("Credential provider does not match the account.")
    validate_credential_kind(provider, credential.credential_kind, for_read=True)


@dataclass(frozen=True, slots=True)
class Snapshot:
    account_id: str
    metrics: tuple[Metric, ...]
    grants: tuple[Grant, ...]
    fetch_state: FetchState
    attempted_at: datetime
    fetched_at: datetime | None = None
    retry_at: datetime | None = None
    diagnostic: Diagnostic | None = None
    organization_id: str | None = None

    def __post_init__(self) -> None:
        _account_id(self.account_id)
        if type(self.metrics) is not tuple or not all(isinstance(m, Metric) for m in self.metrics):
            _fail()
        if type(self.grants) is not tuple or not all(isinstance(g, Grant) for g in self.grants):
            _fail()
        if len({metric.id for metric in self.metrics}) != len(self.metrics):
            _fail()
        object.__setattr__(self, "fetch_state", _enum(FetchState, self.fetch_state))
        object.__setattr__(self, "attempted_at", utc_datetime(self.attempted_at))
        for name in ("fetched_at", "retry_at"):
            object.__setattr__(self, name, _optional_time(getattr(self, name)))
        if self.diagnostic is not None and not isinstance(self.diagnostic, Diagnostic):
            _fail()
        _organization(self.organization_id)

    def to_dict(self) -> dict[str, Any]:
        return _encode(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Snapshot:
        data = _mapping(value)
        _keys(cls, data)
        try:
            data["metrics"] = tuple(_metric_from_dict(item) for item in _array(data["metrics"]))
            data["grants"] = tuple(_grant_from_dict(item) for item in _array(data["grants"]))
            for name in ("attempted_at", "fetched_at", "retry_at"):
                if data.get(name) is not None:
                    data[name] = parse_timestamp(data[name])
            if data.get("diagnostic") is not None:
                diagnostic = _mapping(data["diagnostic"])
                if set(diagnostic) != {"code", "message"}:
                    _fail()
                data["diagnostic"] = Diagnostic(diagnostic["code"])
                if data["diagnostic"].message != diagnostic["message"]:
                    _fail()
            return cls(**data)
        except (KeyError, TypeError):
            raise DomainError("Invalid serialized snapshot.") from None


_SERIALIZABLE = (
    Account,
    Money,
    ExactMoney,
    QuotaValue,
    SourceRef,
    Grant,
    Metric,
    Diagnostic,
    Snapshot,
)


def _encode(value: Any) -> Any:
    if isinstance(value, _SERIALIZABLE):
        return {item.name: _encode(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return format_timestamp(value)
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, tuple):
        return [_encode(item) for item in value]
    if value is None or type(value) in (str, int, bool):
        return value
    raise DomainError("Value cannot be serialized.")


def _mapping(value: Any) -> dict[str, Any]:
    if type(value) is not dict or not all(isinstance(key, str) for key in value):
        _fail()
    return value.copy()


def _array(value: Any) -> list[Any]:
    if type(value) is not list:
        _fail()
    return value


def _keys(cls: type, data: dict[str, Any]) -> None:
    if set(data) - {item.name for item in fields(cls) if item.init}:
        _fail()


def _construct(cls: type, value: Any) -> Any:
    data = _mapping(value)
    _keys(cls, data)
    try:
        return cls(**data)
    except TypeError:
        raise DomainError("Invalid serialized value.") from None


def _grant_from_dict(value: Any) -> Grant:
    data = _mapping(value)
    try:
        data["granted"] = _construct(Money, data["granted"])
        data["remaining"] = _construct(Money, data["remaining"])
        if data.get("expires_at") is not None:
            data["expires_at"] = parse_timestamp(data["expires_at"])
    except KeyError:
        raise DomainError("Invalid serialized grant.") from None
    return _construct(Grant, data)


def _metric_from_dict(value: Any) -> Metric:
    data = _mapping(value)
    try:
        data["source"] = _construct(SourceRef, data["source"])
        for name, cls in (
            ("quota", QuotaValue),
            ("balance", Money),
            ("spent", Money),
            ("spend_limit", Money),
            ("exact_balance", ExactMoney),
        ):
            if data.get(name) is not None:
                data[name] = _construct(cls, data[name])
        for name in ("reset_at", "expires_at"):
            if data.get(name) is not None:
                data[name] = parse_timestamp(data[name])
    except KeyError:
        raise DomainError("Invalid serialized metric.") from None
    return _construct(Metric, data)


SCHEMA_VERSION = 1


def dumps(value: Account | Snapshot) -> str:
    if not isinstance(value, (Account, Snapshot)):
        raise DomainError("Only accounts and snapshots have a public JSON schema.")
    return json.dumps(
        {"schema_version": SCHEMA_VERSION, "type": type(value).__name__, "value": value.to_dict()},
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail()
        result[key] = value
    return result


def loads(value: str) -> Account | Snapshot:
    _text(value, maximum=1_048_576)
    try:
        data = json.loads(
            value,
            object_pairs_hook=_unique_object,
            parse_constant=lambda _: _fail(),
            parse_float=Decimal,
        )
    except (ValueError, RecursionError):
        raise DomainError("Invalid serialized JSON.") from None
    data = _mapping(data)
    if set(data) != {"schema_version", "type", "value"}:
        _fail()
    _integer(data["schema_version"], minimum=SCHEMA_VERSION, maximum=SCHEMA_VERSION)
    if data["type"] == "Account":
        return Account.from_dict(data["value"])
    if data["type"] == "Snapshot":
        return Snapshot.from_dict(data["value"])
    raise DomainError("Unknown serialized value type.")
