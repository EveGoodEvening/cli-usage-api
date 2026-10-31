import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import css from "../styles.css?raw";
import type { Metric } from "../types";
import { MetricRow } from "./MetricRow";

const NOW = Date.parse("2026-10-28T12:00:00Z");
const RESET = "2026-10-28T14:00:00Z";

function metric(overrides: Partial<Metric>): Metric {
  return {
    id: "grok.product.build",
    label: "GrokBuild",
    state: "ready",
    source: { kind: "private_http", contract: "test", version_sensitive: false },
    quota: null,
    balance: null,
    reset_at: null,
    expires_at: null,
    shared_pool_id: "pool-1",
    detail: null,
    share_percent: null,
    ...overrides,
  };
}

function render(m: Metric, expanded = false): string {
  return renderToStaticMarkup(createElement(MetricRow, { id: m.id, metric: m, now: NOW, branch: "mid", expanded }));
}

function text(html: string): string {
  return html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");
}

describe("MetricRow product share", () => {
  it("draws bar + 已用 only, never a reset or remaining, even when reset_at is present", () => {
    const html = render(metric({ share_percent: "30", reset_at: RESET, expires_at: "2026-11-01T00:00:00Z" }));
    expect(text(html)).toContain("30% 已用");
    expect(html).not.toContain("重置");
    expect(html).not.toContain("到期");
    expect(html).not.toContain("剩余");
    expect(html).not.toContain("row__reset-when");
  });

  it("keeps the raw reset in the expanded facts, like the TUI details", () => {
    const html = render(metric({ share_percent: "30", reset_at: RESET }), true);
    expect(text(html)).toContain("重置 UTC");
    expect(html).toContain(RESET);
    expect(html).not.toContain("row__reset-when");
  });

  it("still shows the reset on an ordinary quota row", () => {
    const html = render(
      metric({
        id: "claude.subscription.weekly",
        shared_pool_id: null,
        reset_at: RESET,
        quota: { used_percent: "40", remaining_percent: "60", used_count: null, limit_count: null, remaining_count: null },
      }),
    );
    expect(html).toContain("row__reset-when");
    expect(text(html)).toContain("剩余 60%");
  });

  // Tablet hides .row__reset-rel; meaning-bearing qualifiers must sit outside it.
  const outsideRel = (html: string) => html.replace(/<span class="row__reset-rel">.*?<\/span>/g, "");

  it("keeps a passed reset's 等待刷新 outside the tablet-hidden countdown", () => {
    const html = render(
      metric({
        id: "claude.subscription.weekly",
        shared_pool_id: null,
        reset_at: "2026-10-28T11:00:00Z",
        quota: { used_percent: "40", remaining_percent: "60", used_count: null, limit_count: null, remaining_count: null },
      }),
    );
    expect(text(outsideRel(html))).toContain("等待刷新");
  });

  it("keeps the expiry outside the tablet-hidden countdown and shows no reset on an expiry row", () => {
    const html = render(
      metric({
        id: "claude.subscription.weekly",
        shared_pool_id: null,
        expires_at: "2026-10-31T12:00:00Z",
        quota: { used_percent: "40", remaining_percent: "60", used_count: null, limit_count: null, remaining_count: null },
      }),
    );
    const shown = text(outsideRel(html));
    expect(shown).toContain("到期");
    expect(shown).not.toContain("重置");
  });

  it("labels an unknown Console balance as a balance, not a quota", () => {
    const html = render(
      metric({ id: "claude.platform.purchased_balance", label: "Purchased", shared_pool_id: null, state: "unknown" }),
      true,
    );
    expect(text(html)).toContain("余额 —");
    expect(html).not.toContain("已用 / 剩余");
    expect(html).not.toContain(`class="meter`);
  });
});

describe("MetricRow overage", () => {
  it("names the overage as 超额 at every width, never a bare +x% next to 剩余", () => {
    const html = render(
      metric({
        id: "claude.subscription.weekly",
        shared_pool_id: null,
        reset_at: RESET,
        quota: { used_percent: "110.25", remaining_percent: "0", used_count: null, limit_count: null, remaining_count: null },
      }),
    );
    expect(text(html)).toContain("超额 +10.25%");
    // No rule at any breakpoint may hide the overage word or its container.
    const hidden = [...css.matchAll(/([^{}]+)\{[^{}]*display:\s*none[^{}]*\}/g)].map((m) => m[1]);
    for (const selectors of hidden) {
      expect(selectors).not.toMatch(/\.row__over(-word)?(?![\w-])/);
    }
  });
});

describe("MetricRow balance mismatch", () => {
  const DIFF = "总额 − 明细合计 = -0.01 USD";
  const total = (overrides: Partial<Metric> = {}) =>
    metric({
      id: "claude.platform.total_balance",
      label: "Claude Platform 总余额",
      shared_pool_id: null,
      balance: { minor: 1451, currency: "USD", exponent: 2 },
      detail: DIFF,
      ...overrides,
    });
  const renderTotal = (m: Metric, expanded = false) =>
    renderToStaticMarkup(createElement(MetricRow, { id: m.id, metric: m, now: NOW, detail: DIFF, mismatch: true, expanded }));
  const cell = (html: string) => /<span class="row__reset row__reset--mismatch"[^>]*>(.*?)<\/span><span class="row__sub">/.exec(html);

  it("puts the difference in the total row's reset cell, not a separate line", () => {
    const html = renderTotal(total());
    expect(html).not.toContain("row__detail");
    const found = cell(html);
    expect(found).not.toBeNull();
    expect(html).toContain(`title="${DIFF}"`);
    // The signed amount sits outside the ellipsizing lead; the flex gap supplies the space.
    expect(found![1] ?? "").toBe(
      '<span class="row__reset-what">总额 − 明细合计 =</span><span class="num">-0.01 USD</span>',
    );
    expect(html.split("row__sub")[1]).toContain(`<span class="is-warn">${DIFF}</span>`);
  });

  it("keeps a displaced expiry in the title, phone line and facts", () => {
    const html = renderTotal(total({ expires_at: "2026-11-01T00:00:00Z" }));
    expect(cell(html)).not.toBeNull();
    expect(html).toMatch(new RegExp(`title="${DIFF} · 到期 [^"]+"`));
    expect(text(html.split('class="row__sub"')[1] ?? "")).toContain("到期");
    const open = renderTotal(total({ expires_at: "2026-11-01T00:00:00Z" }), true);
    const facts = open.split('class="facts row__facts"')[1] ?? "";
    expect(facts).toContain("2026-11-01T00:00:00Z");
    expect(text(facts)).toContain(DIFF);
  });

  it("keeps the amount unclipped and the phone line visible in the stylesheet", () => {
    expect(css).toMatch(/\.row__reset--mismatch \.num \{ flex: none; \}/);
    expect(css).toMatch(/\.row__reset--mismatch \{[^}]*column-gap: 0\.25em;[^}]*contain: inline-size;/);
    const phone = css.split("@media (max-width: 639px)")[1] ?? "";
    expect(phone).toMatch(/\.row__sub \{ display: block;/);
  });

  it("leaves an ordinary row note as its own line", () => {
    const m = total({ detail: "note" });
    const html = renderToStaticMarkup(createElement(MetricRow, { id: m.id, metric: m, now: NOW, detail: "note" }));
    expect(html).toContain('<p class="row__detail">note</p>');
    expect(html).not.toContain("row__reset--mismatch");
  });
});
