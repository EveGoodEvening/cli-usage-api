import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
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

describe("MetricRow product share", () => {
  it("draws bar + 已用 only, never a reset or remaining, even when reset_at is present", () => {
    const html = render(metric({ share_percent: "30", reset_at: RESET, expires_at: "2026-11-01T00:00:00Z" }));
    expect(html).toContain("已用 30%");
    expect(html).not.toContain("重置");
    expect(html).not.toContain("到期");
    expect(html).not.toContain("剩余");
    expect(html).not.toContain("row__reset-when");
  });

  it("keeps the raw reset in the expanded facts, like the TUI details", () => {
    const html = render(metric({ share_percent: "30", reset_at: RESET }), true);
    expect(html).toContain("重置 UTC");
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
    expect(html).toContain("剩余 60%");
  });
});
