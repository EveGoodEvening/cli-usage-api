import type { Metric } from "../types";
import {
  UNKNOWN,
  formatMoney,
  fullLocal,
  parseTime,
  percentText,
  relativeUntil,
  shortLocal,
} from "../format";
import { METRIC_LABELS, metricLabel, metricValue } from "../semantics";
import { Meter } from "./Meter";

export interface MetricRowProps {
  id: string;
  metric: Metric | null;
  now: number;
  /** Nested under its shared pool; "last" draws the closing branch. */
  branch?: "mid" | "last" | null;
  /** Older observation (stale or last known): values are dimmed, never hidden. */
  muted?: boolean;
  showDetail?: boolean;
  expanded?: boolean;
}

function ResetCell({ metric, now, quota }: { metric: Metric; now: number; quota: boolean }) {
  const reset = parseTime(metric.reset_at);
  const expiry = parseTime(metric.expires_at);
  if (reset !== null) {
    return (
      <span className="row__reset" title={`重置 ${fullLocal(reset)}（UTC ${metric.reset_at}）`}>
        <span className="row__reset-when">重置 {shortLocal(reset, now)}</span>
        <span className="row__reset-rel">{relativeUntil(reset, now)}</span>
      </span>
    );
  }
  if (expiry !== null) {
    return (
      <span className="row__reset" title={`到期 ${fullLocal(expiry)}（UTC ${metric.expires_at}）`}>
        <span className="row__reset-when">到期 {shortLocal(expiry, now)}</span>
        <span className="row__reset-rel">非周期重置</span>
      </span>
    );
  }
  if (quota) {
    return (
      <span className="row__reset row__reset--unknown">
        <span className="row__reset-when">重置 — 未知</span>
      </span>
    );
  }
  return null;
}

export function MetricRow({ id, metric, now, branch = null, muted = false, showDetail = false, expanded = false }: MetricRowProps) {
  const label = metric ? metricLabel(metric) : (METRIC_LABELS[id] ?? id);
  const value = metric ? metricValue(metric) : { kind: "missing" as const, text: "未知" };
  const classes = ["row", `row--${value.kind}`];
  if (branch) classes.push("row--nested", `row--${branch}`);
  if (muted) classes.push("row--muted");

  let meter = null;
  let figures = null;
  if (value.kind === "missing" || !metric) {
    meter = <Meter value={null} label={label} />;
    figures = (
      <span className="row__figures">
        <span className="fig fig--unknown">{UNKNOWN}</span>
        <span className="row__note">{value.kind === "missing" ? value.text : "未知"}</span>
      </span>
    );
  } else if (value.kind === "balance") {
    figures = (
      <span className="row__figures row__figures--money">
        <span className={`fig fig--money${metric.balance && metric.balance.minor < 0 ? " fig--negative" : ""}`}>
          {formatMoney(metric.balance)}
        </span>
        <span className="row__note">余额</span>
      </span>
    );
  } else if (value.kind === "share") {
    meter = <Meter value={value.used} tone="share" muted={muted} label={label} />;
    figures = (
      <span className="row__figures">
        <span className="fig">已用 {percentText(value.used)}</span>
      </span>
    );
  } else {
    const q = metric.quota;
    meter = <Meter value={value.used} muted={muted} label={label} />;
    figures = (
      <span className="row__figures">
        <span className="fig">已用 {percentText(value.used)}</span>
        <span className="fig fig--soft">剩余 {percentText(value.remaining)}</span>
        {value.overage ? <span className="chip chip--error">超额 +{value.overage}%</span> : null}
        {value.counts && q ? (
          <span className="row__note">
            次数 已用 {q.used_count ?? UNKNOWN} / 上限 {q.limit_count ?? UNKNOWN} / 剩余 {q.remaining_count ?? UNKNOWN}
          </span>
        ) : null}
      </span>
    );
  }

  const showsDetail = metric?.detail && (showDetail || value.kind === "missing");
  return (
    <li className={classes.join(" ")}>
      <span className="row__label">
        {branch ? <span className="row__branch" aria-hidden="true" /> : null}
        <span className="row__name" title={metric?.label ?? id}>
          {label}
        </span>
      </span>
      <span className="row__meter">{meter}</span>
      {figures}
      {metric && value.kind !== "share" ? (
        <ResetCell metric={metric} now={now} quota={value.kind === "quota"} />
      ) : (
        // A product/pool share draws bar + 已用 only: no remaining, no reset.
        // Its raw reset stays in the expanded facts, as in the TUI details.
        <span className="row__reset" />
      )}
      {showsDetail ? <p className="row__detail">{metric?.detail}</p> : null}
      {expanded && metric ? (
        <dl className="row__facts">
          <div>
            <dt>指标 ID</dt>
            <dd>{metric.id}</dd>
          </div>
          <div>
            <dt>来源</dt>
            <dd>
              {metric.source.kind === "offline_demo" ? "离线合成演示" : metric.source.kind}，契约 {metric.source.contract}
              {metric.source.version_sensitive ? "（版本敏感）" : ""}
            </dd>
          </div>
          <div>
            <dt>重置 UTC</dt>
            <dd>{metric.reset_at ?? UNKNOWN}</dd>
          </div>
          <div>
            <dt>到期 UTC</dt>
            <dd>{metric.expires_at ?? UNKNOWN}</dd>
          </div>
          {metric.shared_pool_id ? (
            <div>
              <dt>共享池</dt>
              <dd>{metric.shared_pool_id}</dd>
            </div>
          ) : null}
          {metric.detail ? (
            <div className="row__facts-wide">
              <dt>说明</dt>
              <dd>{metric.detail}</dd>
            </div>
          ) : null}
        </dl>
      ) : null}
    </li>
  );
}
