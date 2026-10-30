// Optional provider extras: Codex credits are displayed; Claude extra usage is
// parse-only (published by the API, deliberately never shown by this UI).
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { AccountView, Dashboard, Metric } from "./types";
import fixture from "./mock/demo-dashboard.json";
import { Board } from "./components/Board";
import { MetricRow } from "./components/MetricRow";
import { creditsText, fixedPointText } from "./format";
import {
  PARSE_ONLY_METRIC_IDS,
  displayDashboard,
  hoistedDetail,
  metricValue,
  nextReset,
  orderedMetrics,
  tightestQuota,
} from "./semantics";
import { planRows, sharedNotes } from "./view";

const NOW = Date.parse("2026-10-28T12:01:00Z");
const EXTRA = "claude.subscription.extra_usage";
const CREDITS = "codex.subscription.credits";
const healthy = fixture.healthy as unknown as Dashboard;

function metric(id: string, overrides: Partial<Metric> = {}): Metric {
  return {
    id,
    label: id,
    state: "ready",
    source: { kind: "private_http", contract: "c", version_sensitive: false },
    quota: null,
    balance: null,
    reset_at: null,
    expires_at: null,
    shared_pool_id: null,
    detail: null,
    share_percent: null,
    spent: null,
    spend_limit: null,
    credits: null,
    unlimited: false,
    ...overrides,
  };
}

function quota(used: string) {
  return { used_percent: used, remaining_percent: null, used_count: null, limit_count: null, remaining_count: null };
}

function account(provider: AccountView["account"]["provider"], metrics: Metric[]): AccountView {
  return {
    account: { id: "a", provider, label: "A", enabled: true, credential_kind: null, poll_interval_seconds: 60 },
    snapshot: {
      account_id: "a",
      metrics,
      grants: [],
      fetch_state: "ok",
      attempted_at: "2026-10-28T12:00:00Z",
      fetched_at: "2026-10-28T12:00:00Z",
      retry_at: null,
      diagnostic: null,
      organization_id: null,
    },
    freshness: null,
  };
}

function row(m: Metric, expanded = false): string {
  return renderToStaticMarkup(createElement(MetricRow, { id: m.id, metric: m, now: NOW, expanded }));
}

function board(views: AccountView[]): string {
  return renderToStaticMarkup(createElement(Board, { views, all: views, now: NOW }));
}

function text(html: string): string {
  return html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");
}

describe("credit amount text", () => {
  it("is plain fixed point: no exponent, no rounding, sign kept", () => {
    expect(fixedPointText("42.5")).toBe("42.5");
    expect(fixedPointText("1E+3")).toBe("1000");
    expect(fixedPointText("1.5E-7")).toBe("0.00000015");
    expect(fixedPointText("0E-7")).toBe("0.0000000");
    expect(fixedPointText("-12.340")).toBe("-12.340");
    expect(fixedPointText("-0")).toBe("-0");
    expect(fixedPointText("1234567890123456789012345678901234567890")).toBe(
      "1234567890123456789012345678901234567890",
    );
    expect(creditsText("7")).toBe("7 credits");
  });

  it("never invents an amount for junk", () => {
    for (const junk of [null, undefined, "", "--1", "1.", "NaN", "Infinity", "1e", "+1", " 1"]) {
      expect(creditsText(junk)).toBe("—");
    }
  });
});

