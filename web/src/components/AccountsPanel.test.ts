import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { UsageClient } from "../api";
import { editDraft, newDraft, withKind } from "../accountForm";
import { createMockClient } from "../mock/client";
import css from "../styles.css?raw";
import type { AccountConfig, Capabilities, PrepareResult } from "../types";
import {
  AccountForm,
  CONSOLE_SESSION_WARNING,
  CONSOLE_SESSION_WARNING_ZH,
  OPENAI_SESSION_WARNING,
  OPENAI_SESSION_WARNING_ZH,
} from "./AccountForm";
import { AccountsPanel, LOST_SESSION_NOTE, READ_ONLY_BANNER } from "./AccountsPanel";

const WRITABLE: Capabilities = { writable: true, secure_store_available: true };
const NO_KEYRING: Capabilities = { writable: true, secure_store_available: false };
const READ: Capabilities = { writable: false, secure_store_available: false };
const REV = "0123456789abcdef0123456789abcdef";
const ORG_ID = "9e8d7c6b-5a49-4382-9170-6f5e4d3c2b1a";

function config(id: string, label: string, patch: Partial<AccountConfig> = {}): AccountConfig {
  return {
    id,
    provider: "codex_subscription",
    label,
    enabled: true,
    poll_interval_seconds: 60,
    effective_poll_interval_seconds: 60,
    credential_kind: "codex_auth_file",
    storage: "external_file",
    reference: "default",
    session_available: null,
    scope_selected: false,
    organization_selected: false,
    revision: REV,
    ...patch,
  };
}

const ACCOUNTS = [
  config("11111111-1111-4111-8111-111111111111", "Codex 主账号"),
  config("22222222-2222-4222-8222-222222222222", "Console", {
    provider: "claude_platform",
    credential_kind: "console_session",
    storage: "session",
    reference: null,
    session_available: false,
    organization_selected: true,
  }),
];

const client = {} as UsageClient;
const noop = () => undefined;

function panel(capabilities: Capabilities, accounts = ACCOUNTS): string {
  return renderToStaticMarkup(
    createElement(AccountsPanel, {
      client,
      capabilities,
      onCapabilities: noop,
      onChanged: noop,
      onLogout: noop,
      onClose: noop,
      menuOpen: false,
      initial: { accounts, capabilities },
    }),
  );
}

function form(props: Partial<Parameters<typeof AccountForm>[0]> = {}): string {
  return renderToStaticMarkup(
    createElement(AccountForm, {
      client,
      original: null,
      capabilities: WRITABLE,
      onSaved: noop,
      onCancel: noop,
      onError: noop,
      onDirty: noop,
      ...props,
    }),
  );
}

function text(html: string): string {
  return html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");
}

describe("AccountsPanel", () => {
  it("shows the read-only banner and no controls on a read-only server", () => {
    const html = panel(READ);
    expect(html).toContain(READ_ONLY_BANNER);
    expect(html).not.toContain("acct__grip");
    // The only control is the way back to the board.
    expect(html.match(/<button/g)).toHaveLength(1);
    expect(text(html)).toContain("返回仪表盘");
    for (const action of ["停用", "重新连接", "删除", "添加账号", "上移"]) expect(text(html)).not.toContain(action);
    expect(text(html)).toContain("Codex 主账号");
  });

  it("labels each grip with its position and offers the row actions", () => {
    const html = panel(WRITABLE);
    expect(html).toContain('aria-label="移动 Codex 主账号，第 1 / 2 个"');
    expect(html).toContain('aria-label="移动 Console，第 2 / 2 个"');
    for (const action of ["编辑", "停用", "重新连接", "删除", "上移", "下移"]) expect(text(html)).toContain(action);
    expect(html).not.toContain(READ_ONLY_BANNER);
  });

  it("flags a lost session-only credential", () => {
    const html = panel(WRITABLE);
    expect(html).toContain(LOST_SESSION_NOTE);
    expect(html.split(LOST_SESSION_NOTE)).toHaveLength(2);
  });

  it("never shows ids or revisions as text", () => {
    const visible = text(panel(WRITABLE));
    expect(visible).not.toContain(REV);
    for (const account of ACCOUNTS) expect(visible).not.toContain(account.id);
  });

  it("shows the writable and read-only empty states", () => {
    expect(text(panel(WRITABLE, []))).toContain("添加账号");
    expect(text(panel(WRITABLE, []))).toContain("也可以在服务器上运行 usage accounts add");
    expect(text(panel(READ, []))).toContain("服务器还没有配置账号。在服务器上运行 usage accounts add，然后重启 usage api serve。");
  });
});

