// Development-only DEMO client (VITE_MOCK=1). It serves the synthetic fixture
// generated from the backend's DemoSource; nothing here is live account data.
// Production builds without VITE_MOCK never import this module.

import { ApiError, READ_ONLY, type UsageClient } from "../api";
import type { Credentials } from "../auth";
import type { AccountConfig, AccountView, Dashboard } from "../types";
import fixture from "./demo-dashboard.json";

export const MOCK_BASE = "http://mock.invalid";

const scenarios = fixture as unknown as Record<"healthy" | "errors", Dashboard>;

function shift(value: string | null, ms: number): string | null {
  if (value === null) return null;
  const at = Date.parse(value);
  return Number.isFinite(at) ? new Date(at + ms).toISOString().replace(".000Z", "Z") : value;
}

/** The demo is always read-only: no credentials, no revisions, no writes. */
export function mockAccountConfig(view: AccountView): AccountConfig {
  const { account } = view;
  return {
    id: account.id,
    provider: account.provider,
    label: account.label,
    enabled: account.enabled,
    poll_interval_seconds: account.poll_interval_seconds,
    effective_poll_interval_seconds: account.poll_interval_seconds,
    credential_kind: null,
    storage: "none",
    reference: null,
    session_available: null,
    scope_selected: false,
    organization_selected: false,
    revision: null,
  };
}

const readOnly = async (): Promise<never> => {
  throw new ApiError("forbidden", 403, null, "read_only");
};

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
      return {
        mode: "demo",
        version: "mock",
        server_time: snapshot().server_time,
        auth: "token",
        capabilities: { ...READ_ONLY },
      };
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
    async accounts() {
      await check();
      return { accounts: snapshot().accounts.map(mockAccountConfig), capabilities: { ...READ_ONLY } };
    },
    async createAccount() {
      await check();
      return readOnly();
    },
    async updateAccount() {
      await check();
      return readOnly();
    },
    async removeAccount() {
      await check();
      return readOnly();
    },
    async reorderAccounts() {
      await check();
      return readOnly();
    },
    async reconnectAccount() {
      await check();
      return readOnly();
    },
    async prepare() {
      await check();
      return readOnly();
    },
  };
}
