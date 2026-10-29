import { useState, type FormEvent } from "react";
import { ApiError, MOCK_ENABLED, createClient, type UsageClient } from "../api";
import { isPlausibleToken, normalizeBaseUrl, type Credentials } from "../auth";
import type { SessionInfo } from "../types";
import { DEFAULT_RETRY_AFTER, useTick, type SignOutNotice } from "../hooks";
import { DemoBadge } from "./Header";

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
      <form className="login__col" onSubmit={submit} noValidate>
        <header className="login__head">
          <h1 className="login__mark">
            CLIUsageAPI
            {MOCK_ENABLED ? <DemoBadge /> : null}
          </h1>
          <p>查看各账号的额度与余额；服务器允许时也可在网页管理账号。</p>
        </header>

        {MOCK_ENABLED ? <p className="rule-note">开发模式：内置合成数据，不连服务器。令牌任填；填 invalid 测试失效。</p> : null}
        {notice ? (
          <div className="rule-note rule-note--error">
            {/* Only the static message is live; the per-second countdown sits outside the alert. */}
            <p role="alert">{notice.message}</p>
            {waitSeconds > 0 ? <p>{waitSeconds} 秒后才能重新连接。</p> : null}
          </div>
        ) : null}

        {MOCK_ENABLED ? (
          <div className="field">
            <span className="field__label" id="scenario-label">
              演示场景
            </span>
            <div className="segmented segmented--wide" role="radiogroup" aria-labelledby="scenario-label">
              {(
                [
                  ["healthy", "正常"],
                  ["errors", "各种错误"],
                ] as const
              ).map(([value, label]) => (
                <label key={value} className={scenario === value ? "is-on" : undefined}>
                  <input
                    type="radio"
                    name="scenario"
                    value={value}
                    checked={scenario === value}
                    onChange={() => setScenario(value)}
                  />
                  {label}
                </label>
              ))}
            </div>
          </div>
        ) : (
          <label className="field">
            <span className="field__label">API 地址</span>
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
          <span className="field__label">API 令牌</span>
          <input
            type="password"
            autoComplete="current-password"
            spellCheck={false}
            placeholder="usk_…"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            required
          />
          <small className="field__help">
            在服务器运行 <code>usage api token create</code> 获取 · 只发送到此地址
          </small>
        </label>

        <label className="check">
          <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
          <span>在这台设备上记住</span>
          <small>{remember ? "保存在本机，直到退出" : "关闭标签页即清除"}</small>
          <small className="check__note">此令牌可能可以修改服务器上的账号；共享设备上不要记住它。</small>
        </label>

        {error ? (
          <p className="form-error" role="alert">
            {error}
          </p>
        ) : null}

        <button type="submit" className="button" disabled={busy || waitSeconds > 0}>
          {busy ? "正在验证…" : waitSeconds > 0 ? `请等待 ${waitSeconds} 秒` : "连接"}
        </button>
      </form>
    </div>
  );
}
