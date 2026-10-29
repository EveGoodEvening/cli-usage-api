import { describe, expect, it } from "vitest";
import type { AccountView, Dashboard, Metric } from "./types";
import fixture from "./mock/demo-dashboard.json";
import {
  grantCountLabel,
  hoistedDetail,
  metricLabel,
  metricValue,
  nestedMetricIds,
  orderedMetrics,
  tightestQuota,
} from "./semantics";

const healthy = fixture.healthy as unknown as Dashboard;
const errors = fixture.errors as unknown as Dashboard;
const byProvider = (d: Dashboard, p: string) => d.accounts.find((a) => a.account.provider === p) as AccountView;

const base: Metric = {
  id: "grok.subscription.shared_pool",
  label: "x",
  state: "ready",
  source: { kind: "private_http", contract: "c", version_sensitive: false },
  quota: null,
  balance: null,
  reset_at: null,
  expires_at: null,
  shared_pool_id: null,
  detail: null,
  share_percent: null,
};

describe("metric semantics", () => {
  it("names a Grok aggregate without pool proof as 汇总, not 共享池", () => {
    expect(metricLabel({ ...base, quota: { used_percent: "45", remaining_percent: "55", used_count: null, limit_count: null, remaining_count: null } })).toBe("Grok 共享池");
    expect(metricLabel({ ...base, share_percent: "45" })).toBe("Grok 汇总");
  });

  it("keeps a share as consumption only", () => {
    expect(metricValue({ ...base, id: "grok.product.build", share_percent: "30" })).toEqual({ kind: "share", used: "30" });
  });

  it("reports unknown, blocked and empty-quota rows as missing, never zero", () => {
    expect(metricValue({ ...base, state: "unknown" })).toEqual({ kind: "missing", text: "未知" });
    expect(metricValue({ ...base, state: "blocked" })).toEqual({ kind: "missing", text: "阻塞" });
    expect(metricValue(base).kind).toBe("missing");
  });

  it("carries exact overage", () => {
    const fable = byProvider(healthy, "claude_subscription").snapshot?.metrics[2] as Metric;
    expect(metricValue(fable)).toMatchObject({ kind: "quota", used: "110.25", remaining: "0", overage: "10.25" });
  });

  it("nests Grok products under their proven pool", () => {
    const grok = byProvider(healthy, "grok_subscription").snapshot?.metrics ?? [];
    expect([...nestedMetricIds(grok)]).toEqual(["grok.product.build", "grok.product.chat"]);
  });

  it("fills missing required rows as unknown", () => {
    const view = byProvider(healthy, "codex_subscription");
    const stripped = { ...view, snapshot: view.snapshot && { ...view.snapshot, metrics: [] } };
    expect(orderedMetrics(stripped)).toEqual([{ id: "codex.subscription.weekly", metric: null }]);
  });

  it("hoists a uniform explanation except for Console balances", () => {
    expect(hoistedDetail(byProvider(healthy, "codex_subscription"))).toContain("synthetic");
    expect(hoistedDetail(byProvider(healthy, "claude_platform"))).toBeNull();
  });

  it("never shows an incomplete grant count as 0", () => {
    expect(grantCountLabel(byProvider(healthy, "claude_platform").snapshot)).toBe("2");
    const failed = errors.accounts.find((a) => a.snapshot?.fetch_state === "schema_error");
    expect(grantCountLabel(failed?.snapshot ?? null)).toBe("—");
    expect(grantCountLabel(null)).toBe("—");
  });

  it("finds the tightest quota without counting product shares", () => {
    expect(tightestQuota(healthy.accounts)?.used).toBe("110.25");
  });
});
