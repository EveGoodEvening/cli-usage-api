import { useCallback, useEffect, useMemo, useState } from "react";
import type { AccountView } from "../types";
import { orderedMetrics } from "../semantics";
import { AccountGroup, GRANTS_KEY, rowKey } from "./AccountGroup";

export type BoardEmpty = "provider" | "attention" | null;

function liveKeys(all: AccountView[]): { rows: Set<string>; accounts: Set<string> } {
  const rows = new Set<string>();
  const accounts = new Set<string>();
  for (const view of all) {
    accounts.add(view.account.id);
    rows.add(rowKey(view.account.id, GRANTS_KEY));
    for (const { id } of orderedMetrics(view)) rows.add(rowKey(view.account.id, id));
  }
  return { rows, accounts };
}

function prune(set: Set<string>, live: Set<string>): Set<string> {
  let changed = false;
  const next = new Set<string>();
  for (const key of set) {
    if (live.has(key)) next.add(key);
    else changed = true;
  }
  return changed ? next : set;
}

function toggled(set: Set<string>, key: string): Set<string> {
  const next = new Set(set);
  if (next.has(key)) next.delete(key);
  else next.add(key);
  return next;
}

/**
 * The account groups. Expansion state survives polls; keys whose row or
 * account has disappeared are dropped. Nothing is persisted.
 */
export function Board({
  views,
  all,
  now,
  empty = null,
  onShowAll,
}: {
  views: AccountView[];
  all: AccountView[];
  now: number;
  empty?: BoardEmpty;
  onShowAll?: () => void;
}) {
  const [rows, setRows] = useState<Set<string>>(() => new Set());
  const [facts, setFacts] = useState<Set<string>>(() => new Set());
  const live = useMemo(() => liveKeys(all), [all]);

  useEffect(() => {
    setRows((current) => prune(current, live.rows));
    setFacts((current) => prune(current, live.accounts));
  }, [live]);

  const toggleRow = useCallback((key: string) => setRows((current) => toggled(current, key)), []);

  if (views.length === 0) {
    return (
      <div className="board-empty">
        {empty === "attention" ? (
          <p>
            没有需要留意的账号。
            <button type="button" className="text-btn" onClick={onShowAll}>
              查看全部
            </button>
          </p>
        ) : (
          <p>这个服务下没有账号。</p>
        )}
      </div>
    );
  }

  return (
    <div className="board">
      {views.map((view) => (
        <AccountGroup
          key={view.account.id}
          view={view}
          now={now}
          expanded={rows}
          onToggleRow={toggleRow}
          factsOpen={facts.has(view.account.id)}
          onToggleFacts={() => setFacts((current) => toggled(current, view.account.id))}
        />
      ))}
    </div>
  );
}
