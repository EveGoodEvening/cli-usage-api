import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ApiError, UsageClient } from "../api";
import type { ThemeChoice } from "../auth";
import type { AccountView, ProviderId, SessionInfo } from "../types";
import { useDashboard, useTick } from "../hooks";
import { PROVIDER_ORDER, accountHealth } from "../semantics";
import { Board } from "./Board";
import { FilterBar, filterItems, type Filter } from "./FilterBar";
import { DemoStrip, Header, Status } from "./Header";
import { MenuPopover } from "./MenuPopover";

interface ShellProps {
  client: UsageClient;
  session: SessionInfo;
  remembered: boolean;
  theme: ThemeChoice;
  resolvedTheme: "light" | "dark";
  onTheme: (theme: ThemeChoice) => void;
  onLogout: (reason?: ApiError) => void;
}

const FILTER_KEY = "usage-web.filter";

function loadFilter(): Filter {
  try {
    return (window.localStorage.getItem(FILTER_KEY) as Filter | null) ?? "all";
  } catch {
    return "all";
  }
}

function saveFilter(value: Filter): void {
  try {
    if (value === "all") window.localStorage.removeItem(FILTER_KEY);
    else window.localStorage.setItem(FILTER_KEY, value);
  } catch {
    // A remembered filter is only a convenience.
  }
}

function needsAttention(view: AccountView): boolean {
  const health = accountHealth(view);
  return health === "warn" || health === "error";
}

export function Shell({ client, session, remembered, theme, onTheme, onLogout }: ShellProps) {
  const state = useDashboard(client, onLogout);
  const clientNow = useTick();
  const now = clientNow + state.offsetMs;
  const [stored, setStored] = useState<Filter>(loadFilter);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuButton = useRef<HTMLButtonElement>(null);

  const all = useMemo(() => state.data?.accounts ?? [], [state.data]);
  const mode = state.data?.mode ?? session.mode;

  const providers = PROVIDER_ORDER.flatMap((provider: ProviderId) => {
    const count = all.filter((v) => v.account.provider === provider).length;
    return count ? [{ provider, count }] : [];
  });
  const attention = all.filter(needsAttention).length;
  const items = filterItems(all.length, providers, attention);
  // A remembered value that no longer applies falls back to all.
  const present = items.some((item) => item.value === stored);
  const filter: Filter = present ? stored : "all";
  // Once data has loaded, forget a stale value so it cannot silently re-apply on a later poll.
  const loaded = state.data !== null;
  useEffect(() => {
    if (loaded && !present) {
      setStored("all");
      saveFilter("all");
    }
  }, [loaded, present]);
  const views =
    filter === "all"
      ? all
      : filter === "attention"
        ? all.filter(needsAttention)
        : all.filter((v) => v.account.provider === filter);

  const choose = (value: Filter) => {
    setStored(value);
    saveFilter(value);
  };
  const closeMenu = useCallback(() => setMenuOpen(false), []);

  const status = (className: string) => (
    <Status views={views} receivedAt={state.receivedAt} clientNow={clientNow} className={className} />
  );

  let body;
  if (!state.data) {
    body = state.error ? (
      <div className="board-empty">
        <p>
          {state.error.message}
          <button type="button" className="text-btn" onClick={state.reload}>
            重试
          </button>
        </p>
      </div>
    ) : (
      <div className="board-empty">
        <p>正在读取…</p>
      </div>
    );
  } else if (all.length === 0) {
    body = (
      <div className="board-empty">
        <p>服务器还没有配置账号。在服务器上运行 usage accounts add 后重启 usage api serve。</p>
      </div>
    );
  } else {
    body = (
      <>
        {status("status-line")}
        <FilterBar items={items} value={filter} onChange={choose} />
        <Board
          views={views}
          all={all}
          now={now}
          empty={filter === "attention" ? "attention" : "provider"}
          onShowAll={() => choose("all")}
        />
      </>
    );
  }

  return (
    <div className="app">
      <Header
        mode={mode}
        status={state.data ? status("header__status") : null}
        now={now}
        loading={state.loading}
        onReload={state.reload}
        menuOpen={menuOpen}
        onMenu={() => setMenuOpen((open) => !open)}
        menuButton={menuButton}
        menu={
          menuOpen ? (
            <MenuPopover
              anchor={menuButton}
              onClose={closeMenu}
              baseUrl={client.baseUrl}
              session={session}
              mode={mode}
              remembered={remembered}
              now={now}
              theme={theme}
              onTheme={onTheme}
              dashboard={state.data}
              onLogout={() => onLogout()}
            />
          ) : null
        }
      />
      {mode === "demo" ? <DemoStrip /> : null}
      {state.error && state.data ? (
        <div className="strip strip--error" role="status">
          <p className="col">读取失败：{state.error.message} · 下面是上一次成功读取的数据</p>
        </div>
      ) : null}
      <main className="col main">{body}</main>
    </div>
  );
}
