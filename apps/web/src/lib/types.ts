/**
 * Types for the Milestone A API contract (docs/api/milestone-a.md) and the
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
  | { type: "message"; message: Message }
  | { type: "ready"; last_seq: number }
  | { type: "ping"; ts: string };

export const ROOM_NAME_MAX = 80;
export const MESSAGE_TEXT_MAX = 32000;
