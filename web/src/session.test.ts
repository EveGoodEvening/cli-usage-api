import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { API_ERROR_MESSAGES, ApiError, isSession } from "./api";
import { DEFAULT_RETRY_AFTER, endsSession, signOutNotice } from "./hooks";
import { Login } from "./components/Login";

const NOW = Date.parse("2026-10-29T12:00:00Z");

function renderLogin(notice: ReturnType<typeof signOutNotice>): string {
  return renderToStaticMarkup(
    createElement(Login, { initialBaseUrl: "https://api.example.com", notice, onSignedIn: () => undefined }),
  );
}

function submitButton(html: string): string {
  return /<button type="submit"[^>]*>[^<]*<\/button>/.exec(html)?.[0] ?? "";
}

describe("session end on authenticated failures", () => {
  it("ends the session on 401 and on 429, never on transient failures", () => {
    expect(endsSession(new ApiError("unauthorized", 401))).toBe(true);
    expect(endsSession(new ApiError("rate_limited", 429, 30))).toBe(true);
    for (const kind of ["not_found", "timeout", "network", "http", "invalid_response"] as const) {
      expect(endsSession(new ApiError(kind))).toBe(false);
    }
  });

  it("turns a 429 into a rate-limited notice with a Retry-After cooldown", () => {
    expect(signOutNotice(new ApiError("rate_limited", 429, 42), NOW)).toEqual({
      message: API_ERROR_MESSAGES.rate_limited,
      retryAt: NOW + 42_000,
    });
    expect(signOutNotice(new ApiError("rate_limited", 429, null), NOW)?.retryAt).toBe(
      NOW + DEFAULT_RETRY_AFTER * 1000,
    );
    expect(signOutNotice(new ApiError("unauthorized", 401), NOW)).toEqual({
      message: "令牌已失效或被撤销，请重新输入。",
      retryAt: null,
    });
    expect(signOutNotice(undefined, NOW)).toBeNull();
  });
});

describe("Login after a rate-limited session end", () => {
  it("shows the notice and countdown and keeps Connect disabled until it ends", () => {
    const notice = signOutNotice(new ApiError("rate_limited", 429, 30), Date.now());
    const html = renderLogin(notice);
    expect(html).toContain(API_ERROR_MESSAGES.rate_limited);
    expect(html).toMatch(/(29|30) 秒后才能重新连接。/);
    const button = submitButton(html);
    expect(button).toContain("disabled");
    expect(button).toMatch(/请等待 (29|30) 秒/);
  });

  it("enables Connect once the cooldown has passed", () => {
    const html = renderLogin({ message: API_ERROR_MESSAGES.rate_limited, retryAt: Date.now() - 1000 });
    expect(html).toContain(API_ERROR_MESSAGES.rate_limited);
    expect(html).not.toContain("秒后才能重新连接");
    const button = submitButton(html);
    expect(button).not.toContain("disabled");
    expect(button).toContain("连接");
  });

  it("states the token's possible write access next to remember", () => {
    const html = renderLogin(null);
    expect(html).toContain("查看各账号的额度与余额；服务器允许时也可在网页管理账号。");
    expect(html).toContain("此令牌可能可以修改服务器上的账号；共享设备上不要记住它。");
    expect(html).not.toContain("只读查看");
  });

  it("does not disable Connect after a 401 sign-out", () => {
    const html = renderLogin(signOutNotice(new ApiError("unauthorized", 401)));
    expect(html).toContain("令牌已失效或被撤销");
    expect(submitButton(html)).not.toContain("disabled");
  });
});

describe("session capabilities", () => {
  const base = { mode: "live", version: "1.0", server_time: "2026-10-29T12:00:00Z", auth: "token" };

  it("treats a missing or malformed capabilities object as read-only", () => {
    const missing: Record<string, unknown> = { ...base };
    expect(isSession(missing)).toBe(true);
    expect(missing.capabilities).toEqual({ writable: false, secure_store_available: false });
    const malformed: Record<string, unknown> = { ...base, capabilities: { writable: "yes" } };
    expect(isSession(malformed)).toBe(true);
    expect(malformed.capabilities).toEqual({ writable: false, secure_store_available: false });
  });

  it("keeps the server's capabilities when present", () => {
    const session: Record<string, unknown> = {
      ...base,
      capabilities: { writable: true, secure_store_available: true },
    };
    expect(isSession(session)).toBe(true);
    expect(session.capabilities).toEqual({ writable: true, secure_store_available: true });
  });
});
