// Pure account-form logic: allowed credential kinds per provider, client-side
// validation (the server validates again), and minimal request bodies. Secrets
// appear only in manual bearer / API key sources and in Console prepare bodies;
// a Console save carries the prepare record and choice, never the key itself.

import type {
  AccountConfig,
  CreateAccountBody,
  CredentialKind,
  PrepareBody,
  ProviderId,
  SourceBody,
  StorageClass,
  UpdateAccountBody,
} from "./types";
import { CREDENTIAL_LABELS } from "./semantics";

/** Display order (accounts.KINDS). */
const KIND_ORDER: CredentialKind[] = [
  "claude_code_file",
  "grok_auth_file",
  "codex_auth_file",
  "console_session",
  "manual_bearer",
  "api_key",
];

/** domain.READ_CREDENTIAL_KINDS; API keys are added for every provider except Codex. */
const READ_KINDS: Record<ProviderId, CredentialKind[]> = {
  claude_subscription: ["claude_code_file", "manual_bearer"],
  claude_platform: ["console_session"],
  codex_subscription: ["codex_auth_file"],
  grok_subscription: ["grok_auth_file", "manual_bearer"],
};

export function allowedKinds(provider: ProviderId): CredentialKind[] {
  const allowed = new Set(READ_KINDS[provider]);
  if (provider !== "codex_subscription") allowed.add("api_key");
  return KIND_ORDER.filter((kind) => allowed.has(kind));
}

export function defaultKind(provider: ProviderId): CredentialKind {
  switch (provider) {
    case "claude_subscription":
      return "claude_code_file";
    case "claude_platform":
      return "console_session";
    case "codex_subscription":
      return "codex_auth_file";
    case "grok_subscription":
      return "grok_auth_file";
  }
}

export function isFileKind(kind: CredentialKind | null): boolean {
  return kind === "claude_code_file" || kind === "codex_auth_file" || kind === "grok_auth_file";
}

/** Kinds that need an explicit server-side read and choice before saving. */
export function needsPrepare(kind: CredentialKind | null): kind is "grok_auth_file" | "console_session" {
  return kind === "grok_auth_file" || kind === "console_session";
}

/** Kinds whose secret travels in the save body itself. */
export function needsSecret(kind: CredentialKind | null): boolean {
  return kind === "manual_bearer" || kind === "api_key";
}

export const KIND_LABELS: Record<CredentialKind, string> = CREDENTIAL_LABELS as Record<CredentialKind, string>;

export const STORAGE_LABELS: Record<StorageClass, string> = {
  external_file: "外部登录文件",
  session: "仅本次会话",
  keyring: "加密密钥环",
  none: "无凭据",
};

export const DEFAULT_PATH_HELP: Partial<Record<CredentialKind, string>> = {
  claude_code_file: "$CLAUDE_CONFIG_DIR/.credentials.json，未设置时 ~/.claude/.credentials.json",
  codex_auth_file: "$CODEX_HOME/auth.json，未设置时 ~/.codex/auth.json",
  grok_auth_file: "$GROK_HOME/auth.json，未设置时 ~/.grok/auth.json",
};

export function referenceBasename(kind: CredentialKind): string {
  return kind === "claude_code_file" ? ".credentials.json" : "auth.json";
}

export const MIN_INTERVAL = 30;
export const MAX_INTERVAL = 3600;
export const MAX_LABEL = 80;

/**
 * Form state. `source` is "keep" (edit only: no source key is sent), "none"
 * (create: no credential; edit: detach) or "set" (a new or re-read source of `kind`).
 * `reference` "current" re-reads the saved Grok login file without naming it.
 */
export interface Draft {
  editing: boolean;
  provider: ProviderId;
  label: string;
  interval: string;
  enabled: boolean;
  source: "keep" | "none" | "set";
  kind: CredentialKind;
  reference: "default" | "custom" | "current";
  path: string;
  /** Manual bearer / API key only. Console keys are sent with prepare, then cleared. */
  secret: string;
  persist: boolean | null;
  prepareId: string | null;
  choiceId: string | null;
  /** Whether the prepare record holds a newly entered Console key. */
  preparedSecret: boolean;
}

