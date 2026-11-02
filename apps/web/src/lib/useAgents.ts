"use client";

import { useCallback, useEffect, useState } from "react";
import { api as defaultApi, isApiError, type Api } from "./api";
import type { Agent } from "./types";

export type AgentsState =
  | { kind: "loading" }
  | { kind: "ready"; agents: Agent[] }
  | { kind: "error"; message: string };

/** All agents known to the server (GET /api/agents). */
export function useAgents(client: Pick<Api, "listAgents"> = defaultApi) {
  const [state, setState] = useState<AgentsState>({ kind: "loading" });
  const [token, setToken] = useState(0);

  useEffect(() => {
    const abort = new AbortController();
    client
      .listAgents(abort.signal)
      .then((agents) => setState({ kind: "ready", agents }))
      .catch((e: unknown) => {
        if (abort.signal.aborted) return;
        setState({ kind: "error", message: isApiError(e) ? e.message : "Could not load agents." });
      });
    return () => abort.abort();
  }, [client, token]);

  const reload = useCallback(() => setToken((t) => t + 1), []);
  return { state, agents: state.kind === "ready" ? state.agents : [], reload };
}
