import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { AccountView, Dashboard, Metric } from "../types";
import fixture from "../mock/demo-dashboard.json";
import css from "../styles.css?raw";
import { accountNote } from "../view";
import { Board } from "./Board";
import { DemoBadge, DemoStrip } from "./Header";

const healthy = fixture.healthy as unknown as Dashboard;
const errors = fixture.errors as unknown as Dashboard;
const NOW = Date.parse("2026-10-28T12:01:00Z");

function board(views: AccountView[]): string {
  return renderToStaticMarkup(createElement(Board, { views, all: views, now: NOW }));
}

function text(html: string): string {
  return html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");
}

function groups(html: string): string[] {
  return html.split('<section class="group').slice(1);
}

function rule(source: string, selector: string): string {
  const match = new RegExp(`(?:^|\\n)${selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*\\{([^}]*)\\}`).exec(source);
  return match?.[1] ?? "";
}

function single(provider: AccountView["account"]["provider"], metrics: Metric[], fetch: "ok" | "partial" = "ok"): AccountView {
  return {
    account: { id: "x", provider, label: "X", enabled: true, credential_kind: null, poll_interval_seconds: 60 },
    snapshot: {
      account_id: "x",
      metrics,
      grants: [],
      fetch_state: fetch,
      attempted_at: "2026-10-28T12:00:00Z",
      fetched_at: "2026-10-28T12:00:00Z",
      retry_at: null,
      diagnostic: null,
      organization_id: null,
    },
    freshness: null,
  };
}

function metric(id: string, overrides: Partial<Metric>): Metric {
  return {
    id,
    label: id,
    state: "ready",
    source: { kind: "offline_demo", contract: "c", version_sensitive: false },
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

describe("Board", () => {
  it("renders the demo badge and strip for demo mode", () => {
    expect(text(renderToStaticMarkup(createElement(DemoBadge)))).toContain("演示 · 合成数据");
    expect(text(renderToStaticMarkup(createElement(DemoStrip)))).toContain("离线合成演示");
  });

  it("shows the hoisted synthetic note once per account subline", () => {
    const html = board(healthy.accounts);
    const parts = groups(html);
    expect(parts).toHaveLength(healthy.accounts.length);
    healthy.accounts.forEach((view, i) => {
      const hoisted = accountNote(view);
      if (!hoisted) return;
      const part = parts[i] ?? "";
      expect(part.split(hoisted).length - 1).toBe(1);
      expect(part).toMatch(new RegExp(`class="group__sub">[^<]*${hoisted.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`));
    });
  });

  it("keeps demo provenance on a healthy Console account's subline", () => {
    const parts = groups(board(healthy.accounts));
    const i = healthy.accounts.findIndex((v) => v.account.provider === "claude_platform");
    expect(i).toBeGreaterThanOrEqual(0);
    const sub = (parts[i] ?? "").split('class="group__sub">')[1]?.split("</p>")[0] ?? "";
    expect(sub).toContain("Fictional synthetic demonstration; not live account data.");
  });

  it("draws no meter on an unknown balance row", () => {
    const html = board(errors.accounts);
    const rows = html.split("<li").filter((li) => li.includes("row--money"));
    expect(rows.length).toBeGreaterThan(0);
    for (const li of rows) expect(li.split("</li>")[0]).not.toContain(`class="meter`);
  });

  it("keeps last success and last attempt apart on an errored head", () => {
    const html = board(errors.accounts);
    const head = groups(html)
      .map((g) => g.split('class="group__sub"')[0] ?? "")
      .find((g) => g.includes("network failure"));
    expect(text(head ?? "")).toContain("成功");
    expect(text(head ?? "")).toContain("尝试");
  });

  it("never shows 0 grants for an incomplete Platform snapshot", () => {
    const platform = errors.accounts.filter((v) => v.account.provider === "claude_platform");
    const t = text(board(platform));
    expect(t).not.toMatch(/赠款 0/);
    expect(t).toMatch(/赠款 (—|≥\d+)/);
  });

  it("reads 重置 — 未知 for a READY quota without reset", () => {
    const v = single("claude_subscription", [
      metric("claude.subscription.weekly", {
        quota: { used_percent: "20", remaining_percent: "80", used_count: null, limit_count: null, remaining_count: null },
      }),
    ]);
    expect(text(board([v]))).toContain("重置 — 未知");
  });

  it("labels a non-unified Grok aggregate 汇总, with no remaining, reset or nesting", () => {
    const v = single("grok_subscription", [
      metric("grok.subscription.shared_pool", { share_percent: "40", reset_at: "2026-10-29T12:00:00Z" }),
      metric("grok.product.build", { share_percent: "30", shared_pool_id: "pool" }),
    ]);
    const html = board([v]);
    const row = html.split("<li").find((li) => li.includes("Grok 汇总")) ?? "";
    expect(row).toContain("Grok 汇总");
    expect(text(row)).not.toContain("剩余");
    expect(text(row)).not.toContain("重置");
    expect(html).not.toContain("row--nested");
    expect(html).not.toContain("共享池");
  });

  it("never truncates figures", () => {
    expect(rule(css, ".row__used")).toMatch(/white-space:\s*nowrap/);
  });
});
