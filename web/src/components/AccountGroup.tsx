import { Fragment, type ReactNode } from "react";
import type { AccountView } from "../types";
import {
  UNKNOWN,
  fullLocalZoned,
  parseTime,
  relativeAge,
  relativeUntil,
  timeTitle,
} from "../format";
import {
  CREDENTIAL_LABELS,
  accountHealth,
  diagnosticLabel,
  healthText,
  providerInfo,
  stateLabel,
} from "../semantics";
import { TOTAL_BALANCE_ID, accountNote, planRows } from "../view";
import { Facts, ZonedTime } from "./Facts";
import { Grants } from "./Grants";
import { MetricRow } from "./MetricRow";
import { ChevronIcon } from "./icons";

function Ago({ raw, ms, now, prefix }: { raw: string | null; ms: number; now: number; prefix: string }) {
  return (
    <time dateTime={raw ?? undefined} title={timeTitle(raw, ms, prefix)}>
      {relativeAge(ms, now)}
    </time>
  );
}

/** Head meta: state, last success and last attempt kept apart, retry, freshness. */
function HeadMeta({ view, now }: { view: AccountView; now: number }) {
  const s = view.snapshot;
  if (!view.account.enabled) return <span className="group__meta">已禁用，不轮询</span>;
  if (!s) return <span className="group__meta">等待首次读取</span>;
  const health = accountHealth(view);
  const fetched = parseTime(s.fetched_at);
  const attempted = parseTime(s.attempted_at);
  const retry = parseTime(s.retry_at);
  const parts: ReactNode[] = [];
  if (s.fetch_state !== "ok") {
    parts.push(<b className={`group__state is-${health}`}>{stateLabel(s.fetch_state)}</b>);
  }
  if (s.fetch_state === "ok" && fetched !== null && s.fetched_at === s.attempted_at) {
    parts.push(
      <>
        更新于 <Ago raw={s.fetched_at} ms={fetched} now={now} prefix="上次成功 " />
      </>,
    );
  } else {
    parts.push(
      <>成功 {fetched === null ? "从未" : <Ago raw={s.fetched_at} ms={fetched} now={now} prefix="上次成功 " />}</>,
    );
    parts.push(
      <>尝试 {attempted === null ? UNKNOWN : <Ago raw={s.attempted_at} ms={attempted} now={now} prefix="上次尝试 " />}</>,
    );
  }
  if (retry !== null && retry > now) {
    parts.push(
      <time className="is-warn" dateTime={s.retry_at ?? undefined} title={timeTitle(s.retry_at, retry, "下次重试 ")}>
        重试 {relativeUntil(retry, now, true)}
      </time>,
    );
  }
  if (view.freshness?.last_known) parts.push(<span className="is-warn">上次已知</span>);
  else if (view.freshness?.stale) parts.push(<span className="is-warn">已过期</span>);
  if (view.freshness?.reset_passed) parts.push(<span className="is-warn">重置已过，等待刷新</span>);
  return (
    <span className="group__meta">
      {parts.map((part, i) => (
        <Fragment key={i}>
          {i ? " · " : null}
          <span>{part}</span>
        </Fragment>
      ))}
    </span>
  );
}

function zoned(raw: string | null | undefined, fallback: string) {
  const ms = parseTime(raw ?? null);
  return ms === null ? fallback : <ZonedTime local={fullLocalZoned(ms)} raw={raw ?? null} />;
}

function AccountFacts({ view, now, id }: { view: AccountView; now: number; id: string }) {
  const s = view.snapshot;
  const retry = parseTime(s?.retry_at ?? null);
  const kind = view.account.credential_kind;
  return (
    <Facts
      className="group__facts"
      id={id}
      items={[
        { label: "服务", value: providerInfo(view.account.provider).name },
        { label: "凭据", value: kind ? (CREDENTIAL_LABELS[kind] ?? kind) : UNKNOWN },
        { label: "轮询间隔", value: `${view.account.poll_interval_seconds} 秒` },
        { label: "状态", value: `${view.account.enabled ? "启用" : "已禁用"} · ${healthText(view)}` },
        {
          label: "诊断",
          value: s?.diagnostic ? `${diagnosticLabel(s.diagnostic.code)}：${s.diagnostic.message}` : UNKNOWN,
          wide: true,
        },
        { label: "上次成功", value: zoned(s?.fetched_at, "从未") },
        { label: "上次尝试", value: zoned(s?.attempted_at, UNKNOWN) },
        {
          label: "下次重试",
          value:
            retry === null ? (
              "无"
            ) : (
              <>
                <span>
                  {fullLocalZoned(retry)}（{relativeUntil(retry, now, true)}）
                </span>
                <span className="facts__utc">UTC {s?.retry_at}</span>
              </>
            ),
        },
        {
          label: "原始 JSON",
          wide: true,
          value: (
            <details className="raw">
              <summary>展开</summary>
              <pre>{JSON.stringify(view, null, 2)}</pre>
            </details>
          ),
        },
      ]}
    />
  );
}

