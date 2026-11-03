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
  /** The workspace project this room works on, e.g. 01-PROJECTS/trading/meme-coin-strategy. */
  project_path?: string | null;
}

/** A project folder in the owner's workspace. */
export interface WorkspaceProject {
  path: string;
  family: string;
  slug: string;
  title: string;
  status: string;
  goal: string;
}

export interface InboxItem {
  name: string;
  size: number | null;
  /** A free keyword guess at the right project. */
  suggested_project: string | null;
}

export interface WorkspaceInfo {
  enabled: boolean;
  /** True when the folder has the workspace layout (01-PROJECTS). */
  structured: boolean;
  families: string[];
  projects: WorkspaceProject[];
  inbox: InboxItem[];
}

export interface FileSuggestions {
  project_path: string | null;
  /** Attached to every run in this project room: card, family page, owner rules. */
  always: string[];
  /** Files matching the goal's words, best first (free keyword match, no AI). */
  suggested: { path: string; size: number | null; matched: string[] }[];
}

export interface NewProject {
  family: string;
  name: string;
  goal?: string;
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

export type RunKind = "collab" | "reply" | "build" | "review" | "code";
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
  /** Owner-chosen files the reviewers read (snapshots taken when the run started). */
  attachments?: { path: string; chars: number }[];
  write_brief?: boolean;
  /** The decision brief that ends the run (markdown), once written. */
  brief?: string | null;
  /** The "Waiting on you" items from the brief. */
  pending_decisions?: string[] | null;
  /** Set when the owner archived the run: hidden from the chat and run list, kept in History. */
  archived_at?: string | null;
  /** The brief's verdict, once written. */
  verdict?: "done" | "blocked" | "needs_you" | null;
  /** Follow-up chains: the run that started the chain, and this run's round (0 = started by the owner). */
  chain_root_id?: string | null;
  chain_depth?: number;
  /** The owner asked this run to conclude now. */
  wrap_up?: boolean;
  /** Code jobs: the pull request, once opened. */
  code_pr?: CodePr | null;
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

export type RunWorkflow = "collab" | "build" | "review" | "code";

/** A code job's pull request on the Command Center's repository. */
export interface CodePr {
  number: number;
  url: string;
  title?: string;
}

/** Whether Claude and GPT can change the Command Center's code (a GitHub token is set). */
export interface CodeJobs {
  enabled: boolean;
  repo: string;
  budget_usd: number;
  reason: string | null;
}

/** What the agents prepared to run when the owner answers a decision. */
export interface FollowUpPlan {
  workflow: RunWorkflow | "none" | string;
  worker: string | null;
  goal: string;
}

export type DecisionStatus = "pending" | "approved" | "declined" | "more_info" | "dismissed";
export type DecisionAnswer = "approve" | "decline" | "more_info" | "dismiss";

/** A decision raised by a run's brief, answered by the owner on the dashboard. */
export interface Decision {
  id: string;
  room_id: string;
  run_id: string;
  run_goal: string;
  question: string;
  recommendation: string | null;
  /** The answer Claude and GPT recommend, for the one-click "follow" button. */
  recommended?: "approve" | "decline" | "more_info" | null;
  /** Plain-language background for a busy owner. */
  why?: string | null;
  /** The note the agents suggest attaching when following their recommendation. */
  suggested_note?: string | null;
  cost: string | null;
  on_approve: FollowUpPlan;
  on_more_info: FollowUpPlan;
  status: DecisionStatus;
  owner_note: string | null;
  decided_at: string | null;
  follow_up_run_id: string | null;
  created_at: string;
  /** Pending: why approving would start nothing (no worker in the room, round limit). */
  cannot_run_reason?: string | null;
  /** Raised in the last allowed round on this topic. */
  final_round?: boolean;
  /** A finished code job: approving merges this pull request, declining closes it. */
  code_pr?: CodePr | null;
}

export interface DecisionAnswerBody {
  answer: DecisionAnswer;
  note?: string;
  budget_usd?: number;
}

export interface HistoryResult {
  runs: Run[];
  decisions: Decision[];
}

export interface DecisionAnswerResult {
  decision: Decision;
  follow_up_run: Run | null;
  /** Approve or more info that started nothing, and why. */
  no_run_reason?: string | null;
  /** A code job's pull request: merged or closed on GitHub. */
  code_result?: string | null;
}

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
  /** Paths inside the shared folder, read once when the run starts. */
  attachments?: string[];
  /** End the run with a decision brief (default true). */
  brief?: boolean;
  /** In a project room: the lead agent picks the project files to read (default true). */
  agent_files?: boolean;
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

export interface FileEntry {
  name: string;
  path: string;
  type: "dir" | "file";
  size: number | null;
  /** A text file that can be attached. */
  readable: boolean;
}

export interface FilesListing {
  enabled: boolean;
  path: string;
  entries: FileEntry[];
  max_files: number;
  max_chars: number;
}
