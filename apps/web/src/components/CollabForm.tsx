"use client";

import { useId, useState, type FormEvent } from "react";
import { isApiError } from "@/lib/api";
import {
  RUN_BUDGET_DEFAULT,
  RUN_BUDGET_MAX,
  RUN_MAX_TURNS_DEFAULT,
  isAgentUsable,
  type CreateRunBody,
  type Run,
} from "@/lib/types";
import { agentStatusLabel, type RoomAgent } from "./AgentsPanel";
import { ErrorText, PanelSection } from "./PanelSection";

export interface CollabInput {
  goal: string;
  plannerId: string;
  criticId: string;
  budget: string;
}

export type CollabErrors = Partial<Record<keyof CollabInput, string>>;

/** Client-side checks that mirror the contract (the server validates again). */
export function validateCollab(input: CollabInput): CollabErrors {
  const errors: CollabErrors = {};
  if (!input.goal.trim()) errors.goal = "Describe the goal.";
  if (!input.plannerId) errors.plannerId = "Pick a planner.";
  if (!input.criticId) errors.criticId = "Pick a critic.";
  else if (input.plannerId && input.plannerId === input.criticId)
    errors.criticId = "Planner and critic must be different agents.";
  const raw = input.budget.trim();
  const budget = Number(raw);
  if (!raw || !Number.isFinite(budget)) errors.budget = "Enter a budget in USD.";
  else if (budget <= 0) errors.budget = "Budget must be more than $0.";
  else if (budget > RUN_BUDGET_MAX) errors.budget = `Budget can be at most $${RUN_BUDGET_MAX.toFixed(2)}.`;
  return errors;
}

interface Props {
  roomId: string | null;
  roomAgents: RoomAgent[];
  createRun: (roomId: string, body: CreateRunBody) => Promise<Run>;
  onStarted: (run: Run) => void;
}