export function rowKey(accountId: string, metricId: string): string {
  return `${accountId}:${metricId}`;
}

export const GRANTS_KEY = "#grants";

const EMPTY: ReadonlySet<string> = new Set();

export function AccountGroup({
  view,
  now,
  expanded,
  onToggleRow,
  factsOpen,
  onToggleFacts,
  shared = EMPTY,
}: {
  view: AccountView;
  now: number;
  expanded: ReadonlySet<string>;
  onToggleRow: (key: string) => void;
  factsOpen: boolean;
  onToggleFacts: () => void;
  /** Notes the board already states once for several accounts. */
  shared?: ReadonlySet<string>;
}) {
  const { account, snapshot } = view;
  const health = accountHealth(view);
  const own = (note: string | null) => (note && !shared.has(note) ? note : null);
  const hoisted = own(accountNote(view));
  const plan = planRows(view);
  const groupNote = own(plan.groupNote);
  const muted = !!view.freshness && (view.freshness.stale || view.freshness.last_known);
  const diag = snapshot?.diagnostic ?? null;
  const diagLabel = diag ? diagnosticLabel(diag.code) : null;
  const diagRepeatsState = !!diag && !!snapshot && diagLabel === stateLabel(snapshot.fetch_state) && snapshot.fetch_state !== "ok";
  const mismatch = diag?.code === "balance_mismatch";
  const factsId = `facts-${account.id}`;
  const grantsKey = rowKey(account.id, GRANTS_KEY);

  return (
    <section className={`group group--${health}`} id={`acct-${account.id}`} aria-label={account.label}>
      <header className="group__head">
        <span className={`dot dot--${health}`} role="img" aria-label={healthText(view)} />
        <h2 className="group__label">{account.label}</h2>
        <span className="group__aside">
          <HeadMeta view={view} now={now} />
          <button
            type="button"
            className="group__more"
            aria-expanded={factsOpen}
            aria-controls={factsOpen ? factsId : undefined}
            onClick={onToggleFacts}
          >
            详情
            <ChevronIcon />
          </button>
        </span>
      </header>
      <p className="group__sub">
        {providerInfo(account.provider).name}
        {hoisted ? ` · ${hoisted}` : null}
      </p>
      {diag ? (
        <p className="group__diag">
          {diagRepeatsState ? null : (
            <b className={`is-${mismatch ? "warn" : health === "error" ? "error" : "warn"}`}>{diagLabel}</b>
          )}
          {diagRepeatsState ? null : " — "}
          <span>{diag.message}</span>
        </p>
      ) : null}
      {groupNote ? <p className="group__note">{groupNote}</p> : null}
      {factsOpen ? <AccountFacts view={view} now={now} id={factsId} /> : null}
      {!account.enabled ? (
        <p className="group__empty">已禁用，服务器不会轮询。</p>
      ) : !snapshot ? (
        <p className="group__empty">等待首次读取。</p>
      ) : (
        <ul className="rows">
          {plan.rows.map((row) => {
            const key = rowKey(account.id, row.id);
            return (
              <MetricRow
                key={row.id}
                id={row.id}
                metric={row.metric}
                now={now}
                branch={row.branch}
                muted={muted}
                detail={mismatch && row.id === TOTAL_BALANCE_ID ? row.detail : own(row.detail)}
                mismatch={mismatch && row.id === TOTAL_BALANCE_ID}
                expanded={expanded.has(key)}
                onToggle={() => onToggleRow(key)}
                factsId={`row-${account.id}-${row.id}`.replace(/[^A-Za-z0-9_-]/g, "-")}
              />
            );
          })}
          {account.provider === "claude_platform" ? (
            <Grants
              snapshot={snapshot}
              now={now}
              open={expanded.has(grantsKey)}
              onToggle={() => onToggleRow(grantsKey)}
              listId={`grants-${account.id}`}
            />
          ) : null}
        </ul>
      )}
    </section>
  );
}
