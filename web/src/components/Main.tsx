import type { ReactNode } from "react";
import type { AccountView, Dashboard, Grant } from "../types";
import {
  UNKNOWN,
  formatMoney,
  formatMoneyAmount,
  fullLocal,
  parseTime,
  relativeAge,
  relativeUntil,
  shortLocal,
} from "../format";
import {
  accountHealth,
  grantCountLabel,
  metricLabel,
  nextReset,
  providerInfo,
  stateLabel,
  tightestQuota,
} from "../semantics";
import { AccountBlock } from "./AccountBlock";
import { Meter } from "./Meter";

export type Tab = "overview" | "metrics" | "grants" | "raw";

export const TABS: Array<{ id: Tab; label: string }> = [
  { id: "overview", label: "概览" },
  { id: "metrics", label: "指标" },
  { id: "grants", label: "赠款" },
  { id: "raw", label: "原始 JSON" },
];

interface MainProps {
  dashboard: Dashboard;
  views: AccountView[];
  selected: AccountView | null;
  tab: Tab;
  now: number;
  onReload: () => void;
  onDiagnostics: () => void;
  loading: boolean;
}

function Card({ label, children, foot }: { label: string; children: ReactNode; foot?: ReactNode }) {
  return (
    <article className="card">
      <h3 className="card__label">{label}</h3>
      <div className="card__body">{children}</div>
      {foot ? <p className="card__foot">{foot}</p> : null}
    </article>
  );
}

function SummaryCards({ views, now, single }: { views: AccountView[]; now: number; single: AccountView | null }) {
  const tight = tightestQuota(views);
  const next = nextReset(views, now);
  const platformTotal =
    single?.account.provider === "claude_platform"
      ? single.snapshot?.metrics.find((m) => m.id === "claude.platform.total_balance") ?? null
      : null;

  const first = platformTotal ? (
    <Card
      label="总余额"
      foot={platformTotal.state === "ready" ? "余额没有周期重置" : "当前值未知，不按 0 计算"}
    >
      {platformTotal.state === "ready" && platformTotal.balance ? (
        <p className="big">
          <span className={platformTotal.balance.minor < 0 ? "fig--negative" : undefined}>
            {formatMoneyAmount(platformTotal.balance)}
          </span>
          <small>{platformTotal.balance.currency}</small>
        </p>
      ) : (
        <p className="big big--unknown">{UNKNOWN}</p>
      )}
    </Card>
  ) : (
    <Card
      label="用量最高的额度"
      foot={tight ? `${metricLabel(tight.metric)}${single ? "" : `，${tight.view.account.label}`}` : "没有可用的百分比额度"}
    >
      {tight ? (
        <>
          <p className="big">
            {tight.used}
            <small>% 已用</small>
          </p>
          <Meter value={tight.used} label={metricLabel(tight.metric)} />
        </>
      ) : (
        <p className="big big--unknown">{UNKNOWN}</p>
      )}
    </Card>
  );

  const second =
    single?.account.provider === "claude_platform" ? (
      <Card label="赠款" foot={single.snapshot?.fetch_state === "ok" ? "来自本次完整读取" : "读取不完整，数量为下限"}>
        <p className="big">{grantCountLabel(single.snapshot)}</p>
      </Card>
    ) : (
      <Card
        label="下一次重置"
        foot={next ? `${metricLabel(next.metric)}，${shortLocal(next.at, now)}` : "没有已知的未来重置时间"}
      >
        <p className={`big big--text${next ? "" : " big--unknown"}`}>{next ? relativeUntil(next.at, now) : UNKNOWN}</p>
      </Card>
    );

  let third;
  if (single) {
    const snapshot = single.snapshot;
    const fetched = parseTime(snapshot?.fetched_at ?? null);
    third = (
      <Card
        label="读取状态"
        foot={fetched === null ? "还没有成功的观察" : `上次成功 ${relativeAge(fetched, now)}`}
      >
        <p className={`big big--state big--${accountHealth(single)}`}>
          {!single.account.enabled ? "已禁用" : snapshot ? stateLabel(snapshot.fetch_state) : "等待中"}
        </p>
      </Card>
    );
  } else {
    const counts = { ok: 0, warn: 0, error: 0, idle: 0 };
    for (const view of views) counts[accountHealth(view)] += 1;
    third = (
      <Card label="账号状态" foot={`共 ${views.length} 个账号${counts.idle ? `，${counts.idle} 个等待或禁用` : ""}`}>
        <p className="tally">
          <span className="tally__ok">
            <b>{counts.ok}</b> 正常
          </span>
          <span className="tally__warn">
            <b>{counts.warn}</b> 留意
          </span>
          <span className="tally__error">
            <b>{counts.error}</b> 异常
          </span>
        </p>
      </Card>
    );
  }

  return (
    <div className="cards">
      {first}
      {second}
      {third}
    </div>
  );
}

