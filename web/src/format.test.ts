import { describe, expect, it, vi } from "vitest";
import {
  UNKNOWN,
  barFill,
  browserZone,
  fullLocalZoned,
  timeTitle,
  utcOffset,
  formatMoney,
  formatMoneyAmount,
  groupThousands,
  overagePercent,
  parseDecimal,
  percentText,
  relativeAge,
  relativeUntil,
  severity,
  shortLocal,
  span,
} from "./format";

describe("money", () => {
  it("formats minor units with the declared exponent, like domain.Money.format", () => {
    expect(formatMoney({ minor: 4250, currency: "USD", exponent: 2 })).toBe("42.50 USD");
    expect(formatMoney({ minor: 5, currency: "USD", exponent: 2 })).toBe("0.05 USD");
    expect(formatMoney({ minor: 0, currency: "USD", exponent: 2 })).toBe("0.00 USD");
    expect(formatMoney({ minor: -1234, currency: "EUR", exponent: 2 })).toBe("-12.34 EUR");
    expect(formatMoney({ minor: 1500, currency: "JPY", exponent: 0 })).toBe("1,500 JPY");
    expect(formatMoney({ minor: 12345, currency: "KWD", exponent: 3 })).toBe("12.345 KWD");
    expect(formatMoney({ minor: 7, currency: "USD", exponent: 4 })).toBe("0.0007 USD");
  });

  it("groups integer digits with commas, like domain.group_thousands", () => {
    expect(formatMoney({ minor: -123450, currency: "USD", exponent: 2 })).toBe("-1,234.50 USD");
    expect(formatMoney({ minor: 99999, currency: "USD", exponent: 2 })).toBe("999.99 USD");
    expect(formatMoney({ minor: 1234567, currency: "JPY", exponent: 0 })).toBe("1,234,567 JPY");
    expect(formatMoney({ minor: 1234567, currency: "BHD", exponent: 3 })).toBe("1,234.567 BHD");
    expect(formatMoney({ minor: Number.MAX_SAFE_INTEGER, currency: "USD", exponent: 2 })).toBe(
      "90,071,992,547,409.91 USD",
    );
    expect(formatMoneyAmount({ minor: -123456789, currency: "USD", exponent: 2 })).toBe("-1,234,567.89");
    expect(groupThousands("-0.00")).toBe("-0.00");
    expect(groupThousands("12345678901234567890.5")).toBe("12,345,678,901,234,567,890.5");
  });

  it("never invents a value for missing or malformed money", () => {
    expect(formatMoney(null)).toBe(UNKNOWN);
    expect(formatMoney({ minor: 1.5, currency: "USD", exponent: 2 })).toBe(UNKNOWN);
    expect(formatMoney({ minor: 1, currency: "usd", exponent: 2 })).toBe(UNKNOWN);
    expect(formatMoney({ minor: 1, currency: "USD", exponent: 5 })).toBe(UNKNOWN);
    expect(formatMoneyAmount(null)).toBe(UNKNOWN);
  });

  it("splits the amount from the currency without rounding", () => {
    expect(formatMoneyAmount({ minor: -50, currency: "USD", exponent: 2 })).toBe("-0.50");
  });
});

describe("percent", () => {
  it("shows the exact decimal string, never rounded", () => {
    expect(percentText("62.25")).toBe("62.25%");
    expect(percentText("0.000001")).toBe("0.000001%");
    expect(percentText("12.3456789012345678901234567890")).toBe("12.3456789012345678901234567890%");
  });

  it("treats null and junk as unknown, not zero", () => {
    expect(percentText(null)).toBe(UNKNOWN);
    expect(percentText(undefined)).toBe(UNKNOWN);
    expect(percentText("")).toBe(UNKNOWN);
    expect(percentText("NaN")).toBe(UNKNOWN);
    expect(percentText("-1")).toBe(UNKNOWN);
    expect(percentText("1".repeat(5000))).toBe(UNKNOWN);
  });

  it("computes overage exactly and only above 100", () => {
    expect(overagePercent("110.25")).toBe("10.25");
    expect(overagePercent("100.10")).toBe("0.10");
    expect(overagePercent("100")).toBeNull();
    expect(overagePercent("99.99")).toBeNull();
    expect(overagePercent("1E+3")).toBe("900");
    expect(overagePercent("100.000000000000000000000000001")).toBe("0.000000000000000000000000001");
    expect(overagePercent(null)).toBeNull();
  });

  it("clamps drawing at 0..100 while values stay exact", () => {
    expect(barFill("37.5")).toBe(37.5);
    expect(barFill("110.25")).toBe(100);
    expect(barFill(null)).toBe(0);
  });

  it("parses Python Decimal exponent forms", () => {
    expect(parseDecimal("0E-7")).toEqual({ units: 0n, scale: 7 });
    expect(parseDecimal("1E+2")).toEqual({ units: 100n, scale: 0 });
    expect(parseDecimal("1E+1001")).toBeNull();
  });

  it("uses the TUI severity thresholds", () => {
    expect(severity("10")).toBe("ok");
    expect(severity("70")).toBe("warn");
    expect(severity("89.999")).toBe("warn");
    expect(severity("90")).toBe("error");
    expect(severity("110.25")).toBe("error");
    expect(severity(null)).toBe("ok");
  });
});

