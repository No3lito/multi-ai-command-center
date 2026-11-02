import type { Agent, Message, Principal, Run, Usage } from "@/lib/types";
import { ROOM_A, msg } from "./fakeWebSocket";

export const CLAUDE_ID = `agt_${"c".repeat(32)}`;
export const GPT_ID = `agt_${"d".repeat(32)}`;
export const GEMINI_ID = `agt_${"e".repeat(32)}`;
export const COORD_ID = `sys_${"f".repeat(32)}`;
export const RUN_ID = `run_${"1".repeat(32)}`;

export function agent(id: string, name: string, over: Partial<Agent> = {}): Agent {
  return {
    id,
    kind: "agent",
    display_name: name,
    role: "Planner",
    provider: "anthropic",
    model: "claude-sonnet-5-5",
    system_prompt: "",
    max_output_tokens: 1024,
    enabled: true,
    status: "simulated",
    price: null,
    ...over,
  };
}

export const CLAUDE = agent(CLAUDE_ID, "Claude");
export const GPT = agent(GPT_ID, "GPT", { provider: "openai", model: "gpt-5", role: "Critic" });

export const member = (a: Agent): Principal => ({ id: a.id, kind: "agent", display_name: a.display_name });

export function run(over: Partial<Run> = {}): Run {
  return {
    id: RUN_ID,
    room_id: ROOM_A,
    kind: "collab",
    status: "running",
    goal: "Create a basic login interface",
    step: "plan",
    planner_id: CLAUDE_ID,
    critic_id: GPT_ID,
    agent_id: null,
    turn_count: 0,
    max_turns: 8,
    budget_usd: 0.5,
    spent_usd: 0,
    simulated: true,
    error: null,
    created_at: "2026-11-02T12:00:00Z",
    updated_at: "2026-11-02T12:00:00Z",
    finished_at: null,
    ...over,
  };
}

export function agentMsg(seq: number, over: Partial<Message> = {}, data: Record<string, unknown> = {}): Message {
  const base = msg(seq, ROOM_A, `agent says ${seq}`);
  return {
    ...base,
    sender: { principal_id: CLAUDE_ID, kind: "agent", display_name: "Claude" },
    correlation_id: RUN_ID,
    usage: { input_tokens: 120, output_tokens: 80, cost_usd: 0 },
    body: {
      text: `agent says ${seq}`,
      data: { run_id: RUN_ID, step: "plan", provider: "anthropic", model: "claude-sonnet-5-5", simulated: true, ...data },
    },
    ...over,
  };
}

export function coordMsg(seq: number, kind: Message["kind"], text: string, correlation: string | null = RUN_ID): Message {
  const base = msg(seq, ROOM_A, text);
  return {
    ...base,
    kind,
    sender: { principal_id: COORD_ID, kind: "system", display_name: "Coordinator" },
    correlation_id: correlation,
    body: { text, data: { run_id: correlation, status: "running" } },
  };
}

export function usage(over: Partial<Usage> = {}): Usage {
  return {
    cap_usd: 10,
    spent_usd: 0.42,
    reserved_usd: 0.01,
    remaining_usd: 9.57,
    by_provider: [
      {
        provider: "anthropic",
        model: "claude-sonnet-5-5",
        calls: 3,
        input_tokens: 1200,
        output_tokens: 900,
        cost_usd: 0.0114,
        simulated: false,
      },
    ],
    simulated_calls: 12,
    ...over,
  };
}
