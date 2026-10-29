import { describe, expect, it } from "vitest";
import {
  allowedKinds,
  createBody,
  defaultKind,
  editDraft,
  formEscape,
  needsPrepare,
  needsSecret,
  newDraft,
  prepareBody,
  rebaseDraft,
  saveUncertain,
  sourceChanged,
  updateBody,
  validateDraft,
  validReference,
  withKind,
  type Draft,
} from "./accountForm";
import type { AccountConfig } from "./types";

const SECRET = "sk-very-secret-value";

function account(patch: Partial<AccountConfig> = {}): AccountConfig {
  return {
    id: "0f0e0d0c-0b0a-4908-8706-050403020100",
    provider: "claude_subscription",
    label: "Work",
    enabled: true,
    poll_interval_seconds: 60,
    effective_poll_interval_seconds: 180,
    credential_kind: "claude_code_file",
    storage: "external_file",
    reference: "default",
    session_available: null,
    scope_selected: false,
    organization_selected: false,
    revision: "0123456789abcdef0123456789abcdef",
    ...patch,
  };
}

function draft(patch: Partial<Draft>): Draft {
  return { ...newDraft("claude_subscription", true), label: "Work", ...patch };
}

describe("kinds", () => {
  it("lists the provider's kinds in display order; Codex has no API key or bearer", () => {
    expect(allowedKinds("claude_subscription")).toEqual(["claude_code_file", "manual_bearer", "api_key"]);
    expect(allowedKinds("claude_platform")).toEqual(["console_session", "api_key"]);
    expect(allowedKinds("codex_subscription")).toEqual(["codex_auth_file"]);
    expect(allowedKinds("grok_subscription")).toEqual(["grok_auth_file", "manual_bearer", "api_key"]);
  });

  it("defaults each provider to its first-party source", () => {
    expect(defaultKind("claude_subscription")).toBe("claude_code_file");
    expect(defaultKind("codex_subscription")).toBe("codex_auth_file");
    expect(defaultKind("grok_subscription")).toBe("grok_auth_file");
    expect(defaultKind("claude_platform")).toBe("console_session");
    expect(newDraft("codex_subscription", false).reference).toBe("default");
  });

  it("classifies prepare and secret kinds", () => {
    expect(needsPrepare("grok_auth_file")).toBe(true);
    expect(needsPrepare("console_session")).toBe(true);
    expect(needsPrepare("codex_auth_file")).toBe(false);
    expect(needsSecret("manual_bearer")).toBe(true);
    expect(needsSecret("api_key")).toBe(true);
    expect(needsSecret("console_session")).toBe(false);
  });
});