describe("AccountForm", () => {
  it("shows the Console warning, in Chinese and English, before the masked key input", () => {
    const html = form({ initialDraft: newDraft("claude_platform", true) });
    const zh = html.indexOf(CONSOLE_SESSION_WARNING_ZH);
    const en = html.indexOf(CONSOLE_SESSION_WARNING);
    const input = html.indexOf('type="password"');
    expect(zh).toBeGreaterThan(-1);
    expect(en).toBeGreaterThan(zh);
    expect(input).toBeGreaterThan(en);
    expect(html).toContain('<p lang="en">');
    const tag = /<input type="password"[^>]*>/.exec(html)?.[0] ?? "";
    // Browsers ignore autocomplete="off" on password fields.
    expect(tag).toMatch(/autocomplete="new-password"/i);
    expect(tag).toContain('data-1p-ignore="true"');
    expect(tag).toContain('data-lpignore="true"');
    expect(tag).toContain('data-bwignore="true"');
    expect(tag).toContain('spellcheck="false"');
    // No native submit fires while a password field is filled.
    expect(html).not.toContain('type="submit"');
  });

  it("masks manual secrets and disables the keyring when the server has none", () => {
    const manual = withKind(newDraft("claude_subscription", false), "manual_bearer", null);
    const html = form({ capabilities: NO_KEYRING, initialDraft: manual });
    const tag = /<input type="password"[^>]*>/.exec(html)?.[0] ?? "";
    expect(tag).toMatch(/autocomplete="new-password"/i);
    expect(tag).toContain('data-1p-ignore="true"');
    expect(html).not.toContain('type="submit"');
    const keyring = /<input type="radio" name="persist"[^>]*>(?=<span>加密保存)/.exec(html)?.[0] ?? "";
    expect(keyring).toContain("disabled");
    expect(html).toContain("服务器没有可用的加密密钥环（例如 Railway 容器）");
    const session = /<input type="radio" name="persist"[^>]*>(?=<span>仅本次会话)/.exec(html)?.[0] ?? "";
    expect(session).toContain("checked");
    expect(session).not.toContain("disabled");
  });

  it("numbers nameless organizations, marks the current one and preselects nothing", () => {
    const prepared: PrepareResult = {
      prepare_id: "prep",
      expires_in: 300,
      kind: "console_organization",
      choices: [
        { id: "c1", label: null, legacy: false, current: false },
        { id: "c2", label: "Research", legacy: false, current: true },
      ],
    };
    const original = config("33333333-3333-4333-8333-333333333333", "Org", {
      provider: "claude_platform",
      credential_kind: "console_session",
      storage: "keyring",
      reference: null,
    });
    const draft = { ...withKind(editDraft(original, true), "console_session", original), source: "set" as const, prepareId: "prep" };
    const html = form({ original, initialDraft: draft, initialPrepared: prepared });
    expect(text(html)).toContain("组织 1");
    expect(text(html)).toContain("Research（当前）");
    expect(html).not.toContain(ORG_ID);
    expect(/name="prepare-choice"[^>]*checked/.test(html)).toBe(false);
    expect(text(html)).toContain("请明确选择组织；不会自动选择。");
    expect(text(html)).toContain("重新发现组织（使用已保存的凭据）");
  });

  it("numbers Grok scopes and marks the legacy key", () => {
    const prepared: PrepareResult = {
      prepare_id: "prep",
      expires_in: 300,
      kind: "grok_scope",
      choices: [
        { id: "c1", label: null, legacy: false, current: false },
        { id: "c2", label: null, legacy: true, current: false },
      ],
    };
    const html = form({ initialDraft: { ...newDraft("grok_subscription", true), prepareId: "prep" }, initialPrepared: prepared });
    expect(text(html)).toContain("Grok 范围 1");
    expect(text(html)).toContain("Grok 范围 2（旧版 accounts.x.ai 登录）");
    expect(text(html)).toContain("请明确选择要读取的范围。");
  });

  it("offers keep, replace and detach on edit and hides a custom path", () => {
    const original = config("44444444-4444-4444-8444-444444444444", "Custom", { reference: "custom" });
    const html = form({ original });
    expect(text(html)).toContain("保持当前凭据（外部登录文件）");
    expect(text(html)).toContain("断开凭据");
    expect(text(html)).toContain("编辑 Custom");
  });
});

describe("mock client", () => {
  it("lists demo accounts read-only and rejects every write with read_only", async () => {
    const mock = createMockClient({ baseUrl: "http://mock.invalid/healthy", token: "x" });
    const list = await mock.accounts();
    expect(list.capabilities).toEqual({ writable: false, secure_store_available: false });
    expect(list.accounts.length).toBeGreaterThan(0);
    expect(list.accounts.every((a) => a.storage === "none" && a.revision === null)).toBe(true);
    const writes = [
      mock.createAccount({ provider: "codex_subscription", label: "x", source: null }),
      mock.updateAccount("a", "r", {}),
      mock.removeAccount("a", "r"),
      mock.reorderAccounts([]),
      mock.reconnectAccount("a"),
      mock.prepare({ account_id: null, revision: null, credential_kind: "grok_auth_file" }),
    ];
    for (const write of writes) await expect(write).rejects.toMatchObject({ kind: "forbidden", status: 403, code: "read_only" });
  });
});