describe("relative time", () => {
  const now = Date.UTC(2026, 9, 28, 12, 0, 0);

  it("formats spans in the TUI vocabulary", () => {
    expect(span(9)).toBe("9秒");
    expect(span(240)).toBe("4分钟");
    expect(span(245, { precise: true })).toBe("4分05秒");
    expect(span(3 * 3600 + 12 * 60)).toBe("3小时12分");
    expect(span(2 * 86400 + 3 * 3600)).toBe("2天3小时");
    expect(span(2 * 86400 + 3 * 3600, { coarse: true })).toBe("2天");
  });

  it("counts down and waits instead of resetting when a deadline passes", () => {
    expect(relativeUntil(now + 7200_000, now)).toBe("2小时后");
    expect(relativeUntil(now, now)).toBe("等待刷新");
    expect(relativeUntil(now - 5000, now)).toBe("等待刷新");
    expect(relativeUntil(now + 90_000, now, true)).toBe("1分30秒后");
  });

  it("ages observations", () => {
    expect(relativeAge(now - 30_000, now)).toBe("刚刚");
    expect(relativeAge(now - 600_000, now)).toBe("10分钟前");
    expect(relativeAge(now + 5000, now)).toBe("刚刚");
  });

  it("labels nearby days relative to now", () => {
    const local = new Date(2026, 9, 28, 9, 0, 0).getTime();
    expect(shortLocal(local + 5 * 3600_000, local)).toBe("今天 14:00");
    expect(shortLocal(local + 24 * 3600_000, local)).toBe("明天 09:00");
    expect(shortLocal(new Date(2027, 0, 2, 8, 5).getTime(), local)).toBe("2027-01-02 08:05");
  });
});

describe("time zone presentation", () => {
  const env = (globalThis as unknown as { process: { env: Record<string, string | undefined> } }).process.env;

  function withTZ<T>(zone: string, run: () => T): T {
    const previous = env.TZ;
    env.TZ = zone;
    try {
      return run();
    } finally {
      if (previous === undefined) delete env.TZ;
      else env.TZ = previous;
    }
  }

  const instant = Date.parse("2026-10-28T14:00:00Z");

  it("shows the local offset at that instant", () => {
    withTZ("Asia/Shanghai", () => {
      expect(utcOffset(instant)).toBe("UTC+08:00");
      expect(fullLocalZoned(instant)).toBe("2026-10-28 22:00:00 UTC+08:00");
    });
    withTZ("UTC", () => {
      expect(utcOffset(instant)).toBe("UTC+00:00");
      expect(fullLocalZoned(instant)).toBe("2026-10-28 14:00:00 UTC+00:00");
    });
  });

  it("is DST-correct across a switch", () => {
    withTZ("America/New_York", () => {
      // US daylight time ends 2026-11-01 06:00 UTC.
      expect(utcOffset(Date.parse("2026-10-31T12:00:00Z"))).toBe("UTC-04:00");
      expect(utcOffset(Date.parse("2026-11-02T12:00:00Z"))).toBe("UTC-05:00");
    });
  });

  it("keeps unknown as a dash", () => {
    expect(fullLocalZoned(null)).toBe(UNKNOWN);
    expect(timeTitle(null, null, "重置 ")).toBe("重置 —");
  });

  it("titles a time with local time, zone and the raw UTC", () => {
    withTZ("Asia/Shanghai", () => {
      const title = timeTitle("2026-10-28T14:00:00Z", instant, "重置 ");
      expect(title).toContain("重置 本地 2026-10-28 22:00:00");
      expect(title).toContain("UTC+08:00");
      expect(title).toContain("Asia/Shanghai");
      expect(title).toContain("UTC 2026-10-28T14:00:00Z");
    });
  });

  it("reports no zone when Intl is unavailable", () => {
    const spy = vi.spyOn(Intl, "DateTimeFormat").mockImplementation(() => {
      throw new Error("unavailable");
    });
    try {
      expect(browserZone()).toBeNull();
    } finally {
      spy.mockRestore();
    }
  });
});
