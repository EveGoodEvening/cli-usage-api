import { useEffect, useRef, useState, type KeyboardEvent, type MutableRefObject } from "react";
import { ApiError, type UsageClient } from "../api";
import {
  DEFAULT_PATH_HELP,
  KIND_LABELS,
  MAX_LABEL,
  STORAGE_LABELS,
  allowedKinds,
  canKeepCredits,
  canKeepReference,
  canReuseSecret,
  creditsSection,
  creditsUsesSaved,
  defaultInterval,
  editDraft,
  formProviders,
  POLL_FLOORS,
  providerName,
  isFileKind,
  needsPrepare,
  needsSecret,
  newDraft,
  prepareBody,
  prepareReferenceError,
  sourceChanged,
  updateBody,
  createBody,
  formEscape,
  rebaseDraft,
  saveUncertain,
  SAVE_UNCERTAIN_NOTE,
  validateDraft,
  validReference,
  withKind,
  type Draft,
  type DraftErrors,
} from "../accountForm";
import type { AccountConfig, Capabilities, MutationResult, PrepareChoice, PrepareResult, ProviderId } from "../types";

/** accounts.CONSOLE_SESSION_WARNING, verbatim. */
export const CONSOLE_SESSION_WARNING =
  "High-sensitivity account session: enter only the sessionKey value. " +
  "Do not enter your password, a full Cookie header, or a HAR file.";
export const CONSOLE_SESSION_WARNING_ZH =
  "高敏感度账号会话：只输入 sessionKey 的值。不要输入密码、完整的 Cookie 请求头或 HAR 文件。";

/** accounts.OPENAI_SESSION_WARNING, verbatim. */
export const OPENAI_SESSION_WARNING =
  "High-sensitivity account session: this is the platform.openai.com dashboard session key. " +
  "It grants full dashboard access to the account (billing, purchases, creating API keys); " +
  "treat it like a password session. Paste only the token value; never your password, a " +
  "full Cookie or Authorization header, or a HAR file. It expires within days and must be " +
  "pasted again (no refresh). It is stored only in the encrypted OS store or kept for this " +
  "session only. This app performs only one read-only GET of the credit balance. " +
  "API keys (sk-...) do not work here.";
export const OPENAI_SESSION_WARNING_ZH =
  "高敏感度账号会话：这是 platform.openai.com 控制台的会话密钥，可完全访问该账号的控制台" +
  "（账单、购买、创建 API key），请像对待密码会话一样保护它。只粘贴令牌值本身；不要输入密码、" +
  "完整的 Cookie 或 Authorization 请求头，也不要上传 HAR 文件。它几天内就会过期，之后需要重新粘贴" +
  "（不会自动续期）。它只保存在服务器的加密系统密钥环中，或只保留到本次会话结束。本工具只发送一个" +
  "只读的 GET 请求读取余额。API key（sk-…）在这里不能使用。";

/** The Claude subscription prepaid-credits read: optional, explicit, one extra request. */
export const CREDITS_HELP =
  "可选：读取 Claude credits 余额。“发现组织”只读取当前登录的资料（只读），不会自动选择；" +
  "明确选择组织后，每次刷新会多发一个只读请求。选择“不读取”则只读取用量。";

/** Choice text: Grok scopes and nameless organizations are numbered, never named by id. */
export function choiceLabel(kind: PrepareResult["kind"], choice: PrepareChoice, index: number): string {
  if (kind === "grok_scope") {
    return `Grok 范围 ${index + 1}${choice.legacy ? "（旧版 accounts.x.ai 登录）" : ""}`;
  }
  return choice.label ?? `组织 ${index + 1}`;
}