describe("account styles", () => {
  function rule(selector: string): string {
    const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    return new RegExp(`(?:^|\\n)${escaped}\\s*\\{([^}]*)\\}`).exec(css)?.[1] ?? "";
  }

  it("gives the grip a 44 px touch target with no browser panning", () => {
    const grip = rule(".acct__grip");
    expect(grip).toMatch(/touch-action:\s*none/);
    expect(grip).toMatch(/min-width:\s*44px/);
    expect(grip).toMatch(/min-height:\s*44px/);
  });

  it("drops every transition under reduced motion, including the new ones", () => {
    expect(rule(".acct")).toMatch(/transition:/);
    const reduced = /@media \(prefers-reduced-motion: reduce\)\s*\{([\s\S]*?)\n\}/.exec(css)?.[1] ?? "";
    expect(reduced).toMatch(/\*, \*::before, \*::after\s*\{[^}]*transition:\s*none !important/);
  });

  it("separates the delete confirmation buttons", () => {
    expect(rule(".acct__confirm p:last-child")).toMatch(/display:\s*flex/);
    expect(rule(".acct__confirm p:last-child")).toMatch(/gap:/);
  });

  it("lets a long check label wrap beside its control", () => {
    expect(rule(".check > span")).toMatch(/min-width:\s*0/);
    expect(rule(".check > span")).toMatch(/flex:\s*1 1 0%/);
    expect(rule(".check input")).toMatch(/flex:\s*none/);
  });

  it("uses tokens only for the new rules", () => {
    const start = css.indexOf("/* -------------------------------------------------------------- accounts */");
    const end = css.indexOf("/* ------------------------------------------------------------ breakpoints */");
    expect(start).toBeGreaterThan(-1);
    expect(css.slice(start, end)).not.toMatch(/#[0-9a-f]{3,8}\b|rgba?\(/i);
  });
});

describe("AccountForm: OpenAI Platform and Claude credits", () => {
  it("shows the OpenAI session warning, in Chinese and English, before the masked key input", () => {
    const html = form({ initialDraft: newDraft("openai_platform", true) });
    const zh = html.indexOf(OPENAI_SESSION_WARNING_ZH);
    const en = html.indexOf(OPENAI_SESSION_WARNING);
    const input = html.indexOf('type="password"');
    expect(zh).toBeGreaterThan(-1);
    expect(en).toBeGreaterThan(zh);
    expect(input).toBeGreaterThan(en);
    const tag = /<input type="password"[^>]*>/.exec(html)?.[0] ?? "";
    expect(tag).toMatch(/autocomplete="new-password"/i);
    expect(tag).toContain('data-1p-ignore="true"');
    expect(tag).toContain('data-lpignore="true"');
    expect(tag).toContain('data-bwignore="true"');
    expect(html).not.toContain('type="submit"');
    expect(text(html)).toContain("OpenAI 组织 ID");
    expect(text(html)).toContain("OpenAI Platform 最少按 300 秒刷新");
    // Only the dashboard session kind is offered (no API key source).
    expect(text(html)).not.toContain("API key 只在本地保存");
    expect(html.match(/name="source"/g)).toHaveLength(2);
    // The Console warning belongs to the Console kind only.
    expect(html).not.toContain(CONSOLE_SESSION_WARNING_ZH);
  });

  it("never prefills or echoes a saved OpenAI organization", () => {
    const original = config("44444444-4444-4444-8444-444444444444", "OpenAI", {
      provider: "openai_platform",
      credential_kind: "openai_platform_session",
      storage: "keyring",
      reference: null,
      organization_selected: true,
    });
    const html = form({ original, initialDraft: editDraft(original, true) });
    expect(text(html)).toContain("OpenAI Platform");
    expect(html).toContain("留空保留已保存的组织（不显示）");
    expect(/<input type="text"[^>]*placeholder="留空保留已保存的组织（不显示）"[^>]*value=""/.test(html)).toBe(true);
  });

  it("offers optional credits discovery for a Claude login and preselects nothing", () => {
    const fresh = form({ initialDraft: newDraft("claude_subscription", true) });
    expect(text(fresh)).toContain("Claude credits 余额");
    expect(/name="credits"[^>]*checked/.test(fresh)).toBe(true);
    expect(text(fresh)).toContain("不读取 credits 余额");
    expect(text(fresh)).not.toContain("保留已保存的组织");
    const prepared: PrepareResult = {
      prepare_id: "prep",
      expires_in: 300,
      kind: "claude_organization",
      choices: [{ id: "c1", label: null, legacy: false, current: true }],
    };
    const original = config("55555555-5555-4555-8555-555555555555", "Claude", {
      provider: "claude_subscription",
      credential_kind: "claude_code_file",
      organization_selected: true,
    });
    const html = form({ original, initialDraft: { ...editDraft(original, true), prepareId: "prep" }, initialPrepared: prepared });
    expect(text(html)).toContain("保留已保存的组织（不显示组织 ID）");
    expect(text(html)).toContain("发现组织（使用已保存的登录）");
    expect(text(html)).toContain("组织 1（当前）");
    expect(/name="prepare-choice"[^>]*checked/.test(html)).toBe(false);
    expect(html).not.toContain(ORG_ID);
    // An API key source has no credits section.
    const key = withKind(newDraft("claude_subscription", true), "api_key", null);
    expect(text(form({ initialDraft: key }))).not.toContain("Claude credits 余额");
  });
});
