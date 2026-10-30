import type { Grant, Snapshot } from "../types";
import { UNKNOWN, formatMoney, parseTime, relativeUntil, shortLocal, timeTitle } from "../format";
import { grantCountLabel } from "../semantics";
import { ChevronIcon } from "./icons";

const CATEGORY: Record<string, string> = { purchased: "购买", promotional: "赠送" };

function Expiry({ grant, now }: { grant: Grant; now: number }) {
  const expiry = parseTime(grant.expires_at);
  if (expiry === null) return <span className="ink-3">到期未知</span>;
  if (expiry <= now) {
    return (
      <time dateTime={grant.expires_at ?? undefined} title={timeTitle(grant.expires_at, expiry, "到期 ")}>
        已过期，不计入当前余额
      </time>
    );
  }
  return (
    <time dateTime={grant.expires_at ?? undefined} title={timeTitle(grant.expires_at, expiry, "到期 ")}>
      {shortLocal(expiry, now)} · {relativeUntil(expiry, now)}
    </time>
  );
}

function expired(grant: Grant, now: number): boolean {
  const expiry = parseTime(grant.expires_at);
  return expiry !== null && expiry <= now;
}

/** Disclosure row and grant list for a Claude Platform account. */
export function Grants({
  snapshot,
  now,
  open,
  onToggle,
  listId,
}: {
  snapshot: Snapshot | null;
  now: number;
  open: boolean;
  onToggle: () => void;
  listId: string;
}) {
  const grants = snapshot?.grants ?? [];
  return (
    <li className={`row row--grants${open ? " is-open" : ""}`}>
      <button type="button" className="row__hit" aria-expanded={open} aria-controls={open ? listId : undefined} onClick={onToggle}>
        <span className="row__label">赠款</span>
        <span className="row__meter" />
        <span className="row__used">
          <b className="fig">{grantCountLabel(snapshot)}</b>
        </span>
        <span className="row__rest" />
        <span className="row__reset grants__chev">
          <ChevronIcon />
        </span>
      </button>
      {open ? (
        <div className="grants" id={listId}>
          {grants.length === 0 ? (
            <p className="grants__empty">
              {snapshot?.fetch_state === "ok" ? "完整读取：没有赠款。" : "读取不完整，赠款数量未知，不代表没有赠款。"}
            </p>
          ) : (
            <>
              <table className="grants__table">
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
                  {grants.map((grant, i) => (
                    <tr key={grant.id ?? i} className={expired(grant, now) ? "is-expired" : undefined}>
                      <td>{CATEGORY[grant.category] ?? grant.category}</td>
                      <td className="grants__name">
                        {grant.name ?? UNKNOWN}
                        {grant.program_id ? <span className="ink-3 mono"> {grant.program_id}</span> : null}
                      </td>
                      <td className="num">{formatMoney(grant.granted)}</td>
                      <td className="num">{formatMoney(grant.remaining)}</td>
                      <td>
                        <Expiry grant={grant} now={now} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <ul className="grants__cards">
                {grants.map((grant, i) => (
                  <li key={grant.id ?? i} className={expired(grant, now) ? "is-expired" : undefined}>
                    <span className="grants__name">{grant.name ?? UNKNOWN}</span>
                    <span className="num">
                      {formatMoney(grant.remaining)} / {formatMoney(grant.granted)}
                    </span>
                    <span className="grants__meta">
                      {CATEGORY[grant.category] ?? grant.category} · <Expiry grant={grant} now={now} />
                    </span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      ) : null}
    </li>
  );
}
