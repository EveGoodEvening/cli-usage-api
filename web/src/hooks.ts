import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, type UsageClient } from "./api";
import type { Dashboard } from "./types";
import { parseTime } from "./format";

export const POLL_MS = 15_000;

/** A 1 s presentation tick. It never triggers a fetch or changes any value. */
export function useTick(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs]);
  return now;
}

export interface DashboardState {
  data: Dashboard | null;
  /** Server clock minus client clock, from the last response. */
  offsetMs: number;
  /** Client time of the last successful read. */
  receivedAt: number | null;
  loading: boolean;
  error: ApiError | null;
  reload: () => void;
}

function documentHidden(): boolean {
  return typeof document !== "undefined" && document.visibilityState === "hidden";
}

/** Fallback cooldown when a 429 carries no usable Retry-After. */
export const DEFAULT_RETRY_AFTER = 60;

/**
 * Whether a failed authenticated call ends the session. A valid bearer never
 * receives 429 from the API: 429 means the bearer failed verification while
 * this client is rate limited, so it is handled like 401 (credentials and data
 * cleared), never as a pause that keeps showing data for a revoked token.
 */
export function endsSession(error: ApiError): boolean {
  return error.kind === "unauthorized" || error.kind === "rate_limited";
}

export interface SignOutNotice {
  message: string;
  /** Client time before which connecting again is disabled (429 only). */
  retryAt: number | null;
}

/** The Login notice after a session ends; null for a user-initiated sign-out. */
export function signOutNotice(reason: ApiError | undefined, now: number = Date.now()): SignOutNotice | null {
  if (reason?.kind === "unauthorized") return { message: "令牌已失效或被撤销，请重新输入。", retryAt: null };
  if (reason?.kind === "rate_limited") {
    return { message: reason.message, retryAt: now + (reason.retryAfter ?? DEFAULT_RETRY_AFTER) * 1000 };
  }
  return null;
}

/**
 * Poll the dashboard every 15 s while the tab is visible. 401 or 429 hands
 * off to sign-in through `onSessionEnded`, which must clear credentials and
 * data; the hook stops polling.
 */
export function useDashboard(client: UsageClient, onSessionEnded: (error: ApiError) => void): DashboardState {
  const [data, setData] = useState<Dashboard | null>(null);
  const [offsetMs, setOffset] = useState(0);
  const [receivedAt, setReceivedAt] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const inflight = useRef<AbortController | null>(null);
  const timer = useRef<number | null>(null);
  const ended = useRef(onSessionEnded);
  ended.current = onSessionEnded;

  const schedule = useRef<(delay: number | null) => void>(() => undefined);

  /** Returns the delay before the next poll, or null when superseded. */
  const load = useCallback(async (): Promise<number | null> => {
    inflight.current?.abort();
    const controller = new AbortController();
    inflight.current = controller;
    setLoading(true);
    try {
      const result = await client.dashboard(controller.signal);
      if (controller.signal.aborted) return null;
      const received = Date.now();
      const server = parseTime(result.server_time);
      setData(result);
      setReceivedAt(received);
      setOffset(server === null ? 0 : server - received);
      setError(null);
      return POLL_MS;
    } catch (caught) {
      if (controller.signal.aborted) return null;
      const failure = caught instanceof ApiError ? caught : new ApiError("network");
      if (endsSession(failure)) {
        setData(null);
        setReceivedAt(null);
        setError(null);
        ended.current(failure);
        return null;
      }
      setError(failure);
      return POLL_MS;
    } finally {
      if (inflight.current === controller) {
        inflight.current = null;
        setLoading(false);
      }
    }
  }, [client]);

  useEffect(() => {
    schedule.current = (delay: number | null) => {
      if (delay === null) return;
      if (timer.current !== null) window.clearTimeout(timer.current);
      timer.current = window.setTimeout(async () => {
        timer.current = null;
        if (documentHidden()) return;
        schedule.current(await load());
      }, Math.max(0, delay));
    };
    void load().then((delay) => schedule.current(delay));
    const onVisibility = () => {
      if (documentHidden()) {
        if (timer.current !== null) window.clearTimeout(timer.current);
        timer.current = null;
      } else {
        void load().then((delay) => schedule.current(delay));
      }
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      if (timer.current !== null) window.clearTimeout(timer.current);
      timer.current = null;
      schedule.current = () => undefined;
      inflight.current?.abort();
    };
  }, [load]);

  const reload = useCallback(() => {
    void load().then((delay) => schedule.current(delay));
  }, [load]);

  return { data, offsetMs, receivedAt, loading, error, reload };
}
