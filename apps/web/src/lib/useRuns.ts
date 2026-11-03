"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api as defaultApi, isApiError, type Api } from "./api";
import { useNewMessages } from "./useNewMessages";
import { isRunActive, type Message, type Run } from "./types";

export interface UseRunsOptions {
  client?: Pick<Api, "listRuns" | "getRun" | "cancelRun"> & Partial<Pick<Api, "wrapUpRun" | "tryAgainRun">>;
  /** Poll interval while any run is queued or running. */
  pollMs?: number;
  limit?: number;
}

const RUN_ID = /^run_/;

/** Keep the newer copy of each run (by updated_at); unknown runs go first. */
export function upsertRun(list: readonly Run[], run: Run): Run[] {
  const i = list.findIndex((r) => r.id === run.id);
  if (i === -1) return [run, ...list];
  const existing = list[i]!;
  if (existing.updated_at > run.updated_at) return list as Run[];
  const next = list.slice();
  next[i] = run;
  return next;
}

function mergeList(prev: readonly Run[], incoming: readonly Run[]): Run[] {
  const byId = new Map(prev.map((r) => [r.id, r]));
  return incoming.map((r) => {
    const old = byId.get(r.id);
    return old && old.updated_at > r.updated_at ? old : r;
  });
}

/**
 * The room's recent runs. Refreshes one run when a room message carries its id
 * as `correlation_id`, reloads the list when an unknown run id appears, and
 * polls while any run is active.
 */
export function useRuns(
  roomId: string | null,
  messages: readonly Message[],
  streamReady: boolean,
  options: UseRunsOptions = {},
) {
  const client = options.client ?? defaultApi;
  const pollMs = options.pollMs ?? 10_000;
  const limit = options.limit ?? 20;
  const [runs, setRuns] = useState<Run[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [listToken, setListToken] = useState(0);
  const runsRef = useRef<Run[]>([]);
  const clientRef = useRef(client);

  useEffect(() => {
    runsRef.current = runs;
    clientRef.current = client;
  });

  useEffect(() => {
    if (!roomId) return;
    const abort = new AbortController();
    clientRef.current
      .listRuns(roomId, limit, abort.signal)
      .then((list) => {
        const mine = list.filter((r) => r.room_id === roomId);
        setRuns((prev) => mergeList(prev, mine));
        setLoaded(true);
        setError(null);
      })
      .catch((e: unknown) => {
        if (abort.signal.aborted) return;
        setLoaded(true);
        setError(isApiError(e) ? e.message : "Could not load runs.");
      });
    return () => abort.abort();
  }, [roomId, limit, listToken]);

  const reload = useCallback(() => setListToken((t) => t + 1), []);

  const refreshRun = useCallback(async (runId: string) => {
    try {
      const run = await clientRef.current.getRun(runId);
      setRuns((prev) => upsertRun(prev, run));
    } catch {
      // The poll or the next correlated message will catch up.
    }
  }, []);

  useNewMessages(messages, streamReady, (fresh) => {
    const ids = new Set<string>();
    for (const m of fresh) if (m.correlation_id && RUN_ID.test(m.correlation_id)) ids.add(m.correlation_id);
    let unknown = false;
    for (const id of ids) {
      if (runsRef.current.some((r) => r.id === id)) void refreshRun(id);
      else unknown = true;
    }
    if (unknown) reload();
  });

  const anyActive = runs.some(isRunActive);
  useEffect(() => {
    if (!anyActive || !roomId) return;
    const timer = setInterval(() => setListToken((t) => t + 1), pollMs);
    return () => clearInterval(timer);
  }, [anyActive, roomId, pollMs]);

  const addRun = useCallback((run: Run) => setRuns((prev) => upsertRun(prev, run)), []);

  const cancel = useCallback(async (runId: string) => {
    const run = await clientRef.current.cancelRun(runId);
    setRuns((prev) => upsertRun(prev, run));
    return run;
  }, []);

  const wrapUp = useCallback(async (runId: string) => {
    const fn = clientRef.current.wrapUpRun;
    if (!fn) throw new Error("Wrap up is not available.");
    const run = await fn(runId);
    setRuns((prev) => upsertRun(prev, run));
    return run;
  }, []);

  const tryAgain = useCallback(async (runId: string) => {
    const fn = clientRef.current.tryAgainRun;
    if (!fn) throw new Error("Try again is not available.");
    const run = await fn(runId);
    setRuns((prev) => upsertRun(prev, run));
    return run;
  }, []);

  return { runs, loaded, error, reload, addRun, cancel, wrapUp, tryAgain };
}
