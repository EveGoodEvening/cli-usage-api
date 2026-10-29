import { useEffect, useRef, type RefObject } from "react";
import type { ThemeChoice } from "../auth";
import type { Dashboard, SessionInfo } from "../types";
import { browserZone, fullLocalZoned, utcOffset } from "../format";
import { Facts } from "./Facts";

function host(baseUrl: string): string {
  try {
    return new URL(baseUrl).host;
  } catch {
    return baseUrl;
  }
}

export function zoneText(now: number): string {
  const zone = browserZone();
  return zone ? `${zone}（${utcOffset(now)}）` : utcOffset(now);
}

const THEMES: Array<[ThemeChoice, string]> = [
  ["system", "跟随系统"],
  ["light", "浅色"],
  ["dark", "深色"],
];

export function MenuPopover({
  anchor,
  onClose,
  baseUrl,
  session,
  mode,
  remembered,
  now,
  theme,
  onTheme,
  dashboard,
  onLogout,
}: {
  anchor: RefObject<HTMLButtonElement>;
  onClose: () => void;
  baseUrl: string;
  session: SessionInfo;
  mode: Dashboard["mode"];
  remembered: boolean;
  now: number;
  theme: ThemeChoice;
  onTheme: (theme: ThemeChoice) => void;
  dashboard: Dashboard | null;
  onLogout: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const button = anchor.current;
    ref.current?.querySelector<HTMLElement>("input, button, summary")?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
      }
    };
    const onPointer = (event: MouseEvent) => {
      const target = event.target as Node;
      if (ref.current?.contains(target) || button?.contains(target)) return;
      onClose();
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onPointer);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onPointer);
      button?.focus();
    };
  }, [anchor, onClose]);

  return (
    <div className="menu" role="dialog" aria-label="菜单" ref={ref}>
      <section className="menu__section">
        <h2 className="kicker">外观</h2>
        <div className="segmented" role="radiogroup" aria-label="主题">
          {THEMES.map(([value, label]) => (
            <label key={value} className={theme === value ? "is-on" : undefined}>
              <input type="radio" name="theme" value={value} checked={theme === value} onChange={() => onTheme(value)} />
              {label}
            </label>
          ))}
        </div>
      </section>
      <section className="menu__section">
        <h2 className="kicker">连接</h2>
        <Facts
          className="facts--menu"
          items={[
            { label: "API 地址", value: <span title={baseUrl}>{host(baseUrl)}</span> },
            { label: "模式", value: mode === "demo" ? "演示（合成数据）" : "实时" },
            { label: "鉴权", value: session.auth === "token" ? "Bearer 令牌" : "未启用（仅本机演示）" },
            { label: "令牌保存", value: remembered ? "这台设备" : "本标签页" },
            { label: "版本", value: /^\d/.test(session.version) ? `v${session.version}` : session.version === "mock" ? "演示" : session.version },
            { label: "服务器时间", value: fullLocalZoned(now) },
            { label: "时区", value: zoneText(now) },
            { label: "自动读取", value: "每 15 秒读取服务器缓存，不会加快上游轮询" },
          ]}
        />
        <p className="menu__note">时间按浏览器时区显示；接口原始数据为 UTC。</p>
      </section>
      <section className="menu__section">
        <details className="raw">
          <summary>原始 JSON</summary>
          <p className="menu__note">百分比为精确小数，金额为最小货币单位整数，时间为 UTC。</p>
          <pre>{dashboard ? JSON.stringify(dashboard, null, 2) : "—"}</pre>
        </details>
      </section>
      <div className="menu__foot">
        <button type="button" className="text-btn text-btn--danger" onClick={onLogout}>
          退出并清除令牌
        </button>
      </div>
    </div>
  );
}
