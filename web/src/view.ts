// Pure view planning for an account group: which rows explain themselves and
// which repeated explanation is shown once for the whole group.

import type { AccountView, Metric } from "./types";
import { hoistedDetail, metricValue, nestedMetricIds, orderedMetrics } from "./semantics";

export const TOTAL_BALANCE_ID = "claude.platform.total_balance";

/** The Grok provider's generic missing-usage sentence (providers/grok.py MISSING_DETAIL). */
export const GROK_MISSING_DETAIL = "Usage is unavailable in this response; missing does not mean zero.";

export interface RowPlan {
  id: string;
  metric: Metric | null;
  branch: "mid" | "last" | null;
  /** The row note shown on the board, or null. The full detail stays in the expanded facts. */
  detail: string | null;
}

/** Subscription quota rows whose reset is part of their meaning. */
export function isQuotaRowId(id: string): boolean {
  return id.startsWith("claude.subscription.") || id.startsWith("codex.subscription.");
}

/** Console money rows: a balance, never a percentage quota, even when unknown. */
export function isBalanceRowId(id: string): boolean {
  return id.startsWith("claude.platform.") && id.endsWith("_balance");
}

/**
 * The once-per-account note for the group subline. It is `hoistedDetail`, plus
 * the offline-demo provenance of a Console snapshot (which `hoistedDetail`
 * declines once a balance is ready) when every metric carries that same note.
 */
export function accountNote(view: AccountView): string | null {
  const hoisted = hoistedDetail(view);
  if (hoisted) return hoisted;
  const metrics = view.snapshot?.metrics ?? [];
  if (view.account.provider !== "claude_platform" || metrics.length === 0) return null;
  if (!metrics.every((m) => m.source.kind === "offline_demo")) return null;
  const details = new Set(metrics.map((m) => m.detail));
  if (details.size !== 1) return null;
  const [only] = details;
  return only ?? null;
}

export function planRows(view: AccountView): { rows: RowPlan[]; groupNote: string | null } {
  const snapshot = view.snapshot;
  const ordered = orderedMetrics(view);
  const nested = nestedMetricIds(ordered.flatMap((r) => (r.metric ? [r.metric] : [])));
  const nestedOrder = ordered.filter((r) => nested.has(r.id)).map((r) => r.id);
  const hoisted = accountNote(view);
  const provider = view.account.provider;
  const grok = provider === "grok_subscription";
  const mismatch = snapshot?.diagnostic?.code === "balance_mismatch";
  const base = !hoisted && !grok && provider !== "claude_platform";

  const keep = new Set<string>();
  const rows: RowPlan[] = ordered.map(({ id, metric }) => {
    const index = nestedOrder.indexOf(id);
    const branch = index < 0 ? null : index === nestedOrder.length - 1 ? "last" : "mid";
    let detail = metric?.detail ?? null;
    if (detail && mismatch && id === TOTAL_BALANCE_ID) {
      // The exact signed difference stays on the total row.
      keep.add(id);
    } else if (detail) {
      const missing = !metric || metricValue(metric).kind === "missing";
      // Grok's 未知 placeholder already says "missing is not zero"; any other
      // note (server period, non-unified caveat) still shows, as in the TUI.
      if (grok && missing) detail = detail.replace(GROK_MISSING_DETAIL, "").trim() || null;
      if (!(base || missing) || detail === hoisted) detail = null;
    }
    return { id, metric, branch, detail };
  });

  const counts = new Map<string, number>();
  for (const row of rows) {
    if (row.detail && !keep.has(row.id)) counts.set(row.detail, (counts.get(row.detail) ?? 0) + 1);
  }
  let groupNote: string | null = null;
  for (const [text, n] of counts) {
    if (n >= 2) {
      groupNote = text;
      break;
    }
  }
  if (groupNote !== null) {
    for (const row of rows) {
      if (!keep.has(row.id) && row.detail === groupNote) row.detail = null;
    }
  }
  return { rows, groupNote };
}