export function newDraft(provider: ProviderId, secureStore: boolean): Draft {
  return {
    editing: false,
    provider,
    label: "",
    interval: "60",
    enabled: true,
    source: "set",
    kind: defaultKind(provider),
    reference: "default",
    path: "",
    secret: "",
    persist: secureStore,
    prepareId: null,
    choiceId: null,
    preparedSecret: false,
  };
}

export function editDraft(account: AccountConfig, secureStore: boolean): Draft {
  return {
    ...newDraft(account.provider, secureStore),
    editing: true,
    label: account.label,
    interval: String(account.poll_interval_seconds),
    enabled: account.enabled,
    source: "keep",
    kind: account.credential_kind ?? defaultKind(account.provider),
  };
}

/** A different provider or kind resets everything that belonged to the old one. */
export function withKind(draft: Draft, kind: CredentialKind, original: AccountConfig | null): Draft {
  return {
    ...draft,
    kind,
    reference: canKeepReference(kind, original) ? "current" : "default",
    path: "",
    secret: "",
    prepareId: null,
    choiceId: null,
    preparedSecret: false,
  };
}

/** Grok can re-read its saved login file without the page ever learning the path. */
export function canKeepReference(kind: CredentialKind, original: AccountConfig | null): boolean {
  return kind === "grok_auth_file" && original?.credential_kind === "grok_auth_file";
}

/** Console can rediscover organizations with its saved key (edit only). */
export function canReuseSecret(kind: CredentialKind, original: AccountConfig | null): boolean {
  return kind === "console_session" && original?.credential_kind === "console_session";
}

export function validReference(kind: CredentialKind, path: string): boolean {
  if (!path.startsWith("/") || path.length > 4096) return false;
  for (const char of path) {
    const code = char.charCodeAt(0);
    if (code < 32 || code === 127) return false;
  }
  if (path.includes("//") || path.includes("/../") || path.includes("/./")) return false;
  return path.endsWith(`/${referenceBasename(kind)}`);
}

export type DraftField = "label" | "interval" | "reference" | "choice" | "secret" | "persist";
export type DraftErrors = Partial<Record<DraftField, string>>;

function secretRequired(draft: Draft, original: AccountConfig | null): boolean {
  return needsSecret(draft.kind) && original?.credential_kind !== draft.kind;
}

export function validateDraft(draft: Draft, original: AccountConfig | null = null): DraftErrors {
  const errors: DraftErrors = {};
  const label = draft.label.trim();
  if (!label) errors.label = "名称不能为空。";
  else if ([...label].length > MAX_LABEL) errors.label = `名称最多 ${MAX_LABEL} 个字符。`;
  const interval = draft.interval.trim();
  const seconds = Number(interval);
  if (!/^\d+$/.test(interval) || seconds < MIN_INTERVAL || seconds > MAX_INTERVAL) {
    errors.interval = "刷新间隔必须是 30 到 3600 之间的整数。";
  }
  if (draft.source !== "set") return errors;
  if (isFileKind(draft.kind) && !needsPrepare(draft.kind) && draft.reference === "custom") {
    if (!validReference(draft.kind, draft.path.trim())) {
      errors.reference = `请填写服务器上 ${referenceBasename(draft.kind)} 的绝对路径（不含 .. 或 //）。`;
    }
  }
  if (needsPrepare(draft.kind) && (draft.prepareId === null || draft.choiceId === null)) {
    errors.choice = "请先读取并明确选择。";
  }
  if (needsSecret(draft.kind)) {
    if (draft.secret === "" && secretRequired(draft, original)) errors.secret = "请输入凭据。";
  }
  if (secretStored(draft) && draft.persist === null) errors.persist = "请选择凭据保存方式。";
  return errors;
}

/** Whether saving will store a new secret (and so needs a storage choice). */
export function secretStored(draft: Draft): boolean {
  if (draft.source !== "set") return false;
  if (needsSecret(draft.kind)) return draft.secret !== "";
  return draft.kind === "console_session" && draft.preparedSecret;
}

/** The prepare-reference validation, before 读取登录范围 is allowed. */
export function prepareReferenceError(draft: Draft): string | null {
  if (draft.kind !== "grok_auth_file" || draft.reference !== "custom") return null;
  return validReference(draft.kind, draft.path.trim())
    ? null
    : "请填写服务器上 auth.json 的绝对路径（不含 .. 或 //）。";
}

