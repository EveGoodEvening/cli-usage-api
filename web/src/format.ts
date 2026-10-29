// Pure presentation helpers. Values are shown exactly as the API reports them:
// decimals stay strings, money stays integer minor units, unknown is "—".

import type { Money } from "./types";

export const UNKNOWN = "—";

// ---------------------------------------------------------------------------
// Exact decimals (Python str(Decimal) output)

const MAX_DECIMAL_TEXT = 4096;
const MAX_EXPONENT = 1000;
const DECIMAL_RE = /^(\d+)(?:\.(\d+))?(?:[eE]([+-]?\d+))?$/;

/** Scaled integer: value = units / 10^scale. */
export interface Exact {
  units: bigint;
  scale: number;
}

/** Parse a nonnegative decimal string exactly; null when unsupported. */
export function parseDecimal(value: string | null | undefined): Exact | null {
  if (typeof value !== "string" || value.length === 0 || value.length > MAX_DECIMAL_TEXT) {
    return null;
  }
  const match = DECIMAL_RE.exec(value);
  if (!match) return null;
  const whole = match[1] ?? "0";
  const frac = match[2] ?? "";
  const exp = match[3] === undefined ? 0 : Number(match[3]);
  if (!Number.isSafeInteger(exp) || Math.abs(exp) > MAX_EXPONENT) return null;
  let units = BigInt(whole + frac);
  let scale = frac.length - exp;
  if (scale < 0) {
    units *= 10n ** BigInt(-scale);
    scale = 0;
  }
  return { units, scale };
}

function align(a: Exact, b: Exact): [bigint, bigint, number] {
  const scale = Math.max(a.scale, b.scale);
  return [
    a.units * 10n ** BigInt(scale - a.scale),
    b.units * 10n ** BigInt(scale - b.scale),
    scale,
  ];
}

export function compareDecimal(a: Exact, b: Exact): number {
  const [x, y] = align(a, b);
  return x === y ? 0 : x < y ? -1 : 1;
}

export function formatExact(value: Exact): string {
  const negative = value.units < 0n;
  const digits = (negative ? -value.units : value.units)
    .toString()
    .padStart(value.scale + 1, "0");
  const body =
    value.scale > 0
      ? `${digits.slice(0, -value.scale)}.${digits.slice(-value.scale)}`
      : digits;
  return negative ? `-${body}` : body;
}

const HUNDRED: Exact = { units: 100n, scale: 0 };

/** Exact "used - 100" for an overage, e.g. "110.25" -> "10.25"; null if not over. */
export function overagePercent(used: string | null): string | null {
  const parsed = parseDecimal(used);
  if (!parsed || compareDecimal(parsed, HUNDRED) <= 0) return null;
  const [x, y, scale] = align(parsed, HUNDRED);
  return formatExact({ units: x - y, scale });
}

/** Display a percentage string verbatim with a % sign; never rounded or truncated. */
export function percentText(value: string | null | undefined): string {
  return parseDecimal(value) ? `${value}%` : UNKNOWN;
}

/** Width for drawing only (0..100). The numeric text is always shown separately. */
export function barFill(value: string | null | undefined): number {
  const parsed = parseDecimal(value);
  if (!parsed) return 0;
  if (compareDecimal(parsed, HUNDRED) >= 0) return 100;
  const n = Number(formatExact(parsed));
  return Number.isFinite(n) ? Math.max(0, Math.min(100, n)) : 0;
}

export type Severity = "ok" | "warn" | "error";

/** Mirrors the TUI: >=90 or over 100 is error, >=70 warning. */
export function severity(used: string | null | undefined): Severity {
  const parsed = parseDecimal(used);
  if (!parsed) return "ok";
  if (compareDecimal(parsed, { units: 90n, scale: 0 }) >= 0) return "error";
  if (compareDecimal(parsed, { units: 70n, scale: 0 }) >= 0) return "warn";
  return "ok";
}

// ---------------------------------------------------------------------------
// Money

function validMoney(money: Money | null | undefined): money is Money {
  return (
    !!money &&
    Number.isSafeInteger(money.minor) &&
    Number.isInteger(money.exponent) &&
    money.exponent >= 0 &&
    money.exponent <= 4 &&
    /^[A-Z]{3}$/.test(money.currency)
  );
}

