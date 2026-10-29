// Domain meaning shared by every view. Mirrors src/cli_usage_api/app.py where the
// TUI already settled a rule (labels, Grok aggregate naming, nesting, hoisting).

import type { AccountView, FetchState, Metric, ProviderId, Snapshot } from "./types";
import { overagePercent, parseTime } from "./format";

export const METRIC_LABELS: Record<string, string> = {
  "claude.subscription.five_hour": "Claude 5h 用量",
  "claude.subscription.weekly": "Claude 每周用量",
  "claude.subscription.fable_weekly": "Claude Fable 每周用量",
  "claude.platform.purchased_balance": "购买余额",
  "claude.platform.promotional_balance": "赠送余额",
  "claude.platform.total_balance": "总余额",
  "codex.subscription.weekly": "Codex weekly (7d)",
  "codex.subscription.five_hour": "Codex 5h",
  "grok.subscription.shared_pool": "Grok 共享池",
  "grok.product.build": "GrokBuild",
  "grok.product.chat": "GrokChat",
};

/** Required rows per provider, in display order (domain.REQUIRED_METRIC_IDS). */
export const REQUIRED_METRICS: Record<ProviderId, string[]> = {
  claude_subscription: [
    "claude.subscription.five_hour",
    "claude.subscription.weekly",
    "claude.subscription.fable_weekly",
  ],
  claude_platform: [
    "claude.platform.purchased_balance",
    "claude.platform.promotional_balance",
    "claude.platform.total_balance",
  ],
  codex_subscription: ["codex.subscription.weekly"],
  grok_subscription: [
    "grok.subscription.shared_pool",
    "grok.product.build",
    "grok.product.chat",
  ],
};

export const PROVIDERS: Record<ProviderId, { name: string; short: string; mark: string }> = {
  claude_subscription: { name: "Claude 订阅", short: "Claude", mark: "Cl" },
  claude_platform: { name: "Claude Platform", short: "Platform", mark: "Pl" },
  codex_subscription: { name: "Codex 订阅", short: "Codex", mark: "Cx" },
  grok_subscription: { name: "Grok 订阅", short: "Grok", mark: "Gk" },
};

export const PROVIDER_ORDER: ProviderId[] = [
  "claude_subscription",
  "claude_platform",
  "codex_subscription",
  "grok_subscription",
];

export function providerInfo(provider: string) {
  return (
    PROVIDERS[provider as ProviderId] ?? { name: provider, short: provider, mark: provider.slice(0, 2) }
  );
}

export const STATE_LABELS: Record<FetchState, string> = {
  ok: "正常",
  partial: "部分数据",
  unconfigured: "未配置",
  auth_required: "需要重新连接",
  permission_denied: "权限不足",
  rate_limited: "限流",
  network_error: "网络错误",
  provider_error: "服务错误",
  schema_error: "数据格式错误",
  upstream_contract_missing: "阻塞：上游契约缺失",
};

export function stateLabel(state: string): string {
  return STATE_LABELS[state as FetchState] ?? state;
}

export const CREDENTIAL_LABELS: Record<string, string> = {
  claude_code_file: "Claude Code 登录文件",
  grok_auth_file: "Grok 登录文件",
  codex_auth_file: "Codex 登录文件",
  console_session: "Console 会话",
  manual_bearer: "手动令牌",
  api_key: "API key",
};

export const DIAGNOSTIC_LABELS: Record<string, string> = {
  credential_unavailable: "凭据不可用",
  credential_expired: "凭据已过期",
  credential_mismatch: "凭据类型不匹配",
  unsafe_credential_file: "凭据文件不安全",
  credential_selection_required: "需要选择凭据",
  secure_store_unavailable: "安全存储不可用",
  organization_selection_required: "需要选择组织",
  forbidden_request: "请求不在允许范围",
  auth_required: "需要重新连接",
  permission_denied: "权限不足",
  rate_limited: "限流",
  network_error: "网络错误",
  provider_error: "服务错误",
  schema_error: "数据格式错误",
  response_too_large: "响应过大",
  partial_data: "部分数据缺失",
  balance_mismatch: "余额明细与总额不一致",
  unconfigured: "未配置",
  upstream_contract_missing: "上游契约缺失",
  invalid_config: "配置无效",
};

export function diagnosticLabel(code: string): string {
  return DIAGNOSTIC_LABELS[code] ?? code;
}

/** An aggregate without proven pool semantics is not labelled a shared pool. */
export function metricLabel(metric: Metric): string {
  if (metric.id === "grok.subscription.shared_pool" && metric.share_percent !== null) {
    return "Grok 汇总";
  }
  return METRIC_LABELS[metric.id] ?? metric.label;
}

export type MetricValue =
  | { kind: "missing"; text: string }
  | { kind: "balance" }
  | { kind: "share"; used: string }
  | { kind: "quota"; used: string | null; remaining: string | null; overage: string | null; counts: boolean };