function Callout({
  mode,
  views,
  onReload,
  onDiagnostics,
  loading,
}: {
  mode: Dashboard["mode"];
  views: AccountView[];
  onReload: () => void;
  onDiagnostics: () => void;
  loading: boolean;
}) {
  const broken = views.filter((v) => accountHealth(v) === "error").length;
  if (broken) {
    return (
      <aside className="callout callout--error">
        <div>
          <h3>{broken} 个账号读取失败</h3>
          <p>
            这里只读，不能修改账号。到运行 usage api serve 的服务器上，用官方 CLI 重新登录或用 usage
            重新连接账号，然后重启服务。
          </p>
        </div>
        <button type="button" className="button" onClick={onDiagnostics}>
          查看诊断
        </button>
      </aside>
    );
  }
  if (mode === "demo") {
    return (
      <aside className="callout callout--demo">
        <div>
          <h3>你在看离线合成演示</h3>
          <p>这些数字来自内置的虚构样例，不代表任何真实账号，也不能证明实时额度可用。</p>
        </div>
        <button type="button" className="button" onClick={onReload} disabled={loading}>
          {loading ? "读取中" : "重新读取"}
        </button>
      </aside>
    );
  }
  return (
    <aside className="callout">
      <div>
        <h3>数据每 15 秒自动读取</h3>
        <p>页面读取服务器保存的最新观察；服务器按各账号的轮询间隔访问上游，不会因为这里刷新而加快。</p>
      </div>
      <button type="button" className="button" onClick={onReload} disabled={loading}>
        {loading ? "读取中" : "立即重新读取"}
      </button>
    </aside>
  );
}

function GrantRow({ grant, now }: { grant: Grant; now: number }) {
  const expiry = parseTime(grant.expires_at);
  const expired = expiry !== null && expiry <= now;
  return (
    <tr className={expired ? "is-expired" : undefined}>
      <td>{grant.category === "purchased" ? "购买" : grant.category === "promotional" ? "赠送" : grant.category}</td>
      <td className="cell-text">
        {grant.name ?? UNKNOWN}
        {grant.program_id ? <small>{grant.program_id}</small> : null}
      </td>
      <td className="num">{formatMoney(grant.granted)}</td>
      <td className="num">{formatMoney(grant.remaining)}</td>
      <td>
        {expiry === null ? (
          <span className="muted">到期未知</span>
        ) : (
          <span title={`UTC ${grant.expires_at}`}>
            {fullLocal(expiry)}
            <small>{expired ? "已过期，不计入当前余额" : `${relativeUntil(expiry, now)}，非周期重置`}</small>
          </span>
        )}
      </td>
    </tr>
  );
}

function Grants({ views, now }: { views: AccountView[]; now: number }) {
  const platform = views.filter((v) => v.account.provider === "claude_platform");
  if (platform.length === 0) {
    return <p className="empty">只有 Claude Platform 账号有赠款记录。当前选择里没有这类账号。</p>;
  }
  return (
    <div className="grants">
      {platform.map((view) => (
        <section key={view.account.id} className="grants__account">
          <h3>
            {view.account.label}
            <span className="muted">赠款 {grantCountLabel(view.snapshot)}</span>
          </h3>
          {view.snapshot && view.snapshot.grants.length > 0 ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th scope="col">类别</th>
                    <th scope="col">名称</th>
                    <th scope="col" className="num">
                      授予
                    </th>
                    <th scope="col" className="num">
                      剩余
                    </th>
                    <th scope="col">到期</th>
                  </tr>
                </thead>
                <tbody>
                  {view.snapshot.grants.map((grant, i) => (
                    <GrantRow key={grant.id ?? i} grant={grant} now={now} />
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="empty">
              {view.snapshot?.fetch_state === "ok"
                ? "完整读取显示没有赠款。"
                : "这次读取不完整，赠款数量未知，不代表没有赠款。"}
            </p>
          )}
          {view.snapshot?.grants.some((g) => g.expires_at === null) ? (
            <p className="footnote">到期未知的赠款按当前值计入余额，但它们何时失效并不确定。</p>
          ) : null}
        </section>
      ))}
    </div>
  );
}

export function Main({ dashboard, views, selected, tab, now, onReload, onDiagnostics, loading }: MainProps) {
  const scope = selected ? [selected] : views;
  const title = selected ? selected.account.label : "全部账号";
  const subtitle = selected
    ? `${providerInfo(selected.account.provider).name}，每 ${selected.account.poll_interval_seconds} 秒轮询`
    : `${views.length} 个账号的订阅额度、余额与读取状态`;

  return (
    <div className="main__inner">
      <header className="main__title">
        <h1>{title}</h1>
        <p>{subtitle}</p>
      </header>

      {tab === "overview" ? (
        <>
          <SummaryCards views={scope} now={now} single={selected} />
          <section className="section" aria-label="用量">
            <h2 className="section__title">用量</h2>
            {scope.length === 0 ? (
              <p className="empty">服务器还没有配置账号。在服务器上添加账号后重启 usage api serve。</p>
            ) : (
              scope.map((view) => <AccountBlock key={view.account.id} view={view} now={now} heading={!selected} />)
            )}
          </section>
          <Callout
            mode={dashboard.mode}
            views={scope}
            onReload={onReload}
            onDiagnostics={onDiagnostics}
            loading={loading}
          />
        </>
      ) : null}

      {tab === "metrics" ? (
        <section className="section" aria-label="指标详情">
          {scope.map((view) => (
            <AccountBlock key={view.account.id} view={view} now={now} expanded />
          ))}
        </section>
      ) : null}

      {tab === "grants" ? <Grants views={scope} now={now} /> : null}

      {tab === "raw" ? (
        <section className="section" aria-label="原始 JSON">
          <p className="footnote">
            API 原样返回的数据。百分比是精确小数字符串，金额是最小货币单位整数，时间是 UTC。
          </p>
          <pre className="raw">{JSON.stringify(selected ?? { ...dashboard, accounts: views }, null, 2)}</pre>
        </section>
      ) : null}
    </div>
  );
}
