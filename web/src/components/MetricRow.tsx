import type { ReactNode } from "react";
import type { Metric } from "../types";
import {
  UNKNOWN,
  creditsText,
  formatMoney,
  fullLocalZoned,
  parseTime,
  percentText,
  relativeUntil,
  shortLocal,
  timeTitle,
} from "../format";
import { METRIC_LABELS, metricLabel, metricValue } from "../semantics";
import { TOTAL_BALANCE_ID, isBalanceRowId, isCreditsRowId, isQuotaRowId } from "../view";
import { Facts, type Fact } from "./Facts";
import { Meter } from "./Meter";

export interface MetricRowProps {
  id: string;
  metric: Metric | null;
  now: number;
  /** Nested under its shared pool; "last" closes the guide line. */
  branch?: "mid" | "last" | null;
  /** Older observation (stale or last known): values are dimmed, never hidden. */
  muted?: boolean;
  /** The board note for this row (planRows), or null. */
  detail?: string | null;
  /** The detail carries a balance mismatch difference. */
  mismatch?: boolean;
  expanded?: boolean;
  onToggle?: () => void;
  /** DOM id of the expanded facts, for aria-controls. */
  factsId?: string;
}

const RESET_UNKNOWN = "重置 — 未知";

interface Timing {
  /** Desktop/tablet reset cell content. */
  cell: ReactNode;
  /** Phone third-line fragment. */
  phone: ReactNode;
}

function timing(metric: Metric | null, now: number, quotaLike: boolean): Timing {
  const reset = parseTime(metric?.reset_at ?? null);
  const expiry = parseTime(metric?.expires_at ?? null);
  if (metric && reset !== null) {
    const passed = reset <= now;
    const rel = relativeUntil(reset, now);
    return {
      cell: (
        <time className="row__reset" dateTime={metric.reset_at ?? undefined} title={timeTitle(metric.reset_at, reset, "重置 ")}>
          <span className="row__reset-when">重置 {shortLocal(reset, now)}</span>
          {passed ? (
            <span className="is-warn"> · {rel}</span>
          ) : (
            <span className="row__reset-rel"> · {rel}</span>
          )}
        </time>
      ),
      phone: passed ? (
        <span className="is-warn">重置已过 · {rel}</span>
      ) : (
        <time dateTime={metric.reset_at ?? undefined} title={timeTitle(metric.reset_at, reset, "重置 ")}>
          {rel}重置
        </time>
      ),
    };
  }
  if (metric && expiry !== null) {
    return {
      cell: (
        <time className="row__reset" dateTime={metric.expires_at ?? undefined} title={timeTitle(metric.expires_at, expiry, "到期 ")}>
          <span className="row__reset-when">到期 {shortLocal(expiry, now)}</span>
          <span> · 非周期重置</span>
        </time>
      ),
      phone: (
        <time dateTime={metric.expires_at ?? undefined} title={timeTitle(metric.expires_at, expiry, "到期 ")}>
          到期 {shortLocal(expiry, now)} · 非周期重置
        </time>
      ),
    };
  }
  if (quotaLike) {
    return {
      cell: (
        <span className="row__reset row__reset--unknown">
          <span className="row__reset-when">{RESET_UNKNOWN}</span>
        </span>
      ),
      phone: <span>{RESET_UNKNOWN}</span>,
    };
  }
  return { cell: <span className="row__reset" />, phone: null };
}

function sourceText(metric: Metric): string {
  const kind = metric.source.kind === "offline_demo" ? "离线合成演示" : metric.source.kind;
  return `${kind}，契约 ${metric.source.contract}${metric.source.version_sensitive ? "（版本敏感）" : ""}`;
}

const UNLIMITED_TEXT = "不限量 / Unlimited";

