"use client";

import { useRef, useState } from "react";
import { isApiError } from "@/lib/api";
import type { Decision, DecisionAnswer, DecisionAnswerBody, FollowUpPlan, Run } from "@/lib/types";
import { PanelSection } from "./PanelSection";
import { VerdictPill } from "./VerdictPill";

interface Props {
  runs: Run[];
  decisions?: Decision[];
  onAnswer?: (decisionId: string, body: DecisionAnswerBody) => Promise<unknown>;
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

/** Plain words for what runs when the owner answers. */
export function describePlan(plan: FollowUpPlan): string {
  if (plan.workflow === "none") return "Nothing more runs; your answer is recorded and shared with the agents.";
  if ((plan.workflow === "review" || plan.workflow === "build") && plan.worker)
    return `${plan.worker} does the work, then Claude and GPT check it.`;
  return "Claude and GPT work it out and report back.";
}

const FOLLOW_LABEL: Record<DecisionAnswer, string> = {
  approve: "Approve",
  more_info: "Need more info",
  decline: "Decline",
  dismiss: "Dismiss",
};

const STATUS_LABEL: Record<Decision["status"], string> = {
  pending: "Pending",
  approved: "Approved",
  declined: "Declined",
  more_info: "More info asked",
  dismissed: "Dismissed",
};

function DecisionCard({
  decision,
  onAnswer,
}: {
  decision: Decision;
  onAnswer?: (decisionId: string, body: DecisionAnswerBody) => Promise<unknown>;
}) {
  // The agents' suggested note is filled in; the owner can edit it or clear it.
  const [showNote, setShowNote] = useState(!!decision.suggested_note);
  const [note, setNote] = useState(decision.suggested_note ?? "");
  const follow = decision.recommended ?? null;
  const [budget, setBudget] = useState("");
  const [busy, setBusy] = useState<DecisionAnswer | null>(null);
  // Every answer is confirmed first: what it does and its budget, before anything starts.
  const [confirming, setConfirming] = useState<DecisionAnswer | null>(null);
  const sending = useRef(false);
  const [error, setError] = useState<string | null>(null);

  const budgetNum = budget.trim() ? Number(budget) : undefined;
  const budgetBad = budgetNum !== undefined && (!Number.isFinite(budgetNum) || budgetNum <= 0 || budgetNum > 5);

  const send = async (answer: DecisionAnswer) => {
    const startsRun = answer === "approve" || answer === "more_info";
    if (!onAnswer || (startsRun && budgetBad) || sending.current) return;
    sending.current = true; // a double click sends once
    setBusy(answer);
    setError(null);
    try {
      await onAnswer(decision.id, {
        answer,
        ...(note.trim() ? { note: note.trim() } : {}),
        ...(budgetNum !== undefined && startsRun ? { budget_usd: budgetNum } : {}),
      });
    } catch (e: unknown) {
      setError(isApiError(e) ? e.message : "Could not save your answer.");
    } finally {
      sending.current = false;
      setBusy(null);
      setConfirming(null);
    }
  };

  const btn = "rounded-md px-2 py-1 text-[11px] font-medium disabled:opacity-50";
  return (
    <li
      data-testid="decision-card"
      data-recommended={decision.recommended ?? undefined}
      className="rounded-md border border-line bg-bg p-2 text-xs"
      style={{ borderLeft: `4px solid ${EDGE[decision.recommended ?? "none"]}` }}
    >
      <p className="font-medium text-fg">
        {decision.final_round && (
          <span
            data-testid="decision-final-round"
            className="mr-1 rounded bg-warn-soft px-1 text-[10px] font-semibold text-warn"
            title="This topic reached its follow-up limit: this is the final recommendation"
          >
            Final round
          </span>
        )}
        {decision.question}
      </p>
      {decision.why && (
        <p className="mt-1 text-fg" data-testid="decision-why">
          <span className="font-semibold">Why it matters: </span>
          {decision.why}
        </p>
      )}
      {decision.recommendation && (
        <p className="mt-1 text-fg" data-testid="decision-recommendation">
          <span className="font-semibold text-accent">Recommended: </span>
          {decision.recommendation}
        </p>
      )}
      <p className="mt-0.5 text-[11px] text-muted" data-testid="decision-cost">
        Cost: {decision.cost || "unknown"}
      </p>
      {decision.cannot_run_reason ? (
        <p className="mt-0.5 text-[11px] text-warn" data-testid="decision-cannot-run">
          If approved: nothing starts. {decision.cannot_run_reason} Your answer is still recorded.
        </p>
      ) : (
        <p className="mt-0.5 text-[11px] text-muted" data-testid="decision-plan">
          If approved: {describePlan(decision.on_approve)}
        </p>
      )}
      {showNote ? (
        <div className="mt-1.5 space-y-1">
          <textarea
            data-testid="decision-note"
            className="w-full rounded border border-line bg-bg p-1 text-xs"
            rows={4}
            maxLength={2000}
            placeholder="Optional note or limit, e.g. cap at 50k Helius credits"
            aria-label="Note for the agents"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
          <label className="flex items-center gap-1 text-[11px] text-muted">
            Budget for the follow-up run, $
            <input
              data-testid="decision-budget"
              className="w-16 rounded border border-line bg-bg px-1 py-0.5 text-xs"
              inputMode="decimal"
              placeholder="0.50"
              value={budget}
              onChange={(e) => setBudget(e.target.value)}
            />
          </label>
          {budgetBad && <p className="text-[11px] text-danger">Budget must be above $0 and at most $5.</p>}
        </div>
      ) : (
        <button
          type="button"
          className="mt-1 text-[11px] underline"
          data-testid="decision-add-note"
          onClick={() => setShowNote(true)}
        >
          Add a note or budget
        </button>
      )}
      {follow && (
        <button
          type="button"
          data-testid="decision-follow"
          className={`${btn} mt-2 w-full bg-accent py-1.5 text-white`}
          disabled={!!busy || !onAnswer || (follow !== "decline" && budgetBad)}
          onClick={() => setConfirming(follow)}
          title={note.trim() ? "Sends the note above with your answer" : undefined}
        >
          {busy === follow ? "Saving…" : `Do what they recommend: ${FOLLOW_LABEL[follow]}`}
          {note.trim() ? " (with the note)" : ""}
        </button>
      )}
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <button
          type="button"
          data-testid="decision-approve"
          className={`${btn} ${follow ? "border border-line" : "bg-accent text-white"}`}
          disabled={!!busy || !onAnswer || budgetBad}
          onClick={() => setConfirming("approve")}
        >
          {busy === "approve" ? "Starting…" : "Approve"}
        </button>
        <button
          type="button"
          data-testid="decision-more-info"
          className={`${btn} border border-line`}
          disabled={!!busy || !onAnswer || budgetBad}
          onClick={() => setConfirming("more_info")}
        >
          Need more info
        </button>
        <button
          type="button"
          data-testid="decision-decline"
          className={`${btn} border border-line text-danger`}
          disabled={!!busy || !onAnswer}
          onClick={() => setConfirming("decline")}
        >
          Decline
        </button>
        <button
          type="button"
          data-testid="decision-dismiss"
          className="ml-auto text-[10px] text-muted underline disabled:opacity-50"
          disabled={!!busy || !onAnswer}
          onClick={() => setConfirming("dismiss")}
          title="No longer relevant; nothing runs"
        >
          Dismiss
        </button>
      </div>
      {confirming && (
        <div data-testid="decision-confirm-box" className="mt-2 rounded-md border border-accent bg-accent-soft p-2">
          <p className="text-[11px] font-semibold text-fg">
            Your answer: {FOLLOW_LABEL[confirming]}
            {note.trim() ? " (with the note above)" : ""}
          </p>
          <p className="mt-0.5 text-[11px] text-fg" data-testid="decision-what-happens">
            {whatHappens(decision, confirming, budgetNum)}
          </p>
          <div className="mt-1.5 flex items-center gap-2">
            <button
              type="button"
              data-testid="decision-confirm"
              className={`${btn} bg-accent text-white`}
              disabled={!!busy}
              onClick={() => void send(confirming)}
            >
              {busy ? "Saving…" : confirmLabel(decision, confirming, budgetNum)}
            </button>
            <button
              type="button"
              data-testid="decision-confirm-back"
              className="text-[11px] text-muted underline"
              disabled={!!busy}
              onClick={() => setConfirming(null)}
            >
              Back
            </button>
          </div>
        </div>
      )}
      {error && <p className="mt-1 text-[11px] text-danger">{error}</p>}
    </li>
  );
}

const EDGE: Record<string, string> = {
  approve: "#34C79A",
  more_info: "#E3B341",
  decline: "#F0616D",
  none: "transparent",
};

function startsRun(d: Decision, answer: DecisionAnswer): boolean {
  if (answer === "decline" || answer === "dismiss") return false;
  if (answer === "approve" && d.cannot_run_reason) return false;
  const plan = answer === "approve" ? d.on_approve : d.on_more_info;
  return plan.workflow !== "none";
}

/** Plain words for what an answer will do, shown before it is sent. */
export function whatHappens(d: Decision, answer: DecisionAnswer, budget: number | undefined): string {
  if (answer === "decline") return "Nothing runs. Your answer and note are recorded and shared with the agents.";
  if (answer === "dismiss") return "Nothing runs. The card is closed as no longer relevant.";
  if (answer === "approve" && d.cannot_run_reason) return `Nothing starts: ${d.cannot_run_reason}`;
  if (!startsRun(d, answer)) return "Nothing more runs. Your answer is recorded and shared with the agents.";
  const plan = answer === "approve" ? d.on_approve : d.on_more_info;
  const money = budget !== undefined ? `$${budget.toFixed(2)}` : "the default (within the topic's $2 limit)";
  return `${answer === "approve" ? "Starts" : "Starts, to get the missing facts:"} ${describePlan(plan)} Budget: ${money}.`;
}

export function confirmLabel(d: Decision, answer: DecisionAnswer, budget: number | undefined): string {
  if (!startsRun(d, answer)) return "Record answer";
  const verb = answer === "approve" ? "Approve and start" : "Ask and start";
  return budget !== undefined ? `${verb} · $${budget.toFixed(2)}` : verb;
}

/** The latest conclusion and the decisions waiting on the owner. Past briefs live in History. */
export function DecisionsPanel({ runs, decisions = [], onAnswer }: Props) {
  const withBriefs = runs.filter((r) => r.brief);
  const latest = withBriefs[0];
  if (!latest && decisions.length === 0) return null;
  const pending = decisions.filter((d) => d.status === "pending");
  const decided = decisions.filter((d) => d.status !== "pending").slice(0, 5);
  // Runs from before decision cards existed only have the brief's bullet list.
  const legacy = decisions.length === 0 ? (latest?.pending_decisions ?? []) : [];
  const waitingCount = pending.length || legacy.length;

  return (
    <PanelSection title="Decisions" count={waitingCount || withBriefs.length} testId="decisions-panel">
      {latest && (
        <div className="mb-2 rounded-md border border-accent bg-accent-soft p-2 text-xs" data-testid="decision-latest">
          <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-accent">Latest conclusion</p>
          <p className="flex items-start gap-1.5 font-medium text-fg">
            <VerdictPill verdict={latest.verdict} />
            <span>{bottomLine(latest.brief ?? "")}</span>
          </p>
          <p className="mt-0.5 truncate text-[10px] text-muted" title={latest.goal}>
            {latest.goal.split("\n")[0]}
          </p>
        </div>
      )}
      <div className="mb-2" data-testid="decision-waiting">
        <p className="mb-1 text-[11px] font-semibold text-fg">
          Waiting on you {waitingCount > 0 && <span className="text-warn">({waitingCount})</span>}
        </p>
        {pending.length > 0 ? (
          <ul className="space-y-2">
            {pending.map((d) => (
              <DecisionCard key={d.id} decision={d} onAnswer={onAnswer} />
            ))}
          </ul>
        ) : legacy.length > 0 ? (
          <ul className="list-disc space-y-1 pl-4 text-xs text-fg">
            {legacy.map((item, i) => (
              <li key={i} data-testid="decision-item">
                {item}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-xs text-muted">Nothing. No decision is needed from you right now.</p>
        )}
      </div>
      {decided.length > 0 && (
        <div className="mb-2" data-testid="decision-decided">
          <p className="mb-1 text-[11px] font-semibold text-fg">Recently decided</p>
          <ul className="space-y-1">
            {decided.map((d) => (
              <li key={d.id} data-testid="decision-decided-item" className="text-[11px]">
                <span
                  className={`mr-1 rounded px-1 py-0.5 text-[10px] font-medium ${
                    d.status === "approved"
                      ? "bg-accent-soft text-accent"
                      : d.status === "declined"
                        ? "text-danger"
                        : "text-muted"
                  }`}
                >
                  {STATUS_LABEL[d.status]}
                </span>
                <span className="text-fg">{d.question}</span>
                {d.owner_note && <span className="block text-[10px] text-muted">Note: {d.owner_note}</span>}
                {d.follow_up_run_id && (
                  <span className="block text-[10px] text-muted">Follow-up run started; see the Runs tab.</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </PanelSection>
  );
}
