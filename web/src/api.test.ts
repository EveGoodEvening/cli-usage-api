import { afterEach, describe, expect, it, vi } from "vitest";
import {
  API_ERROR_MESSAGES,
  ApiError,
  ERROR_CODE_MESSAGES,
  MAX_BODY_BYTES,
  MAX_ERROR_BODY_BYTES,
  PREPARE_TIMEOUT_MS,
  REQUEST_TIMEOUT_MS,
  createHttpClient,
  isDashboard,
  parseRetryAfter,
} from "./api";
import { endsSession } from "./hooks";
import type { AccountConfig, MutationResult } from "./types";
import fixture from "./mock/demo-dashboard.json";

const creds = { baseUrl: "https://api.example.com", token: "usk_secret-token" };

function respond(status: number, body: unknown, headers: Record<string, string> = {}) {
  return vi.fn(async () => new Response(JSON.stringify(body), { status, headers }));
}

describe("http client", () => {
  it("sends the bearer token in a header, never in the URL, without cookies", async () => {
    const fetchMock = respond(200, fixture.healthy);
    const client = createHttpClient(creds, fetchMock as unknown as typeof fetch);
    const data = await client.dashboard();
    expect(data.accounts).toHaveLength(5);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("https://api.example.com/api/v1/dashboard");
    expect(url).not.toContain(creds.token);
    expect((init.headers as Record<string, string>).Authorization).toBe(`Bearer ${creds.token}`);
    expect(init.credentials).toBe("omit");
    expect(init.redirect).toBe("error");
  });

  it("maps 401 to unauthorized and 429 to rate_limited with Retry-After", async () => {
    const unauthorized = createHttpClient(creds, respond(401, { error: "unauthorized" }) as unknown as typeof fetch);
    await expect(unauthorized.session()).rejects.toMatchObject({ kind: "unauthorized", status: 401 });
    const limited = createHttpClient(
      creds,
      respond(429, { error: "rate_limited" }, { "Retry-After": "42" }) as unknown as typeof fetch,
    );
    await expect(limited.dashboard()).rejects.toMatchObject({ kind: "rate_limited", retryAfter: 42 });
  });

  it("rejects responses that do not match the contract", async () => {
    const client = createHttpClient(creds, respond(200, { mode: "live" }) as unknown as typeof fetch);
    await expect(client.dashboard()).rejects.toMatchObject({ kind: "invalid_response" });
  });

  it("reports network failures without leaking the token in the message", async () => {
    const failing = vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    });
    const client = createHttpClient(creds, failing as unknown as typeof fetch);
    const error = await client.dashboard().catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).kind).toBe("network");
    expect((error as ApiError).message).not.toContain(creds.token);
  });

  it("encodes account ids in the path", async () => {
    const view = fixture.healthy.accounts[0];
    const fetchMock = respond(200, view);
    const client = createHttpClient(creds, fetchMock as unknown as typeof fetch);
    await client.account("a/b");
    expect((fetchMock.mock.calls[0] as unknown as [string])[0]).toBe(
      "https://api.example.com/api/v1/accounts/a%2Fb",
    );
  });
});

