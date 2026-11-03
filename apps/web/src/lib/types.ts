/**
 * Types for the API contracts (docs/api/milestone-a.md, docs/api/milestone-b.md) and the
 * CCMP v1 message envelope (packages/protocol/ccmp.schema.json).
 */

export type PrincipalKind = "owner" | "human" | "agent" | "external" | "system";

export interface Principal {
  id: string;
  kind: PrincipalKind;
  display_name: string;
}

export interface Room {
  id: string;
  name: string;
  created_at: string;
  member_count: number;
  /** Highest seq in this room; 0 for an empty room. seq is per room. */
  last_seq: number;
}

export interface RoomDetail extends Room {
  members: Principal[];
}

export type MessageKind =
  | "chat"
  | "task.assign"
  | "task.result"
  | "task.status"
  | "tool.request"
  | "tool.result"
  | "approval.request"
  | "approval.decision"
  | "artifact"
  | "error"
  | "control";

export interface MessageSender {
  principal_id: string;
  kind: PrincipalKind;
  display_name: string;
}

export interface MessageUsage {
  input_tokens?: number;
  output_tokens?: number;
  cost_usd?: number;
}

/** CCMP v1 envelope. `seq` is gap-free and increasing within each room. */
export interface Message {
  id: string;
  protocol: "ccmp/1";
  seq: number;
  room_id: string;
  thread_id?: string | null;
  sender: MessageSender;
  kind: MessageKind;
  reply_to?: string | null;
  mentions?: string[];
  body: { text: string; data?: Record<string, unknown> };
  task_id?: string | null;
  correlation_id?: string | null;
  usage?: MessageUsage | null;
  created_at: string;
}

export interface MessagePage {
  items: Message[];
  has_more: boolean;
  next_after_seq: number;
}

export interface PostMessageBody {
  kind: "chat";
  body: { text: string };
  reply_to: string | null;
  mentions: string[];
  idempotency_key: string;
}

export type ServerFrame =
  { type: "message"; message: Message } | { type: "ready"; last_seq: number } | { type: "ping"; ts: string };

export const ROOM_NAME_MAX = 80;
export const MESSAGE_TEXT_MAX = 32000;

/* ---------------------------------------------------------------------------
 * Milestone B (docs/api/milestone-b.md): agents, runs and usage.
 * ------------------------------------------------------------------------- */

export type AgentProvider = "anthropic" | "openai" | "xai" | "simulated";

/** Whether an agent can run right now. */
export type AgentStatus = "live" | "simulated" | "missing_key" | "unknown_price" | "disabled";

export interface AgentIn {
  display_name: string;
  role: string;
  provider: AgentProvider;
  model: string;
  system_prompt: string;
  max_output_tokens: number;
  enabled: boolean;
}

export interface AgentPrice {
  input_per_mtok: number;
  output_per_mtok: number;
}

export interface Agent extends AgentIn {
  id: string;
  kind: "agent";
  status: AgentStatus;
  price: AgentPrice | null;
}

export type RunKind = "collab" | "reply" | "build" | "review";
export type RunStatus = "queued" | "running" | "waiting" | "completed" | "failed" | "cancelled" | "budget_exceeded";
export type RunStep = string;

export interface Run {
  id: string;
  room_id: string;
  kind: RunKind;
  status: RunStatus;
  goal: string;
  step: RunStep;
  planner_id: string | null;
  critic_id: string | null;
  builder_id?: string | null;
  agent_id: string | null;
  root_run_id?: string | null;
  /** Set while status is "waiting": the external agent whose turn it is. */
  waiting_for?: string | null;
  turn_count: number;
  max_turns: number;
  budget_usd: number;
  spent_usd: number;
  simulated: boolean;
  error: string | null;
  created_at: string;
  updated_at: string;
  finished_at: string | null;
}

export type RunWorkflow = "collab" | "build" | "review";

/** An external agent (for example Grok Bot) connected over MCP with a token. */
export interface Connection {
  id: string;
  display_name: string;
  status: "active" | "disabled";
  created_at: string;
  last_used_at: string | null;
  rooms: { id: string; name: string }[];
  /** Only present right after creating or rotating; shown once, never stored by the server. */
  token: string | null;
  mcp_path: string;
  mcp_port: number;
}

export interface CreateRunBody {
  goal: string;
  /** build: planner and critic co-design, builder builds exactly what they specify. */
  workflow?: RunWorkflow;
  planner_id: string;
  critic_id: string;
  builder_id?: string;
  budget_usd?: number;
  max_turns?: number;
}

export interface UsageRow {
  provider: string;
  model: string;
  calls: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  simulated: boolean;
}

export interface Usage {
  cap_usd: number;
  spent_usd: number;
  reserved_usd: number;
  remaining_usd: number;
  by_provider: UsageRow[];
  /** Calls answered by the local stand-in. Never real API usage; never touch the cap. */
  simulated_calls: number;
}

export const RUN_BUDGET_DEFAULT = 0.5;
export const RUN_BUDGET_MAX = 5;
export const RUN_MAX_TURNS_DEFAULT = 8;

export const ACTIVE_RUN_STATUSES: readonly RunStatus[] = ["queued", "running", "waiting"];
export const isRunActive = (run: Pick<Run, "status">): boolean => ACTIVE_RUN_STATUSES.includes(run.status);

/** Agents that can take a turn right now. */
export const isAgentUsable = (agent: Pick<Agent, "status">): boolean =>
  agent.status === "live" || agent.status === "simulated";
