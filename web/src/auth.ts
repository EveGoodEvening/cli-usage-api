// Credential persistence. The token lives in sessionStorage by default (gone when
// the tab closes) or localStorage only when the user ticks "remember". It is
// never put in a URL, cookie or log. Every storage access tolerates failure.

export interface Credentials {
  baseUrl: string;
  token: string;
}

export interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

export interface Storages {
  session: StorageLike | null;
  local: StorageLike | null;
}

export const CREDENTIALS_KEY = "usage-web.credentials.v1";
export const BASE_URL_KEY = "usage-web.base-url";
export const THEME_KEY = "usage-web.theme";

const MAX_TOKEN_LENGTH = 512;

function safeStorage(get: () => Storage): StorageLike | null {
  try {
    const storage = get();
    return storage ?? null;
  } catch {
    return null;
  }
}

export function browserStorages(): Storages {
  return {
    session: safeStorage(() => window.sessionStorage),
    local: safeStorage(() => window.localStorage),
  };
}

function read(storage: StorageLike | null, key: string): string | null {
  try {
    return storage?.getItem(key) ?? null;
  } catch {
    return null;
  }
}

function write(storage: StorageLike | null, key: string, value: string): boolean {
  try {
    if (!storage) return false;
    storage.setItem(key, value);
    return true;
  } catch {
    return false;
  }
}

function remove(storage: StorageLike | null, key: string): void {
  try {
    storage?.removeItem(key);
  } catch {
    // Unavailable storage holds nothing to clear.
  }
}

/** Token shape check before it is stored or sent: printable ASCII, bounded, no spaces. */
export function isPlausibleToken(token: string): boolean {
  return token.length > 0 && token.length <= MAX_TOKEN_LENGTH && /^[\x21-\x7e]+$/.test(token);
}

/** Normalize an API base URL: http(s) only, no credentials, query or fragment. */
export function normalizeBaseUrl(input: string): string | null {
  const trimmed = input.trim();
  if (!trimmed || trimmed.length > 2048) return null;
  let url: URL;
  try {
    url = new URL(trimmed);
  } catch {
    return null;
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") return null;
  if (url.username || url.password || url.search || url.hash) return null;
  if (trimmed.includes("?") || trimmed.includes("#")) return null;
  const path = url.pathname.replace(/\/+$/, "");
  return `${url.protocol}//${url.host}${path}`;
}

function parse(raw: string | null): Credentials | null {
  if (!raw) return null;
  try {
    const value: unknown = JSON.parse(raw);
    if (typeof value !== "object" || value === null) return null;
    const { baseUrl, token } = value as Record<string, unknown>;
    if (typeof baseUrl !== "string" || typeof token !== "string") return null;
    const normalized = normalizeBaseUrl(baseUrl);
    if (!normalized || !isPlausibleToken(token)) return null;
    return { baseUrl: normalized, token };
  } catch {
    return null;
  }
}

export interface Loaded {
  credentials: Credentials;
  remembered: boolean;
}

/** Session copy wins over a remembered one. */
export function loadCredentials(storages: Storages): Loaded | null {
  const session = parse(read(storages.session, CREDENTIALS_KEY));
  if (session) return { credentials: session, remembered: false };
  const local = parse(read(storages.local, CREDENTIALS_KEY));
  if (local) return { credentials: local, remembered: true };
  return null;
}

/**
 * Store in exactly one place and clear the other. Returns false when the chosen
 * storage is unavailable; the caller still keeps the token in memory for this tab.
 */
export function saveCredentials(storages: Storages, credentials: Credentials, remember: boolean): boolean {
  const raw = JSON.stringify({ baseUrl: credentials.baseUrl, token: credentials.token });
  remove(remember ? storages.session : storages.local, CREDENTIALS_KEY);
  const ok = write(remember ? storages.local : storages.session, CREDENTIALS_KEY, raw);
  // The base URL is not a secret; remember it to prefill the next sign-in.
  write(storages.local, BASE_URL_KEY, credentials.baseUrl);
  return ok;
}

export function clearCredentials(storages: Storages): void {
  remove(storages.session, CREDENTIALS_KEY);
  remove(storages.local, CREDENTIALS_KEY);
}

export function lastBaseUrl(storages: Storages): string | null {
  return normalizeBaseUrl(read(storages.local, BASE_URL_KEY) ?? "");
}

export type ThemeChoice = "system" | "light" | "dark";

export function loadTheme(storages: Storages): ThemeChoice {
  const value = read(storages.local, THEME_KEY);
  return value === "light" || value === "dark" ? value : "system";
}

export function saveTheme(storages: Storages, theme: ThemeChoice): void {
  if (theme === "system") remove(storages.local, THEME_KEY);
  else write(storages.local, THEME_KEY, theme);
}
