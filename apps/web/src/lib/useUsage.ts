"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api as defaultApi, isApiError, type Api } from "./api";
import { useNewMessages } from "./useNewMessages";
import type { Message, Usage } from "./types";

export interface UseUsageOptions {
  client?: Pick<Api, "getUsage">;
  pollMs?: number;
  /** Coalesces bursts of agent messages into one request. */
  debounceMs?: number;
}

/** Instance-wide usage (GET /api/usage). Refreshes after agent messages and on an interval. */
export function useUsage(messages: readonly Message[], streamReady: boolean, options: UseUsageOptions = {}) {
  const client = options.client ?? defaultApi;
  const pollMs = options.pollMs ?? 30_000;
  const debounceMs = options.debounceMs ?? 300;
  const [usage, setUsage] = useState<Usage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [token, setToken] = useState(0);
  const clientRef = useRef(client);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    clientRef.current = client;
  });

  useEffect(() => {
    const abort = new AbortController();
    clientRef.current
      .getUsage(abort.signal)
      .then((u) => {
        setUsage(u);
        setError(null);
      })
      .catch((e: unknown) => {
        if (abort.signal.aborted) return;
        setError(isApiError(e) ? e.message : "Could not load usage.");
      });
    return () => abort.abort();
  }, [token]);

  useEffect(() => {
    const timer = setInterval(() => setToken((t) => t + 1), pollMs);
    return () => clearInterval(timer);
  }, [pollMs]);

  useEffect(
    () => () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    },
    [],
  );

  const reload = useCallback(() => setToken((t) => t + 1), []);

  useNewMessages(messages, streamReady, (fresh) => {
    if (!fresh.some((m) => m.sender.kind === "agent")) return;
    if (debounceRef.current) return;
    debounceRef.current = setTimeout(() => {
      debounceRef.current = null;
      setToken((t) => t + 1);
    }, debounceMs);
  });

  return { usage, error, reload };
}
