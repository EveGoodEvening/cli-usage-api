// Typed client for the read-only usage API. Bearer auth only; the token is
// never logged, never placed in a URL, and no cookies are sent.

import type { AccountView, Dashboard, SessionInfo } from "./types";
import type { Credentials } from "./auth";

export type ApiErrorKind =
  | "unauthorized"
  | "rate_limited"
  | "not_found"
  | "timeout"
  | "network"
  | "http"
  | "invalid_response";

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status: number | null;
  /** Seconds to wait, from Retry-After, when rate limited. */
  readonly retryAfter: number | null;

  constructor(kind: ApiErrorKind, status: number | null = null, retryAfter: number | null = null) {
    super(API_ERROR_MESSAGES[kind]);
    this.name = "ApiError";
    this.kind = kind;
    this.status = status;
    this.retryAfter = retryAfter;
  }
}

export const API_ERROR_MESSAGES: Record<ApiErrorKind, string> = {
  unauthorized: "令牌无效或已撤销。请输入有效的 API 令牌。",
  rate_limited: "令牌未通过验证，且失败次数过多，服务器暂时拒绝请求。请在倒计时结束后重新输入有效令牌。",
  not_found: "API 没有这个地址。检查 API 地址是否指向 usage api serve。",
  timeout: "API 在 10 秒内没有响应。",
  network: "无法连接 API。检查地址、服务是否在运行，以及 --allow-origin 是否包含本页面的来源。",
  http: "API 返回了意外的状态码。",
  invalid_response: "API 返回的数据不符合预期格式。",
};

export interface UsageClient {
  readonly baseUrl: string;
  session(signal?: AbortSignal): Promise<SessionInfo>;
  dashboard(signal?: AbortSignal): Promise<Dashboard>;
  account(id: string, signal?: AbortSignal): Promise<AccountView>;
}

export const REQUEST_TIMEOUT_MS = 10_000;
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

export function isSession(value: unknown): value is SessionInfo {
  return (
    isObject(value) &&
    (value.mode === "live" || value.mode === "demo") &&
    typeof value.version === "string" &&
    typeof value.server_time === "string" &&
    (value.auth === "token" || value.auth === "none")
  );
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

export function createHttpClient(credentials: Credentials, fetchImpl: Fetch = fetch.bind(globalThis)): UsageClient {
  const { baseUrl, token } = credentials;

  async function get<T>(path: string, guard: (v: unknown) => v is T, outer?: AbortSignal): Promise<T> {
    const controller = new AbortController();
    let timedOut = false;
    // One deadline covers the whole exchange: headers *and* body. Clearing it
    // once headers arrive would let a stalled body hang polling forever.
    const timer = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, REQUEST_TIMEOUT_MS);
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
    try {
      let response: Response;
      try {
        response = await Promise.race([
          fetchImpl(baseUrl + path, {
            method: "GET",
            headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
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
      if (response.status === 404) throw new ApiError("not_found", 404);
      if (!response.ok) throw new ApiError("http", response.status);
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

  return {
    baseUrl,
    session: (signal) => get("/api/v1/session", isSession, signal),
    dashboard: (signal) => get("/api/v1/dashboard", isDashboard, signal),
    account: (id, signal) =>
      get(`/api/v1/accounts/${encodeURIComponent(id)}`, isAccountView, signal),
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
