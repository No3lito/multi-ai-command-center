"use client";

import { useState } from "react";
import { isApiError } from "@/lib/api";
import type { Agent, AgentStatus, Principal } from "@/lib/types";
import { ErrorText, PanelSection, Pill, type PillTone } from "./PanelSection";

const STATUS: Record<AgentStatus, { label: string; tone: PillTone; title: string }> = {
  live: { label: "Live", tone: "ok", title: "API key configured and price known." },
  simulated: { label: "Simulated", tone: "warn", title: "Uses the local stand-in. No real API calls, no cost." },
  missing_key: { label: "No API key", tone: "danger", title: "No API key is configured for this provider." },
  unknown_price: { label: "No price", tone: "danger", title: "This model has no price, so live calls are blocked." },
  disabled: { label: "Disabled", tone: "muted", title: "This agent is turned off." },
};

export function agentStatusLabel(status: AgentStatus): string {
  return STATUS[status]?.label ?? status;
}

export function AgentStatusPill({ status }: { status: AgentStatus | "unknown" }) {
  const s =
    status === "unknown"
      ? { label: "Unknown", tone: "muted" as const, title: "This agent is not in the agent list." }
      : (STATUS[status] ?? { label: status, tone: "muted" as const, title: "" });
  return (
    <Pill tone={s.tone} testId="agent-status" value={status} title={s.title}>
      {s.label}
    </Pill>
  );
}

/** A room member of kind agent, joined with its profile when the agent list has it. */
export interface RoomAgent {
  member: Principal;
  agent: Agent | null;
}

interface Props {
  hasRoom: boolean;
  loading: boolean;
  error: string | null;
  roomAgents: RoomAgent[];
  otherAgents: Agent[];
  onAdd: (agentId: string) => Promise<void>;
  onRetry: () => void;
}

export function AgentsPanel({ hasRoom, loading, error, roomAgents, otherAgents, onAdd, onRetry }: Props) {
  const [adding, setAdding] = useState<string | null>(null);
  const [addError, setAddError] = useState<string | null>(null);

  async function add(id: string) {
    setAdding(id);
    setAddError(null);
    try {
      await onAdd(id);
    } catch (e) {
      setAddError(isApiError(e) ? e.message : "Could not add the agent.");
    } finally {
      setAdding(null);
    }
  }

  return (
    <PanelSection title="Agents" count={hasRoom ? roomAgents.length : undefined} testId="agents-panel">
      {!hasRoom ? (
        <p className="text-xs text-muted">No room selected.</p>
      ) : (
        <>
          {loading && roomAgents.length === 0 && <p className="text-xs text-muted">Loading...</p>}
          {!loading && roomAgents.length === 0 && <p className="text-xs text-muted">No agents in this room yet.</p>}
          <ul className="space-y-1.5">
            {roomAgents.map(({ member, agent }) => (
              <li key={member.id} data-testid="agent-item" data-agent-id={member.id} data-in-room="true">
                <div className="flex items-center gap-2">
                  <span className="min-w-0 flex-1 truncate font-medium">{member.display_name}</span>
                  <AgentStatusPill status={agent?.status ?? "unknown"} />
                </div>
                {agent && (
                  <p className="truncate font-mono text-[10px] text-muted" title={`${agent.provider} / ${agent.model}`}>
                    {agent.role ? `${agent.role} · ` : ""}
                    {agent.provider} / {agent.model}
                  </p>
                )}
              </li>
            ))}
          </ul>

          {otherAgents.length > 0 && (
            <div className="mt-3">
              <h4 className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted">Not in this room</h4>
              <ul className="space-y-1.5">
                {otherAgents.map((a) => (
                  <li key={a.id} data-testid="agent-item" data-agent-id={a.id} data-in-room="false">
                    <div className="flex items-center gap-2">
                      <span className="min-w-0 flex-1 truncate">{a.display_name}</span>
                      <AgentStatusPill status={a.status} />
                      <button
                        type="button"
                        data-testid="add-agent-to-room"
                        onClick={() => void add(a.id)}
                        disabled={adding !== null}
                        aria-label={`Add ${a.display_name} to room`}
                        className="rounded border border-line px-1.5 py-px text-[11px] font-medium hover:bg-panel-2 disabled:opacity-50"
                      >
                        {adding === a.id ? "Adding" : "Add to room"}
                      </button>
                    </div>
                    <p className="truncate font-mono text-[10px] text-muted">
                      {a.provider} / {a.model}
                    </p>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {error && (
            <p role="alert" className="mt-1 text-xs text-danger">
              {error}{" "}
              <button type="button" onClick={onRetry} className="font-medium text-fg underline">
                Retry
              </button>
            </p>
          )}
          {addError && <ErrorText>{addError}</ErrorText>}
        </>
      )}
    </PanelSection>
  );
}
