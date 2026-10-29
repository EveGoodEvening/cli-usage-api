// Development-only DEMO client (VITE_MOCK=1). It serves the synthetic fixture
// generated from the backend's DemoSource; nothing here is live account data.
// Production builds without VITE_MOCK never import this module.

import { ApiError, type UsageClient } from "../api";
import type { Credentials } from "../auth";
import type { Dashboard } from "../types";
import fixture from "./demo-dashboard.json";

export const MOCK_BASE = "http://mock.invalid";

const scenarios = fixture as unknown as Record<"healthy" | "errors", Dashboard>;

function shift(value: string | null, ms: number): string | null {
  if (value === null) return null;
  const at = Date.parse(value);
  return Number.isFinite(at) ? new Date(at + ms).toISOString().replace(".000Z", "Z") : value;
}

export function createMockClient(credentials: Credentials): UsageClient {
  const scenario = credentials.baseUrl.endsWith("/errors") ? "errors" : "healthy";
  const started = Date.now();
  // Demo time advances with elapsed wall time, like the backend's demo clock.
  // Only server_time moves; observations, resets and retry deadlines stay fixed.
  const snapshot = (): Dashboard => {
    const base = scenarios[scenario];
    return { ...base, server_time: shift(base.server_time, Date.now() - started) ?? base.server_time };
  };
  const check = async () => {
    await new Promise((resolve) => setTimeout(resolve, 120));
    if (credentials.token === "invalid") throw new ApiError("unauthorized", 401);
  };
  return {
    baseUrl: credentials.baseUrl,
    async session() {
      await check();
      return { mode: "demo", version: "mock", server_time: snapshot().server_time, auth: "token" };
    },
    async dashboard() {
      await check();
      return structuredClone(snapshot());
    },
    async account(id) {
      await check();
      const view = snapshot().accounts.find((item) => item.account.id === id);
      if (!view) throw new ApiError("not_found", 404);
      return structuredClone(view);
    },
  };
}
