import type { AccountView } from "../types";
import { UNKNOWN, barFill, parseTime, relativeAge, relativeUntil, severity } from "../format";
import {
  PROVIDER_ORDER,
  accountHealth,
  diagnosticLabel,
  metricLabel,
  providerInfo,
  stateLabel,
} from "../semantics";

/** Concentric arcs: one ring per ready quota row, drawn to its (clamped) used share. */
function Dial({ views }: { views: AccountView[] }) {
  const rings = views
    .flatMap((view) =>
      (view.snapshot?.metrics ?? [])
        .filter((m) => m.state === "ready" && m.quota?.used_percent != null)
        .map((m) => ({ view, metric: m, used: m.quota?.used_percent ?? "0" })),
    )
    .slice(0, 6);
  const size = 168;
  const c = size / 2;
  return (
    <figure className="dial">
      <svg viewBox={`0 0 ${size} ${size}`} role="img" aria-label="各额度已用比例">
        {rings.length === 0 ? (
          <circle cx={c} cy={c} r={60} className="dial__track dial__track--empty" />
        ) : (
          rings.map((ring, i) => {
            const r = 74 - i * 11;
            const length = 2 * Math.PI * r;
            const fill = barFill(ring.used) / 100;
            const health = severity(ring.used);
            return (
              <g key={`${ring.view.account.id}-${ring.metric.id}`}>
                <circle cx={c} cy={c} r={r} className="dial__track" />
                <circle
                  cx={c}
                  cy={c}
                  r={r}
                  className={`dial__arc dial__arc--${health}`}
                  strokeDasharray={`${fill * length} ${length}`}
                  transform={`rotate(-90 ${c} ${c})`}
                >
                  <title>{`${metricLabel(ring.metric)}：已用 ${ring.used}%`}</title>
                </circle>
              </g>
            );
          })
        )}
      </svg>
      <figcaption>
        {rings.length === 0
          ? "没有可绘制的百分比额度"
          : `由外到内：${rings.map((r) => `${metricLabel(r.metric)} ${r.used}%`).join("，")}`}
      </figcaption>
    </figure>
  );
}

export function RightBar({
  views,
  selected,
  now,
  receivedAt,
  clientNow,
}: {
  views: AccountView[];
  selected: AccountView | null;
  now: number;
  receivedAt: number | null;
  clientNow: number;
}) {
  const scope = selected ? [selected] : views;
  const fetchedTimes = scope
    .map((v) => parseTime(v.snapshot?.fetched_at ?? null))
    .filter((t): t is number => t !== null);
  const oldest = fetchedTimes.length ? Math.min(...fetchedTimes) : null;
  const retries = scope
    .map((v) => parseTime(v.snapshot?.retry_at ?? null))
    .filter((t): t is number => t !== null && t > now);
  const nextRetry = retries.length ? Math.min(...retries) : null;
  const diagnostics = scope.filter((v) => v.snapshot?.diagnostic);
  const present = PROVIDER_ORDER.filter((p) => views.some((v) => v.account.provider === p));

  return (
    <aside className="rightbar" aria-label="摘要">
      <section className="panel">
        <h2 className="panel__title">新鲜度</h2>
        <ul className="bullets">
          <li>
            <span>页面读取</span>
            <b>{receivedAt === null ? UNKNOWN : relativeAge(receivedAt, clientNow)}</b>
          </li>
          <li>
            <span>{selected ? "上次成功观察" : "最旧的成功观察"}</span>
            <b>{oldest === null ? UNKNOWN : relativeAge(oldest, now)}</b>
          </li>
          <li>
            <span>下次重试</span>
            <b>{nextRetry === null ? "无" : relativeUntil(nextRetry, now, true)}</b>
          </li>
        </ul>
      </section>

      <section className="panel panel--visual">
        <Dial views={scope} />
      </section>

      <section className="panel">
        <h2 className="panel__title">读取状态</h2>
        <ul className="bullets bullets--status">
          {scope.slice(0, 6).map((view) => (
            <li key={view.account.id}>
              <span className={`dot dot--${accountHealth(view)}`} aria-hidden="true" />
              <span className="bullets__text" title={view.account.label}>
                {selected ? "当前账号" : view.account.label}
              </span>
              <b>{view.snapshot ? stateLabel(view.snapshot.fetch_state) : view.account.enabled ? "等待" : "禁用"}</b>
            </li>
          ))}
          {scope.length > 6 ? <li className="muted">另有 {scope.length - 6} 个账号</li> : null}
        </ul>
        {diagnostics.length ? (
          <ul className="diag-list">
            {diagnostics.slice(0, 3).map((v) => (
              <li key={v.account.id}>
                <b>{diagnosticLabel(v.snapshot?.diagnostic?.code ?? "")}</b>
                <span>{v.snapshot?.diagnostic?.message}</span>
              </li>
            ))}
          </ul>
        ) : null}
      </section>

      <section className="panel">
        <h2 className="panel__title">服务</h2>
        <ul className="bullets">
          {present.map((p) => (
            <li key={p}>
              <span className={`mark mark--${p} mark--sm`} aria-hidden="true">
                {providerInfo(p).mark}
              </span>
              <span className="bullets__text">{providerInfo(p).name}</span>
              <b>{views.filter((v) => v.account.provider === p).length}</b>
            </li>
          ))}
        </ul>
      </section>
    </aside>
  );
}