describe("validation", () => {
  it("checks label and interval", () => {
    expect(validateDraft(draft({ label: "  " })).label).toBeDefined();
    expect(validateDraft(draft({ label: "x".repeat(81) })).label).toBeDefined();
    expect(validateDraft(draft({ label: "x".repeat(80) })).label).toBeUndefined();
    for (const bad of ["29", "3601", "60.5", "abc", "", "-60"]) {
      expect(validateDraft(draft({ interval: bad })).interval).toBeDefined();
    }
    expect(validateDraft(draft({ interval: "30" }))).toEqual({});
    expect(validateDraft(draft({ interval: "3600" }))).toEqual({});
  });

  it("requires the kind's basename and a normalized absolute path", () => {
    expect(validReference("claude_code_file", "/root/.claude/.credentials.json")).toBe(true);
    expect(validReference("claude_code_file", "/root/.claude/auth.json")).toBe(false);
    expect(validReference("codex_auth_file", "/root/.codex/auth.json")).toBe(true);
    expect(validReference("grok_auth_file", "/srv/grok/auth.json")).toBe(true);
    expect(validReference("codex_auth_file", "relative/auth.json")).toBe(false);
    expect(validReference("codex_auth_file", "/a/../auth.json")).toBe(false);
    expect(validReference("codex_auth_file", "/a//auth.json")).toBe(false);
    expect(validReference("codex_auth_file", "/a/auth.json.bak")).toBe(false);
    expect(validReference("codex_auth_file", "/a/\u0001/auth.json")).toBe(false);
    const custom = draft({ reference: "custom", path: "/etc/passwd" });
    expect(validateDraft(custom).reference).toBeDefined();
  });

  it("requires an explicit choice after prepare", () => {
    const grok = { ...newDraft("grok_subscription", true), label: "G" };
    expect(validateDraft(grok).choice).toBeDefined();
    expect(validateDraft({ ...grok, prepareId: "p" }).choice).toBeDefined();
    expect(validateDraft({ ...grok, prepareId: "p", choiceId: "c1" })).toEqual({});
  });

  it("requires a secret for a new manual source and a storage choice when one is present", () => {
    const manual = withKind(draft({}), "manual_bearer", null);
    expect(validateDraft(manual).secret).toBeDefined();
    expect(validateDraft({ ...manual, secret: SECRET, persist: null }).persist).toBeDefined();
    expect(validateDraft({ ...manual, secret: SECRET, persist: false })).toEqual({});
    // Same kind on edit: blank keeps the existing secret.
    const original = account({ credential_kind: "manual_bearer", storage: "keyring", reference: null });
    const keep = { ...withKind(editDraft(original, true), "manual_bearer", original), source: "set" as const };
    expect(validateDraft(keep, original)).toEqual({});
  });
});

describe("bodies", () => {
  it("creates with every field and a default file reference", () => {
    expect(createBody(draft({ interval: "90" }))).toEqual({
      provider: "claude_subscription",
      label: "Work",
      poll_interval_seconds: 90,
      enabled: true,
      source: { credential_kind: "claude_code_file", reference: "default" },
    });
    expect(createBody(draft({ source: "none" })).source).toBeNull();
    expect(createBody(draft({ reference: "custom", path: " /h/.claude/.credentials.json " })).source).toEqual({
      credential_kind: "claude_code_file",
      reference: "/h/.claude/.credentials.json",
    });
  });

  it("sends only what changed on edit; {} is a no-op and source:null detaches", () => {
    const original = account();
    const unchanged = editDraft(original, true);
    expect(updateBody(unchanged, original)).toEqual({});
    expect(updateBody({ ...unchanged, label: " Home " }, original)).toEqual({ label: "Home" });
    expect(updateBody({ ...unchanged, enabled: false, interval: "300" }, original)).toEqual({
      enabled: false,
      poll_interval_seconds: 300,
    });
    expect(updateBody({ ...unchanged, source: "none" }, original)).toEqual({ source: null });
    expect(sourceChanged(unchanged, original)).toBe(false);
    expect(sourceChanged({ ...unchanged, source: "none" }, original)).toBe(true);
    expect(sourceChanged({ ...unchanged, source: "set" }, account({ credential_kind: null, storage: "none" }))).toBe(
      false,
    );
  });

  it("puts a manual secret only in its source, with persist", () => {
    const manual = { ...withKind(draft({}), "api_key", null), secret: SECRET, persist: false };
    expect(createBody(manual).source).toEqual({ credential_kind: "api_key", secret: SECRET, persist: false });
    const original = account({ credential_kind: "api_key", storage: "keyring", reference: null });
    const keep = { ...withKind(editDraft(original, true), "api_key", original), source: "set" as const };
    expect(updateBody(keep, original)).toEqual({ source: { credential_kind: "api_key" } });
  });

  it("never puts a Console key in the save body", () => {
    const console = {
      ...newDraft("claude_platform", false),
      label: "Org",
      prepareId: "prep",
      choiceId: "c2",
      preparedSecret: true,
      persist: false,
    };
    const body = createBody(console);
    expect(body.source).toEqual({
      credential_kind: "console_session",
      prepare_id: "prep",
      choice_id: "c2",
      persist: false,
    });
    expect(JSON.stringify(body)).not.toContain(SECRET);
    // An organization-only change carries no persist.
    expect(createBody({ ...console, preparedSecret: false }).source).toEqual({
      credential_kind: "console_session",
      prepare_id: "prep",
      choice_id: "c2",
    });
  });

  it("sends the Console key only in the prepare body", () => {
    const console = { ...newDraft("claude_platform", true), label: "Org" };
    expect(prepareBody(console, null, SECRET)).toEqual({
      account_id: null,
      revision: null,
      provider: "claude_platform",
      credential_kind: "console_session",
      secret: SECRET,
    });
    const original = account({ provider: "claude_platform", credential_kind: "console_session", storage: "session" });
    const rediscover = prepareBody({ ...editDraft(original, true), source: "set" }, original, "");
    expect(rediscover).toEqual({
      account_id: original.id,
      revision: original.revision,
      provider: "claude_platform",
      credential_kind: "console_session",
    });
  });

  it("re-reads the saved Grok file without naming it, or reads a new reference", () => {
    const original = account({ provider: "grok_subscription", credential_kind: "grok_auth_file", reference: "custom" });
    const edit = withKind(editDraft(original, true), "grok_auth_file", original);
    expect(edit.reference).toBe("current");
    expect(prepareBody(edit, original, "")).not.toHaveProperty("reference");
    expect(prepareBody({ ...edit, reference: "default" }, original, "")?.reference).toBe("default");
    const fresh = { ...newDraft("grok_subscription", true), reference: "custom" as const, path: "/g/auth.json" };
    expect(prepareBody(fresh, null, "")?.reference).toBe("/g/auth.json");
    expect(prepareBody(draft({}), null, "")).toBeNull();
  });
});

