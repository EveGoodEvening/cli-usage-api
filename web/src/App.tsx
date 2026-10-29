import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, createClient, type UsageClient } from "./api";
import {
  browserStorages,
  clearCredentials,
  lastBaseUrl,
  loadCredentials,
  loadTheme,
  saveCredentials,
  saveTheme,
  type ThemeChoice,
} from "./auth";
import type { SessionInfo } from "./types";
import { Login, type SignedIn } from "./components/Login";
import { Shell } from "./components/Shell";
import { endsSession, signOutNotice, type SignOutNotice } from "./hooks";

interface Active {
  client: UsageClient;
  session: SessionInfo;
  remembered: boolean;
}

function systemDark(): boolean {
  try {
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  } catch {
    return false;
  }
}

function useTheme() {
  const storages = useMemo(browserStorages, []);
  const [theme, setTheme] = useState<ThemeChoice>(() => loadTheme(storages));
  const [dark, setDark] = useState(systemDark);
  useEffect(() => {
    let query: MediaQueryList;
    try {
      query = window.matchMedia("(prefers-color-scheme: dark)");
    } catch {
      return;
    }
    const onChange = () => setDark(query.matches);
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);
  useEffect(() => {
    const root = document.documentElement;
    if (theme === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", theme);
    saveTheme(storages, theme);
  }, [theme, storages]);
  const resolved: "light" | "dark" = theme === "system" ? (dark ? "dark" : "light") : theme;
  return { theme, setTheme, resolved };
}

export function App() {
  const storages = useMemo(browserStorages, []);
  const { theme, setTheme, resolved } = useTheme();
  const [active, setActive] = useState<Active | null>(null);
  const [restoring, setRestoring] = useState(true);
  const [notice, setNotice] = useState<SignOutNotice | null>(null);

  const logout = useCallback(
    (reason?: ApiError) => {
      clearCredentials(storages);
      setActive(null);
      // 401 and 429 both mean the bearer failed verification (signOutNotice
      // carries the 429 cooldown); a user-initiated sign-out has no notice.
      setNotice(signOutNotice(reason));
    },
    [storages],
  );

  // Restore a stored token once, validating it before showing any data.
  useEffect(() => {
    const loaded = loadCredentials(storages);
    if (!loaded) {
      setRestoring(false);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const client = await createClient(loaded.credentials);
        const session = await client.session();
        if (!cancelled) setActive({ client, session, remembered: loaded.remembered });
      } catch (caught) {
        if (cancelled) return;
        if (caught instanceof ApiError && endsSession(caught)) {
          clearCredentials(storages);
          setNotice(signOutNotice(caught));
        } else {
          setNotice({ message: caught instanceof ApiError ? caught.message : "无法连接 API。", retryAt: null });
        }
      } finally {
        if (!cancelled) setRestoring(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [storages]);

  const signedIn = (result: SignedIn) => {
    saveCredentials(storages, result.credentials, result.remember);
    setNotice(null);
    setActive({ client: result.client, session: result.session, remembered: result.remember });
  };

  if (restoring) {
    return (
      <div className="login">
        <p className="empty">正在验证保存的令牌…</p>
      </div>
    );
  }

  if (!active) {
    const initial =
      loadCredentials(storages)?.credentials.baseUrl ??
      lastBaseUrl(storages) ??
      import.meta.env.VITE_API_BASE_URL ??
      "";
    return <Login initialBaseUrl={initial} notice={notice} onSignedIn={signedIn} />;
  }

  return (
    <Shell
      key={active.client.baseUrl}
      client={active.client}
      session={active.session}
      remembered={active.remembered}
      theme={theme}
      resolvedTheme={resolved}
      onTheme={setTheme}
      onLogout={logout}
    />
  );
}
