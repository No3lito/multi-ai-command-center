"use client";

import { useState } from "react";
import { isApiError } from "@/lib/api";
import { formatUsd } from "@/lib/format";
import { isRunActive, type Run, type RunStatus } from "@/lib/types";
import { ErrorText, PanelSection, Pill, type PillTone } from "./PanelSection";

const STATUS: Record<RunStatus, { label: string; tone: PillTone }> = {
  queued: { label: "Queued", tone: "muted" },
  running: { label: "Running", tone: "accent" },
  completed: { label: "Completed", tone: "ok" },
  failed: { label: "Failed", tone: "danger" },
  cancelled: { label: "Cancelled", tone: "muted" },
  budget_exceeded: { label: "Over budget", tone: "danger" },
};

interface Props {
  hasRoom: boolean;
  runs: Run[];
  loaded: boolean;
  error: string | null;
  agentName: (id: string | null) => string | null;
  onCancel: (runId: string) => Promise<unknown>;
  onRetry: () => void;
}

export function RunsPanel({ hasRoom, runs, loaded, error, agentName, onCancel, onRetry }: Props) {
  return (
    <PanelSection title="Runs" count={hasRoom ? runs.length : undefined} testId="runs-panel">
      {!hasRoom ? (
        <p className="text-xs text-muted">No room selected.</p>
      ) : (
        <>
          {!loaded && <p className="text-xs text-muted">Loading...</p>}
          {loaded && runs.length === 0 && !error && <p className="text-xs text-muted">No runs yet.</p>}
          <ul className="space-y-2">
            {runs.map((r) => (
              <RunItem key={r.id} run={r} agentName={agentName} onCancel={onCancel} />
            ))}
          </ul>
          {error && (
            <p role="alert" className="mt-1 text-xs text-danger">
              {error}{" "}
              <button type="button" onClick={onRetry} className="font-medium text-fg underline">
                Retry
              </button>
            </p>
          )}
        </>
      )}
    </PanelSection>
  );
}

function RunItem({
  run,
  agentName,
  onCancel,
}: {
  run: Run;
  agentName: (id: string | null) => string | null;
  onCancel: (runId: string) => Promise<unknown>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const s = STATUS[run.status] ?? { label: run.status, tone: "muted" as const };
  const active = isRunActive(run);
  const who =
    run.kind === "collab"
      ? [agentName(run.planner_id), agentName(run.critic_id)].filter(Boolean).join(" and ")
      : agentName(run.agent_id);

  async function cancel() {
    setBusy(true);
    setError(null);
    try {
      await onCancel(run.id);
    } catch (e) {
      setError(isApiError(e) ? e.message : "Could not cancel the run.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <li
      data-testid="run-item"
      data-run-id={run.id}
      data-status={run.status}
      className="rounded-md border border-line bg-bg px-2 py-1.5"
    >
      <div className="flex items-center gap-1.5">
        <Pill tone={s.tone} testId="run-status" value={run.status}>
          {s.label}
        </Pill>
        <span className="font-mono text-[10px] uppercase text-muted">{run.kind}</span>
        {run.simulated && (
          <span
            data-testid="run-simulated"
            className="rounded bg-warn-soft px-1 font-mono text-[10px] font-bold uppercase text-warn"
          >
            Simulated
          </span>
        )}
        {active && (
          <button
            type="button"
            data-testid="run-cancel"
            onClick={() => void cancel()}
            disabled={busy}
            className="ml-auto rounded border border-line px-1.5 py-px text-[11px] font-medium hover:bg-panel-2 disabled:opacity-50"
          >
            {busy ? "Cancelling" : "Cancel"}
          </button>
        )}
      </div>
      <p className="mt-1 line-clamp-2 break-words text-xs" title={run.goal}>
        {run.goal || <span className="text-muted">(no goal)</span>}
      </p>
      {who && <p className="truncate text-[10px] text-muted">{who}</p>}
      <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-2 font-mono text-[10px] text-muted">
        <dt>step</dt>
        <dd data-testid="run-step" className="text-fg">
          {run.step}
        </dd>
        <dt>turns</dt>
        <dd data-testid="run-turns" className="text-fg">
          {run.turn_count}/{run.max_turns}
        </dd>
        <dt>spent</dt>
        <dd data-testid="run-spent" className="text-fg">
          {formatUsd(run.spent_usd)} of {formatUsd(run.budget_usd)}
        </dd>
      </dl>
      {run.error && <p className="mt-1 break-words text-[11px] text-danger">{run.error}</p>}
      {error && <ErrorText>{error}</ErrorText>}
    </li>
  );
}
