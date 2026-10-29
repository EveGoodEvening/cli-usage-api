import type { AccountView, ProviderId } from "../types";
import { accountHealth, healthText, PROVIDER_ORDER, providerInfo } from "../semantics";
import { ProviderMark } from "./AccountBlock";

export type ProviderFilter = "all" | ProviderId;

export function Sidebar({
  views,
  selected,
  onSelect,
  filter,
  onFilter,
}: {
  views: AccountView[];
  selected: string | null;
  onSelect: (id: string | null) => void;
  filter: ProviderFilter;
  onFilter: (filter: ProviderFilter) => void;
}) {
  const present = PROVIDER_ORDER.filter((p) => views.some((v) => v.account.provider === p));
  const shown = filter === "all" ? views : views.filter((v) => v.account.provider === filter);
  const problems = views.filter((v) => ["error", "warn"].includes(accountHealth(v))).length;
  return (
    <nav className="sidebar" aria-label="账号">
      <div className="sidebar__head">
        <label className="select">
          <span className="visually-hidden">按服务筛选</span>
          <select value={filter} onChange={(e) => onFilter(e.target.value as ProviderFilter)}>
            <option value="all">全部账号</option>
            {present.map((p) => (
              <option key={p} value={p}>
                {providerInfo(p).name}
              </option>
            ))}
          </select>
        </label>
      </div>
      <ul className="sidebar__list">
        <li>
          <button
            type="button"
            className={`item item--all${selected === null ? " is-active" : ""}`}
            aria-current={selected === null ? "true" : undefined}
            onClick={() => onSelect(null)}
          >
            <span className="mark mark--all mark--md" aria-hidden="true">
              {views.length}
            </span>
            <span className="item__text">
              <span className="item__title">全部账号</span>
              <span className="item__sub">
                {problems ? `${problems} 个需要留意` : "全部正常或等待中"}
              </span>
            </span>
          </button>
        </li>
        {shown.map((view) => {
          const health = accountHealth(view);
          const active = selected === view.account.id;
          return (
            <li key={view.account.id}>
              <button
                type="button"
                className={`item${active ? " is-active" : ""}`}
                aria-current={active ? "true" : undefined}
                onClick={() => onSelect(view.account.id)}
              >
                <ProviderMark provider={view.account.provider} />
                <span className="item__text">
                  <span className="item__title" title={view.account.label}>
                    {view.account.label}
                  </span>
                  <span className="item__sub">
                    {providerInfo(view.account.provider).short}，{healthText(view)}
                  </span>
                </span>
                <span className={`dot dot--${health}`} role="img" aria-label={healthText(view)} />
              </button>
            </li>
          );
        })}
        {shown.length === 0 ? (
          <li className="sidebar__empty">
            {views.length === 0
              ? "服务器还没有配置账号。在服务器上运行 usage accounts add 后重启 usage api serve。"
              : "这个服务下没有账号。"}
          </li>
        ) : null}
      </ul>
    </nav>
  );
}
