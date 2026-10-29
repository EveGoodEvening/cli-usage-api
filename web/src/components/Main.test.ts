import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Dashboard } from "../types";
import fixture from "../mock/demo-dashboard.json";
import css from "../styles.css?raw";
import { Main } from "./Main";

const dashboard = fixture.healthy as unknown as Dashboard;
// 1 h 59 min before the fixture's earliest reset (claude five_hour, 14:00 UTC).
const NOW = Date.parse("2026-10-28T12:01:00Z");

function renderOverview(): string {
  return renderToStaticMarkup(
    createElement(Main, {
      dashboard,
      views: dashboard.accounts,
      selected: null,
      tab: "overview",
      now: NOW,
      onReload: () => undefined,
      onDiagnostics: () => undefined,
      loading: false,
    }),
  );
}

function rule(css: string, selector: string): string {
  const match = new RegExp(`(?:^|\\n)${selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*\\{([^}]*)\\}`).exec(css);
  return match?.[1] ?? "";
}

describe("next-reset summary card", () => {
  it("renders the relative reset as one unbreakable, width-scaled value", () => {
    const html = renderOverview();
    expect(html).toContain('<p class="big big--text">1小时59分后</p>');
  });

  it("styles worded values to stay on one line, sized from the card width", () => {
    const text = rule(css, ".big--text");
    expect(text).toMatch(/white-space:\s*nowrap/);
    expect(text).toMatch(/overflow-wrap:\s*normal/);
    expect(text).toMatch(/font-size:\s*clamp\(\s*16px,\s*14cqi,\s*36px\s*\)/);
    expect(rule(css, ".card")).toMatch(/container:\s*card\s*\/\s*inline-size/);
  });
});