/** The source to send: undefined means "keep" (no key), null means none/detach. */
export function sourceBody(draft: Draft): SourceBody | null | undefined {
  if (draft.source === "keep") return undefined;
  if (draft.source === "none") return null;
  const kind = draft.kind;
  if (needsPrepare(kind)) {
    const body: SourceBody = {
      credential_kind: kind,
      prepare_id: draft.prepareId ?? "",
      choice_id: draft.choiceId ?? "",
    };
    if (kind === "console_session" && draft.preparedSecret) body.persist = draft.persist ?? false;
    return body;
  }
  if (isFileKind(kind)) {
    return { credential_kind: kind, reference: draft.reference === "custom" ? draft.path.trim() : "default" };
  }
  if (draft.secret === "") return { credential_kind: kind };
  return { credential_kind: kind, secret: draft.secret, persist: draft.persist ?? false };
}

export function createBody(draft: Draft): CreateAccountBody {
  return {
    provider: draft.provider,
    label: draft.label.trim(),
    poll_interval_seconds: Number(draft.interval.trim()),
    enabled: draft.enabled,
    source: sourceBody(draft) ?? null,
  };
}

/** Only the fields that differ; `{}` is a valid, revision-checked no-op. */
export function updateBody(draft: Draft, original: AccountConfig): UpdateAccountBody {
  const body: UpdateAccountBody = {};
  const label = draft.label.trim();
  if (label !== original.label) body.label = label;
  const seconds = Number(draft.interval.trim());
  if (seconds !== original.poll_interval_seconds) body.poll_interval_seconds = seconds;
  if (draft.enabled !== original.enabled) body.enabled = draft.enabled;
  const source = sourceBody(draft);
  if (source !== undefined) body.source = source;
  return body;
}

/** An edit that replaces or removes an existing credential reference needs confirmation. */
export function sourceChanged(draft: Draft, original: AccountConfig | null): boolean {
  return original !== null && original.credential_kind !== null && draft.source !== "keep";
}

export function prepareBody(draft: Draft, original: AccountConfig | null, secret: string): PrepareBody | null {
  if (!needsPrepare(draft.kind)) return null;
  const body: PrepareBody = {
    account_id: original?.id ?? null,
    revision: original?.revision ?? null,
    provider: draft.provider,
    credential_kind: draft.kind,
  };
  if (draft.kind === "grok_auth_file") {
    if (draft.reference === "custom") body.reference = draft.path.trim();
    else if (draft.reference === "default" || !canKeepReference(draft.kind, original)) body.reference = "default";
  } else if (secret !== "") {
    body.secret = secret;
  }
  return body;
}

/**
 * Rebase an open edit onto a reloaded account (after a revision conflict).
 * `before` and `after` are `editDraft` of the old and the reloaded account: a field
 * the user left untouched follows the server, so a retry cannot silently revert
 * another client's change. Prepare results are bound to the old revision and dropped.
 */
export function rebaseDraft(draft: Draft, before: Draft, after: Draft): Draft {
  const next: Record<string, unknown> = { ...draft };
  for (const key of Object.keys(after) as (keyof Draft)[]) {
    if (draft[key] === before[key]) next[key] = after[key];
  }
  return { ...(next as unknown as Draft), prepareId: null, choiceId: null, preparedSecret: false };
}

/** Escape inside an open form, innermost first: a save in flight, then the inline confirm. */
export type FormEscape = "ignore" | "dismiss_confirm" | "close";

export function formEscape(state: { busy: boolean; confirming: boolean }): FormEscape {
  // A save may already be committed on the server: closing would hide its result.
  if (state.busy) return "ignore";
  if (state.confirming) return "dismiss_confirm";
  return "close";
}

/** A failed save whose request may still have been committed by the server. */
export function saveUncertain(kind: string): boolean {
  return kind === "timeout" || kind === "network" || kind === "invalid_response";
}

export const SAVE_UNCERTAIN_NOTE = "服务器可能已经保存；已重新载入账号列表，请确认后再决定是否重试。";