export function ChoiceList({
  prepared,
  value,
  onChange,
  disabled,
}: {
  prepared: PrepareResult;
  value: string | null;
  onChange: (id: string) => void;
  disabled?: boolean;
}) {
  const grok = prepared.kind === "grok_scope";
  return (
    <fieldset className="field choices">
      <legend className="field__label">{grok ? "登录范围" : "组织"}</legend>
      <p className="field__help">{grok ? "请明确选择要读取的范围。" : "请明确选择组织；不会自动选择。"}</p>
      {prepared.choices.map((choice, i) => (
        <label key={choice.id} className="check">
          <input
            type="radio"
            name="prepare-choice"
            value={choice.id}
            checked={value === choice.id}
            onChange={() => onChange(choice.id)}
            disabled={disabled}
          />
          <span>
            {choiceLabel(prepared.kind, choice, i)}
            {choice.current ? "（当前）" : null}
          </span>
        </label>
      ))}
    </fieldset>
  );
}

/**
 * Secret inputs stay out of browser password managers: a "new-password" hint
 * (browsers ignore autocomplete="off" on password fields), the common manager
 * opt-outs, and a form that never fires a native submit with a filled password.
 */
export const SECRET_INPUT_PROPS = {
  type: "password",
  autoComplete: "new-password",
  spellCheck: false,
  autoCapitalize: "off",
  "data-1p-ignore": "true",
  "data-lpignore": "true",
  "data-bwignore": "true",
  "data-form-type": "other",
} as const;

export function StorageChoice({
  persist,
  secureStore,
  onChange,
  error,
}: {
  persist: boolean | null;
  secureStore: boolean;
  onChange: (persist: boolean) => void;
  error?: string | undefined;
}) {
  return (
    <fieldset className="field">
      <legend className="field__label">凭据保存方式</legend>
      <label className="check">
        <input
          type="radio"
          name="persist"
          checked={persist === true}
          disabled={!secureStore}
          onChange={() => onChange(true)}
        />
        <span>加密保存到服务器系统密钥环</span>
        {secureStore ? (
          <small>服务器报告有加密密钥环；保存时仍可能失败，失败时不会改用其他方式。</small>
        ) : (
          <small>服务器没有可用的加密密钥环（例如 Railway 容器）</small>
        )}
      </label>
      <label className="check">
        <input type="radio" name="persist" checked={persist === false} onChange={() => onChange(false)} />
        <span>仅本次会话（服务器进程重启后丢失，需要重新输入）</span>
      </label>
      {error ? <p className="form-error">{error}</p> : null}
    </fieldset>
  );
}

export function OpenAIWarning() {
  return (
    <div className="rule-note rule-note--warn">
      <p>{OPENAI_SESSION_WARNING_ZH}</p>
      <p lang="en">{OPENAI_SESSION_WARNING}</p>
    </div>
  );
}

export function ConsoleWarning() {
  return (
    <div className="rule-note rule-note--warn">
      <p>{CONSOLE_SESSION_WARNING_ZH}</p>
      <p lang="en">{CONSOLE_SESSION_WARNING}</p>
    </div>
  );
}

export const WARNING_MESSAGES: Record<string, string> = {
  committed_uncertain: "已保存，但服务器无法确认已写入磁盘；旧凭据已保留。请刷新后再保存一次。",
  cleanup_failed: "已保存，但旧凭据清理失败；请在服务器上解锁密钥环后手动删除旧条目。",
  host_refresh_failed: "已保存，但服务器刷新失败；重启 usage api serve 以确保生效。",
  credential_expired: "已保存；登录令牌已过期，等待 keepalive 续期或重新登录对应 CLI。",
};

export interface AccountFormProps {
  client: UsageClient;
  /** null creates a new account. */
  original: AccountConfig | null;
  capabilities: Capabilities;
  onSaved: (result: MutationResult) => void;
  onCancel: () => void;
  /** Session end, read-only, conflict and not-found are handled by the panel. */
  onError: (error: ApiError) => void;
  onDirty: (dirty: boolean) => void;
  /** Seed state (tests and re-renders); never carries a secret from storage. */
  initialDraft?: Draft;
  initialPrepared?: PrepareResult | null;
  /** A save failed in a way the server may still have committed: reload the list. */
  onUncertain?: () => void;
  /**
   * Set to the form's Escape handler; it returns true when the form consumed the
   * key (a save in flight, or an open inline confirmation), so the panel keeps it open.
   */
  escapeRef?: MutableRefObject<(() => boolean) | null>;
}

