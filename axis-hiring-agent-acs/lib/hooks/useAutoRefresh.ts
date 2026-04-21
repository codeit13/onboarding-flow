"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Polls an async loader on a fixed interval and exposes the latest value,
 * loading + error state, and a manual `refresh` callback.
 *
 * Designed to drive every "live" pane in the app — Thrive employee status,
 * the HR kanban, the HR application detail page, the Panel queue. The
 * orchestrator runs in a background thread on the backend, so we can't push
 * server events; instead each pane polls every few seconds.
 *
 * The loader is wrapped in a stable callback ref so the consumer can pass
 * an inline arrow function without thrashing the interval. The interval is
 * paused when the document tab is hidden — there's no point burning cycles
 * on a backgrounded tab during the demo.
 */
export function useAutoRefresh<T>(
  loader: () => Promise<T>,
  intervalMs = 4000,
): {
  data: T | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
} {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Stable ref so the polling effect doesn't re-subscribe on every render.
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  const refresh = useCallback(async () => {
    try {
      const next = await loaderRef.current();
      setData(next);
      setError(null);
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const tick = async () => {
      if (cancelled) return;
      if (typeof document !== "undefined" && document.hidden) {
        // Tab is hidden — skip the network round-trip but keep the timer alive.
        timer = setTimeout(tick, intervalMs);
        return;
      }
      await refresh();
      if (cancelled) return;
      timer = setTimeout(tick, intervalMs);
    };

    tick();

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [intervalMs, refresh]);

  return { data, loading, error, refresh };
}