/** Same output as domain.Money.format(): "-12.50 USD". */
export function formatMoney(money: Money | null | undefined): string {
  if (!validMoney(money)) return UNKNOWN;
  const digits = Math.abs(money.minor)
    .toString()
    .padStart(money.exponent + 1, "0");
  const body = money.exponent
    ? `${digits.slice(0, -money.exponent)}.${digits.slice(-money.exponent)}`
    : digits;
  return `${money.minor < 0 ? "-" : ""}${body} ${money.currency}`;
}

/** Amount without the currency, for large display; the currency is shown beside it. */
export function formatMoneyAmount(money: Money | null | undefined): string {
  const text = formatMoney(money);
  return text === UNKNOWN ? text : text.slice(0, -4);
}

// ---------------------------------------------------------------------------
// Time

export function parseTime(value: string | null | undefined): number | null {
  if (typeof value !== "string") return null;
  const ms = Date.parse(value);
  return Number.isFinite(ms) ? ms : null;
}

/** Duration in the TUI's compact vocabulary: "2天3小时", "5小时12分", "4分钟", "9秒". */
export function span(totalSeconds: number, opts: { precise?: boolean; coarse?: boolean } = {}): string {
  let seconds = Math.max(0, Math.floor(totalSeconds));
  const days = Math.floor(seconds / 86400);
  seconds -= days * 86400;
  const hours = Math.floor(seconds / 3600);
  seconds -= hours * 3600;
  const minutes = Math.floor(seconds / 60);
  seconds -= minutes * 60;
  if (days) return hours && !opts.coarse ? `${days}天${hours}小时` : `${days}天`;
  if (hours) return minutes && !opts.coarse ? `${hours}小时${minutes}分` : `${hours}小时`;
  if (minutes) {
    return opts.precise && seconds ? `${minutes}分${String(seconds).padStart(2, "0")}秒` : `${minutes}分钟`;
  }
  return `${seconds}秒`;
}

export const AWAITING_REFRESH = "等待刷新";

/** Countdown to a deadline; a passed deadline waits for data, it never resets anything. */
export function relativeUntil(target: number, now: number, precise = false): string {
  const seconds = Math.floor((target - now) / 1000);
  if (seconds <= 0) return AWAITING_REFRESH;
  return `${span(seconds, { precise })}后`;
}

/** Age of an observation: "刚刚" under a minute. */
export function relativeAge(since: number, now: number): string {
  const seconds = Math.max(0, Math.floor((now - since) / 1000));
  return seconds < 60 ? "刚刚" : `${span(seconds)}前`;
}

const WEEKDAYS = "日一二三四五六";

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

/** "今天 14:00", "明天 09:30", "周五 12:00", "11-03 12:00", "2027-01-02 12:00" (local). */
export function shortLocal(ms: number, now: number): string {
  const d = new Date(ms);
  const current = new Date(now);
  if (Number.isNaN(d.getTime())) return UNKNOWN;
  const startOf = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const days = Math.round((startOf(d) - startOf(current)) / 86400000);
  const clock = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  if (days >= -1 && days <= 1) return `${["昨天", "今天", "明天"][days + 1]} ${clock}`;
  if (days > 1 && days < 7) return `周${WEEKDAYS[d.getDay()]} ${clock}`;
  const md = `${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  return d.getFullYear() === current.getFullYear()
    ? `${md} ${clock}`
    : `${d.getFullYear()}-${md} ${clock}`;
}

/** Full local timestamp with seconds, e.g. "2026-10-28 20:00:00". */
export function fullLocal(ms: number | null): string {
  if (ms === null) return UNKNOWN;
  const d = new Date(ms);
  if (Number.isNaN(d.getTime())) return UNKNOWN;
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(
    d.getMinutes(),
  )}:${pad(d.getSeconds())}`;
}

/** UTC ISO text as received, or "—". */
export function utcText(value: string | null | undefined): string {
  return typeof value === "string" && value ? value : UNKNOWN;
}
