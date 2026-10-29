// Wire types for the read-only usage API. They mirror the Python dataclasses in
// src/cli_usage_api/domain.py exactly (Snapshot.to_dict()). Decimals arrive as
// strings and must stay strings: never parse them into a float for display.

export type ProviderId =
  | "claude_subscription"
  | "claude_platform"
  | "codex_subscription"
  | "grok_subscription";

export type CredentialKind =
  | "claude_code_file"
  | "grok_auth_file"
  | "codex_auth_file"
  | "console_session"
  | "manual_bearer"
  | "api_key";

export type MetricState = "ready" | "unknown" | "not_applicable" | "blocked";

export type FetchState =
  | "ok"
  | "partial"
  | "unconfigured"
  | "auth_required"
  | "permission_denied"
  | "rate_limited"
  | "network_error"
  | "provider_error"
  | "schema_error"
  | "upstream_contract_missing";

export type SourceKind = "private_http" | "offline_demo" | "unresolved";

export type GrantCategory = "purchased" | "promotional";

/** Exact decimal as emitted by Python's str(Decimal). */
export type DecimalString = string;
/** RFC3339 UTC timestamp, e.g. 2026-10-28T12:00:00Z. */
export type Timestamp = string;

export interface Money {
  /** Integer minor units; may be zero or negative. */
  minor: number;
  currency: string;
  /** 0..4 digits after the decimal point. */
  exponent: number;
}

export interface QuotaValue {
  used_percent: DecimalString | null;
  remaining_percent: DecimalString | null;
  used_count: number | null;
  limit_count: number | null;
  remaining_count: number | null;
}

export interface SourceRef {
  kind: SourceKind;
  contract: string;
  version_sensitive: boolean;
}

export interface Grant {
  category: GrantCategory;
  granted: Money;
  remaining: Money;
  id: string | null;
  program_id: string | null;
  name: string | null;
  expires_at: Timestamp | null;
}

export interface Metric {
  id: string;
  label: string;
  state: MetricState;
  source: SourceRef;
  quota: QuotaValue | null;
  balance: Money | null;
  reset_at: Timestamp | null;
  expires_at: Timestamp | null;
  shared_pool_id: string | null;
  detail: string | null;
  /** Reported consumption share; never an allowance and never a source of "remaining". */
  share_percent: DecimalString | null;
}

export interface Diagnostic {
  code: string;
  message: string;
}

export interface Snapshot {
  account_id: string;
  metrics: Metric[];
  grants: Grant[];
  fetch_state: FetchState;
  attempted_at: Timestamp;
  fetched_at: Timestamp | null;
  retry_at: Timestamp | null;
  diagnostic: Diagnostic | null;
  /** Always null over the API. */
  organization_id: string | null;
}

export interface Freshness {
  age_seconds: number | null;
  attempted_age_seconds: number;
  stale: boolean;
  reset_passed: boolean;
  last_known: boolean;
}

export interface AccountInfo {
  id: string;
  provider: ProviderId;
  label: string;
  enabled: boolean;
  credential_kind: CredentialKind | null;
  /** Effective runtime cadence in seconds. */
  poll_interval_seconds: number;
}

export interface AccountView {
  account: AccountInfo;
  snapshot: Snapshot | null;
  freshness: Freshness | null;
}

export type ApiMode = "live" | "demo";

export interface SessionInfo {
  mode: ApiMode;
  version: string;
  server_time: Timestamp;
  auth: "token" | "none";
}

export interface Dashboard {
  mode: ApiMode;
  server_time: Timestamp;
  accounts: AccountView[];
}