export function CollabForm({ roomId, roomAgents, createRun, onStarted }: Props) {
  const usable = roomAgents.filter((r) => r.agent && isAgentUsable(r.agent));
  const [goal, setGoal] = useState("");
  const [plannerSel, setPlannerSel] = useState<string | null>(null);
  const [criticSel, setCriticSel] = useState<string | null>(null);
  const [budget, setBudget] = useState(RUN_BUDGET_DEFAULT.toFixed(2));
  const [errors, setErrors] = useState<CollabErrors>({});
  const [serverError, setServerError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const ids = { goal: useId(), planner: useId(), critic: useId(), budget: useId(), why: useId() };

  const usableIds = usable.map((r) => r.member.id);
  const plannerId = plannerSel ?? usableIds[0] ?? "";
  const criticId = criticSel ?? usableIds.find((id) => id !== plannerId) ?? "";
  const notEnough = usable.length < 2;
  const blocked = !roomId || notEnough;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (blocked || busy || !roomId) return;
    const input = { goal, plannerId, criticId, budget };
    const found = validateCollab(input);
    setErrors(found);
    setServerError(null);
    if (Object.keys(found).length > 0) return;
    setBusy(true);
    try {
      const run = await createRun(roomId, {
        goal: goal.trim(),
        planner_id: plannerId,
        critic_id: criticId,
        budget_usd: Math.round(Number(budget) * 100) / 100,
        max_turns: RUN_MAX_TURNS_DEFAULT,
      });
      setGoal("");
      onStarted(run);
    } catch (err) {
      setServerError(isApiError(err) ? err.message : "Could not start the run.");
    } finally {
      setBusy(false);
    }
  }

  const fieldClass =
    "w-full rounded-md border border-line bg-bg px-2 py-1 text-sm placeholder:text-muted aria-[invalid=true]:border-danger";
  const labelClass = "mb-0.5 block text-[11px] font-medium text-muted";

  return (
    <PanelSection title="Collaborate" testId="collab-panel">
      <form onSubmit={submit} noValidate className="space-y-2">
        <div>
          <label htmlFor={ids.goal} className={labelClass}>
            Goal
          </label>
          <textarea
            id={ids.goal}
            data-testid="collab-goal"
            rows={2}
            required
            value={goal}
            onChange={(e) => {
              setGoal(e.target.value);
              if (errors.goal) setErrors((p) => ({ ...p, goal: undefined }));
            }}
            placeholder="What should the agents work out?"
            aria-invalid={errors.goal ? true : undefined}
            className={`${fieldClass} resize-y`}
          />
          {errors.goal && <ErrorText>{errors.goal}</ErrorText>}
        </div>
        <div className="grid grid-cols-2 gap-2">
          <AgentSelect
            id={ids.planner}
            label="Planner"
            testId="collab-planner"
            value={plannerId}
            onChange={(v) => {
              setPlannerSel(v);
              setErrors((p) => ({ ...p, plannerId: undefined, criticId: undefined }));
            }}
            roomAgents={roomAgents}
            invalid={!!errors.plannerId}
            className={fieldClass}
            labelClass={labelClass}
          />
          <AgentSelect
            id={ids.critic}
            label="Critic"
            testId="collab-critic"
            value={criticId}
            onChange={(v) => {
              setCriticSel(v);
              setErrors((p) => ({ ...p, criticId: undefined }));
            }}
            roomAgents={roomAgents}
            invalid={!!errors.criticId}
            className={fieldClass}
            labelClass={labelClass}
          />
        </div>
        {(errors.plannerId || errors.criticId) && <ErrorText>{errors.plannerId ?? errors.criticId}</ErrorText>}
        <div className="flex items-end gap-2">
          <div className="w-28">
            <label htmlFor={ids.budget} className={labelClass}>
              Budget (USD)
            </label>
            <input
              id={ids.budget}
              data-testid="collab-budget"
              type="number"
              inputMode="decimal"
              min={0.01}
              max={RUN_BUDGET_MAX}
              step={0.01}
              value={budget}
              onChange={(e) => {
                setBudget(e.target.value);
                if (errors.budget) setErrors((p) => ({ ...p, budget: undefined }));
              }}
              aria-invalid={errors.budget ? true : undefined}
              className={`${fieldClass} font-mono`}
            />
          </div>
          <button
            type="submit"
            data-testid="collab-start"
            disabled={blocked || busy}
            aria-describedby={notEnough ? ids.why : undefined}
            className="ml-auto rounded-md bg-accent px-3 py-1 text-sm font-medium text-accent-fg hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {busy ? "Starting" : "Start"}
          </button>
        </div>
        {errors.budget && <ErrorText>{errors.budget}</ErrorText>}
        <p className="text-[10px] text-muted">Max ${RUN_BUDGET_MAX.toFixed(2)} per run. Simulated runs cost nothing.</p>
        {roomId && notEnough && (
          <p id={ids.why} data-testid="collab-blocked" className="text-xs text-warn">
            Needs at least two agents in this room that can run (status Live or Simulated). Add an agent or
            configure its API key.
          </p>
        )}
        {serverError && <ErrorText>{serverError}</ErrorText>}
      </form>
    </PanelSection>
  );
}

function AgentSelect({
  id,
  label,
  testId,
  value,
  onChange,
  roomAgents,
  invalid,
  className,
  labelClass,
}: {
  id: string;
  label: string;
  testId: string;
  value: string;
  onChange: (v: string) => void;
  roomAgents: RoomAgent[];
  invalid: boolean;
  className: string;
  labelClass: string;
}) {
  return (
    <div className="min-w-0">
      <label htmlFor={id} className={labelClass}>
        {label}
      </label>
      <select
        id={id}
        data-testid={testId}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        aria-invalid={invalid ? true : undefined}
        className={className}
      >
        {value === "" && <option value="">Choose</option>}
        {roomAgents.map(({ member, agent }) => {
          const usable = !!agent && isAgentUsable(agent);
          return (
            <option key={member.id} value={member.id} disabled={!usable}>
              {usable ? member.display_name : `${member.display_name} (${agent ? agentStatusLabel(agent.status) : "Unknown"})`}
            </option>
          );
        })}
      </select>
    </div>
  );
}
