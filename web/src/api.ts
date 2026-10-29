// Typed client for the usage API: dashboard reads and, when the server allows
// it, account management. Bearer auth only; the token and any credential secret
// are never logged and never placed in a URL, and no cookies are sent. Secrets
// travel only in JSON request bodies.

import type {
  AccountConfig,
  AccountList,
  AccountView,
  Capabilities,
  CreateAccountBody,
  Dashboard,
  MutationResult,
  PrepareBody,
  PrepareResult,
  SessionInfo,
  UpdateAccountBody,
} from "./types";
import type { Credentials } from "./auth";

export type ApiErrorKind =
  | "unauthorized"
  | "rate_limited"
  | "forbidden"
  | "not_found"
  | "conflict"
  | "invalid"
  | "expired"
  | "unavailable"
  | "too_large"
  | "server"
  | "timeout"
  | "network"
  | "http"
  | "invalid_response";

/** Server error codes the page may name (API v1 §1.8, plus not_found). */
export const KNOWN_ERROR_CODES: ReadonlySet<string> = new Set([
  "invalid_request",
  "read_only",
  "forbidden_origin",
  "not_found",
  "method_not_allowed",
  "request_timeout",
  "conflict",
  "discovery_busy",
  "prepare_expired",
  "payload_too_large",
  "unsupported_media_type",
  "invalid_label",
  "invalid_poll_interval",
  "invalid_kind",
  "invalid_reference",
  "invalid_secret",
  "secret_required",
  "persist_required",
  "selection_required",
  "invalid_choice",
  "no_choices",
  "credential_unavailable",
  "too_many_accounts",
  "precondition_required",
  "discovery_failed",
  "secure_store_unavailable",
  "config_unavailable",
  "save_failed",
  "credential_cleanup_failed",
  "internal_error",
]);

/** Fixed display text per server code. Server-supplied text is never rendered. */
export const ERROR_CODE_MESSAGES: Readonly<Record<string, string>> = {
  read_only: "服务器为只读模式，不能修改账号。",
  not_found: "账号已不存在，已重新载入。",
  conflict: "账号列表已更新，已重新载入，请再试一次。",
  secure_store_unavailable: "服务器没有可用的加密密钥环，未保存任何更改。可改选“仅本次会话”。",
  config_unavailable: "服务器无法读写账号配置（权限或旧版配置需在终端迁移），未做任何更改。",
  prepare_expired: "读取结果已过期或登录已变化，请重新读取。",
  discovery_failed: "连接失败：检查 sessionKey 或登录状态后重试。",
  discovery_busy: "读取请求过于频繁，请稍后重试。",
  no_choices: "没有找到可选的组织。请重新登录后重试。",
  credential_unavailable:
    "服务器读不到这个凭据：确认文件存在、属于服务进程用户且权限为 0600，或重新登录对应 CLI。",
  invalid_secret: "凭据格式无效：只输入值本身，不要包含请求头或 HAR。",
  invalid_reference: "请填写“默认位置”，或服务器上 auth.json（Claude 为 .credentials.json）的绝对路径。",
  invalid_label: "名称不能为空。",
  invalid_poll_interval: "刷新间隔必须是 30 到 3600 之间的整数。",
  invalid_kind: "该服务不支持这种凭据。",
  selection_required: "请先读取并明确选择。",
  invalid_choice: "请先读取并明确选择。",
  persist_required: "请选择凭据保存方式。",
  secret_required: "请输入凭据。",
  too_many_accounts: "账号数量已达上限（100）。",
  payload_too_large: "内容过大。",
  request_timeout: "请求超时，未做任何更改。",
  save_failed: "保存失败，未做任何更改。",
  credential_cleanup_failed: "保存失败，未做任何更改。",
  internal_error: "保存失败，未做任何更改。",
};

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status: number | null;
  /** Seconds to wait: Retry-After on 429, or retry_after on 409 discovery_busy. */
  readonly retryAfter: number | null;
  /** A whitelisted server error code, or null. */
  readonly code: string | null;

  constructor(
    kind: ApiErrorKind,
    status: number | null = null,
    retryAfter: number | null = null,
    code: string | null = null,
  ) {
    super((code !== null ? ERROR_CODE_MESSAGES[code] : undefined) ?? API_ERROR_MESSAGES[kind]);
    this.name = "ApiError";
    this.kind = kind;
    this.status = status;
    this.retryAfter = retryAfter;
    this.code = code;
  }
}

