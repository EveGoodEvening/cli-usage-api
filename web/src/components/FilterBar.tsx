import type { ProviderId } from "../types";
import { providerInfo } from "../semantics";

export type Filter = "all" | "attention" | ProviderId;

export interface FilterItem {
  value: Filter;
  label: string;
  count: number;
}

export function filterItems(
  total: number,
  providers: Array<{ provider: ProviderId; count: number }>,
  attention: number,
): FilterItem[] {
  const items: FilterItem[] = [{ value: "all", label: "全部", count: total }];
  for (const { provider, count } of providers) items.push({ value: provider, label: providerInfo(provider).name, count });
  if (attention > 0) items.push({ value: "attention", label: "需留意", count: attention });
  return items;
}

export function FilterBar({
  items,
  value,
  onChange,
}: {
  items: FilterItem[];
  value: Filter;
  onChange: (value: Filter) => void;
}) {
  return (
    <div className="filter" role="tablist" aria-label="筛选账号">
      {items.map((item) => {
        const active = item.value === value;
        return (
          <button
            key={item.value}
            type="button"
            role="tab"
            aria-selected={active}
            className={`filter__tab${active ? " is-active" : ""}${item.value === "attention" ? " filter__tab--attention" : ""}`}
            onClick={() => onChange(item.value)}
          >
            {item.label} <span className="filter__count">{item.count}</span>
          </button>
        );
      })}
    </div>
  );
}
