// Optional provider extras: Codex credits are displayed (rounded to 2 dp); OpenAI
// Platform exact money shows at cents with a rounding note; Claude prepaid
// credits are a money balance; Claude extra usage is parse-only (published by
// the API, deliberately never shown by this UI).
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { AccountView, Dashboard, Metric } from "./types";
import fixture from "./mock/demo-dashboard.json";
import { Board } from "./components/Board";
import { MetricRow } from "./components/MetricRow";
import {
  ROUNDED_NOTE,
  creditsText,
  exactMoneyCents,
  exactMoneyText,
  fixedPointText,
  roundTwoDecimals,
} from "./format";
import {
  PARSE_ONLY_METRIC_IDS,
  PROVIDER_ORDER,
  REQUIRED_METRICS,
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
  it("fixed point keeps the exact value: no exponent, no rounding, sign kept", () => {
    expect(fixedPointText("42.5")).toBe("42.5");
    expect(fixedPointText("1E+3")).toBe("1000");
    expect(fixedPointText("1.5E-7")).toBe("0.00000015");
    expect(fixedPointText("0E-7")).toBe("0.0000000");
    expect(fixedPointText("-12.340")).toBe("-12.340");
    expect(fixedPointText("-0")).toBe("-0");
    expect(fixedPointText("1234567890123456789012345678901234567890")).toBe(
      "1234567890123456789012345678901234567890",
    );
  });

  it("credits round half-even to two decimals, always two decimals", () => {
    expect(creditsText("7")).toBe("7.00 credits");
    expect(creditsText("137.5")).toBe("137.50 credits");
    expect(creditsText("1E+3")).toBe("1,000.00 credits");
    expect(creditsText("2.675")).toBe("2.68 credits");
    expect(creditsText("0.125")).toBe("0.12 credits");
    expect(creditsText("0.135")).toBe("0.14 credits");
    expect(creditsText("0.0050000001")).toBe("0.01 credits");
    expect(creditsText("1.5E-7")).toBe("0.00 credits");
    expect(creditsText("-12.345")).toBe("-12.34 credits");
    // Python's Decimal.quantize keeps the sign of a tiny negative amount.
    expect(creditsText("-0.001")).toBe("-0.00 credits");
    expect(creditsText("1234567890123456789012345678901234567.895")).toBe(
      "1,234,567,890,123,456,789,012,345,678,901,234,567.90 credits",
    );
  });

  it("groups integer digits with commas, like domain.format_two_decimals", () => {
    expect(creditsText("12345.5")).toBe("12,345.50 credits");
    expect(creditsText("999.995")).toBe("1,000.00 credits");
    expect(creditsText("1234567.891")).toBe("1,234,567.89 credits");
    expect(creditsText("0.5")).toBe("0.50 credits");
    expect(creditsText("999.99")).toBe("999.99 credits");
    expect(creditsText("-1234.5")).toBe("-1,234.50 credits");
    expect(creditsText("1E+21")).toBe("1,000,000,000,000,000,000,000.00 credits");
    expect(roundTwoDecimals("12345.675")).toEqual({ text: "12,345.68", changed: true });
  });

  it("reports whether rounding changed the value", () => {
    expect(roundTwoDecimals("3.07")).toEqual({ text: "3.07", changed: false });
    expect(roundTwoDecimals("3.0700")).toEqual({ text: "3.07", changed: false });
    expect(roundTwoDecimals("3.0700000000000003")).toEqual({ text: "3.07", changed: true });
    expect(roundTwoDecimals("4.9")).toEqual({ text: "4.90", changed: false });
    expect(roundTwoDecimals("17.3715455")).toEqual({ text: "17.37", changed: true });
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
    expect(text(html)).toContain("1,000.00 credits");
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
    expect(text(html)).toContain("Codex credits 余额");
    expect(text(html)).toContain("42.50 credits");
    // The data keeps the exact value; only the display rounds.
    expect(codex.snapshot?.metrics.find((m) => m.id === CREDITS)?.credits).toBe("42.5");
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

describe("OpenAI Platform exact money", () => {
  const AVAILABLE = "openai.platform.available_balance";
  const PAID = "openai.platform.paid_available_balance";
  const usd = (amount: string) => ({ amount, currency: "USD" });

  it("is a provider with one required balance row", () => {
    expect(PROVIDER_ORDER).toContain("openai_platform");
    expect(REQUIRED_METRICS.openai_platform).toEqual([AVAILABLE]);
  });

  it("rounds half-even to cents and says whether that changed the value", () => {
    expect(exactMoneyCents(usd("3.0700000000000003"))).toEqual({ text: "3.07 USD", changed: true });
    expect(exactMoneyCents(usd("4.9"))).toEqual({ text: "4.90 USD", changed: false });
    expect(exactMoneyCents(usd("0.125"))).toEqual({ text: "0.12 USD", changed: true });
    expect(exactMoneyCents(usd("-1.005"))).toEqual({ text: "-1.00 USD", changed: true });
    expect(exactMoneyText(usd("1.5E-7"))).toBe("0.00000015 USD");
    expect(exactMoneyCents(usd("-1234567.891"))).toEqual({ text: "-1,234,567.89 USD", changed: true });
    expect(exactMoneyText(usd("1234567890.005"))).toBe("1,234,567,890.005 USD");
    for (const junk of [null, usd("NaN"), usd("1e"), { amount: "1", currency: "usd" }]) {
      expect(exactMoneyCents(junk)).toBeNull();
      expect(exactMoneyText(junk)).toBe("—");
    }
  });

  it("shows cents as a money figure with the rounding note; facts keep the exact amount", () => {
    const m = metric(AVAILABLE, { exact_balance: usd("17.3715455") });
    expect(metricValue(m)).toEqual({ kind: "exact", text: "17.37 USD", changed: true, negative: false });
    const view = account("openai_platform", [m]);
    const plan = planRows(view);
    expect(plan.rows[0]?.detail).toBe(ROUNDED_NOTE);
    const html = board([view]);
    expect(text(html)).toContain("OpenAI 可用余额");
    expect(text(html)).toContain("17.37 USD");
    expect(text(html)).toContain(ROUNDED_NOTE);
    expect(html).not.toContain("17.3715455");
    expect(html).not.toContain('class="meter');
    expect(html).not.toContain("重置");
    expect(html).toContain("row--money");
    const facts = text(row(m, true));
    expect(facts).toContain("余额 17.37 USD");
    expect(facts).toContain("精确金额 17.3715455 USD");
  });

  it("adds no note when the amount is already whole cents", () => {
    const view = account("openai_platform", [metric(AVAILABLE, { exact_balance: usd("4.9") })]);
    expect(planRows(view).rows[0]?.detail).toBeNull();
    const html = board([view]);
    expect(text(html)).toContain("4.90 USD");
    expect(html).not.toContain(ROUNDED_NOTE);
  });

  it("states a repeated rounding note once and keeps another detail beside it", () => {
    const view = account("openai_platform", [
      metric(AVAILABLE, { exact_balance: usd("4.905"), detail: "granted 23.0, used 3.07" }),
      metric(PAID, { exact_balance: usd("1.001") }),
    ]);
    const { rows } = planRows(view);
    expect(rows.map((r) => r.id)).toEqual([AVAILABLE, PAID]);
    expect(rows[0]?.detail).toBe(`granted 23.0, used 3.07 · ${ROUNDED_NOTE}`);
    expect(rows[1]?.detail).toBe(ROUNDED_NOTE);
    const html = board([view]);
    expect(text(html)).toContain("4.90 USD");
    expect(text(html)).toContain("1.00 USD");
    expect(text(html)).toContain("OpenAI 付费余额");
  });

  it("marks a negative balance and never turns an unknown balance into zero", () => {
    expect(metricValue(metric(AVAILABLE, { exact_balance: usd("-0.5") }))).toMatchObject({ negative: true });
    const unknown = account("openai_platform", []);
    const html = board([unknown]);
    expect(text(html)).toContain("OpenAI 可用余额");
    expect(text(html)).toContain("— 未知");
    expect(html).not.toContain("0.00 USD");
    expect(html).not.toContain('class="meter');
    expect(html).not.toContain("重置 — 未知");
  });
});

describe("Claude prepaid credits balance", () => {
  const ID = "claude.subscription.credit_balance";
  const usage = [
    metric("claude.subscription.five_hour", { quota: quota("10") }),
    metric("claude.subscription.weekly", { quota: quota("20") }),
    metric("claude.subscription.fable_weekly", { quota: quota("30") }),
  ];

  it("is a money row after the required Claude rows, not a quota or parse-only", () => {
    const view = account("claude_subscription", [
      ...usage,
      metric(ID, { balance: { minor: 2550, currency: "USD", exponent: 2 }, detail: "auto-reload off" }),
    ]);
    expect(PARSE_ONLY_METRIC_IDS.has(ID)).toBe(false);
    expect(REQUIRED_METRICS.claude_subscription).not.toContain(ID);
    expect(orderedMetrics(view).map((r) => r.id).at(-1)).toBe(ID);
    const html = board([view]);
    expect(text(html)).toContain("Claude credits 余额");
    expect(text(html)).toContain("25.50 USD");
    expect(text(html)).toContain("auto-reload off");
    expect(tightestQuota([view])?.metric.id).toBe("claude.subscription.fable_weekly");
  });

  it("an unknown credits balance has no meter, no reset placeholder and no zero", () => {
    const html = row(metric(ID, { state: "unknown", detail: "no billing permission" }));
    expect(text(html)).toContain("— 未知");
    expect(html).not.toContain('class="meter');
    expect(html).not.toContain("重置");
    expect(html).not.toContain("0.00");
    expect(html).toContain("row--money");
  });

  it("is absent when no organization is selected: no row is invented", () => {
    const view = account("claude_subscription", usage);
    expect(orderedMetrics(view).map((r) => r.id)).not.toContain(ID);
  });
});
