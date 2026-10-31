import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { AccountView, Dashboard, Metric } from "../types";
import fixture from "../mock/demo-dashboard.json";
import css from "../styles.css?raw";
import { accountNote, sharedNotes } from "../view";
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

function nodes(html: string): string[] {
  return [...html.matchAll(/>([^<]+)</g)].map((m) => (m[1] ?? "").replace(/^ · /, "").trim());
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

  it("states a diagnostic message that already starts with its label only once", () => {
    const money = { minor: 1451, currency: "USD", exponent: 2 };
    const source = { kind: "private_http", contract: "c", version_sensitive: false } as const;
    const view = single("claude_platform", [
      metric("claude.platform.total_balance", { source, balance: money, detail: "总额 − 明细合计 = 0.01 USD" }),
    ]);
    view.snapshot!.diagnostic = { code: "balance_mismatch", message: "余额明细与总额不一致；差额见总余额详情。" };
    const html = board([view]);
    expect(html).toContain('<p class="group__diag"><span class="is-warn">余额明细与总额不一致；差额见总余额详情。</span></p>');
    const plain = text(html);
    expect(plain.split("余额明细与总额不一致").length - 1).toBe(1);
    // Once per breakpoint: the desktop reset cell and the phone sub line, never an extra row.
    expect(plain.split("总额 − 明细合计 = 0.01 USD").length - 1).toBe(2);
    expect(html).toContain('class="row__reset row__reset--mismatch"');
    expect(html).toContain('<span class="is-warn">总额 − 明细合计 = 0.01 USD</span>');
    expect(html).not.toContain("row__detail");
  });

  it("keeps the label for a diagnostic message that does not repeat it", () => {
    const view = single("claude_platform", [metric("claude.platform.total_balance", {})], "partial");
    view.snapshot!.diagnostic = { code: "partial_data", message: "Some values are unavailable." };
    expect(board([view])).toMatch(/<b class="is-[a-z]+">部分数据缺失<\/b> — <span>Some values are unavailable\.<\/span>/);
  });

  it("states a note repeated across accounts once, above the groups", () => {
    for (const data of [healthy, errors]) {
      const html = board(data.accounts);
      const plain = text(html);
      const shared = sharedNotes(data.accounts);
      expect(shared.size).toBeGreaterThan(0);
      for (const [note, n] of shared) {
        // Exact text nodes: one shared note can contain another as a substring.
        expect(nodes(html).filter((t) => t === note)).toHaveLength(1);
        expect(plain).toContain(`${note} · ${n} 个账号`);
      }
      const parts = groups(html);
      data.accounts.forEach((view, i) => {
        const hoisted = accountNote(view);
        if (!hoisted || shared.has(hoisted)) return;
        expect(parts[i] ?? "").toMatch(new RegExp(`class="group__sub">[^<]*${hoisted.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`));
      });
    }
  });

  it("keeps a lone account's note on its own subline", () => {
    const view = healthy.accounts.find((v) => accountNote(v)) as AccountView;
    const note = accountNote(view) as string;
    const html = board([view]);
    expect(html).not.toContain("board__notes");
    expect(html.split('class="group__sub">')[1]?.split("</p>")[0]).toContain(note);
  });

  it("keeps demo provenance visible for every Console account", () => {
    const provenance = "Fictional synthetic demonstration; not live account data.";
    expect(text(board(healthy.accounts))).toContain(provenance);
    const consoleOnly = healthy.accounts.filter((v) => v.account.provider === "claude_platform");
    expect(consoleOnly.length).toBeGreaterThan(0);
    expect(text(board(consoleOnly))).toContain(provenance);
  });

  it("puts a balance figure in the meter's place on wider screens", () => {
    expect(css).toMatch(/\.row--money \.row__used[^{]*\{[^}]*grid-column: meter \/ rest/);
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
