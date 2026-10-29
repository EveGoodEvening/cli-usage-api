import { useCallback, useEffect, useLayoutEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { ApiError, READ_ONLY, type UsageClient } from "../api";
import { STORAGE_LABELS, KIND_LABELS } from "../accountForm";
import { endsSession } from "../hooks";
import { dropIndex, isMoveKey, keyMove, move, positionLabel, reconcilePending, sameOrder } from "../reorder";
import { providerInfo } from "../semantics";
import type { AccountConfig, AccountList, Capabilities, MutationResult } from "../types";
import { AccountForm, WARNING_MESSAGES } from "./AccountForm";
import { GripIcon } from "./icons";

export const READ_ONLY_BANNER = "服务器为只读模式（--read-only 或演示），只能查看账号。";
export const LOST_SESSION_NOTE = "会话凭据已丢失（服务器重启过）· 编辑以重新输入";
export const DELETE_CONFIRM =
  "删除该账号以及本工具保存的密钥？外部登录文件不会被删除，也不会撤销远端登录会话。";
export const RECONNECT_NOTE = "已请求重新连接；仍遵守刷新间隔与限流重试期限。";
export const OUT_OF_PROCESS_NOTE =
  "在服务器上用 usage accounts 做的修改，会在下一次网页修改或重启 usage api serve 后生效。";

/** Edge autoscroll zone and step while dragging. */
const EDGE = 48;
const EDGE_STEP = 12;

type FormState = { mode: "create" } | { mode: "edit"; id: string } | null;

interface Drag {
  id: string;
  from: number;
  pointerId: number;
  startY: number;
  scrollY0: number;
  /** Midpoints of the other rows, in client coordinates at drag start. */
  midpoints: number[];
  /** Insertion-line offsets within the list, one per possible target index. */
  lines: number[];
  lastY: number;
  target: number;
}

export interface AccountsPanelProps {
  client: UsageClient;
  capabilities: Capabilities;
  onCapabilities: (capabilities: Capabilities) => void;
  /** Called after any successful mutation, so the dashboard reloads. */
  onChanged: () => void;
  onLogout: (reason?: ApiError) => void;
  /** Return to the board. */
  onClose: () => void;
  /** Escape is left to the menu while it is open. */
  menuOpen: boolean;
  /** Open the create form immediately (the board's empty-state CTA). */
  startCreate?: boolean;
  /** Seed state (tests); the panel still loads on open. */
  initial?: AccountList | null;
  initialForm?: FormState;
}

export function AccountsPanel({
  client,
  capabilities,
  onCapabilities,
  onChanged,
  onLogout,
  onClose,
  menuOpen,
  startCreate = false,
  initial = null,
  initialForm = null,
}: AccountsPanelProps) {
  const [list, setList] = useState<AccountConfig[] | null>(initial?.accounts ?? null);
  const [caps, setCaps] = useState<Capabilities>(initial?.capabilities ?? capabilities);
  const [loadError, setLoadError] = useState<ApiError | null>(null);
  /** Local optimistic order while a reorder is dragged, in flight or pending. */
  const [order, setOrder] = useState<string[] | null>(null);
  const [saving, setSaving] = useState(false);
  const [rowBusy, setRowBusy] = useState(false);
  const [notice, setNotice] = useState<{ text: string; tone: "info" | "warn" | "error" } | null>(null);
  const [announce, setAnnounce] = useState("");
  const [form, setForm] = useState<FormState>(initialForm ?? (startCreate ? { mode: "create" } : null));
  const [formDirty, setFormDirty] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [drag, setDrag] = useState<Drag | null>(null);
  const [focusId, setFocusId] = useState<string | null>(null);

  const listRef = useRef<HTMLUListElement>(null);
  const rows = useRef(new Map<string, HTMLLIElement>());
  const grips = useRef(new Map<string, HTMLButtonElement>());
  const dragRef = useRef<Drag | null>(null);
  const orderRef = useRef<string[] | null>(null);
  const inflight = useRef(false);
  const pending = useRef<string[] | null>(null);
  const loadSeq = useRef(0);
  const frame = useRef<number | null>(null);
  const formEscape = useRef<(() => boolean) | null>(null);

  orderRef.current = order;
  dragRef.current = drag;

  const writable = caps.writable;
  const serverIds = (list ?? []).map((a) => a.id);
  const byId = new Map((list ?? []).map((a) => [a.id, a]));
  const ids = order ?? serverIds;
  const accounts = ids.flatMap((id) => {
    const account = byId.get(id);
    return account ? [account] : [];
  });
  /** The ids actually rendered, which drag and keyboard moves permute. */
  const shown = accounts.map((a) => a.id);
  const reorderBusy = saving || order !== null;
  const locked = reorderBusy || rowBusy;

  const adoptCaps = useCallback(
    (next: Capabilities) => {
      setCaps(next);
      onCapabilities(next);
    },
    [onCapabilities],
  );

  const cancelDrag = useCallback(() => {
    if (frame.current !== null) cancelAnimationFrame(frame.current);
    frame.current = null;
    dragRef.current = null;
    setDrag(null);
  }, []);

  /** Adopt a server list; a local order survives only as a reconciled permutation. */
  const adopt = useCallback(
    (accounts: AccountConfig[], next: Capabilities) => {
      setList(accounts);
      adoptCaps(next);
      const local = orderRef.current;
      if (local === null) return;
      const reconciled = reconcilePending(local, accounts.map((a) => a.id));
      if (reconciled === null) {
        pending.current = null;
        if (dragRef.current) cancelDrag();
        if (!inflight.current) setOrder(null);
      } else {
        if (pending.current) pending.current = reconcilePending(pending.current, accounts.map((a) => a.id));
        setOrder(reconciled);
      }
    },
    [adoptCaps, cancelDrag],
  );

  const load = useCallback(async () => {
    const seq = ++loadSeq.current;
    try {
      const result = await client.accounts();
      if (seq !== loadSeq.current) return;
      setLoadError(null);
      adopt(result.accounts, result.capabilities);
    } catch (caught) {
      if (seq !== loadSeq.current) return;
      const failure = caught instanceof ApiError ? caught : new ApiError("network");
      if (endsSession(failure)) onLogout(failure);
      else setLoadError(failure);
    }
  }, [client, adopt, onLogout]);

  useEffect(() => {
    void load();
  }, [load]);

  /** Shared failure handling for every panel request. */
  const handle = useCallback(
    (failure: ApiError) => {
      if (endsSession(failure)) {
        onLogout(failure);
        return;
      }
      if (failure.code === "read_only") {
        adoptCaps({ ...READ_ONLY });
        setForm(null);
      }
      if (failure.code === "not_found") setForm(null);
      setNotice({ text: failure.message, tone: "error" });
      if (failure.kind === "conflict" || failure.code === "not_found") void load();
    },
    [adoptCaps, load, onLogout],
  );

  const succeeded = useCallback(
    (result: MutationResult, text: string) => {
      // A load started before this mutation's response returns an older list: drop it.
      loadSeq.current += 1;
      adopt(result.accounts, result.capabilities);
      setNotice(
        result.warning
          ? { text: WARNING_MESSAGES[result.warning] ?? text, tone: "warn" }
          : { text, tone: "info" },
      );
      onChanged();
    },
    [adopt, onChanged],
  );

  // ------------------------------------------------------------ reorder queue

  const send = useCallback(
    async (next: string[]) => {
      inflight.current = true;
      setSaving(true);
      try {
        const result = await client.reorderAccounts(next);
        loadSeq.current += 1;
        const queued = pending.current;
        pending.current = null;
        const serverNow = result.accounts.map((a) => a.id);
        setList(result.accounts);
        adoptCaps(result.capabilities);
        const follow = reconcilePending(queued, serverNow);
        if (follow !== null && !sameOrder(follow, serverNow)) {
          // Keep the local order and send the newer one; adopt only when the queue is empty.
          setOrder(follow);
          void send(follow);
          return;
        }
        inflight.current = false;
        setSaving(false);
        setOrder(null);
        onChanged();
      } catch (caught) {
        pending.current = null;
        inflight.current = false;
        setSaving(false);
        setOrder(null);
        cancelDrag();
        setAnnounce("排序未保存，已恢复");
        handle(caught instanceof ApiError ? caught : new ApiError("network"));
      }
    },
    [client, adoptCaps, cancelDrag, handle, onChanged],
  );

  const commitOrder = useCallback(
    (next: string[], movedId: string) => {
      setOrder(next);
      orderRef.current = next;
      const index = next.indexOf(movedId);
      setAnnounce(`已移动到${positionLabel(index, next.length)}`);
      if (inflight.current) pending.current = next;
      else void send(next);
    },
    [send],
  );

  // Keyboard moves keep focus on the moved row's grip.
  useLayoutEffect(() => {
    if (focusId === null) return;
    grips.current.get(focusId)?.focus();
    setFocusId(null);
  }, [focusId]);

  const keyboardMove = (id: string, key: string) => {
    if (!isMoveKey(key) || rowBusy || dragRef.current) return false;
    const next = keyMove(shown, id, key);
    if (next) {
      commitOrder(next, id);
      setFocusId(id);
    }
    return true;
  };

  // ------------------------------------------------------------- pointer drag

  const dragAt = (current: Drag, clientY: number) => {
    const y = clientY + (window.scrollY - current.scrollY0);
    const target = dropIndex(current.midpoints, y);
    const next = { ...current, lastY: clientY, target };
    dragRef.current = next;
    setDrag(next);
  };

  const edgeScroll = () => {
    frame.current = null;
    const current = dragRef.current;
    if (!current) return;
    const step =
      current.lastY < EDGE ? -EDGE_STEP : current.lastY > window.innerHeight - EDGE ? EDGE_STEP : 0;
    if (step === 0) return;
    window.scrollBy(0, step);
    dragAt(current, current.lastY);
    frame.current = requestAnimationFrame(edgeScroll);
  };

  const onGripDown = (event: ReactPointerEvent<HTMLButtonElement>, id: string) => {
    if (!event.isPrimary || event.button !== 0 || rowBusy || !writable) return;
    const listEl = listRef.current;
    if (!listEl) return;
    event.preventDefault();
    event.currentTarget.focus();
    event.currentTarget.setPointerCapture(event.pointerId);
    const listTop = listEl.getBoundingClientRect().top;
    const rects = shown.map((rowId) => rows.current.get(rowId)?.getBoundingClientRect() ?? null);
    const from = shown.indexOf(id);
    const others = rects.filter((_, i) => i !== from);
    const midpoints = others.map((r) => (r ? r.top + r.height / 2 : 0));
    const lines = [
      (others[0]?.top ?? 0) - listTop,
      ...others.map((r) => (r ? r.bottom - listTop : 0)),
    ];
    const next: Drag = {
      id,
      from,
      pointerId: event.pointerId,
      startY: event.clientY,
      scrollY0: window.scrollY,
      midpoints,
      lines,
      lastY: event.clientY,
      target: from,
    };
    dragRef.current = next;
    setDrag(next);
  };

  const onGripMove = (event: ReactPointerEvent<HTMLButtonElement>) => {
    const current = dragRef.current;
    if (!current || current.pointerId !== event.pointerId) return;
    dragAt(current, event.clientY);
    const nearEdge = event.clientY < EDGE || event.clientY > window.innerHeight - EDGE;
    if (nearEdge && frame.current === null) frame.current = requestAnimationFrame(edgeScroll);
  };

  const onGripUp = (event: ReactPointerEvent<HTMLButtonElement>) => {
    const current = dragRef.current;
    if (!current || current.pointerId !== event.pointerId) return;
    cancelDrag();
    if (current.target !== current.from) commitOrder(move(shown, current.from, current.target), current.id);
  };

  const onGripCancel = () => {
    if (!dragRef.current) return;
    cancelDrag();
    setAnnounce("排序未保存，已恢复");
  };

  // ------------------------------------------------------------- row actions

  const run = async (work: () => Promise<void>) => {
    if (locked) return;
    setRowBusy(true);
    try {
      await work();
    } catch (caught) {
      handle(caught instanceof ApiError ? caught : new ApiError("network"));
    } finally {
      setRowBusy(false);
    }
  };

  const toggle = (account: AccountConfig) =>
    run(async () => {
      const result = await client.updateAccount(account.id, account.revision ?? "", { enabled: !account.enabled });
      succeeded(result, account.enabled ? "已停用。" : "已启用。");
    });

  const reconnect = (account: AccountConfig) =>
    run(async () => {
      await client.reconnectAccount(account.id);
      setNotice({ text: RECONNECT_NOTE, tone: "info" });
    });

  const remove = (account: AccountConfig) =>
    run(async () => {
      setConfirmDelete(null);
      const result = await client.removeAccount(account.id, account.revision ?? "");
      succeeded(result, "已删除。");
    });

  // ---------------------------------------------------- Escape, innermost first

  const escapeState = useRef({ menuOpen, confirmDelete, form, formDirty, onClose, onGripCancel });
  escapeState.current = { menuOpen, confirmDelete, form, formDirty, onClose, onGripCancel };
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      const s = escapeState.current;
      if (s.menuOpen) return;
      event.stopPropagation();
      if (dragRef.current) s.onGripCancel();
      else if (s.confirmDelete !== null) setConfirmDelete(null);
      else if (s.form !== null) {
        // The form's inline confirmation, or a save in flight, takes the key first.
        if (formEscape.current?.()) return;
        // A form (dirty or not) is closed; the view itself stays.
        setForm(null);
        setFormDirty(false);
      } else s.onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  useEffect(
    () => () => {
      if (frame.current !== null) cancelAnimationFrame(frame.current);
    },
    [],
  );

  // ------------------------------------------------------------------ render

  const editing = form?.mode === "edit" ? (byId.get(form.id) ?? null) : null;
  const formOpen = writable && form !== null && (form.mode === "create" || editing !== null);

  let content;
  if (formOpen) {
    content = (
      <AccountForm
        key={form?.mode === "edit" ? form.id : "create"}
        client={client}
        original={editing}
        capabilities={caps}
        onSaved={(result) => {
          setForm(null);
          setFormDirty(false);
          succeeded(result, editing ? "已保存。" : "已添加账号。");
        }}
        onCancel={() => {
          setForm(null);
          setFormDirty(false);
        }}
        onError={handle}
        onUncertain={() => {
          void load();
          onChanged();
        }}
        escapeRef={formEscape}
        onDirty={setFormDirty}
      />
    );
  } else if (list === null) {
    content = loadError ? (
      <div className="board-empty">
        <p>
          {loadError.message}
          <button type="button" className="text-btn" onClick={() => void load()}>
            重试
          </button>
        </p>
      </div>
    ) : (
      <div className="board-empty">
        <p>正在读取…</p>
      </div>
    );
  } else if (accounts.length === 0) {
    content = <EmptyAccounts writable={writable} onCreate={() => setForm({ mode: "create" })} />;
  } else {
    content = (
      <ul className="acct-list" ref={listRef} aria-describedby={writable ? "acct-order-help" : undefined}>
        {accounts.map((account, index) => {
          const dragging = drag?.id === account.id;
          const position = positionLabel(index, accounts.length);
          return (
            <li
              key={account.id}
              className={`acct${dragging ? " acct--dragging" : ""}`}
              ref={(el) => {
                if (el) rows.current.set(account.id, el);
                else rows.current.delete(account.id);
              }}
              style={dragging && drag ? { transform: `translateY(${dragOffset(drag)}px)` } : undefined}
            >
              {writable ? (
                <button
                  type="button"
                  className="acct__grip"
                  aria-label={`移动 ${account.label}，${position}`}
                  aria-disabled={rowBusy || undefined}
                  ref={(el) => {
                    if (el) grips.current.set(account.id, el);
                    else grips.current.delete(account.id);
                  }}
                  onKeyDown={(event) => {
                    if (keyboardMove(account.id, event.key)) event.preventDefault();
                  }}
                  onPointerDown={(event) => onGripDown(event, account.id)}
                  onPointerMove={onGripMove}
                  onPointerUp={onGripUp}
                  onPointerCancel={onGripCancel}
                  onLostPointerCapture={onGripCancel}
                >
                  <GripIcon />
                </button>
              ) : null}
              <AccountSummary account={account} />
              {writable ? (
                <div className="acct__actions">
                  {confirmDelete === account.id ? (
                    <div className="acct__confirm" role="alert">
                      <p>{DELETE_CONFIRM}</p>
                      <p>
                        <button
                          type="button"
                          className="text-btn text-btn--danger"
                          aria-disabled={locked || undefined}
                          onClick={() => void remove(account)}
                        >
                          确认删除
                        </button>
                        <button type="button" className="text-btn" onClick={() => setConfirmDelete(null)}>
                          取消
                        </button>
                      </p>
                    </div>
                  ) : (
                    <>
                      <ActionButton locked={locked} onClick={() => setForm({ mode: "edit", id: account.id })}>
                        编辑
                      </ActionButton>
                      <ActionButton locked={locked} onClick={() => void toggle(account)}>
                        {account.enabled ? "停用" : "启用"}
                      </ActionButton>
                      <ActionButton locked={locked} onClick={() => void reconnect(account)}>
                        重新连接
                      </ActionButton>
                      <ActionButton locked={locked} danger onClick={() => setConfirmDelete(account.id)}>
                        删除
                      </ActionButton>
                      <details className="acct__more">
                        <summary aria-label={`更多操作：${account.label}`}>移动</summary>
                        <ActionButton
                          locked={rowBusy || index === 0}
                          onClick={() => keyboardMove(account.id, "ArrowUp")}
                        >
                          上移
                        </ActionButton>
                        <ActionButton
                          locked={rowBusy || index === accounts.length - 1}
                          onClick={() => keyboardMove(account.id, "ArrowDown")}
                        >
                          下移
                        </ActionButton>
                      </details>
                    </>
                  )}
                </div>
              ) : null}
            </li>
          );
        })}
        {drag && drag.target !== drag.from ? (
          <li className="acct-drop" aria-hidden="true" style={{ top: `${drag.lines[drag.target] ?? 0}px` }} />
        ) : null}
      </ul>
    );
  }

  return (
    <section className="accounts" aria-labelledby="accounts-title">
      <header className="accounts__head">
        <h1 className="accounts__title" id="accounts-title">
          账号管理
        </h1>
        <span className="header__spacer" />
        {writable && !formOpen && list !== null && list.length > 0 ? (
          <button
            type="button"
            className="text-btn"
            aria-disabled={locked || undefined}
            onClick={() => {
              if (!locked) setForm({ mode: "create" });
            }}
          >
            添加账号
          </button>
        ) : null}
        <button type="button" className="text-btn" onClick={onClose}>
          返回仪表盘
        </button>
      </header>
      {!writable ? <p className="rule-note accounts__banner">{READ_ONLY_BANNER}</p> : null}
      {writable && !formOpen ? (
        <p className="accounts__help" id="acct-order-help">
          拖动 ⠿ 或聚焦后按 ↑ ↓ Home End 调整顺序，仪表盘按此顺序显示。{OUT_OF_PROCESS_NOTE}
        </p>
      ) : null}
      {saving || (order !== null && !drag) ? (
        <p className="accounts__saving" role="status">
          正在保存排序…
        </p>
      ) : null}
      {notice ? (
        <p className={`accounts__notice${notice.tone === "info" ? "" : ` is-${notice.tone}`}`} role="status">
          {notice.text}
        </p>
      ) : null}
      <p className="visually-hidden" aria-live="polite">
        {announce}
      </p>
      {content}
    </section>
  );
}

/** The dragged row follows the pointer, including any scroll since the drag began. */
function dragOffset(drag: Drag): number {
  return drag.lastY + (window.scrollY - drag.scrollY0) - drag.startY;
}

function ActionButton({
  locked,
  danger = false,
  onClick,
  children,
}: {
  locked: boolean;
  danger?: boolean;
  onClick: () => void;
  children: string;
}) {
  return (
    <button
      type="button"
      className={danger ? "text-btn text-btn--danger" : "text-btn"}
      aria-disabled={locked || undefined}
      onClick={() => {
        if (!locked) onClick();
      }}
    >
      {children}
    </button>
  );
}

export function AccountSummary({ account }: { account: AccountConfig }) {
  const provider = providerInfo(account.provider);
  const kind = account.credential_kind ? KIND_LABELS[account.credential_kind] : null;
  return (
    <div className="acct__main">
      <p className="acct__label">{account.label}</p>
      <p className="acct__meta">
        <span>{provider.name}</span>
        <span className="acct__badge" title={kind ?? undefined}>
          {STORAGE_LABELS[account.storage]}
        </span>
        <span className={account.enabled ? undefined : "is-warn"}>{account.enabled ? "已启用" : "已停用"}</span>
        <span>
          每 <span className="num">{account.effective_poll_interval_seconds}</span> 秒
        </span>
      </p>
      {account.session_available === false ? <p className="acct__lost is-warn">{LOST_SESSION_NOTE}</p> : null}
    </div>
  );
}

export function EmptyAccounts({ writable, onCreate }: { writable: boolean; onCreate: () => void }) {
  return writable ? (
    <div className="board-empty">
      <p>
        <button type="button" className="button button--inline" onClick={onCreate}>
          添加账号
        </button>
      </p>
      <p>也可以在服务器上运行 usage accounts add（之后需重启 usage api serve，或在网页中做任意修改后生效）。</p>
    </div>
  ) : (
    <div className="board-empty">
      <p>服务器还没有配置账号。在服务器上运行 usage accounts add，然后重启 usage api serve。</p>
    </div>
  );
}
