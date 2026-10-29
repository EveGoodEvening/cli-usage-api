import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, MAX_BODY_BYTES, REQUEST_TIMEOUT_MS, createHttpClient, isDashboard, parseRetryAfter } from "./api";
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
    expect(data.accounts).toHaveLength(4);
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
