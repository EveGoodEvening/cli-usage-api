import { useEffect, useMemo, useState } from "react";
import type { UsageClient } from "../api";
import type { ApiError } from "../api";
import type { ThemeChoice } from "../auth";
import type { AccountView, SessionInfo } from "../types";
import { UNKNOWN, fullLocal, parseTime, relativeUntil } from "../format";
import { useDashboard, useTick } from "../hooks";
import { CREDENTIAL_LABELS, accountHealth, diagnosticLabel, providerInfo, stateLabel } from "../semantics";
import { AccountBlock, ProviderMark } from "./AccountBlock";
import { Main, TABS, type Tab } from "./Main";
import { RightBar } from "./RightBar";
import { Sidebar, type ProviderFilter } from "./Sidebar";
import {
  AccountsIcon,
  CloseIcon,
  GaugeIcon,
  MenuIcon,
  MoonIcon,
  PulseIcon,
  RefreshIcon,
  SlidersIcon,
  SunIcon,
} from "./icons";

type View = "dashboard" | "accounts" | "diagnostics" | "settings";

const RAIL: Array<{ id: View; label: string; icon: () => JSX.Element }> = [
  { id: "dashboard", label: "概览", icon: GaugeIcon },
  { id: "accounts", label: "账号", icon: AccountsIcon },
  { id: "diagnostics", label: "诊断", icon: PulseIcon },
  { id: "settings", label: "设置", icon: SlidersIcon },
];

const VIEW_TITLES: Record<Exclude<View, "dashboard">, string> = {
  accounts: "账号",
  diagnostics: "诊断",
  settings: "设置",
};

interface ShellProps {
  client: UsageClient;
  session: SessionInfo;
  remembered: boolean;
  theme: ThemeChoice;
  resolvedTheme: "light" | "dark";
  onTheme: (theme: ThemeChoice) => void;
  onLogout: (reason?: ApiError) => void;
}

function host(baseUrl: string): string {
  try {
    return new URL(baseUrl).host;
  } catch {
    return baseUrl;
  }
}