/** Failures the panel must see: it logs out, flips to read-only, or reloads. */
function panelFailure(failure: ApiError): boolean {
  if (failure.kind === "unauthorized" || failure.kind === "rate_limited") return true;
  if (failure.code === "read_only" || failure.code === "not_found") return true;
  return failure.kind === "conflict" && failure.code !== "discovery_busy";
}

export function AccountForm({
  client,
  original,
  capabilities,
  onSaved,
  onCancel,
  onError,
  onDirty,
  initialDraft,
  initialPrepared = null,
  onUncertain,
  escapeRef,
}: AccountFormProps) {
  const secureStore = capabilities.secure_store_available;
  const [draft, setDraft] = useState<Draft>(
    () => initialDraft ?? (original ? editDraft(original, secureStore) : newDraft("claude_subscription", secureStore)),
  );
  const [consoleKey, setConsoleKey] = useState("");
  const [prepared, setPrepared] = useState<PrepareResult | null>(initialPrepared);
  const [errors, setErrors] = useState<DraftErrors>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [preparing, setPreparing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [dirty, setDirty] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const prepareController = useRef<AbortController | null>(null);
  const base = useRef(original);

  useEffect(() => onDirty(dirty), [dirty, onDirty]);
  // Abort any request in flight when the form goes away; React drops the secrets with the state.
  useEffect(
    () => () => {
      controller.current?.abort();
      prepareController.current?.abort();
    },
    [],
  );

  // A reload after a conflict brings a new revision: untouched fields follow the
  // server and prepare results (bound to the old revision) are dropped.
  useEffect(() => {
    const previous = base.current;
    base.current = original;
    if (!original || !previous || previous.revision === original.revision) return;
    setDraft((d) => rebaseDraft(d, editDraft(previous, secureStore), editDraft(original, secureStore)));
    prepareController.current?.abort();
    prepareController.current = null;
    setPreparing(false);
    setPrepared(null);
    setConfirming(false);
  }, [original, secureStore]);

  useEffect(() => {
    if (!escapeRef) return;
    escapeRef.current = () => {
      const action = formEscape({ busy, confirming });
      if (action === "dismiss_confirm") setConfirming(false);
      return action !== "close";
    };
    return () => {
      escapeRef.current = null;
    };
  }, [escapeRef, busy, confirming]);

  const update = (patch: Partial<Draft>) => {
    setDraft((d) => ({ ...d, ...patch }));
    setDirty(true);
    setConfirming(false);
  };
  /** A prepare still in flight read the old inputs: its late result must not apply. */
  const abortPrepare = () => {
    prepareController.current?.abort();
    prepareController.current = null;
    setPreparing(false);
  };
  /** A change to what the prepare read covers invalidates its choices. */
  const resetPrepare = () => {
    abortPrepare();
    setPrepared(null);
    setDraft((d) => ({ ...d, prepareId: null, choiceId: null, preparedSecret: false }));
  };
  const chooseKind = (kind: Draft["kind"]) => {
    abortPrepare();
    setDraft((d) => ({ ...withKind(d, kind, original), source: "set" }));
    setConsoleKey("");
    setPrepared(null);
    setDirty(true);
    setConfirming(false);
  };
  const chooseProvider = (provider: ProviderId) => {
    abortPrepare();
    setDraft((d) => ({
      ...newDraft(provider, secureStore),
      label: d.label,
      // An untouched default follows the provider's own default (its polling floor).
      interval: d.interval.trim() === String(defaultInterval(d.provider)) ? String(defaultInterval(provider)) : d.interval,
      enabled: d.enabled,
    }));
    setConsoleKey("");
    setPrepared(null);
    setDirty(true);
  };

  const fail = (caught: unknown, secretKind: boolean, saving = false) => {
    const failure = caught instanceof ApiError ? caught : new ApiError("network");
    if (panelFailure(failure)) onError(failure);
    if (failure.code === "prepare_expired") resetPrepare();
    let message = failure.message;
    if (saving && saveUncertain(failure.kind)) {
      // The commit runs to completion on the server even when the response is lost.
      onUncertain?.();
      message += SAVE_UNCERTAIN_NOTE;
    }
    // No prepare record holds a manual secret, so it must be typed again.
    if (failure.code === "secure_store_unavailable" && secretKind) message += "请重新输入凭据。";
    if (failure.code === "discovery_busy" && failure.retryAfter !== null) {
      message = `读取请求过于频繁，请 ${failure.retryAfter} 秒后重试。`;
    }
    setError(message);
  };

  async function runPrepare() {
    if (preparing || busy) return;
    const referenceError = prepareReferenceError(draft);
    if (referenceError) {
      setErrors({ reference: referenceError });
      return;
    }
    const key = draft.kind === "console_session" && !creditsSection(draft, original) ? consoleKey : "";
    const body = prepareBody(draft, original, key);
    if (!body) return;
    // The key leaves page state as soon as it is sent.
    setConsoleKey("");
    setPrepared(null);
    setDraft((d) => ({ ...d, prepareId: null, choiceId: null, preparedSecret: false }));
    setError(null);
    setErrors({});
    setPreparing(true);
    const current = new AbortController();
    prepareController.current = current;
    try {
      const result = await client.prepare(body, current.signal);
      if (current.signal.aborted) return;
      setPrepared(result);
      setDraft((d) => ({ ...d, prepareId: result.prepare_id, choiceId: null, preparedSecret: key !== "" }));
      setDirty(true);
    } catch (caught) {
      if (!current.signal.aborted) fail(caught, false);
    } finally {
      if (prepareController.current === current) {
        prepareController.current = null;
        setPreparing(false);
      }
    }
  }

  /** Enter in a text field saves without a native submit (see SECRET_INPUT_PROPS). */
  const onFormKey = (event: KeyboardEvent<HTMLFormElement>) => {
    const target = event.target as HTMLInputElement;
    if (event.key !== "Enter" || target.tagName !== "INPUT") return;
    if (target.type !== "text" && target.type !== "password") return;
    event.preventDefault();
    void submit();
  };

  async function submit() {
    if (busy || preparing) return;
    const found = validateDraft(draft, original);
    setErrors(found);
    if (Object.keys(found).length) return;
    if (original && sourceChanged(draft, original) && !confirming) {
      setConfirming(true);
      return;
    }
    setConfirming(false);
    const secretKind = draft.source === "set" && needsSecret(draft.kind);
    const request = original ? updateBody(draft, original) : createBody(draft);
    // Secrets are cleared on submit; a failed manual save asks for the value again.
    setDraft((d) => ({ ...d, secret: "" }));
    setError(null);
    setBusy(true);
    const current = new AbortController();
    controller.current = current;
    try {
      const result = original
        ? await client.updateAccount(original.id, original.revision ?? "", request, current.signal)
        : await client.createAccount(request as ReturnType<typeof createBody>, current.signal);
      if (current.signal.aborted) return;
      setDirty(false);
      onSaved(result);
    } catch (caught) {
      if (!current.signal.aborted) fail(caught, secretKind, true);
    } finally {
      if (controller.current === current) controller.current = null;
      setBusy(false);
    }
  }

  const cancel = () => {
    // A save in flight may already be committed; closing would hide its result.
    if (busy) return;
    prepareController.current?.abort();
    controller.current?.abort();
    setDraft((d) => ({ ...d, secret: "" }));
    setConsoleKey("");
    setDirty(false);
    onCancel();
  };

  const kinds = allowedKinds(draft.provider);
  const set = draft.source === "set";
  const kind = draft.kind;
  const showPersist =
    set && (needsSecret(kind) || (kind === "console_session" && (consoleKey !== "" || draft.preparedSecret)));
  const sameSecretKind = original?.credential_kind === kind && needsSecret(kind);
  const reuseKey = canReuseSecret(kind, original);
  const credits = creditsSection(draft, original);
  const creditsSaved = creditsUsesSaved(draft, original);
  const creditsReady =
    creditsSaved ||
    (needsSecret(kind) ? draft.secret !== "" : draft.reference !== "custom" || validReference(kind, draft.path.trim()));
  const floor = POLL_FLOORS[draft.provider];

  return (
    <section className="acct-form" aria-labelledby="acct-form-title">
      <h2 className="acct-form__title" id="acct-form-title">
        {original ? `编辑 ${original.label}` : "添加账号"}
      </h2>
      <form
        className="acct-form__body"
        onSubmit={(event) => event.preventDefault()}
        onKeyDown={onFormKey}
        noValidate
        autoComplete="off"
      >
        {original ? (
          <p className="field">
            <span className="field__label">服务</span>
            <span>{providerName(draft.provider)}</span>
          </p>
        ) : (
          <fieldset className="field">
            <legend className="field__label">服务</legend>
            <div className="choice-grid">
              {formProviders().map((provider) => (
                <label key={provider} className="check">
                  <input
                    type="radio"
                    name="provider"
                    checked={draft.provider === provider}
                    onChange={() => chooseProvider(provider)}
                  />
                  <span>{providerName(provider)}</span>
                </label>
              ))}
            </div>
          </fieldset>
        )}

        <fieldset className="field">
          <legend className="field__label">凭据来源</legend>
          {original ? (
            <>
              <label className="check">
                <input
                  type="radio"
                  name="source"
                  checked={draft.source === "keep"}
                  onChange={() => update({ source: "keep" })}
                />
                <span>保持当前凭据（{STORAGE_LABELS[original.storage]}）</span>
              </label>
              {kinds.map((k) => (
                <label key={k} className="check">
                  <input type="radio" name="source" checked={set && kind === k} onChange={() => chooseKind(k)} />
                  <span>更换为{KIND_LABELS[k]}</span>
                </label>
              ))}
              <label className="check">
                <input
                  type="radio"
                  name="source"
                  checked={draft.source === "none"}
                  onChange={() => update({ source: "none" })}
                />
                <span>断开凭据</span>
              </label>
            </>
          ) : (
            <>
              {kinds.map((k) => (
                <label key={k} className="check">
                  <input type="radio" name="source" checked={set && kind === k} onChange={() => chooseKind(k)} />
                  <span>{KIND_LABELS[k]}</span>
                </label>
              ))}
              <label className="check">
                <input
                  type="radio"
                  name="source"
                  checked={draft.source === "none"}
                  onChange={() => update({ source: "none" })}
                />
                <span>无凭据</span>
              </label>
            </>
          )}
        </fieldset>

        {set && isFileKind(kind) ? (
          <fieldset className="field">
            <legend className="field__label">登录文件</legend>
            {canKeepReference(kind, original) ? (
              <label className="check">
                <input
                  type="radio"
                  name="reference"
                  checked={draft.reference === "current"}
                  onChange={() => {
                    update({ reference: "current" });
                    resetPrepare();
                  }}
                />
                <span>当前登录文件{original?.reference === "custom" ? "（自定义路径，已隐藏）" : ""}</span>
              </label>
            ) : null}
            <label className="check">
              <input
                type="radio"
                name="reference"
                checked={draft.reference === "default"}
                onChange={() => {
                  update({ reference: "default" });
                  resetPrepare();
                }}
              />
              <span>默认位置</span>
              <small className="mono">{DEFAULT_PATH_HELP[kind]}</small>
            </label>
            <label className="check">
              <input
                type="radio"
                name="reference"
                checked={draft.reference === "custom"}
                onChange={() => {
                  update({ reference: "custom" });
                  resetPrepare();
                }}
              />
              <span>服务器上的绝对路径</span>
            </label>
            {draft.reference === "custom" ? (
              <input
                type="text"
                aria-label="服务器上的绝对路径"
                autoComplete="off"
                spellCheck={false}
                placeholder="/…/auth.json"
                value={draft.path}
                onChange={(e) => {
                  update({ path: e.target.value });
                  resetPrepare();
                }}
              />
            ) : null}
            {original?.reference === "custom" && original.credential_kind === kind ? (
              <small className="field__help">当前：自定义路径（已隐藏）</small>
            ) : null}
            <small className="field__help">
              只读取服务器上属于服务进程用户、权限为 0600、文件名为 auth.json（Claude 为 .credentials.json）的文件；不会显示或上传文件内容。
            </small>
            <small className="field__help">keepalive 只维护服务启动时已存在的默认登录文件；自定义路径不会被自动续期。</small>
            {errors.reference ? <p className="form-error">{errors.reference}</p> : null}
          </fieldset>
        ) : null}

        {set && kind === "console_session" ? (
          <div className="field">
            <ConsoleWarning />
            <label className="field">
              <span className="field__label">sessionKey</span>
              <input
                {...SECRET_INPUT_PROPS}
                value={consoleKey}
                onChange={(e) => {
                  setConsoleKey(e.target.value);
                  setDirty(true);
                  // Also abandons a discovery still running for the previous key.
                  resetPrepare();
                }}
              />
              {reuseKey ? <small className="field__help">留空则使用已保存的凭据重新发现组织。</small> : null}
            </label>
          </div>
        ) : null}

        {set && needsPrepare(kind) ? (
          <div className="field">
            <button
              type="button"
              className="button button--quiet"
              onClick={runPrepare}
              disabled={preparing || busy || (kind === "console_session" && consoleKey === "" && !reuseKey)}
            >
              {preparing
                ? "正在读取…"
                : kind === "grok_auth_file"
                  ? "读取登录范围"
                  : consoleKey === "" && reuseKey
                    ? "重新发现组织（使用已保存的凭据）"
                    : "发现组织"}
            </button>
            {prepared ? (
              <ChoiceList
                prepared={prepared}
                value={draft.choiceId}
                onChange={(id) => update({ choiceId: id })}
                disabled={busy}
              />
            ) : null}
            {errors.choice ? <p className="form-error">{errors.choice}</p> : null}
          </div>
        ) : null}

        {draft.provider === "openai_platform" ? (
          <label className="field">
            <span className="field__label">OpenAI 组织 ID</span>
            <input
              type="text"
              autoComplete="off"
              spellCheck={false}
              autoCapitalize="off"
              placeholder={original ? "留空保留已保存的组织（不显示）" : "org-…"}
              value={draft.organizationId}
              onChange={(e) => update({ organizationId: e.target.value })}
            />
            <small className="field__help">
              在 platform.openai.com 的组织设置中查看（org- 开头）。余额读取绑定到这个组织；服务器不会回显已保存的组织 ID。
            </small>
            {errors.organization ? <p className="form-error">{errors.organization}</p> : null}
          </label>
        ) : null}

        {set && kind === "openai_platform_session" ? <OpenAIWarning /> : null}

        {set && needsSecret(kind) ? (
          <label className="field">
            <span className="field__label">{KIND_LABELS[kind]}</span>
            <input
              {...SECRET_INPUT_PROPS}
              value={draft.secret}
              placeholder={sameSecretKind ? "留空保留现有凭据" : undefined}
              onChange={(e) => {
                update({ secret: e.target.value });
                // A credits discovery read the previous bearer: its choice no longer applies.
                if (credits) resetPrepare();
              }}
            />
            {kind === "api_key" ? (
              <small className="field__help">API key 只在本地保存，不会启用订阅额度或余额读取。</small>
            ) : null}
            {errors.secret ? <p className="form-error">{errors.secret}</p> : null}
          </label>
        ) : null}

        {credits ? (
          <fieldset className="field">
            <legend className="field__label">Claude credits 余额</legend>
            <p className="field__help">{CREDITS_HELP}</p>
            <label className="check">
              <input
                type="radio"
                name="credits"
                checked={draft.credits === "none"}
                onChange={() => update({ credits: "none", choiceId: null })}
              />
              <span>不读取 credits 余额</span>
            </label>
            {canKeepCredits(draft, original) ? (
              <label className="check">
                <input
                  type="radio"
                  name="credits"
                  checked={draft.credits === "keep"}
                  onChange={() => update({ credits: "keep", choiceId: null })}
                />
                <span>保留已保存的组织（不显示组织 ID）</span>
              </label>
            ) : null}
            <button
              type="button"
              className="button button--quiet"
              onClick={runPrepare}
              disabled={preparing || busy || !creditsReady}
            >
              {preparing ? "正在读取…" : creditsSaved ? "发现组织（使用已保存的登录）" : "发现组织"}
            </button>
            {needsSecret(kind) && !creditsSaved ? (
              <small className="field__help">发现时会发送上面输入的令牌；保存时需使用同一个令牌。</small>
            ) : null}
            {prepared && prepared.kind === "claude_organization" ? (
              <ChoiceList
                prepared={prepared}
                value={draft.credits === "select" ? draft.choiceId : null}
                onChange={(id) => update({ credits: "select", choiceId: id })}
                disabled={busy}
              />
            ) : null}
            {errors.credits ? <p className="form-error">{errors.credits}</p> : null}
          </fieldset>
        ) : null}

        {showPersist ? (
          <StorageChoice
            persist={draft.persist}
            secureStore={secureStore}
            onChange={(persist) => update({ persist })}
            error={errors.persist}
          />
        ) : null}

        <fieldset className="field">
          <legend className="field__label">基本信息</legend>
          <label className="field">
            <span className="field__label">名称</span>
            <input
              type="text"
              autoComplete="off"
              maxLength={MAX_LABEL}
              required
              value={draft.label}
              onChange={(e) => update({ label: e.target.value })}
            />
            {errors.label ? <p className="form-error">{errors.label}</p> : null}
          </label>
          <label className="field">
            <span className="field__label">刷新间隔（秒）</span>
            <input
              type="text"
              inputMode="numeric"
              autoComplete="off"
              value={draft.interval}
              onChange={(e) => update({ interval: e.target.value })}
            />
            <small className="field__help">
              30–3600{floor ? `；${providerName(draft.provider)} 最少按 ${floor} 秒刷新` : ""}
            </small>
            {errors.interval ? <p className="form-error">{errors.interval}</p> : null}
          </label>
          <label className="check">
            <input type="checkbox" checked={draft.enabled} onChange={(e) => update({ enabled: e.target.checked })} />
            <span>启用</span>
          </label>
        </fieldset>

        {confirming ? (
          <div className="rule-note rule-note--warn" role="alert">
            <p>将替换/移除现有凭据引用？旧值不会显示。只删除本工具保存的旧密钥；外部登录文件不会被删除。</p>
            <p className="acct-form__confirm">
              <button type="button" className="text-btn text-btn--danger" disabled={busy} onClick={() => void submit()}>
                确认
              </button>
              <button type="button" className="text-btn" onClick={() => setConfirming(false)}>
                取消
              </button>
            </p>
          </div>
        ) : null}

        {error ? (
          <p className="form-error" role="alert">
            {error}
          </p>
        ) : null}

        <div className="acct-form__actions">
          <button
            type="button"
            className="button"
            disabled={busy || preparing || confirming}
            onClick={() => void submit()}
          >
            {busy ? "正在保存…" : original ? "保存" : "添加账号"}
          </button>
          <button type="button" className="button button--quiet" onClick={cancel} disabled={busy}>
            取消
          </button>
        </div>
      </form>
    </section>
  );
}
