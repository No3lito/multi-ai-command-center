"use client";

import { useState } from "react";
import type { Run } from "@/lib/types";
import { PanelSection } from "./PanelSection";

interface Props {
  runs: Run[];
}

/** First line of a brief's "Bottom line", without the heading. */
export function bottomLine(brief: string): string {
  for (const raw of brief.split("\n")) {
    const line = raw.trim();
    const bare = line.replace(/^[#*_\s]+/, "");
    if (/^bottom line/i.test(bare)) {
      const rest = line.includes(":")
        ? line
            .slice(line.indexOf(":") + 1)
            .replace(/^[\s*_]+/, "")
            .trim()
        : "";
      if (rest) return rest;
    }
  }
  const first = brief.split("\n").find((l) => l.trim() && !/^[#*_\s]*bottom line/i.test(l.trim()));
  return (first ?? "").replace(/^[-*•\s]+/, "").trim();
}

/** Conclusions of finished runs in this room: the bottom line, and what is waiting on the owner. */
export function DecisionsPanel({ runs }: Props) {
  const withBriefs = runs.filter((r) => r.brief);
  const [open, setOpen] = useState<string | null>(null);
  const latest = withBriefs[0];
  if (!latest) return null;
  const waiting = latest.pending_decisions ?? [];

  return (
    <PanelSection title="Decisions" count={withBriefs.length} testId="decisions-panel">
      <div className="mb-2 rounded-md border border-accent bg-accent-soft p-2 text-xs" data-testid="decision-latest">
        <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-accent">Latest conclusion</p>
        <p className="font-medium text-fg">{bottomLine(latest.brief ?? "")}</p>
        <p className="mt-0.5 truncate text-[10px] text-muted" title={latest.goal}>
          {latest.goal.split("\n")[0]}
        </p>
      </div>
      <div className="mb-2" data-testid="decision-waiting">
        <p className="mb-1 text-[11px] font-semibold text-fg">
          Waiting on you {waiting.length > 0 && <span className="text-warn">({waiting.length})</span>}
        </p>
        {waiting.length === 0 ? (
          <p className="text-xs text-muted">Nothing. No decision is needed from the latest run.</p>
        ) : (
          <ul className="list-disc space-y-1 pl-4 text-xs text-fg">
            {waiting.map((item, i) => (
              <li key={i} data-testid="decision-item">
                {item}
              </li>
            ))}
          </ul>
        )}
      </div>
      <ul className="space-y-1.5">
        {withBriefs.slice(0, 10).map((r) => {
          const expanded = open === r.id;
          return (
            <li key={r.id} data-testid="decision-brief" className="rounded-md border border-line bg-bg px-2 py-1.5">
              <button
                type="button"
                className="w-full text-left text-xs"
                aria-expanded={expanded}
                onClick={() => setOpen(expanded ? null : r.id)}
              >
                <span className="font-medium">{bottomLine(r.brief ?? "")}</span>
                <span className="block truncate text-[10px] text-muted">
                  {new Date(r.finished_at ?? r.updated_at).toLocaleString()} · {r.goal.split("\n")[0]}
                </span>
              </button>
              {expanded && (
                <div data-testid="decision-brief-full" className="mt-1 whitespace-pre-wrap text-xs text-fg">
                  {r.brief}
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </PanelSection>
  );
}
