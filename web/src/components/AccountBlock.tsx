import type { AccountView } from "../types";
import { parseTime, relativeAge, relativeUntil } from "../format";
import {
  accountHealth,
  diagnosticLabel,
  hoistedDetail,
  nestedMetricIds,
  orderedMetrics,
  providerInfo,
  stateLabel,
} from "../semantics";
import { MetricRow } from "./MetricRow";

export function ProviderMark({ provider, size = "md" }: { provider: string; size?: "sm" | "md" | "lg" }) {
  const info = providerInfo(provider);
  return (
    <span className={`mark mark--${provider} mark--${size}`} aria-hidden="true">
      {info.mark}
    </span>
  );
}

export function StatusChips({ view, now }: { view: AccountView; now: number }) {
  const snapshot = view.snapshot;
  if (!view.account.enabled) return <span className="chip chip--idle">已禁用，不轮询</span>;
  if (!snapshot) return <span className="chip chip--idle">等待首次观察</span>;
  const health = accountHealth(view);
  const fetched = parseTime(snapshot.fetched_at);
  const retry = parseTime(snapshot.retry_at);
  return (
    <span className="chips">
      <span className={`chip chip--${health}`}>{stateLabel(snapshot.fetch_state)}</span>
      {view.freshness?.last_known ? <span className="chip chip--warn">上次已知</span> : null}
      {view.freshness?.stale ? <span className="chip chip--warn">已过期</span> : null}
      {view.freshness?.reset_passed ? <span className="chip chip--warn">重置已过，等待刷新</span> : null}
      <span className="chip chip--plain">
        {fetched === null ? "从未成功" : `成功 ${relativeAge(fetched, now)}`}
      </span>
      {retry !== null ? <span className="chip chip--plain">重试 {relativeUntil(retry, now, true)}</span> : null}
    </span>
  );
}

export function AccountBlock({
  view,
  now,
  expanded = false,
  heading = true,
}: {
  view: AccountView;
  now: number;
  expanded?: boolean;
  heading?: boolean;
}) {
  const snapshot = view.snapshot;
  const rows = orderedMetrics(view);
  const nested = nestedMetricIds(rows.flatMap((r) => (r.metric ? [r.metric] : [])));
  const nestedOrder = rows.filter((r) => nested.has(r.id)).map((r) => r.id);
  const hoisted = hoistedDetail(view);
  const muted = !!view.freshness && (view.freshness.stale || view.freshness.last_known);
  const grok = view.account.provider === "grok_subscription";
  return (
    <section className="account" aria-label={view.account.label}>
      {heading ? (
        <header className="account__head">
          <ProviderMark provider={view.account.provider} />
          <div className="account__title">
            <h3>{view.account.label}</h3>
            <p>{providerInfo(view.account.provider).name}</p>
          </div>
          <StatusChips view={view} now={now} />
        </header>
      ) : null}
      {snapshot?.diagnostic ? (
        <p className={`account__diag account__diag--${accountHealth(view)}`}>
          <strong>{diagnosticLabel(snapshot.diagnostic.code)}</strong>
          <span>{snapshot.diagnostic.message}</span>
        </p>
      ) : null}
      {hoisted && !expanded ? <p className="account__note">{hoisted}</p> : null}
      {!view.account.enabled ? (
        <p className="account__empty">账号已禁用，服务器不会轮询它。</p>
      ) : !snapshot ? (
        <p className="account__empty">服务器尚未完成首次读取。数据到达后会自动出现。</p>
      ) : (
        <ul className="rows">
          {rows.map(({ id, metric }) => {
            const index = nestedOrder.indexOf(id);
            const branch = index < 0 ? null : index === nestedOrder.length - 1 ? "last" : "mid";
            // Numeric Grok rows carry no per-row explanation; unknown rows always do.
            // A balance mismatch keeps its exact difference visible on the total row.
            const mismatch =
              snapshot.diagnostic?.code === "balance_mismatch" && id === "claude.platform.total_balance";
            const showDetail =
              expanded || mismatch || (!hoisted && !grok && view.account.provider !== "claude_platform");
            return (
              <MetricRow
                key={id}
                id={id}
                metric={metric}
                now={now}
                branch={branch}
                muted={muted}
                showDetail={showDetail}
                expanded={expanded}
              />
            );
          })}
        </ul>
      )}
    </section>
  );
}