describe("conflict retry", () => {
  it("rebases untouched fields onto the reloaded account", () => {
    const before = account();
    // Another client disabled the account and renamed it.
    const after = account({ enabled: false, label: "Theirs", revision: "f".repeat(32) });
    const edited = { ...editDraft(before, true), interval: "120" };
    const rebased = rebaseDraft(edited, editDraft(before, true), editDraft(after, true));
    expect(rebased.enabled).toBe(false);
    expect(rebased.label).toBe("Theirs");
    expect(rebased.interval).toBe("120");
    // The retry sends only the user's own change, so nothing is silently reverted.
    expect(updateBody(rebased, after)).toEqual({ poll_interval_seconds: 120 });
  });

  it("keeps the user's own edits and drops revision-bound prepare results", () => {
    const before = account({ provider: "grok_subscription", credential_kind: "grok_auth_file" });
    const after = { ...before, label: "Theirs", revision: "f".repeat(32) };
    const edited = {
      ...editDraft(before, true),
      label: "Mine",
      source: "set" as const,
      prepareId: "prep",
      choiceId: "c1",
    };
    const rebased = rebaseDraft(edited, editDraft(before, true), editDraft(after, true));
    expect(rebased.label).toBe("Mine");
    expect(rebased.source).toBe("set");
    expect(rebased.prepareId).toBeNull();
    expect(rebased.choiceId).toBeNull();
  });
});

describe("form escape and save outcome", () => {
  it("never closes a form with a save in flight and dismisses the inline confirm first", () => {
    expect(formEscape({ busy: true, confirming: true })).toBe("ignore");
    expect(formEscape({ busy: true, confirming: false })).toBe("ignore");
    expect(formEscape({ busy: false, confirming: true })).toBe("dismiss_confirm");
    expect(formEscape({ busy: false, confirming: false })).toBe("close");
  });

  it("treats lost responses as possibly committed", () => {
    expect(saveUncertain("timeout")).toBe(true);
    expect(saveUncertain("network")).toBe(true);
    expect(saveUncertain("invalid_response")).toBe(true);
    expect(saveUncertain("conflict")).toBe(false);
    expect(saveUncertain("invalid")).toBe(false);
  });
});
