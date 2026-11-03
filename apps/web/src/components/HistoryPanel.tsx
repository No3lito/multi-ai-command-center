"use client";

import { useEffect, useRef, useState } from "react";
import { isApiError, type Api } from "@/lib/api";
import type { HistoryResult, Run } from "@/lib/types";
import { bottomLine } from "./DecisionsPanel";
import { PanelSection } from "./PanelSection";
import { VerdictPill } from "./VerdictPill";

interface Props {
  roomId: string;
  client: Pick<Api, "history" | "archiveRun" | "unarchiveRun">;
  /** Called with the updated run after archiving or unarchiving, so the chat and run list update. */
  onRunChanged: (run: Run) => void;
  /** Changes when runs finish, so the list refreshes without polling. */
  refreshKey?: string;
  debounceMs?: number;
}

const STATUS_LABEL: Record<string, string> = {
  pending: "Pending",
  approved: "Approved",
  declined: "Declined",
  more_info: "More info asked",
  dismissed: "Dismissed",
};

/** Every past brief and decision in the room, searchable; archived runs come back from here. */
export function HistoryPanel({ roomId, client, onRunChanged, refreshKey = "", debounceMs = 300 }: Props) {
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [archivedOnly, setArchivedOnly] = useState(false);
  const [result, setResult] = useState<HistoryResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [token, setToken] = useState(0);
  const clientRef = useRef(client);
  useEffect(() => {
    clientRef.current = client;
  });

  useEffect(() => {
    const t = setTimeout(() => setQuery(q.trim()), debounceMs);
    return () => clearTimeout(t);
  }, [q, debounceMs]);

  useEffect(() => {
    const abort = new AbortController();
    clientRef.current
      .history(roomId, query, archivedOnly ? "only" : "include", abort.signal)
      .then((r) => {
        setResult(r);
        setError(null);
      })
      .catch((e: unknown) => {
        if (!abort.signal.aborted) setError(isApiError(e) ? e.message : "Could not load history.");
      });
    return () => abort.abort();
  }, [roomId, query, archivedOnly, refreshKey, token]);

  const toggleArchive = async (run: Run) => {
    try {
      const updated = run.archived_at
        ? await clientRef.current.unarchiveRun(run.id)
        : await clientRef.current.archiveRun(run.id);
      onRunChanged(updated);
      setToken((t) => t + 1);
    } catch (e: unknown) {
      setError(isApiError(e) ? e.message : "Could not update the run.");
    }
  };

  const runs = result?.runs ?? [];
  const decisions = (result?.decisions ?? []).filter((d) => query || d.status !== "pending");
  return (
    <PanelSection title="History" count={result ? runs.length : undefined} testId="history-panel">
      <div className="mb-2 flex items-center gap-2">
        <input
          type="search"
          data-testid="history-search"
          aria-label="Search past runs and decisions"
          placeholder="Search, e.g. H123 or Helius"
          className="min-w-0 flex-1 rounded border border-line bg-bg px-2 py-1 text-xs"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <label className="flex shrink-0 items-center gap-1 text-[11px] text-muted">
          <input
            type="checkbox"
            data-testid="history-archived"
            checked={archivedOnly}
            onChange={(e) => setArchivedOnly(e.target.checked)}
          />
          Archived only
        </label>
      </div>
      {error && <p className="mb-1 text-xs text-danger">{error}</p>}
      {result && runs.length === 0 && decisions.length === 0 && (
        <p className="text-xs text-muted">{query ? "Nothing matches." : "No finished runs yet."}</p>
      )}
      <ul className="space-y-1.5">
        {runs.map((r) => {
          const expanded = open === r.id;
          return (
            <li
              key={r.id}
              data-testid="history-run"
              data-run-id={r.id}
              className="rounded-md border border-line bg-bg px-2 py-1.5"
            >
              <button
                type="button"
                className="w-full text-left text-xs"
                aria-expanded={expanded}
                onClick={() => setOpen(expanded ? null : r.id)}
              >
                <span className="flex items-start gap-1.5 font-medium">
                  <VerdictPill verdict={r.verdict} />
                  <span>{(r.brief && bottomLine(r.brief)) || r.goal.split("\n")[0]}</span>
                </span>
                <span className="block truncate text-[10px] text-muted">
                  {new Date(r.finished_at ?? r.updated_at).toLocaleString()} · {r.goal.split("\n")[0]}
                  {r.archived_at ? " · archived" : ""}
                </span>
              </button>
              {expanded && (
                <div data-testid="history-brief" className="mt-1 whitespace-pre-wrap text-xs text-fg">
                  {r.brief ?? "This run has no brief."}
                </div>
              )}
              <button
                type="button"
                data-testid="history-archive-toggle"
                className="mt-1 text-[11px] text-muted underline"
                onClick={() => void toggleArchive(r)}
              >
                {r.archived_at ? "Unarchive (show in chat again)" : "Archive"}
              </button>
            </li>
          );
        })}
      </ul>
      {decisions.length > 0 && (
        <>
          <p className="mb-1 mt-3 text-[11px] font-semibold text-fg">Decisions</p>
          <ul className="space-y-1">
            {decisions.map((d) => (
              <li key={d.id} data-testid="history-decision" className="text-[11px]">
                <span className="mr-1 text-[10px] font-medium text-muted">{STATUS_LABEL[d.status] ?? d.status}</span>
                <span className="text-fg">{d.question}</span>
                {d.owner_note && <span className="block text-[10px] text-muted">Note: {d.owner_note}</span>}
              </li>
            ))}
          </ul>
        </>
      )}
    </PanelSection>
  );
}