describe("Codex credits row", () => {
  it("shows the exact amount as a figure: no meter, no reset, not money", () => {
    const html = row(metric(CREDITS, { credits: "1E+3" }));
    expect(text(html)).toContain("1000 credits");
    expect(html).not.toContain('class="meter');
    expect(html).not.toContain("重置");
    expect(html).not.toContain("USD");
    expect(html).toContain("row--figure");
  });

  it("is a value, not an unknown placeholder, and its facts show the amount", () => {
    expect(metricValue(metric(CREDITS, { credits: "0" }))).toEqual({ kind: "credits", amount: "0" });
    const html = row(metric(CREDITS, { credits: "-2.50" }), true);
    expect(text(html)).toContain("Credits -2.50 credits");
    expect(text(html)).not.toContain("未知");
    expect(html).not.toContain("已用 / 剩余");
  });

  it("shows a positive unlimited report as 不限量, in the row and its facts", () => {
    const m = metric(CREDITS, { unlimited: true });
    expect(metricValue(m)).toEqual({ kind: "unlimited" });
    const html = row(m, true);
    expect(text(html)).toContain("不限量");
    expect(text(html)).toContain("Credits 不限量 / Unlimited");
    expect(text(html)).not.toContain("Credits —");
    expect(text(html).split("不限量 / Unlimited").length - 1).toBe(1);
    expect(html).not.toContain('class="meter');
    expect(html).not.toContain("重置 — 未知");
  });

  it("never shows the unknown credits marker beside a positive unlimited report (has_credits false)", () => {
    const html = row(metric(CREDITS, { unlimited: true, credits: null }), true);
    expect(text(html)).not.toContain("Credits —");
    expect(text(html)).toContain("Credits 不限量 / Unlimited");
  });

  it("keeps an unknown credits row honest: a dash, never zero, no quota meter or reset", () => {
    const html = row(metric(CREDITS, { state: "unknown", detail: "credits available, amount unknown" }), true);
    expect(text(html)).toContain("— 未知");
    expect(text(html)).toContain("Credits —");
    expect(html).not.toContain('class="meter');
    expect(html).not.toContain("重置 — 未知");
    expect(html).not.toContain("0 credits");
  });

  it("follows the required Codex rows on the board and keeps the demo provenance", () => {
    const codex = healthy.accounts.find((v) => v.account.provider === "codex_subscription") as AccountView;
    const ids = orderedMetrics(codex).map((r) => r.id);
    expect(ids[0]).toBe("codex.subscription.weekly");
    expect(ids.at(-1)).toBe(CREDITS);
    const credits = codex.snapshot?.metrics.find((m) => m.id === CREDITS);
    expect(credits?.source.kind).toBe("offline_demo");
    const html = board([codex]);
    expect(text(html)).toContain("Codex credits");
    expect(text(html)).toContain("42.5 credits");
    expect(text(html)).toContain("Fictional synthetic demonstration");
  });
});

describe("Claude extra usage is parse-only", () => {
  const detail = "same note";
  const extra = metric(EXTRA, {
    label: "Claude 额外用量",
    quota: quota("99.5"),
    spent: { minor: 1234, currency: "USD", exponent: 2 },
    spend_limit: { minor: 5000, currency: "USD", exponent: 2 },
    reset_at: "2026-10-28T12:30:00Z",
    detail: "spend in the current billing period; no reset time",
  });
  const claude = account("claude_subscription", [
    metric("claude.subscription.five_hour", { quota: quota("10"), detail, reset_at: "2026-10-28T15:00:00Z" }),
    metric("claude.subscription.weekly", { quota: quota("20"), detail }),
    metric("claude.subscription.fable_weekly", { quota: quota("30"), detail }),
    extra,
  ]);

  it("names exactly that one metric id", () => {
    expect([...PARSE_ONLY_METRIC_IDS]).toEqual([EXTRA]);
  });

  it("draws no row, label, amount or note on the board", () => {
    const html = board([claude]);
    expect(html).not.toContain(EXTRA);
    expect(html).not.toContain("额外用量");
    expect(html).not.toContain("12.34");
    expect(html).not.toContain("99.5");
    expect(html).not.toContain("billing period");
    expect(planRows(claude).rows.map((r) => r.id)).not.toContain(EXTRA);
  });

  it("has no header, hoisting or shared-note effect", () => {
    expect(tightestQuota([claude])?.metric.id).toBe("claude.subscription.fable_weekly");
    expect(nextReset([claude], NOW)?.metric.id).toBe("claude.subscription.five_hour");
    expect(hoistedDetail(claude)).toBe(detail);
    expect([...sharedNotes([claude, { ...claude, account: { ...claude.account, id: "b" } }]).keys()]).toEqual([detail]);
  });

  it("is removed where dashboard data enters the UI, so raw JSON never shows it", () => {
    const codex = account("codex_subscription", [metric(CREDITS, { credits: "5" })]);
    const dashboard: Dashboard = { mode: "live", server_time: "2026-10-28T12:00:00Z", accounts: [claude, codex] };
    const shown = displayDashboard(dashboard);
    expect(JSON.stringify(shown)).not.toContain(EXTRA);
    expect(shown.accounts[0]?.snapshot?.metrics.map((m) => m.id)).toEqual([
      "claude.subscription.five_hour",
      "claude.subscription.weekly",
      "claude.subscription.fable_weekly",
    ]);
    // Displayed extras and untouched accounts pass through as they are.
    expect(shown.accounts[1]).toBe(codex);
    // The wire data itself is not mutated.
    expect(dashboard.accounts[0]?.snapshot?.metrics).toHaveLength(4);
  });
});