const STATE_TEXT: Record<string, string> = {
  unknown: "未知",
  blocked: "阻塞",
  not_applicable: "不适用",
};

/** What a row can honestly show. Absent values are never turned into zero. */
export function metricValue(metric: Metric): MetricValue {
  if (metric.state !== "ready") {
    return { kind: "missing", text: STATE_TEXT[metric.state] ?? "未知" };
  }
  if (metric.balance) return { kind: "balance" };
  if (metric.share_percent !== null) return { kind: "share", used: metric.share_percent };
  const quota = metric.quota;
  if (quota) {
    const counts =
      quota.used_count !== null || quota.limit_count !== null || quota.remaining_count !== null;
    if (quota.used_percent !== null || quota.remaining_percent !== null || counts) {
      return {
        kind: "quota",
        used: quota.used_percent,
        remaining: quota.remaining_percent,
        overage: overagePercent(quota.used_percent),
        counts,
      };
    }
  }
  return { kind: "missing", text: "未知" };
}

/** Product rows that belong under a quota row of the same pool (TUI _nesting). */
export function nestedMetricIds(metrics: Metric[]): Set<string> {
  const pools = new Set<string>();
  const nested = new Set<string>();
  for (const metric of metrics) {
    if (metric.quota) {
      pools.add(metric.id);
      if (metric.shared_pool_id) pools.add(metric.shared_pool_id);
    } else if (metric.shared_pool_id && pools.has(metric.shared_pool_id)) {
      nested.add(metric.id);
    }
  }
  return nested;
}

/** Rows to show: required ids first (unknown if absent), then provider extras. */
export function orderedMetrics(view: AccountView): Array<{ id: string; metric: Metric | null }> {
  const metrics = view.snapshot?.metrics ?? [];
  const byId = new Map(metrics.map((m) => [m.id, m]));
  const required = REQUIRED_METRICS[view.account.provider] ?? [];
  const rows = required.map((id) => ({ id, metric: byId.get(id) ?? null }));
  for (const metric of metrics) {
    if (!required.includes(metric.id)) rows.push({ id: metric.id, metric });
  }
  return rows;
}

/** One shared explanation for every metric is shown once, at the account level. */
export function hoistedDetail(view: AccountView): string | null {
  const snapshot = view.snapshot;
  if (!snapshot || snapshot.metrics.length === 0) return null;
  if (
    view.account.provider === "claude_platform" &&
    snapshot.metrics.some((m) => m.state === "ready" && m.balance)
  ) {
    return null;
  }
  const details = new Set(snapshot.metrics.map((m) => m.detail));
  if (details.size !== 1) return null;
  const [only] = details;
  return only ?? null;
}

/** Grant count honesty: an incomplete Console fetch is "≥N" or "—", never 0. */
export function grantCountLabel(snapshot: Snapshot | null): string {
  if (!snapshot) return "—";
  const n = snapshot.grants.length;
  if (snapshot.fetch_state === "ok") return String(n);
  return n > 0 ? `≥${n}` : "—";
}

export type Health = "ok" | "warn" | "error" | "idle";

export function accountHealth(view: AccountView): Health {
  if (!view.account.enabled) return "idle";
  const snapshot = view.snapshot;
  if (!snapshot) return "idle";
  if (snapshot.fetch_state === "ok") {
    return view.freshness?.stale || snapshot.diagnostic ? "warn" : "ok";
  }
  if (snapshot.fetch_state === "partial" || view.freshness?.last_known) return "warn";
  return "error";
}

export function healthText(view: AccountView): string {
  if (!view.account.enabled) return "已禁用";
  const snapshot = view.snapshot;
  if (!snapshot) return "等待首次观察";
  const parts = [stateLabel(snapshot.fetch_state)];
  if (view.freshness?.last_known) parts.push("上次已知");
  else if (view.freshness?.stale) parts.push("已过期");
  return parts.join("，");
}

export interface Tightest {
  view: AccountView;
  metric: Metric;
  used: string;
}

/** Highest reported used percentage among ready quota rows (not product shares). */
export function tightestQuota(views: AccountView[]): Tightest | null {
  let best: Tightest | null = null;
  let bestValue = -1;
  for (const view of views) {
    for (const metric of view.snapshot?.metrics ?? []) {
      const used = metric.state === "ready" ? metric.quota?.used_percent : null;
      if (!used) continue;
      const n = Number(used);
      if (Number.isFinite(n) && n > bestValue) {
        bestValue = n;
        best = { view, metric, used };
      }
    }
  }
  return best;
}

export interface NextReset {
  view: AccountView;
  metric: Metric;
  at: number;
}

export function nextReset(views: AccountView[], now: number): NextReset | null {
  let best: NextReset | null = null;
  for (const view of views) {
    for (const metric of view.snapshot?.metrics ?? []) {
      const at = metric.state === "ready" ? parseTime(metric.reset_at) : null;
      if (at === null || at <= now) continue;
      if (!best || at < best.at) best = { view, metric, at };
    }
  }
  return best;
}