describe("contract guards", () => {
  it("accepts both demo scenarios generated from the backend", () => {
    expect(isDashboard(fixture.healthy)).toBe(true);
    expect(isDashboard(fixture.errors)).toBe(true);
  });

  it("bounds Retry-After", () => {
    expect(parseRetryAfter("30")).toBe(30);
    expect(parseRetryAfter(" 30 ")).toBe(30);
    expect(parseRetryAfter("999999")).toBe(3600);
    expect(parseRetryAfter("99999999999")).toBe(3600);
    expect(parseRetryAfter("0")).toBe(1);
    expect(parseRetryAfter(null)).toBeNull();
    expect(parseRetryAfter("")).toBeNull();
    expect(parseRetryAfter("soon")).toBeNull();
    expect(parseRetryAfter("-5")).toBeNull();
    expect(parseRetryAfter("1.5")).toBeNull();
  });

  it("reads Retry-After HTTP-dates relative to now, clamped to 1 s .. 3600 s", () => {
    const now = Date.parse("Wed, 21 Oct 2015 07:28:00 GMT");
    expect(parseRetryAfter("Wed, 21 Oct 2015 07:28:42 GMT", now)).toBe(42);
    expect(parseRetryAfter("Wed, 21 Oct 2015 07:28:00 GMT", now)).toBe(1);
    expect(parseRetryAfter("Tue, 20 Oct 2015 07:28:00 GMT", now)).toBe(1);
    expect(parseRetryAfter("Thu, 22 Oct 2015 07:28:00 GMT", now)).toBe(3600);
    expect(parseRetryAfter("Wed, 99 Foo 2015 07:28:00 GMT", now)).toBeNull();
    expect(parseRetryAfter("Wed, 31 Feb 2015 07:28:00 GMT", now)).toBeNull();
  });

  it("accepts only RFC 9110 HTTP-date shapes, not whatever Date.parse tolerates", () => {
    const now = Date.parse("Wed, 21 Oct 2015 07:28:00 GMT");
    // Date.parse reads both of these as dates in V8.
    expect(Number.isFinite(Date.parse("x 2015"))).toBe(true);
    expect(parseRetryAfter("x 2015", now)).toBeNull();
    expect(parseRetryAfter("soon 1", now)).toBeNull();
    expect(parseRetryAfter("2015-10-21T07:28:42Z", now)).toBeNull();
    expect(parseRetryAfter("Wed, 21 Oct 2015 07:28:42 +0000", now)).toBeNull();
    expect(parseRetryAfter("wed, 21 oct 2015 07:28:42 gmt", now)).toBeNull();
    // Obsolete forms from RFC 9110 §5.6.7, read as UTC.
    expect(parseRetryAfter("Wednesday, 21-Oct-15 07:28:42 GMT", now)).toBe(42);
    expect(parseRetryAfter("Wed Oct 21 07:28:42 2015", now)).toBe(42);
    expect(parseRetryAfter("Wed Oct  1 07:28:42 2015", now)).toBe(1);
  });
});

describe("Retry-After on 429", () => {
  it("surfaces an HTTP-date Retry-After as clamped seconds", async () => {
    const at = new Date(Date.now() + 120_000).toUTCString();
    const client = createHttpClient(creds, respond(429, { error: "rate_limited" }, { "Retry-After": at }) as unknown as typeof fetch);
    const error = (await client.dashboard().catch((e: unknown) => e)) as ApiError;
    expect(error.kind).toBe("rate_limited");
    expect(error.retryAfter).toBeGreaterThanOrEqual(118);
    expect(error.retryAfter).toBeLessThanOrEqual(120);
  });

  it("never yields a zero-second pause", async () => {
    const client = createHttpClient(creds, respond(429, {}, { "Retry-After": "0" }) as unknown as typeof fetch);
    await expect(client.dashboard()).rejects.toMatchObject({ kind: "rate_limited", retryAfter: 1 });
  });
});

/** A 200 response whose body sends its headers and then never produces a byte. */
function stalledStream() {
  let cancelled = false;
  const stream = new ReadableStream<Uint8Array>({
    cancel() {
      cancelled = true;
    },
  });
  return { stream, wasCancelled: () => cancelled };
}

function stalledBody() {
  const { stream, wasCancelled } = stalledStream();
  const fetchMock = vi.fn(async () => new Response(stream, { status: 200, headers: { "Content-Type": "application/json" } }));
  return { fetchMock, wasCancelled };
}

