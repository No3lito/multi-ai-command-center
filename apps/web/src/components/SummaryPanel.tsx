"use client";

import { useState } from "react";
import { formatUsd } from "@/lib/format";
import { isRunActive, type Decision, type Run, type Usage } from "@/lib/types";
import { bottomLine } from "./DecisionsPanel";

const KEY = (roomId: string) => `cc.lastSeen.${roomId}`;
const DAY_MS = 24 * 60 * 60 * 1000;

const seen = new Map<string, number | null>();

/**
 * When the owner last opened this room in this browser, read once per page load (then set to
 * now), so repeated renders agree. A convenience only: without storage it is null and the
 * summary covers the last 24 hours.
 */
export function lastSeenFor(roomId: string, now: () => number = Date.now): number | null {
  if (!seen.has(roomId)) {
    let at: number | null = null;
    try {
      const raw = window.localStorage.getItem(KEY(roomId));
      at = raw ? Number(raw) || null : null;
      window.localStorage.setItem(KEY(roomId), String(now()));
    } catch {
      at = null;
    }
    seen.set(roomId, at);
  }
  return seen.get(roomId) ?? null;
}

/** Tests only. */
export function resetLastSeen(): void {
  seen.clear();
}

export interface SummaryInput {
  runs: readonly Run[];
  decisions: readonly Decision[];
  usage: Usage | null;
  since: number | null;
  now: number;
  agentName: (id: string | null) => string | null;
}

export interface Summary {
  sinceLabel: string;
  finished: { id: string; line: string; status: Run["status"] }[];
  waiting: { question: string; cost: string | null }[];
  active: { id: string; goal: string; waitingFor: string | null }[];
  spend: { spent: number; cap: number; remaining: number } | null;
}

/** What happened since the owner last looked, in a few plain lines. */
export function buildSummary({ runs, decisions, usage, since, now, agentName }: SummaryInput): Summary {
  const from = since ?? now - DAY_MS;
  const visible = runs.filter((r) => !r.archived_at && r.kind !== "reply");
  const finished = visible
    .filter((r) => !isRunActive(r) && r.finished_at && Date.parse(r.finished_at) > from)
    .map((r) => ({
      id: r.id,
      status: r.status,
      line: (r.brief ? bottomLine(r.brief) : "") || r.goal.split("\n")[0]!.slice(0, 160),
    }));
  return {
    sinceLabel: since ? `Since you last looked (${new Date(since).toLocaleString()})` : "In the last 24 hours",
    finished,
    waiting: decisions.filter((d) => d.status === "pending").map((d) => ({ question: d.question, cost: d.cost })),
    active: visible.filter(isRunActive).map((r) => ({
      id: r.id,
      goal: r.goal.split("\n")[0]!.slice(0, 120),
      waitingFor: r.status === "waiting" ? (agentName(r.waiting_for ?? null) ?? "a connected agent") : null,
    })),
    spend: usage ? { spent: usage.spent_usd, cap: usage.cap_usd, remaining: usage.remaining_usd } : null,
  };
}

/** The top of the Decide tab: the few things the owner needs to know, without reading the chat. */
export function SummaryPanel(props: Omit<SummaryInput, "now"> & { now?: number }) {
  const [mountedAt] = useState(() => Date.now());
  const s = buildSummary({ ...props, now: props.now ?? mountedAt });
  const nothing = s.finished.length === 0 && s.waiting.length === 0 && s.active.length === 0;
  return (
    <section data-testid="summary-panel" className="border-b border-line px-3 py-3 text-xs">
      <h3 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted">{s.sinceLabel}</h3>
      <ul className="list-disc space-y-1 pl-4 text-fg">
        {s.finished.length > 0 && (
          <li data-testid="summary-finished">
            <span className="font-semibold">
              {s.finished.length} {s.finished.length === 1 ? "run" : "runs"} finished.
            </span>
            <ul className="mt-0.5 space-y-0.5 text-muted">
              {s.finished.slice(0, 3).map((f) => (
                <li key={f.id}>{f.line}</li>
              ))}
            </ul>
          </li>
        )}
        <li data-testid="summary-waiting">
          {s.waiting.length === 0 ? (
            "Nothing is waiting on you."
          ) : (
            <span className="font-semibold text-warn">
              {s.waiting.length} {s.waiting.length === 1 ? "decision is" : "decisions are"} waiting on you, below.
            </span>
          )}
        </li>
        {s.active.length > 0 && (
          <li data-testid="summary-active">
            {s.active.length} in progress
            {s.active.some((a) => a.waitingFor)
              ? `; waiting for ${[...new Set(s.active.map((a) => a.waitingFor).filter(Boolean))].join(", ")}`
              : ""}
            .
          </li>
        )}
        {s.spend && (
          <li data-testid="summary-spend">
            Spent {formatUsd(s.spend.spent)} of {formatUsd(s.spend.cap)}; {formatUsd(s.spend.remaining)} left.
          </li>
        )}
        {nothing && <li className="text-muted">No new results since then.</li>}
      </ul>
    </section>
  );
}
