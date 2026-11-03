"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api as defaultApi, isApiError, type Api } from "./api";
import type { Decision, DecisionAnswerBody, DecisionAnswerResult, Run } from "./types";

export interface UseDecisionsOptions {
  client?: Pick<Api, "listDecisions" | "answerDecision">;
}

/** Keep the server's order (pending first, newest first) and replace one decision in place. */
export function replaceDecision(list: readonly Decision[], d: Decision): Decision[] {
  const i = list.findIndex((x) => x.id === d.id);
  if (i === -1) return [d, ...list];
  const next = list.slice();
  next[i] = d;
  return next;
}

/**
 * The room's decisions. Reloads whenever a run's brief appears or changes (that is when new
 * decisions are created), and after each answer.
 */
export function useDecisions(roomId: string | null, runs: readonly Run[], options: UseDecisionsOptions = {}) {
  const client = options.client ?? defaultApi;
  const clientRef = useRef(client);
  useEffect(() => {
    clientRef.current = client;
  });
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [token, setToken] = useState(0);

  // Changes when a brief is written, so new decisions are fetched without polling.
  const briefKey = runs
    .filter((r) => r.brief)
    .map((r) => `${r.id}:${r.updated_at}`)
    .join(",");

  useEffect(() => {
    if (!roomId) return;
    const abort = new AbortController();
    clientRef.current
      .listDecisions(roomId, abort.signal)
      .then((list) => {
        setDecisions(list.filter((d) => d.room_id === roomId));
        setLoaded(true);
        setError(null);
      })
      .catch((e: unknown) => {
        if (abort.signal.aborted) return;
        setLoaded(true);
        setError(isApiError(e) ? e.message : "Could not load decisions.");
      });
    return () => abort.abort();
  }, [roomId, briefKey, token]);

  const reload = useCallback(() => setToken((t) => t + 1), []);

  const answer = useCallback(async (id: string, body: DecisionAnswerBody): Promise<DecisionAnswerResult> => {
    const result = await clientRef.current.answerDecision(id, body);
    setDecisions((prev) => replaceDecision(prev, result.decision));
    return result;
  }, []);

  // Never show another room's decisions while the new room's list loads.
  const mine = roomId ? decisions.filter((d) => d.room_id === roomId) : [];
  return { decisions: mine, loaded, error, reload, answer };
}