export const API_ERROR_MESSAGES: Record<ApiErrorKind, string> = {
  unauthorized: "令牌无效或已撤销。请输入有效的 API 令牌。",
  rate_limited: "令牌未通过验证，且失败次数过多，服务器暂时拒绝请求。请在倒计时结束后重新输入有效令牌。",
  forbidden: "API 拒绝了这个请求。",
  not_found: "API 没有这个地址。检查 API 地址是否指向 usage api serve。",
  conflict: "账号列表已更新，请重新载入后再试。",
  invalid: "请求无效，未做任何更改。",
  expired: "读取结果已过期，请重新读取。",
  unavailable: "服务器暂时无法处理这个请求，未做任何更改。",
  too_large: "内容过大。",
  server: "服务器出错，请稍后重试。",
  timeout: "API 没有在时限内响应（读取 10 秒，发现组织 40 秒）。",
  network: "无法连接 API。检查地址、服务是否在运行，以及 --allow-origin 是否包含本页面的来源。",
  http: "API 返回了意外的状态码。",
  invalid_response: "API 返回的数据不符合预期格式。",
};

export interface UsageClient {
  readonly baseUrl: string;
  session(signal?: AbortSignal): Promise<SessionInfo>;
  dashboard(signal?: AbortSignal): Promise<Dashboard>;
  account(id: string, signal?: AbortSignal): Promise<AccountView>;
  accounts(signal?: AbortSignal): Promise<AccountList>;
  createAccount(body: CreateAccountBody, signal?: AbortSignal): Promise<MutationResult>;
  updateAccount(id: string, revision: string, body: UpdateAccountBody, signal?: AbortSignal): Promise<MutationResult>;
  removeAccount(id: string, revision: string, signal?: AbortSignal): Promise<MutationResult>;
  reorderAccounts(ids: readonly string[], signal?: AbortSignal): Promise<MutationResult>;
  reconnectAccount(id: string, signal?: AbortSignal): Promise<{ status: "queued" }>;
  prepare(body: PrepareBody, signal?: AbortSignal): Promise<PrepareResult>;
}

export const REQUEST_TIMEOUT_MS = 10_000;
/** Console organization discovery may take up to 30 s on the server. */
export const PREPARE_TIMEOUT_MS = 40_000;
/** Error bodies are read only this far, and only on account-management calls. */
export const MAX_ERROR_BODY_BYTES = 4096;
export const MIN_RETRY_AFTER = 1;
export const MAX_RETRY_AFTER = 3600;