function AccountsView({ views }: { views: AccountView[] }) {
  return (
    <div className="main__inner">
      <header className="main__title">
        <h1>账号</h1>
        <p>服务器启动时读取的账号配置。这里只读；修改账号后需要在服务器上重启 usage api serve。</p>
      </header>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th scope="col">账号</th>
              <th scope="col">服务</th>
              <th scope="col">凭据类型</th>
              <th scope="col" className="num">
                轮询间隔
              </th>
              <th scope="col">状态</th>
            </tr>
          </thead>
          <tbody>
            {views.map((v) => (
              <tr key={v.account.id}>
                <td className="cell-text">
                  <span className="cell-account">
                    <ProviderMark provider={v.account.provider} size="sm" />
                    {v.account.label}
                  </span>
                </td>
                <td>{providerInfo(v.account.provider).name}</td>
                <td>
                  {v.account.credential_kind
                    ? (CREDENTIAL_LABELS[v.account.credential_kind] ?? v.account.credential_kind)
                    : UNKNOWN}
                </td>
                <td className="num">{v.account.poll_interval_seconds} 秒</td>
                <td>{v.account.enabled ? "启用" : "已禁用"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function DiagnosticsView({ views, now }: { views: AccountView[]; now: number }) {
  const flagged = views.filter((v) => ["warn", "error"].includes(accountHealth(v)));
  return (
    <div className="main__inner">
      <header className="main__title">
        <h1>诊断</h1>
        <p>
          {flagged.length
            ? `${flagged.length} 个账号的读取不完整、过期或失败。`
            : "所有已启用账号的最近一次读取都正常。"}
        </p>
      </header>
      {flagged.map((view) => {
        const s = view.snapshot;
        const retry = parseTime(s?.retry_at ?? null);
        return (
          <section key={view.account.id} className="diag-card">
            <AccountBlock view={view} now={now} />
            {s ? (
              <dl className="facts">
                <div>
                  <dt>状态</dt>
                  <dd>{stateLabel(s.fetch_state)}</dd>
                </div>
                <div>
                  <dt>诊断</dt>
                  <dd>{s.diagnostic ? `${diagnosticLabel(s.diagnostic.code)}：${s.diagnostic.message}` : UNKNOWN}</dd>
                </div>
                <div>
                  <dt>上次成功</dt>
                  <dd>{fullLocal(parseTime(s.fetched_at))}</dd>
                </div>
                <div>
                  <dt>上次尝试</dt>
                  <dd>{fullLocal(parseTime(s.attempted_at))}</dd>
                </div>
                <div>
                  <dt>下次重试</dt>
                  <dd>{retry === null ? "无" : `${fullLocal(retry)}（${relativeUntil(retry, now, true)}）`}</dd>
                </div>
              </dl>
            ) : null}
          </section>
        );
      })}
    </div>
  );
}

function SettingsView({
  client,
  session,
  remembered,
  theme,
  onTheme,
  onLogout,
}: Pick<ShellProps, "client" | "session" | "remembered" | "theme" | "onTheme" | "onLogout">) {
  return (
    <div className="main__inner">
      <header className="main__title">
        <h1>设置</h1>
        <p>外观和这台设备上的连接。</p>
      </header>
      <section className="section">
        <h2 className="section__title">外观</h2>
        <div className="segmented" role="radiogroup" aria-label="主题">
          {(
            [
              ["system", "跟随系统"],
              ["light", "浅色"],
              ["dark", "深色"],
            ] as const
          ).map(([value, label]) => (
            <label key={value} className={theme === value ? "is-on" : undefined}>
              <input
                type="radio"
                name="theme"
                value={value}
                checked={theme === value}
                onChange={() => onTheme(value)}
              />
              {label}
            </label>
          ))}
        </div>
      </section>
      <section className="section">
        <h2 className="section__title">连接</h2>
        <dl className="facts">
          <div>
            <dt>API 地址</dt>
            <dd>{client.baseUrl}</dd>
          </div>
          <div>
            <dt>模式</dt>
            <dd>{session.mode === "demo" ? "演示（合成数据）" : "实时"}</dd>
          </div>
          <div>
            <dt>鉴权</dt>
            <dd>{session.auth === "token" ? "Bearer 令牌" : "未启用（仅本机演示）"}</dd>
          </div>
          <div>
            <dt>令牌保存位置</dt>
            <dd>{remembered ? "这台设备（localStorage），退出前一直有效" : "当前标签页（sessionStorage），关闭即清除"}</dd>
          </div>
        </dl>
        <button type="button" className="button button--danger" onClick={() => onLogout()}>
          退出并清除令牌
        </button>
      </section>
    </div>
  );
}

export function Shell(props: ShellProps) {
  const { client, session, theme, resolvedTheme, onTheme, onLogout } = props;
  const state = useDashboard(client, onLogout);
  const clientNow = useTick();
  const now = clientNow + state.offsetMs;
  const [view, setView] = useState<View>("dashboard");
  const [tab, setTab] = useState<Tab>("overview");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [filter, setFilter] = useState<ProviderFilter>("all");
  const [drawer, setDrawer] = useState(false);

  const all = useMemo(() => state.data?.accounts ?? [], [state.data]);
  const views = filter === "all" ? all : all.filter((v) => v.account.provider === filter);
  const selected = all.find((v) => v.account.id === selectedId) ?? null;
  const mode = state.data?.mode ?? session.mode;
  const serverTime = state.data ? fullLocal(now) : UNKNOWN;

  useEffect(() => {
    if (selectedId && state.data && !all.some((v) => v.account.id === selectedId)) setSelectedId(null);
  }, [all, selectedId, state.data]);

  useEffect(() => {
    if (!drawer) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setDrawer(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [drawer]);

  const select = (id: string | null) => {
    setSelectedId(id);
    setView("dashboard");
    setDrawer(false);
  };


  return (
    <div className={`shell${drawer ? " shell--drawer" : ""}${mode === "demo" ? " shell--demo" : ""}`}>
      <nav className="rail" aria-label="主导航">
        <span className="rail__brand" aria-hidden="true">
          <GaugeIcon />
        </span>
        <ul>
          {RAIL.map(({ id, label, icon: IconComponent }) => (
            <li key={id}>
              <button
                type="button"
                className={`rail__btn${view === id ? " is-active" : ""}`}
                aria-current={view === id ? "page" : undefined}
                onClick={() => {
                  setView(id);
                  if (id === "accounts") setDrawer(true);
                }}
              >
                <IconComponent />
                <span className="rail__label">{label}</span>
              </button>
            </li>
          ))}
        </ul>
        <button type="button" className="rail__avatar" onClick={() => onLogout()} title="退出并清除令牌">
          <span aria-hidden="true">{mode === "demo" ? "演" : "我"}</span>
          <span className="visually-hidden">退出并清除令牌</span>
        </button>
      </nav>

      <div className="sidebar-wrap" id="account-drawer">
        <div className="sidebar-wrap__close">
          <button type="button" className="icon-btn" onClick={() => setDrawer(false)} aria-label="关闭账号列表">
            <CloseIcon />
          </button>
        </div>
        <Sidebar
          views={all}
          selected={selectedId}
          onSelect={select}
          filter={filter}
          onFilter={(f) => {
            setFilter(f);
            if (selected && f !== "all" && selected.account.provider !== f) setSelectedId(null);
          }}
        />
      </div>
      {drawer ? <button type="button" className="scrim" aria-label="关闭账号列表" onClick={() => setDrawer(false)} /> : null}

      <header className="tabsbar">
        <button
          type="button"
          className="icon-btn tabsbar__menu"
          aria-label="打开账号列表"
          aria-controls="account-drawer"
          aria-expanded={drawer}
          onClick={() => setDrawer(true)}
        >
          <MenuIcon />
        </button>
        {view === "dashboard" ? (
          <div className="tabs" role="tablist" aria-label="内容">
            {TABS.map((t) => (
              <button
                key={t.id}
                type="button"
                role="tab"
                aria-selected={tab === t.id}
                className={`tab${tab === t.id ? " is-active" : ""}`}
                onClick={() => setTab(t.id)}
              >
                {t.label}
              </button>
            ))}
          </div>
        ) : (
          <div className="tabs">
            <span className="tab is-active">{VIEW_TITLES[view]}</span>
          </div>
        )}
        <div className="tabsbar__tools">
          <button
            type="button"
            className="icon-btn"
            onClick={state.reload}
            disabled={state.loading}
            aria-label="重新读取"
            title="重新读取"
          >
            <span className={state.loading ? "spin" : undefined}>
              <RefreshIcon />
            </span>
          </button>
          <button
            type="button"
            className="icon-btn"
            onClick={() => onTheme(resolvedTheme === "dark" ? "light" : "dark")}
            aria-label={resolvedTheme === "dark" ? "切换到浅色" : "切换到深色"}
            title={theme === "system" ? "当前跟随系统" : undefined}
          >
            {resolvedTheme === "dark" ? <SunIcon /> : <MoonIcon />}
          </button>
        </div>
      </header>

      <main className="main" id="main">
        {state.error ? (
          <div className="banner banner--error" role="status">
            <span>{state.error.message}</span>
            {state.data ? (
              <span>下面显示的是上一次成功读取的数据。</span>
            ) : null}
          </div>
        ) : null}
        {!state.data ? (
          <div className="main__inner">
            <p className="empty">{state.error ? "还没有读到数据。" : "正在读取…"}</p>
          </div>
        ) : view === "accounts" ? (
          <AccountsView views={all} />
        ) : view === "diagnostics" ? (
          <DiagnosticsView views={all} now={now} />
        ) : view === "settings" ? (
          <SettingsView {...props} />
        ) : (
          <Main
            dashboard={state.data}
            views={views}
            selected={selected}
            tab={tab}
            now={now}
            onReload={state.reload}
            onDiagnostics={() => setView("diagnostics")}
            loading={state.loading}
          />
        )}
      </main>

      {state.data ? (
        <RightBar views={views} selected={selected} now={now} receivedAt={state.receivedAt} clientNow={clientNow} />
      ) : (
        <aside className="rightbar" />
      )}

      <footer className="bottombar">
        <div className="bottombar__left">
          {mode === "demo" ? <span className="badge badge--demo">DEMO 合成数据</span> : <span className="badge">实时</span>}
          <span className="bottombar__host" title={client.baseUrl}>
            {host(client.baseUrl)}
          </span>
        </div>
        <div className="bottombar__right">
          <span>v{session.version}</span>
          <span title="服务器时间（本地时区显示）">服务器时间 {serverTime}</span>
          <button type="button" className="link" onClick={() => setView("settings")}>
            设置
          </button>
          <button type="button" className="link" onClick={() => onLogout()}>
            退出
          </button>
        </div>
      </footer>
    </div>
  );
}