function rowFacts(metric: Metric): Fact[] {
  const value = metricValue(metric);
  const q = metric.quota;
  const reset = parseTime(metric.reset_at);
  const expiry = parseTime(metric.expires_at);
  const items: Fact[] = [];
  if (value.kind === "share") {
    items.push({ label: "已用", value: percentText(value.used) });
  } else if (value.kind === "credits" || value.kind === "unlimited" || (isCreditsRowId(metric.id) && !q)) {
    // A positive unlimited report is a value, not an unknown amount: never "—" beside it.
    const credits =
      metric.credits != null ? creditsText(metric.credits) : metric.unlimited === true ? UNLIMITED_TEXT : UNKNOWN;
    items.push({ label: "Credits", value: credits });
  } else if (value.kind === "balance" || (isBalanceRowId(metric.id) && !q)) {
    items.push({ label: "余额", value: value.kind === "balance" ? formatMoney(metric.balance) : UNKNOWN });
  } else {
    items.push({ label: "已用 / 剩余", value: `${percentText(q?.used_percent)} / ${percentText(q?.remaining_percent)}` });
  }
  if (metric.unlimited === true && !items.some((f) => f.value === UNLIMITED_TEXT)) {
    items.push({ label: "上限", value: UNLIMITED_TEXT });
  }
  if (q && (q.used_count !== null || q.limit_count !== null || q.remaining_count !== null)) {
    items.push({
      label: "次数",
      value: `已用 ${q.used_count ?? UNKNOWN} / 上限 ${q.limit_count ?? UNKNOWN} / 剩余 ${q.remaining_count ?? UNKNOWN}`,
    });
  }
  items.push({ label: "重置", value: fullLocalZoned(reset) });
  items.push({ label: "重置 UTC", value: <span className="mono">{metric.reset_at ?? UNKNOWN}</span> });
  items.push({ label: "到期", value: fullLocalZoned(expiry) });
  items.push({ label: "到期 UTC", value: <span className="mono">{metric.expires_at ?? UNKNOWN}</span> });
  if (metric.shared_pool_id) items.push({ label: "共享池", value: <span className="mono">{metric.shared_pool_id}</span> });
  items.push({ label: "来源", value: sourceText(metric) });
  items.push({ label: "指标 ID", value: <span className="mono">{metric.id}</span> });
  if (metric.detail) items.push({ label: "说明", value: metric.detail, wide: true });
  return items;
}

/** A figure: tabular numerals, never truncated. */
function Fig({ text, className }: { text: string; className?: string }) {
  return <b className={`fig${className ? ` ${className}` : ""}`}>{text}</b>;
}

