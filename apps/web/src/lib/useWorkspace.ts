"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api as defaultApi, type Api } from "./api";
import type { WorkspaceInfo } from "./types";

const EMPTY: WorkspaceInfo = { enabled: false, structured: false, families: [], projects: [], inbox: [] };

/** The owner's workspace: projects, families and inbox. Empty (and quiet) when unavailable. */
export function useWorkspace(client: Pick<Api, "getWorkspace"> = defaultApi, refreshKey: string | number = 0) {
  const clientRef = useRef(client);
  useEffect(() => {
    clientRef.current = client;
  });
  const [info, setInfo] = useState<WorkspaceInfo>(EMPTY);
  const [token, setToken] = useState(0);

  useEffect(() => {
    const abort = new AbortController();
    clientRef.current
      .getWorkspace(abort.signal)
      .then((w) => setInfo(w))
      .catch(() => {
        // Not the owner, or no workspace: project features stay hidden.
      });
    return () => abort.abort();
  }, [token, refreshKey]);

  const reload = useCallback(() => setToken((t) => t + 1), []);
  return { workspace: info, reload };
}

/** "trading" -> "Trading", "agent-systems" -> "Agent systems". */
export function familyLabel(slug: string): string {
  const words = slug.replace(/[-_]+/g, " ").trim();
  return words ? words[0]!.toUpperCase() + words.slice(1) : slug;
}