describe("request deadline", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("times out a response whose body stalls after the headers", async () => {
    vi.useFakeTimers();
    const { fetchMock, wasCancelled } = stalledBody();
    const client = createHttpClient(creds, fetchMock as unknown as typeof fetch);
    const outcome = client.dashboard().catch((e: unknown) => e);
    await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS - 1);
    expect(wasCancelled()).toBe(false);
    let settled = false;
    void outcome.then(() => {
      settled = true;
    });
    await Promise.resolve();
    expect(settled).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    const error = await outcome;
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).kind).toBe("timeout");
    await vi.advanceTimersByTimeAsync(0);
    expect(wasCancelled()).toBe(true);
  });

  it("times out a request whose headers never arrive, even if fetch ignores the signal", async () => {
    vi.useFakeTimers();
    const hanging = vi.fn(() => new Promise<Response>(() => undefined));
    const client = createHttpClient(creds, hanging as unknown as typeof fetch);
    const outcome = client.session().catch((e: unknown) => e);
    await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS);
    expect(await outcome).toMatchObject({ kind: "timeout" });
  });

  it("propagates a caller abort during the body read as an abort, not a timeout", async () => {
    const { fetchMock, wasCancelled } = stalledBody();
    const client = createHttpClient(creds, fetchMock as unknown as typeof fetch);
    const outer = new AbortController();
    const outcome = client.dashboard(outer.signal).catch((e: unknown) => e);
    await new Promise((resolve) => setTimeout(resolve, 0));
    outer.abort();
    const error = await outcome;
    expect(error).not.toBeInstanceOf(ApiError);
    expect((error as DOMException).name).toBe("AbortError");
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(wasCancelled()).toBe(true);
  });

  it("refuses and cancels a body larger than the size cap", async () => {
    let cancelled = false;
    let sent = 0;
    const chunk = new Uint8Array(1024 * 1024).fill(0x20);
    const stream = new ReadableStream<Uint8Array>({
      pull(ctrl) {
        sent += chunk.byteLength;
        ctrl.enqueue(chunk);
      },
      cancel() {
        cancelled = true;
      },
    });
    const fetchMock = vi.fn(async () => new Response(stream, { status: 200 }));
    const client = createHttpClient(creds, fetchMock as unknown as typeof fetch);
    await expect(client.dashboard()).rejects.toMatchObject({ kind: "invalid_response" });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(cancelled).toBe(true);
    expect(sent).toBeLessThanOrEqual(MAX_BODY_BYTES + 2 * chunk.byteLength);
  });

  it("refuses a declared Content-Length over the cap without reading the body", async () => {
    vi.useFakeTimers();
    const { stream, wasCancelled } = stalledStream();
    const fetchMock = vi.fn(
      async () => new Response(stream, { status: 200, headers: { "Content-Length": String(MAX_BODY_BYTES + 1) } }),
    );
    const client = createHttpClient(creds, fetchMock as unknown as typeof fetch);
    const outcome = client.dashboard().catch((e: unknown) => e);
    // Settles at once, without waiting for the request deadline.
    await vi.advanceTimersByTimeAsync(0);
    expect(await outcome).toMatchObject({ kind: "invalid_response" });
    expect(wasCancelled()).toBe(true);
  });

  it("parses a body delivered in several chunks, including multi-byte characters split across them", async () => {
    const payload = { ...fixture.healthy, note: "额度" };
    const bytes = new TextEncoder().encode(JSON.stringify(payload));
    const split = bytes.findIndex((byte) => byte >= 0x80) + 1;
    expect(split).toBeGreaterThan(0);
    const pieces = [bytes.slice(0, split), bytes.slice(split, split + 1), bytes.slice(split + 1)];
    const stream = new ReadableStream<Uint8Array>({
      start(ctrl) {
        for (const piece of pieces) ctrl.enqueue(piece);
        ctrl.close();
      },
    });
    const fetchMock = vi.fn(async () => new Response(stream, { status: 200 }));
    const client = createHttpClient(creds, fetchMock as unknown as typeof fetch);
    expect(await client.dashboard()).toEqual(payload);
  });
});

