import type { ReactNode, RefObject } from "react";
import type { AccountView, ApiMode } from "../types";
import { browserZone, relativeAge, timeTitle, utcOffset } from "../format";
import { accountHealth } from "../semantics";
import { AccountsIcon, MoreIcon, RefreshIcon } from "./icons";

export function DemoBadge() {
  return (
    <span className="badge" title="离线合成演示数据，不代表任何真实账号">
      演示<span className="badge__more"> · 合成数据</span>
    </span>
  );
}

/** "● 1 异常 · ● 2 留意 · 4 个账号 · 更新于 刚刚" */
export function Status({
  views,
  receivedAt,
  clientNow,
  className,
}: {
  views: AccountView[];
  receivedAt: number | null;
  clientNow: number;
  className: string;
}) {
  let errors = 0;
  let warns = 0;
  for (const view of views) {
    const health = accountHealth(view);
    if (health === "error") errors += 1;
    else if (health === "warn") warns += 1;
  }
  const parts: ReactNode[] = [];
  if (errors) {
    parts.push(
      <span className="is-error">
        ● <span className="num">{errors}</span> 异常
      </span>,
    );
  }
  if (warns) {
    parts.push(
      <span className="is-warn">
        ● <span className="num">{warns}</span> 留意
      </span>,
    );
  }
  parts.push(
    <>
      <span className="num">{views.length}</span> 个账号
    </>,
  );
  if (receivedAt !== null) {
    parts.push(
      <>
        更新于{" "}
        <time
          dateTime={new Date(receivedAt).toISOString()}
          title={timeTitle(new Date(receivedAt).toISOString(), receivedAt, "页面读取 ")}
        >
          {relativeAge(receivedAt, clientNow)}
        </time>
      </>,
    );
  }
  return (
    <p className={className}>
      {parts.map((part, i) => (
        <span key={i}>
          {i ? " · " : null}
          {part}
        </span>
      ))}
    </p>
  );
}

export function Header({
  mode,
  status,
  now,
  loading,
  onReload,
  menuOpen,
  onMenu,
  menuButton,
  menu,
  accountsOpen,
  onAccounts,
}: {
  mode: ApiMode;
  status: ReactNode;
  now: number;
  loading: boolean;
  onReload: () => void;
  menuOpen: boolean;
  onMenu: () => void;
  menuButton: RefObject<HTMLButtonElement>;
  menu: ReactNode;
  accountsOpen: boolean;
  onAccounts: () => void;
}) {
  const zone = browserZone();
  const offset = utcOffset(now);
  return (
    <header className="header">
      <div className="header__inner">
        <span className="wordmark">CLIUsageAPI</span>
        {mode === "demo" ? <DemoBadge /> : null}
        <span className="header__spacer" />
        {status}
        <span
          className="header__tz num"
          title={`时区 ${zone ? `${zone}（${offset}）` : offset}`}
        >
          {offset}
        </span>
        <button
          type="button"
          className="icon-btn"
          onClick={onAccounts}
          aria-label="账号管理"
          aria-pressed={accountsOpen}
          title="账号管理"
        >
          <AccountsIcon />
        </button>
        <button
          type="button"
          className="icon-btn"
          onClick={onReload}
          disabled={loading}
          aria-label="重新读取"
          title="刷新"
        >
          <span className={loading ? "spin" : undefined}>
            <RefreshIcon />
          </span>
        </button>
        <span className="header__menu">
          <button
            type="button"
            className="icon-btn"
            ref={menuButton}
            aria-label="菜单"
            aria-haspopup="dialog"
            aria-expanded={menuOpen}
            onClick={onMenu}
          >
            <MoreIcon />
          </button>
          {menu}
        </span>
      </div>
    </header>
  );
}

export function DemoStrip() {
  return (
    <div className="strip strip--demo">
      <p className="col">离线合成演示：数字来自内置虚构样例，不代表任何真实账号，也不能证明实时额度可用。</p>
    </div>
  );
}
