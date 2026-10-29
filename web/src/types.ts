// Wire types for the usage API. Dashboard types mirror the Python dataclasses in
// src/cli_usage_api/domain.py exactly (Snapshot.to_dict()). Decimals arrive as
// strings and must stay strings: never parse them into a float for display.
// Account-management types mirror the API v1 amendment (PLAN.md §18).

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

/** What this token may do on this server, evaluated per request. */
export interface Capabilities {
  writable: boolean;
  /** Backend type only: a persist=true write can still fail with 503. */
  secure_store_available: boolean;
}

export interface SessionInfo {
  mode: ApiMode;
  version: string;
  server_time: Timestamp;
  auth: "token" | "none";
  /** Absent on older servers; normalized to read-only by the client. */
  capabilities?: Capabilities;
}

export interface Dashboard {
  mode: ApiMode;
  server_time: Timestamp;
  accounts: AccountView[];
}

export type StorageClass = "external_file" | "session" | "keyring" | "none";

/**
 * Redacted account configuration. Paths, Grok selectors, organization ids and
 * credential refs are never sent; a custom path arrives only as "custom".
 */
export interface AccountConfig {
  id: string;
  provider: ProviderId;
  label: string;
  enabled: boolean;
  poll_interval_seconds: number;
  effective_poll_interval_seconds: number;
  credential_kind: CredentialKind | null;
  storage: StorageClass;
  /** File kinds only. */
  reference: "default" | "custom" | null;
  /** Session storage on a writable server only; false means the server restarted. */
  session_available: boolean | null;
  scope_selected: boolean;
  organization_selected: boolean;
  /** Opaque optimistic-concurrency token; null when the server is not writable. */
  revision: string | null;
}

export interface AccountList {
  accounts: AccountConfig[];
  capabilities: Capabilities;
}

export type MutationWarning = "committed_uncertain" | "cleanup_failed" | "host_refresh_failed" | "credential_expired";

export interface MutationResult {
  account: AccountConfig | null;
  accounts: AccountConfig[];
  capabilities: Capabilities;
  warning: MutationWarning | null;
}

export interface PrepareChoice {
  /** Opaque per-record id such as "c1"; never a selector or organization id. */
  id: string;
  label: string | null;
  legacy: boolean;
  /** Display hint only: never preselected. */
  current: boolean;
}

export interface PrepareResult {
  prepare_id: string;
  expires_in: number;
  kind: "grok_scope" | "console_organization";
  choices: PrepareChoice[];
}

export interface SourceBody {
  credential_kind: CredentialKind;
  reference?: string;
  secret?: string;
  persist?: boolean;
  prepare_id?: string;
  choice_id?: string;
}

export interface CreateAccountBody {
  provider: ProviderId;
  label: string;
  poll_interval_seconds?: number;
  enabled?: boolean;
  source: SourceBody | null;
}

export interface UpdateAccountBody {
  label?: string;
  poll_interval_seconds?: number;
  enabled?: boolean;
  source?: SourceBody | null;
}

export interface PrepareBody {
  account_id: string | null;
  revision: string | null;
  provider?: ProviderId;
  credential_kind: "grok_auth_file" | "console_session";
  reference?: string;
  secret?: string;
}
