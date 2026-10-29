import { useState, type FormEvent } from "react";
import { ApiError, MOCK_ENABLED, createClient, type UsageClient } from "../api";
import { isPlausibleToken, normalizeBaseUrl, type Credentials } from "../auth";
import type { SessionInfo } from "../types";
import { DEFAULT_RETRY_AFTER, useTick, type SignOutNotice } from "../hooks";
import { GaugeIcon } from "./icons";

const MOCK_BASE = "http://mock.invalid";

export interface SignedIn {
  credentials: Credentials;
  client: UsageClient;
  session: SessionInfo;
  remember: boolean;
}

export function Login({
  initialBaseUrl,
  notice,
  onSignedIn,
}: {
  initialBaseUrl: string;
  notice: SignOutNotice | null;
  onSignedIn: (result: SignedIn) => void;
}) {
  const [baseUrl, setBaseUrl] = useState(initialBaseUrl);
  const [token, setToken] = useState("");
  const [remember, setRemember] = useState(false);
  const [scenario, setScenario] = useState<"healthy" | "errors">("healthy");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // While the server rate-limits failed verification, connecting stays disabled.
  const [retryAt, setRetryAt] = useState<number | null>(notice?.retryAt ?? null);
  const now = useTick();
  const waitSeconds = retryAt !== null && retryAt > now ? Math.ceil((retryAt - now) / 1000) : 0;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy || (retryAt !== null && Date.now() < retryAt)) return;
    setError(null);
    const normalized = MOCK_ENABLED ? `${MOCK_BASE}/${scenario}` : normalizeBaseUrl(baseUrl);
    if (!normalized) {
      setError("API 地址需要是完整的 http:// 或 https:// 地址，不带查询参数。");
      return;
    }
    const trimmed = token.trim();
    if (!isPlausibleToken(trimmed)) {
      setError("令牌不能为空，也不能包含空格。它通常以 usk_ 开头。");
      return;
    }
    setBusy(true);
    try {
      const credentials = { baseUrl: normalized, token: trimmed };
      const client = await createClient(credentials);
      const session = await client.session();
      setToken("");
      onSignedIn({ credentials, client, session, remember });
    } catch (caught) {
      if (caught instanceof ApiError && caught.kind === "rate_limited") {
        setRetryAt(Date.now() + (caught.retryAfter ?? DEFAULT_RETRY_AFTER) * 1000);
      }
      setError(caught instanceof ApiError ? caught.message : "无法连接 API。");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login">
      <form className="login__card" onSubmit={submit} noValidate>
        <div className="login__brand">
          <span className="login__logo" aria-hidden="true">
            <GaugeIcon />
          </span>
          <div>
            <h1>用量面板</h1>
            <p>连接到 usage api serve，只读查看各账号的额度与余额。</p>
          </div>
        </div>

        {MOCK_ENABLED ? (
          <p className="banner banner--warn">开发模式：使用内置 DEMO 合成数据，不连接任何服务器。令牌填任意值即可，填 invalid 可测试失效。</p>
        ) : null}
        {notice ? (
          <p className="banner banner--error" role="alert">
            {notice.message}
          </p>
        ) : null}

        {MOCK_ENABLED ? (
          <label className="field">
            <span>演示场景</span>
            <select value={scenario} onChange={(e) => setScenario(e.target.value as "healthy" | "errors")}>
              <option value="healthy">正常</option>
              <option value="errors">各种错误</option>
            </select>
          </label>
        ) : (
          <label className="field">
            <span>API 地址</span>
            <input
              type="url"
              inputMode="url"
              autoComplete="url"
              spellCheck={false}
              placeholder="https://usage.example.com"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              required
            />
          </label>
        )}

        <label className="field">
          <span>API 令牌</span>
          <input
            type="password"
            autoComplete="current-password"
            spellCheck={false}
            placeholder="usk_…"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            required
          />
          <small>在服务器上运行 usage api token create 获取。令牌只发送到上面的 API 地址。</small>
        </label>

        <label className="check">
          <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
          <span>
            在这台设备上记住
            <small>{remember ? "保存在浏览器本地，直到你退出。" : "只保存在当前标签页，关闭后需要重新输入。"}</small>
          </span>
        </label>

        {error ? (
          <p className="form-error" role="alert">
            {error}
          </p>
        ) : null}

        {waitSeconds > 0 ? (
          <p className="banner banner--warn" role="status">
            {waitSeconds} 秒后才能重新连接。
          </p>
        ) : null}

        <button type="submit" className="button button--primary" disabled={busy || waitSeconds > 0}>
          {busy ? "正在验证" : waitSeconds > 0 ? `请等待 ${waitSeconds} 秒` : "连接"}
        </button>
      </form>
    </div>
  );
}