function clampRetryAfter(seconds: number): number {
  return Math.max(MIN_RETRY_AFTER, Math.min(MAX_RETRY_AFTER, seconds));
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const MONTH = "(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)";
const TIME = "(\\d{2}):(\\d{2}):(\\d{2})";
// RFC 9110 §5.6.7: IMF-fixdate, plus the obsolete rfc850-date and asctime-date.
const IMF_FIXDATE = new RegExp(`^(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun), (\\d{2}) ${MONTH} (\\d{4}) ${TIME} GMT$`);
const RFC850_DATE = new RegExp(
  `^(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday), (\\d{2})-${MONTH}-(\\d{2}) ${TIME} GMT$`,
);
const ASCTIME_DATE = new RegExp(`^(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) ${MONTH} ( \\d|\\d{2}) ${TIME} (\\d{4})$`);

function utcMillis(year: number, month: string, day: number, h: number, m: number, s: number): number | null {
  const monthIndex = MONTHS.indexOf(month);
  if (monthIndex < 0 || h > 23 || m > 59 || s > 60) return null;
  const at = Date.UTC(year, monthIndex, day, h, m, Math.min(s, 59));
  const check = new Date(at);
  // Reject calendar overflow such as 31 Feb rather than letting it roll over.
  if (check.getUTCFullYear() !== year || check.getUTCMonth() !== monthIndex || check.getUTCDate() !== day) return null;
  return at;
}

/** An RFC 9110 HTTP-date as epoch milliseconds (always UTC), or null for any other shape. */
export function parseHttpDate(value: string, now: number = Date.now()): number | null {
  let match = IMF_FIXDATE.exec(value);
  if (match) {
    const [day, month, year, h, m, s] = groups(match);
    return utcMillis(Number(year), month, Number(day), Number(h), Number(m), Number(s));
  }
  match = RFC850_DATE.exec(value);
  if (match) {
    const [day, month, yy, h, m, s] = groups(match);
    // §5.6.7: a two-digit year more than 50 years ahead belongs to the previous century.
    const current = new Date(now).getUTCFullYear();
    let year = current - (current % 100) + Number(yy);
    if (year > current + 50) year -= 100;
    return utcMillis(year, month, Number(day), Number(h), Number(m), Number(s));
  }
  match = ASCTIME_DATE.exec(value);
  if (match) {
    const [month, day, h, m, s, year] = groups(match);
    return utcMillis(Number(year), month, Number(day.trim()), Number(h), Number(m), Number(s));
  }
  return null;
}

type Six = [string, string, string, string, string, string];

/** The six capture groups every HTTP-date pattern defines. */
function groups(match: RegExpExecArray): Six {
  return match.slice(1, 7).map((g) => g ?? "") as Six;
}

/**
 * Seconds to wait from a Retry-After header: either delta-seconds or an
 * HTTP-date (RFC 9110 §10.2.3) in one of the exact §5.6.7 shapes. The result
 * is clamped to 1 s .. 3600 s so a zero/past value cannot cause a hot retry
 * loop and a huge value cannot park the page indefinitely. Anything else,
 * including strings a lenient Date.parse would accept, is ignored (null).
 */
export function parseRetryAfter(value: string | null, now: number = Date.now()): number | null {
  if (value === null) return null;
  const trimmed = value.trim();
  if (trimmed === "") return null;
  if (/^\d+$/.test(trimmed)) return clampRetryAfter(Number(trimmed));
  const at = parseHttpDate(trimmed, now);
  if (at === null) return null;
  return clampRetryAfter(Math.ceil((at - now) / 1000));
}

/** Upper bound on a decoded JSON response body; larger bodies are refused. */
export const MAX_BODY_BYTES = 5 * 1024 * 1024;

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isAccountView(value: unknown): value is AccountView {
  if (!isObject(value) || !isObject(value.account)) return false;
  const account = value.account;
  if (typeof account.id !== "string" || typeof account.provider !== "string") return false;
  if (typeof account.label !== "string" || typeof account.enabled !== "boolean") return false;
  const snapshot = value.snapshot;
  if (snapshot !== null) {
    if (!isObject(snapshot)) return false;
    if (!Array.isArray(snapshot.metrics) || !Array.isArray(snapshot.grants)) return false;
    if (typeof snapshot.fetch_state !== "string" || typeof snapshot.attempted_at !== "string") return false;
    if (!snapshot.metrics.every((m) => isObject(m) && typeof m.id === "string" && typeof m.state === "string")) {
      return false;
    }
  }
  return value.freshness === null || isObject(value.freshness);
}

export function isDashboard(value: unknown): value is Dashboard {
  return (
    isObject(value) &&
    (value.mode === "live" || value.mode === "demo") &&
    typeof value.server_time === "string" &&
    Array.isArray(value.accounts) &&
    value.accounts.every(isAccountView)
  );
}

export const READ_ONLY: Capabilities = Object.freeze({ writable: false, secure_store_available: false });

export function isCapabilities(value: unknown): value is Capabilities {
  return (
    isObject(value) && typeof value.writable === "boolean" && typeof value.secure_store_available === "boolean"
  );
}

/**
 * Session guard. It also normalizes `capabilities`: an older server that sends
 * none, or a malformed value, is treated as read-only (fail closed).
 */
export function isSession(value: unknown): value is SessionInfo {
  if (
    !(
      isObject(value) &&
      (value.mode === "live" || value.mode === "demo") &&
      typeof value.version === "string" &&
      typeof value.server_time === "string" &&
      (value.auth === "token" || value.auth === "none")
    )
  ) {
    return false;
  }
  if (!isCapabilities(value.capabilities)) value.capabilities = { ...READ_ONLY };
  return true;
}

const STORAGE_CLASSES = new Set(["external_file", "session", "keyring", "none"]);

export function isAccountConfig(value: unknown): value is AccountConfig {
  return (
    isObject(value) &&
    typeof value.id === "string" &&
    typeof value.provider === "string" &&
    typeof value.label === "string" &&
    typeof value.enabled === "boolean" &&
    typeof value.poll_interval_seconds === "number" &&
    typeof value.effective_poll_interval_seconds === "number" &&
    (value.credential_kind === null || typeof value.credential_kind === "string") &&
    typeof value.storage === "string" &&
    STORAGE_CLASSES.has(value.storage) &&
    (value.reference === null || value.reference === "default" || value.reference === "custom") &&
    (value.session_available === null || typeof value.session_available === "boolean") &&
    typeof value.scope_selected === "boolean" &&
    typeof value.organization_selected === "boolean" &&
    (value.revision === null || typeof value.revision === "string")
  );
}

export function isAccountList(value: unknown): value is AccountList {
  return (
    isObject(value) &&
    Array.isArray(value.accounts) &&
    value.accounts.every(isAccountConfig) &&
    isCapabilities(value.capabilities)
  );
}

const WARNINGS = new Set([null, "committed_uncertain", "cleanup_failed", "host_refresh_failed", "credential_expired"]);

export function isMutationResult(value: unknown): value is MutationResult {
  return (
    isObject(value) &&
    (value.account === null || isAccountConfig(value.account)) &&
    Array.isArray(value.accounts) &&
    value.accounts.every(isAccountConfig) &&
    isCapabilities(value.capabilities) &&
    WARNINGS.has(value.warning as string | null)
  );
}

export function isPrepareResult(value: unknown): value is PrepareResult {
  return (
    isObject(value) &&
    typeof value.prepare_id === "string" &&
    typeof value.expires_in === "number" &&
    (value.kind === "grok_scope" || value.kind === "console_organization") &&
    Array.isArray(value.choices) &&
    value.choices.every(
      (c) =>
        isObject(c) &&
        typeof c.id === "string" &&
        (c.label === null || typeof c.label === "string") &&
        typeof c.legacy === "boolean" &&
        typeof c.current === "boolean",
    )
  );
}

function isQueued(value: unknown): value is { status: "queued" } {
  return isObject(value) && value.status === "queued";
}

/** The ApiError kind for a non-2xx status other than 401/429. */
export function statusKind(status: number): ApiErrorKind {
  switch (status) {
    case 403:
      return "forbidden";
    case 404:
      return "not_found";
    case 409:
      return "conflict";
    case 400:
    case 422:
    case 428:
      return "invalid";
    case 410:
      return "expired";
    case 413:
      return "too_large";
    case 503:
      return "unavailable";
    default:
      return status >= 500 ? "server" : "http";
  }
}

type Fetch = typeof fetch;

/**
 * Read and parse a JSON body through an explicit reader so the stream can be
 * cancelled: on the shared deadline/abort (`aborted` rejects), on a body over
 * MAX_BODY_BYTES, or on any other failure before the end of the stream.
 */
async function readJsonBody(response: Response, aborted: Promise<never>): Promise<unknown> {
  const declared = Number(response.headers.get("Content-Length"));
  if (Number.isFinite(declared) && declared > MAX_BODY_BYTES) {
    response.body?.cancel().catch(() => undefined);
    throw new ApiError("invalid_response", response.status);
  }
  if (!response.body) return JSON.parse("");
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8", { fatal: true });
  let text = "";
  let total = 0;
  let finished = false;
  try {
    for (;;) {
      const { done, value } = await Promise.race([reader.read(), aborted]);
      if (done) break;
      total += value.byteLength;
      if (total > MAX_BODY_BYTES) throw new ApiError("invalid_response", response.status);
      text += decoder.decode(value, { stream: true });
    }
    finished = true;
    text += decoder.decode();
  } finally {
    if (!finished) reader.cancel().catch(() => undefined);
  }
  return JSON.parse(text) as unknown;
}

/**
 * Read at most MAX_ERROR_BODY_BYTES of an error body for its `{error}` code.
 * Anything larger, malformed, or not a whitelisted code yields no code.
 */
async function readErrorBody(
  response: Response,
  aborted: Promise<never>,
): Promise<{ code: string | null; retryAfter: number | null }> {
  const none = { code: null, retryAfter: null };
  const declared = Number(response.headers.get("Content-Length"));
  if (!response.body || (Number.isFinite(declared) && declared > MAX_ERROR_BODY_BYTES)) {
    response.body?.cancel().catch(() => undefined);
    return none;
  }
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  let finished = false;
  try {
    for (;;) {
      const { done, value } = await Promise.race([reader.read(), aborted]);
      if (done) break;
      total += value.byteLength;
      if (total > MAX_ERROR_BODY_BYTES) return none;
      chunks.push(value);
    }
    finished = true;
  } finally {
    if (!finished) reader.cancel().catch(() => undefined);
  }
  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
  } catch {
    return none;
  }
  if (!isObject(parsed) || typeof parsed.error !== "string" || !KNOWN_ERROR_CODES.has(parsed.error)) return none;
  const wait = parsed.retry_after;
  const retryAfter =
    typeof wait === "number" && Number.isInteger(wait) && wait >= 0 ? clampRetryAfter(wait) : null;
  return { code: parsed.error, retryAfter };
}