const ID = "0f0e0d0c-0b0a-4908-8706-050403020100";
const REV = "0123456789abcdef0123456789abcdef";
const SECRET = "sk-ant-sid01-super-secret";
const CAPS = { writable: true, secure_store_available: false };

const CONFIG: AccountConfig = {
  id: ID,
  provider: "codex_subscription",
  label: "Codex",
  enabled: true,
  poll_interval_seconds: 60,
  effective_poll_interval_seconds: 60,
  credential_kind: "codex_auth_file",
  storage: "external_file",
  reference: "default",
  session_available: null,
  scope_selected: false,
  organization_selected: false,
  revision: REV,
};
const RESULT: MutationResult = { account: CONFIG, accounts: [CONFIG], capabilities: CAPS, warning: null };

type Call = [string, RequestInit];

function call(mock: ReturnType<typeof vi.fn>, index = 0): { url: string; init: RequestInit; headers: Record<string, string> } {
  const [url, init] = mock.mock.calls[index] as unknown as Call;
  return { url, init, headers: init.headers as Record<string, string> };
}

describe("account management calls", () => {
  it("sends each call with its method, path, headers and the fixed init flags", async () => {
    const cases: Array<{
      run: (c: ReturnType<typeof createHttpClient>) => Promise<unknown>;
      reply: unknown;
      method: string;
      path: string;
      body: unknown;
      ifMatch?: string;
    }> = [
      { run: (c) => c.accounts(), reply: { accounts: [CONFIG], capabilities: CAPS }, method: "GET", path: "/api/v1/accounts", body: undefined },
      {
        run: (c) => c.createAccount({ provider: "codex_subscription", label: "C", source: null }),
        reply: RESULT,
        method: "POST",
        path: "/api/v1/accounts",
        body: { provider: "codex_subscription", label: "C", source: null },
      },
      {
        run: (c) => c.updateAccount(ID, REV, { enabled: false }),
        reply: RESULT,
        method: "PATCH",
        path: `/api/v1/accounts/${ID}`,
        body: { enabled: false },
        ifMatch: `"${REV}"`,
      },
      {
        run: (c) => c.removeAccount(ID, REV),
        reply: { ...RESULT, account: null },
        method: "DELETE",
        path: `/api/v1/accounts/${ID}`,
        body: undefined,
        ifMatch: `"${REV}"`,
      },
      {
        run: (c) => c.reorderAccounts([ID]),
        reply: { ...RESULT, account: null },
        method: "PUT",
        path: "/api/v1/accounts/order",
        body: { ids: [ID] },
      },
      {
        run: (c) => c.reconnectAccount(ID),
        reply: { status: "queued" },
        method: "POST",
        path: `/api/v1/accounts/${ID}/reconnect`,
        body: undefined,
      },
      {
        run: (c) =>
          c.prepare({ account_id: null, revision: null, provider: "grok_subscription", credential_kind: "grok_auth_file", reference: "default" }),
        reply: { prepare_id: "p", expires_in: 300, kind: "grok_scope", choices: [{ id: "c1", label: null, legacy: false, current: false }] },
        method: "POST",
        path: "/api/v1/accounts/prepare",
        body: { account_id: null, revision: null, provider: "grok_subscription", credential_kind: "grok_auth_file", reference: "default" },
      },
    ];
    for (const item of cases) {
      const fetchMock = respond(200, item.reply);
      await item.run(createHttpClient(creds, fetchMock as unknown as typeof fetch));
      const { url, init, headers } = call(fetchMock);
      expect(url).toBe(creds.baseUrl + item.path);
      expect(init.method).toBe(item.method);
      expect(headers.Authorization).toBe(`Bearer ${creds.token}`);
      expect(init.credentials).toBe("omit");
      expect(init.redirect).toBe("error");
      expect(init.cache).toBe("no-store");
      expect(init.referrerPolicy).toBe("no-referrer");
      expect(init.mode).toBe("cors");
      if (item.body === undefined) {
        expect(init.body).toBeUndefined();
        expect(headers).not.toHaveProperty("Content-Type");
      } else {
        expect(JSON.parse(init.body as string)).toEqual(item.body);
        expect(headers["Content-Type"]).toBe("application/json");
      }
      if (item.ifMatch) expect(headers["If-Match"]).toBe(item.ifMatch);
      else expect(headers).not.toHaveProperty("If-Match");
    }
  });

  it("keeps secrets in the body, never the URL, and encodes ids", async () => {
    const fetchMock = respond(200, { prepare_id: "p", expires_in: 300, kind: "console_organization", choices: [] });
    const client = createHttpClient(creds, fetchMock as unknown as typeof fetch);
    await client.prepare({ account_id: null, revision: null, provider: "claude_platform", credential_kind: "console_session", secret: SECRET });
    const { url, init } = call(fetchMock);
    expect(url).not.toContain(SECRET);
    expect(init.body).toContain(SECRET);
    const update = respond(200, RESULT);
    await createHttpClient(creds, update as unknown as typeof fetch).updateAccount("a/b", REV, {
      source: { credential_kind: "api_key", secret: SECRET, persist: false },
    });
    expect(call(update).url).toBe(`${creds.baseUrl}/api/v1/accounts/a%2Fb`);
    expect(call(update).url).not.toContain(SECRET);
  });

  it("accepts a Claude credits discovery and names the organization error codes", async () => {
    const fetchMock = respond(200, {
      prepare_id: "p",
      expires_in: 300,
      kind: "claude_organization",
      choices: [{ id: "c1", label: null, legacy: false, current: false }],
    });
    const client = createHttpClient(creds, fetchMock as unknown as typeof fetch);
    const result = await client.prepare({
      account_id: null,
      revision: null,
      provider: "claude_subscription",
      credential_kind: "manual_bearer",
      secret: SECRET,
    });
    expect(result.kind).toBe("claude_organization");
    expect(call(fetchMock).url).not.toContain(SECRET);
    for (const code of ["organization_required", "invalid_organization", "organization_reselect_required"]) {
      const failing = createHttpClient(creds, respond(422, { error: code }) as unknown as typeof fetch);
      const error = (await failing
        .createAccount({ provider: "openai_platform", label: "x", source: null })
        .catch((e: unknown) => e)) as ApiError;
      expect(error).toMatchObject({ kind: "invalid", code });
      expect(error.message).toBe(ERROR_CODE_MESSAGES[code]);
    }
  });

  it("names only whitelisted error codes and falls back to the kind message", async () => {
    const known = createHttpClient(creds, respond(503, { error: "secure_store_unavailable" }) as unknown as typeof fetch);
    const error = (await known.updateAccount(ID, REV, {}).catch((e: unknown) => e)) as ApiError;
    expect(error).toMatchObject({ kind: "unavailable", status: 503, code: "secure_store_unavailable" });
    expect(error.message).toBe(ERROR_CODE_MESSAGES.secure_store_unavailable);

    const unknown = createHttpClient(creds, respond(422, { error: "<b>evil server text</b>" }) as unknown as typeof fetch);
    const other = (await unknown.createAccount({ provider: "codex_subscription", label: "x", source: null }).catch((e: unknown) => e)) as ApiError;
    expect(other).toMatchObject({ kind: "invalid", code: null });
    expect(other.message).toBe(API_ERROR_MESSAGES.invalid);
    expect(other.message).not.toContain("evil");

    for (const [status, kind] of [
      [400, "invalid"],
      [403, "forbidden"],
      [404, "not_found"],
      [409, "conflict"],
      [410, "expired"],
      [413, "too_large"],
      [428, "invalid"],
      [500, "server"],
      [502, "server"],
    ] as const) {
      const client = createHttpClient(creds, respond(status, {}) as unknown as typeof fetch);
      await expect(client.reorderAccounts([])).rejects.toMatchObject({ kind, status, code: null });
    }
  });

  it("reads retry_after for discovery_busy, which never ends the session", async () => {
    const client = createHttpClient(
      creds,
      respond(409, { error: "discovery_busy", retry_after: 7 }, { "Retry-After": "7" }) as unknown as typeof fetch,
    );
    const error = (await client
      .prepare({ account_id: null, revision: null, provider: "claude_platform", credential_kind: "console_session", secret: "k" })
      .catch((e: unknown) => e)) as ApiError;
    expect(error).toMatchObject({ kind: "conflict", code: "discovery_busy", retryAfter: 7 });
    expect(endsSession(error)).toBe(false);
  });

  it("ends the session on 401 and 429 from account calls", async () => {
    const unauthorized = createHttpClient(creds, respond(401, { error: "unauthorized" }) as unknown as typeof fetch);
    const a = (await unauthorized.removeAccount(ID, REV).catch((e: unknown) => e)) as ApiError;
    expect(endsSession(a)).toBe(true);
    const limited = createHttpClient(creds, respond(429, {}, { "Retry-After": "30" }) as unknown as typeof fetch);
    const b = (await limited.accounts().catch((e: unknown) => e)) as ApiError;
    expect(b).toMatchObject({ kind: "rate_limited", retryAfter: 30 });
    expect(endsSession(b)).toBe(true);
  });

  it("does not read error bodies on dashboard reads", async () => {
    const client = createHttpClient(creds, respond(403, { error: "read_only" }) as unknown as typeof fetch);
    await expect(client.dashboard()).rejects.toMatchObject({ kind: "forbidden", code: null });
  });

  it("reads at most 4 KiB of an error body", async () => {
    let sent = 0;
    let cancelled = false;
    const head = new TextEncoder().encode('{"error":"conflict","pad":"');
    const pad = new Uint8Array(1024).fill(0x61);
    const stream = new ReadableStream<Uint8Array>({
      start(ctrl) {
        ctrl.enqueue(head);
        sent += head.byteLength;
      },
      pull(ctrl) {
        sent += pad.byteLength;
        ctrl.enqueue(pad);
      },
      cancel() {
        cancelled = true;
      },
    });
    const fetchMock = vi.fn(async () => new Response(stream, { status: 409 }));
    const client = createHttpClient(creds, fetchMock as unknown as typeof fetch);
    await expect(client.reorderAccounts([])).rejects.toMatchObject({ kind: "conflict", code: null });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(cancelled).toBe(true);
    expect(sent).toBeLessThanOrEqual(MAX_ERROR_BODY_BYTES + 2 * pad.byteLength);
    const declared = vi.fn(
      async () =>
        new Response(JSON.stringify({ error: "conflict" }), {
          status: 409,
          headers: { "Content-Length": String(MAX_ERROR_BODY_BYTES + 1) },
        }),
    );
    await expect(
      createHttpClient(creds, declared as unknown as typeof fetch).reorderAccounts([]),
    ).rejects.toMatchObject({ code: null });
  });
});

describe("prepare deadline", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("allows 40 s for discovery while other calls keep 10 s", async () => {
    vi.useFakeTimers();
    const hanging = vi.fn(() => new Promise<Response>(() => undefined));
    const client = createHttpClient(creds, hanging as unknown as typeof fetch);
    const prepare = client
      .prepare({ account_id: null, revision: null, provider: "claude_platform", credential_kind: "console_session", secret: "k" })
      .catch((e: unknown) => e);
    const accounts = client.accounts().catch((e: unknown) => e);
    let settled = false;
    void prepare.then(() => {
      settled = true;
    });
    await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS);
    expect(await accounts).toMatchObject({ kind: "timeout" });
    expect(settled).toBe(false);
    await vi.advanceTimersByTimeAsync(PREPARE_TIMEOUT_MS - REQUEST_TIMEOUT_MS);
    expect(await prepare).toMatchObject({ kind: "timeout" });
  });
});
