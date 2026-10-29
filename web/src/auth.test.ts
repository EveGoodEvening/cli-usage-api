import { describe, expect, it } from "vitest";
import {
  BASE_URL_KEY,
  CREDENTIALS_KEY,
  clearCredentials,
  isPlausibleToken,
  lastBaseUrl,
  loadCredentials,
  loadTheme,
  normalizeBaseUrl,
  saveCredentials,
  saveTheme,
  type StorageLike,
  type Storages,
} from "./auth";

class MemoryStorage implements StorageLike {
  data = new Map<string, string>();
  getItem(key: string) {
    return this.data.get(key) ?? null;
  }
  setItem(key: string, value: string) {
    this.data.set(key, value);
  }
  removeItem(key: string) {
    this.data.delete(key);
  }
}

class BrokenStorage implements StorageLike {
  getItem(): string | null {
    throw new Error("blocked");
  }
  setItem() {
    throw new Error("blocked");
  }
  removeItem() {
    throw new Error("blocked");
  }
}

function stores(): Storages & { session: MemoryStorage; local: MemoryStorage } {
  return { session: new MemoryStorage(), local: new MemoryStorage() };
}

const creds = { baseUrl: "https://api.example.com", token: "usk_abc-DEF_123" };

describe("base URL", () => {
  it("accepts http(s) and strips trailing slashes", () => {
    expect(normalizeBaseUrl(" https://api.example.com/ ")).toBe("https://api.example.com");
    expect(normalizeBaseUrl("http://127.0.0.1:8787")).toBe("http://127.0.0.1:8787");
    expect(normalizeBaseUrl("https://host.example/usage//")).toBe("https://host.example/usage");
  });

  it("rejects other schemes, credentials, queries and fragments", () => {
    expect(normalizeBaseUrl("javascript:alert(1)")).toBeNull();
    expect(normalizeBaseUrl("ftp://x.example")).toBeNull();
    expect(normalizeBaseUrl("https://user:pw@x.example")).toBeNull();
    expect(normalizeBaseUrl("https://x.example/?token=1")).toBeNull();
    expect(normalizeBaseUrl("https://x.example/?")).toBeNull();
    expect(normalizeBaseUrl("https://x.example/#a")).toBeNull();
    expect(normalizeBaseUrl("not a url")).toBeNull();
    expect(normalizeBaseUrl("")).toBeNull();
  });
});

describe("token shape", () => {
  it("requires printable, space-free, bounded text", () => {
    expect(isPlausibleToken("usk_abc")).toBe(true);
    expect(isPlausibleToken("")).toBe(false);
    expect(isPlausibleToken("has space")).toBe(false);
    expect(isPlausibleToken("line\nbreak")).toBe(false);
    expect(isPlausibleToken("x".repeat(513))).toBe(false);
  });
});

describe("credential storage", () => {
  it("defaults to session storage and keeps nothing in local", () => {
    const s = stores();
    expect(saveCredentials(s, creds, false)).toBe(true);
    expect(s.session.getItem(CREDENTIALS_KEY)).not.toBeNull();
    expect(s.local.getItem(CREDENTIALS_KEY)).toBeNull();
    expect(loadCredentials(s)).toEqual({ credentials: creds, remembered: false });
  });

  it("remembers in local storage only when asked, clearing the session copy", () => {
    const s = stores();
    saveCredentials(s, creds, false);
    saveCredentials(s, creds, true);
    expect(s.session.getItem(CREDENTIALS_KEY)).toBeNull();
    expect(loadCredentials(s)).toEqual({ credentials: creds, remembered: true });
  });

  it("logout clears both copies but keeps the nonsecret base URL", () => {
    const s = stores();
    saveCredentials(s, creds, true);
    clearCredentials(s);
    expect(loadCredentials(s)).toBeNull();
    expect(s.local.getItem(BASE_URL_KEY)).toBe(creds.baseUrl);
    expect(lastBaseUrl(s)).toBe(creds.baseUrl);
    expect([...s.local.data.values()].some((v) => v.includes(creds.token))).toBe(false);
  });

  it("ignores corrupt or tampered entries", () => {
    const s = stores();
    s.session.setItem(CREDENTIALS_KEY, "{not json");
    expect(loadCredentials(s)).toBeNull();
    s.session.setItem(CREDENTIALS_KEY, JSON.stringify({ baseUrl: "javascript:x", token: "usk_a" }));
    expect(loadCredentials(s)).toBeNull();
    s.session.setItem(CREDENTIALS_KEY, JSON.stringify({ baseUrl: creds.baseUrl, token: "a b" }));
    expect(loadCredentials(s)).toBeNull();
  });

  it("survives unavailable or throwing storage", () => {
    const broken: Storages = { session: new BrokenStorage(), local: null };
    expect(saveCredentials(broken, creds, false)).toBe(false);
    expect(loadCredentials(broken)).toBeNull();
    expect(() => clearCredentials(broken)).not.toThrow();
    expect(loadTheme(broken)).toBe("system");
  });
});

describe("theme preference", () => {
  it("stores only explicit choices", () => {
    const s = stores();
    saveTheme(s, "dark");
    expect(loadTheme(s)).toBe("dark");
    saveTheme(s, "system");
    expect(loadTheme(s)).toBe("system");
    s.local.setItem("usage-web.theme", "neon");
    expect(loadTheme(s)).toBe("system");
  });
});