export interface RequestOptions<T> {
  guard: (value: unknown) => value is T;
  /** Serialized as JSON; Content-Type is sent only when a body is present. */
  body?: unknown;
  /** Revision for If-Match, sent quoted. */
  ifMatch?: string;
  signal?: AbortSignal;
  timeoutMs?: number;
  /** Read a bounded error body for its code (account-management calls only). */
  errorCodes?: boolean;
}

export function createHttpClient(credentials: Credentials, fetchImpl: Fetch = fetch.bind(globalThis)): UsageClient {
  const { baseUrl, token } = credentials;

  async function request<T>(method: string, path: string, options: RequestOptions<T>): Promise<T> {
    const { guard, signal: outer } = options;
    const timeoutMs = options.timeoutMs ?? REQUEST_TIMEOUT_MS;
    const controller = new AbortController();
    let timedOut = false;
    // One deadline covers the whole exchange: headers *and* body. Clearing it
    // once headers arrive would let a stalled body hang polling forever.
    const timer = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, timeoutMs);
    const forward = () => controller.abort();
    if (outer?.aborted) controller.abort();
    outer?.addEventListener("abort", forward, { once: true });
    const aborted = new Promise<never>((_, reject) => {
      const fail = () => reject(new DOMException("Aborted", "AbortError"));
      if (controller.signal.aborted) fail();
      else controller.signal.addEventListener("abort", fail, { once: true });
    });
    // Never an unhandled rejection when the race below has already settled.
    aborted.catch(() => undefined);
    const failure = (error: unknown, fallback: ApiErrorKind, status: number | null = null): unknown => {
      if (outer?.aborted) return error;
      return new ApiError(timedOut ? "timeout" : fallback, timedOut ? null : status);
    };
    const headers: Record<string, string> = { Authorization: `Bearer ${token}`, Accept: "application/json" };
    const hasBody = options.body !== undefined;
    if (hasBody) headers["Content-Type"] = "application/json";
    if (options.ifMatch !== undefined) headers["If-Match"] = `"${options.ifMatch}"`;
    try {
      let response: Response;
      try {
        response = await Promise.race([
          fetchImpl(baseUrl + path, {
            method,
            headers,
            ...(hasBody ? { body: JSON.stringify(options.body) } : {}),
            signal: controller.signal,
            cache: "no-store",
            credentials: "omit",
            redirect: "error",
            referrerPolicy: "no-referrer",
            mode: "cors",
          }),
          aborted,
        ]);
      } catch (error) {
        throw failure(error, "network");
      }
      if (response.status === 401) throw new ApiError("unauthorized", 401);
      if (response.status === 429) {
        throw new ApiError("rate_limited", 429, parseRetryAfter(response.headers.get("Retry-After")));
      }
      if (!response.ok) {
        const kind = statusKind(response.status);
        if (!options.errorCodes) {
          response.body?.cancel().catch(() => undefined);
          throw new ApiError(kind, response.status);
        }
        let detail: { code: string | null; retryAfter: number | null } = { code: null, retryAfter: null };
        try {
          detail = await readErrorBody(response, aborted);
        } catch (error) {
          if (outer?.aborted) throw error;
        }
        const retryAfter = detail.retryAfter ?? parseRetryAfter(response.headers.get("Retry-After"));
        throw new ApiError(kind, response.status, retryAfter, detail.code);
      }
      let body: unknown;
      try {
        body = await readJsonBody(response, aborted);
      } catch (error) {
        throw failure(error, "invalid_response", response.status);
      }
      if (!guard(body)) throw new ApiError("invalid_response", response.status);
      return body;
    } finally {
      clearTimeout(timer);
      outer?.removeEventListener("abort", forward);
    }
  }

  const accountPath = (id: string) => `/api/v1/accounts/${encodeURIComponent(id)}`;
  const write = { errorCodes: true, guard: isMutationResult } as const;

  return {
    baseUrl,
    session: (signal) => request("GET", "/api/v1/session", { guard: isSession, signal }),
    dashboard: (signal) => request("GET", "/api/v1/dashboard", { guard: isDashboard, signal }),
    account: (id, signal) => request("GET", accountPath(id), { guard: isAccountView, signal }),
    accounts: (signal) => request("GET", "/api/v1/accounts", { guard: isAccountList, errorCodes: true, signal }),
    createAccount: (body, signal) => request("POST", "/api/v1/accounts", { ...write, body, signal }),
    updateAccount: (id, revision, body, signal) =>
      request("PATCH", accountPath(id), { ...write, body, ifMatch: revision, signal }),
    removeAccount: (id, revision, signal) =>
      request("DELETE", accountPath(id), { ...write, ifMatch: revision, signal }),
    reorderAccounts: (ids, signal) =>
      request("PUT", "/api/v1/accounts/order", { ...write, body: { ids: [...ids] }, signal }),
    reconnectAccount: (id, signal) =>
      request("POST", `${accountPath(id)}/reconnect`, { guard: isQueued, errorCodes: true, signal }),
    prepare: (body, signal) =>
      request("POST", "/api/v1/accounts/prepare", {
        guard: isPrepareResult,
        errorCodes: true,
        body,
        signal,
        timeoutMs: PREPARE_TIMEOUT_MS,
      }),
  };
}

/** Production uses HTTP; VITE_MOCK=1 builds swap in the bundled DEMO fixture. */
export async function createClient(credentials: Credentials): Promise<UsageClient> {
  if (import.meta.env.VITE_MOCK === "1") {
    const { createMockClient } = await import("./mock/client");
    return createMockClient(credentials);
  }
  return createHttpClient(credentials);
}

export const MOCK_ENABLED = import.meta.env.VITE_MOCK === "1";