export function MetricRow({
  id,
  metric,
  now,
  branch = null,
  muted = false,
  detail = null,
  mismatch = false,
  expanded = false,
  onToggle,
  factsId,
}: MetricRowProps) {
  const label = metric ? metricLabel(metric) : (METRIC_LABELS[id] ?? id);
  const value = metric ? metricValue(metric) : ({ kind: "missing", text: "未知" } as const);
  const money = isBalanceRowId(id) && value.kind !== "share" && !metric?.quota;
  // Credits and "unlimited" are figures, not utilization: no meter, no reset.
  const credits =
    value.kind === "credits" || value.kind === "unlimited" || (isCreditsRowId(id) && !metric?.quota);
  const classes = ["row", `row--${value.kind}`];
  if (money) classes.push("row--money");
  if (credits) classes.push("row--figure");
  if (branch) classes.push("row--nested", `row--${branch}`);
  if (muted) classes.push("row--muted");
  if (id === TOTAL_BALANCE_ID && money) classes.push("row--total");

  let meter: ReactNode = null;
  let used: ReactNode;
  let rest: ReactNode = null;
  let sub: ReactNode[] = [];
  let counts: ReactNode = null;
  let time: Timing;

  if (value.kind === "missing" || !metric) {
    // A balance has no meter, known or not: an empty track would read as a quota.
    if (!money && !credits) meter = <Meter value={null} label={label} />;
    used = (
      <>
        <Fig text={UNKNOWN} className="fig--unknown" />
        <span className="unit"> {value.kind === "missing" ? value.text : "未知"}</span>
      </>
    );
    time = timing(metric, now, isQuotaRowId(id));
    if (time.phone) sub = [time.phone];
  } else if (value.kind === "balance") {
    const negative = !!metric.balance && metric.balance.minor < 0;
    used = <Fig text={formatMoney(metric.balance)} className={negative ? "is-error" : undefined} />;
    time = timing(metric, now, false);
    if (time.phone) sub = [time.phone];
  } else if (value.kind === "credits") {
    const text = creditsText(value.amount);
    const negative = text !== UNKNOWN && value.amount.startsWith("-");
    used = <Fig text={text} className={negative ? "is-error" : text === UNKNOWN ? "fig--unknown" : undefined} />;
    time = timing(metric, now, false);
    if (time.phone) sub = [time.phone];
  } else if (value.kind === "unlimited") {
    used = <Fig text="不限量" />;
    time = timing(metric, now, false);
    if (time.phone) sub = [time.phone];
  } else if (value.kind === "share") {
    // A product/pool share draws bar + 已用 only: no remaining, no reset.
    // Its raw reset stays in the expanded facts, as in the TUI details.
    meter = <Meter value={value.used} tone="share" muted={muted} label={label} />;
    used = (
      <>
        <Fig text={percentText(value.used)} />
        <span className="unit"> 已用</span>
      </>
    );
    time = { cell: <span className="row__reset" />, phone: null };
  } else {
    const q = metric.quota;
    meter = <Meter value={value.used} muted={muted} label={label} />;
    used = (
      <>
        <Fig text={percentText(value.used)} className={value.overage ? "is-error" : undefined} />
        <span className="unit"> 已用</span>
      </>
    );
    const remaining = (
      <span className="row__rem">
        剩余 <span className="num">{percentText(value.remaining)}</span>
      </span>
    );
    const over = value.overage ? (
      <span className="row__over">
        <span className="row__over-word">超额 </span>+{value.overage}%
      </span>
    ) : null;
    rest = (
      <>
        {remaining}
        {over}
      </>
    );
    time = timing(metric, now, true);
    sub = [remaining, time.phone];
    if (over) sub.push(over);
    if (value.counts && q) {
      counts = (
        <span className="row__counts">
          次数 已用 <span className="num">{q.used_count ?? UNKNOWN}</span> / 上限{" "}
          <span className="num">{q.limit_count ?? UNKNOWN}</span> / 剩余{" "}
          <span className="num">{q.remaining_count ?? UNKNOWN}</span>
        </span>
      );
    }
  }
  sub = sub.filter(Boolean);

  return (
    <li className={classes.join(" ")}>
      <button
        type="button"
        className="row__hit"
        aria-expanded={expanded}
        aria-controls={expanded && factsId ? factsId : undefined}
        onClick={onToggle}
      >
        <span className="row__label" title={metric?.label ?? id}>
          {label}
        </span>
        <span className="row__meter">{meter}</span>
        <span className="row__used">{used}</span>
        <span className="row__rest">{rest}</span>
        {time.cell}
        {sub.length ? (
          <span className="row__sub">
            {sub.map((part, i) => (
              <span key={i}>
                {i ? " · " : null}
                {part}
              </span>
            ))}
          </span>
        ) : null}
        {counts}
      </button>
      {detail && !expanded ? (
        <p className={`row__detail${mismatch ? " row__detail--mismatch" : ""}`}>{detail}</p>
      ) : null}
      {expanded && metric ? <Facts className="row__facts" id={factsId} items={rowFacts(metric)} /> : null}
      {expanded && !metric ? (
        <Facts
          className="row__facts"
          id={factsId}
          items={[
            { label: "指标 ID", value: <span className="mono">{id}</span> },
            { label: "说明", value: "这次读取没有返回这一项，当前值未知，不代表 0。", wide: true },
          ]}
        />
      ) : null}
    </li>
  );
}
