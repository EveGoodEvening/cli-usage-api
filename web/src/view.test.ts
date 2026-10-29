import { describe, expect, it } from "vitest";
import type { AccountView, Dashboard, Metric } from "./types";
import fixture from "./mock/demo-dashboard.json";
import { hoistedDetail } from "./semantics";
import { GROK_MISSING_DETAIL, TOTAL_BALANCE_ID, accountNote, planRows, sharedNotes } from "./view";

const errors = fixture.errors as unknown as Dashboard;
const byLabel = (label: string) => errors.accounts.find((a) => a.account.label.includes(label)) as AccountView;

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
    ...overrides,
  };
}

function view(provider: AccountView["account"]["provider"], metrics: Metric[], code: string | null = null): AccountView {
  return {
    account: { id: "a", provider, label: "A", enabled: true, credential_kind: null, poll_interval_seconds: 60 },
    snapshot: {
      account_id: "a",
      metrics,
      grants: [],
      fetch_state: code === "balance_mismatch" ? "ok" : "partial",
      attempted_at: "2026-10-28T12:00:00Z",
      fetched_at: "2026-10-28T12:00:00Z",
      retry_at: null,
      diagnostic: code ? { code, message: "m" } : null,
      organization_id: null,
    },
    freshness: null,
  };
}

const quota = { used_percent: "10", remaining_percent: "90", used_count: null, limit_count: null, remaining_count: null };

describe("planRows", () => {
  it("shows a repeated row detail once, as the group note", () => {
    const v = byLabel("unknown Fable");
    const { rows, groupNote } = planRows(v);
    expect(groupNote).toBe("Fictional synthetic demonstration; not live account data.");
    for (const row of rows) {
      expect(row.detail).not.toBe(groupNote);
    }
    // The single missing-row explanation stays on its row.
    expect(rows.find((r) => r.id === "claude.subscription.fable_weekly")?.detail).toBe(
      "Synthetic missing or malformed field; current value unknown, never zero.",
    );
  });

  it("collapses repeated missing-row details on hand-built views", () => {
    const repeated = "missing, never zero";
    const v = view("codex_subscription", [
      metric("codex.subscription.weekly", { state: "unknown", detail: repeated }),
      metric("codex.subscription.five_hour", { state: "unknown", detail: repeated }),
      metric("codex.subscription.extra", { quota, detail: "other" }),
    ]);
    const { rows, groupNote } = planRows(v);
    expect(groupNote).toBe(repeated);
    expect(rows.filter((r) => r.detail).map((r) => r.id)).toEqual(["codex.subscription.extra"]);
  });

  it("strips only Grok's generic missing sentence from unknown rows", () => {
    const period = "Server period: weekly.";
    const v = view("grok_subscription", [
      metric("grok.subscription.shared_pool", { state: "unknown", detail: `${GROK_MISSING_DETAIL} ${period}` }),
      metric("grok.product.build", { state: "unknown", detail: GROK_MISSING_DETAIL }),
      metric("grok.product.chat", { share_percent: "3", detail: "Reported consumption share: 3%." }),
    ]);
    const { rows, groupNote } = planRows(v);
    expect(groupNote).toBeNull();
    expect(rows.find((r) => r.id === "grok.subscription.shared_pool")?.detail).toBe(period);
    expect(rows.find((r) => r.id === "grok.product.build")?.detail).toBeNull();
    expect(rows.find((r) => r.id === "grok.product.chat")?.detail).toBeNull();
    for (const v2 of errors.accounts) {
      for (const row of planRows(v2).rows) expect(row.detail ?? "").not.toContain(GROK_MISSING_DETAIL);
    }
  });

  it("never repeats the hoisted note on rows", () => {
    for (const v of errors.accounts) {
      const hoisted = hoistedDetail(v);
      if (!hoisted) continue;
      const { rows, groupNote } = planRows(v);
      expect(groupNote).not.toBe(hoisted);
      for (const row of rows) {
        expect(row.detail).not.toBe(hoisted);
      }
    }
  });

  it("keeps the balance mismatch difference on the total row", () => {
    const money = { minor: 100, currency: "USD", exponent: 2 };
    const detail = "Total differs by 0.01 USD";
    const v = view(
      "claude_platform",
      [
        metric("claude.platform.purchased_balance", { balance: money, detail }),
        metric("claude.platform.promotional_balance", { balance: money, detail }),
        metric("claude.platform.total_balance", { balance: money, detail }),
      ],
      "balance_mismatch",
    );
    const { rows } = planRows(v);
    expect(rows.find((r) => r.id === "claude.platform.total_balance")?.detail).toBe(detail);
  });

  it("hoists offline-demo provenance for a healthy Console account", () => {
    const healthy = fixture.healthy as unknown as Dashboard;
    const platform = healthy.accounts.find((a) => a.account.provider === "claude_platform") as AccountView;
    expect(hoistedDetail(platform)).toBeNull();
    expect(accountNote(platform)).toBe("Fictional synthetic demonstration; not live account data.");
    expect(planRows(platform).rows.every((r) => r.detail === null)).toBe(true);
    const live = view("claude_platform", [
      metric("claude.platform.total_balance", { balance: { minor: 1, currency: "USD", exponent: 2 }, detail: "x" }),
    ]);
    expect(accountNote(live)).toBeNull();
  });
});

describe("sharedNotes", () => {
  it("counts notes repeated by two or more accounts only", () => {
    const a = view("claude_subscription", [metric("claude.subscription.five_hour", { state: "unknown", detail: "same" })]);
    const b = { ...a, account: { ...a.account, id: "b" } };
    expect(sharedNotes([a])).toEqual(new Map());
    expect(sharedNotes([a, b])).toEqual(new Map([["same", 2]]));
  });

  it("never shares a balance mismatch difference", () => {
    const total = metric(TOTAL_BALANCE_ID, { balance: { minor: 100, exponent: 2, currency: "USD" }, detail: "diff" });
    const a = view("claude_platform", [total], "balance_mismatch");
    const b = { ...a, account: { ...a.account, id: "b" } };
    expect(sharedNotes([a, b]).has("diff")).toBe(false);
  });
});
