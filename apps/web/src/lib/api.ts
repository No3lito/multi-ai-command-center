import type {
  Agent,
  AgentIn,
  CodeJobs,
  CreateRunBody,
  Decision,
  DecisionAnswerBody,
  DecisionAnswerResult,
  FileSuggestions,
  HistoryResult,
  NewProject,
  WorkspaceInfo,
  Message,
  MessagePage,
  PostMessageBody,
  Principal,
  Room,
  RoomDetail,
  Run,
  Usage,
  Connection,
  FilesListing,
} from "./types";

/** Error with the contract's `{"error": {"code", "message"}}` shape mapped onto it. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

export const isApiError = (e: unknown): e is ApiError => e instanceof ApiError;

type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

let fetchImpl: FetchLike = (input, init) => globalThis.fetch(input, init);
let unauthorizedHandler: (() => void) | null = null;

/** Test hook: replace the fetch implementation. */
export function setFetchImpl(impl: FetchLike): void {
  fetchImpl = impl;
}

/**
 * Called whenever an authenticated request returns 401, so the app can drop
 * back to the login screen. Login and /auth/me handle their own 401s.
 */
export function setUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler;
}

const FALLBACK_MESSAGES: Record<number, string> = {
  400: "The request was not valid.",
  401: "You are not signed in.",
  403: "This action is not allowed.",
  404: "Not found.",
  409: "That conflicts with existing data.",
  422: "Some fields are not valid.",
  429: "Too many attempts. Wait a few minutes and try again.",
};

function fallbackCode(status: number): string {
  if (status === 401) return "unauthenticated";
  if (status === 404) return "not_found";
  if (status === 429) return "rate_limited";
  if (status >= 500) return "server_error";
  return "http_error";
}

async function toApiError(res: Response): Promise<ApiError> {
  let code = fallbackCode(res.status);
  let message =
    FALLBACK_MESSAGES[res.status] ??
    (res.status >= 500 ? "The server had a problem. Try again shortly." : `Request failed (${res.status}).`);
  try {
    const data: unknown = await res.json();
    if (data && typeof data === "object" && "error" in data) {
      const err = (data as { error: unknown }).error;
      if (err && typeof err === "object") {
        const e = err as { code?: unknown; message?: unknown };
        if (typeof e.code === "string" && e.code) code = e.code;
        if (typeof e.message === "string" && e.message) message = e.message;
      }
    }
  } catch {
    // Body was not JSON (for example a proxy error page); keep the fallback.
  }
  return new ApiError(res.status, code, message);
}

interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
  /** Skip the global 401 handler (used by login and the session probe). */
  skipUnauthorizedHandler?: boolean;
}

/** Low-level request: same-origin relative path, cookies, CSRF header on non-GET. */
export async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const method = opts.method ?? "GET";
  const headers: Record<string, string> = { Accept: "application/json" };
  if (method !== "GET") headers["X-CC-CSRF"] = "1";
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";

  let res: Response;
  try {
    res = await fetchImpl(path, {
      method,
      headers,
      credentials: "include",
      body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
      signal: opts.signal,
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    throw new ApiError(0, "network_error", "Cannot reach the Command Center server.");
  }

  if (!res.ok) {
    const err = await toApiError(res);
    if (err.status === 401 && !opts.skipUnauthorizedHandler) unauthorizedHandler?.();
    throw err;
  }
  if (res.status === 204) return undefined as T;
  try {
    return (await res.json()) as T;
  } catch {
    throw new ApiError(res.status, "invalid_response", "The server sent an unreadable response.");
  }
}

const enc = encodeURIComponent;

export const api = {
  login: (password: string) =>
    request<{ principal: Principal }>("/api/auth/login", {
      method: "POST",
      body: { password },
      skipUnauthorizedHandler: true,
    }),
  logout: () =>
    request<void>("/api/auth/logout", {
      method: "POST",
      skipUnauthorizedHandler: true,
    }),
  me: () => request<Principal>("/api/auth/me", { skipUnauthorizedHandler: true }),
  health: () => request<{ status: string; database: string }>("/api/health"),

  listRooms: () => request<Room[]>("/api/rooms"),
  createRoom: (name: string, project?: { project_path?: string; new_project?: NewProject }) =>
    request<Room>("/api/rooms", { method: "POST", body: { name, ...(project ?? {}) } }),
  setRoomProject: (roomId: string, projectPath: string | null) =>
    request<RoomDetail>(`/api/rooms/${enc(roomId)}/project`, {
      method: "PUT",
      body: { project_path: projectPath },
    }),
  suggestFiles: (roomId: string, goal: string, signal?: AbortSignal) =>
    request<FileSuggestions>(`/api/rooms/${enc(roomId)}/suggest-files?goal=${encodeURIComponent(goal)}`, {
      signal,
    }),
  getWorkspace: (signal?: AbortSignal) => request<WorkspaceInfo>("/api/workspace", { signal }),
  fileInboxItem: (name: string, projectPath: string) =>
    request<{ path: string }>("/api/workspace/inbox/file", {
      method: "POST",
      body: { name, project_path: projectPath },
    }),
  getRoom: (roomId: string, signal?: AbortSignal) => request<RoomDetail>(`/api/rooms/${enc(roomId)}`, { signal }),

  listMessages: (roomId: string, afterSeq: number, limit = 200, signal?: AbortSignal) =>
    request<MessagePage>(`/api/rooms/${enc(roomId)}/messages?after_seq=${afterSeq}&limit=${limit}`, {
      signal,
    }),
  postMessage: (roomId: string, text: string, idempotencyKey: string, mentions: readonly string[] = []) => {
    const body: PostMessageBody = {
      kind: "chat",
      body: { text },
      reply_to: null,
      mentions: [...mentions],
      idempotency_key: idempotencyKey,
    };
    return request<Message>(`/api/rooms/${enc(roomId)}/messages`, {
      method: "POST",
      body,
    });
  },

  // Milestone B: agents
  listAgents: (signal?: AbortSignal) => request<Agent[]>("/api/agents", { signal }),
  getCodeJobs: (signal?: AbortSignal) => request<CodeJobs>("/api/code-jobs", { signal }),
  createAgent: (agent: AgentIn) => request<Agent>("/api/agents", { method: "POST", body: agent }),
  updateAgent: (agentId: string, patch: Partial<AgentIn>) =>
    request<Agent>(`/api/agents/${enc(agentId)}`, {
      method: "PATCH",
      body: patch,
    }),
  addRoomMember: (roomId: string, principalId: string) =>
    request<RoomDetail>(`/api/rooms/${enc(roomId)}/members`, {
      method: "POST",
      body: { principal_id: principalId },
    }),

  // Milestone B: runs
  createRun: (roomId: string, body: CreateRunBody) =>
    request<Run>(`/api/rooms/${enc(roomId)}/runs`, { method: "POST", body }),
  listRuns: (roomId: string, limit = 20, signal?: AbortSignal) =>
    request<Run[]>(`/api/rooms/${enc(roomId)}/runs?limit=${limit}`, { signal }),
  getRun: (runId: string, signal?: AbortSignal) => request<Run>(`/api/runs/${enc(runId)}`, { signal }),
  cancelRun: (runId: string) => request<Run>(`/api/runs/${enc(runId)}/cancel`, { method: "POST" }),
  wrapUpRun: (runId: string) => request<Run>(`/api/runs/${enc(runId)}/wrap-up`, { method: "POST" }),
  archiveRun: (runId: string) => request<Run>(`/api/runs/${enc(runId)}/archive`, { method: "POST" }),
  unarchiveRun: (runId: string) => request<Run>(`/api/runs/${enc(runId)}/unarchive`, { method: "POST" }),
  history: (roomId: string, q = "", archived: "include" | "only" | "exclude" = "include", signal?: AbortSignal) =>
    request<HistoryResult>(
      `/api/rooms/${enc(roomId)}/history?q=${encodeURIComponent(q)}&archived=${archived}&limit=50`,
      { signal },
    ),

  listDecisions: (roomId: string, signal?: AbortSignal) =>
    request<Decision[]>(`/api/rooms/${enc(roomId)}/decisions?status=all&limit=50`, { signal }),
  answerDecision: (decisionId: string, body: DecisionAnswerBody) =>
    request<DecisionAnswerResult>(`/api/decisions/${enc(decisionId)}/answer`, { method: "POST", body }),

  listFiles: (path = "", signal?: AbortSignal) =>
    request<FilesListing>(`/api/files?path=${encodeURIComponent(path)}`, { signal }),
  listConnections: (signal?: AbortSignal) => request<Connection[]>("/api/connections", { signal }),
  createConnection: (displayName: string, roomIds: string[] = []) =>
    request<Connection>("/api/connections", {
      method: "POST",
      body: { display_name: displayName, room_ids: roomIds },
    }),
  rotateConnection: (id: string) =>
    request<Connection>(`/api/connections/${enc(id)}/rotate`, {
      method: "POST",
    }),
  revokeConnection: (id: string) =>
    request<Connection>(`/api/connections/${enc(id)}/revoke`, {
      method: "POST",
    }),

  // Milestone B: usage and cost
  getUsage: (signal?: AbortSignal) => request<Usage>("/api/usage", { signal }),
};

export type Api = typeof api;

/**
 * WebSocket base: NEXT_PUBLIC_WS_BASE when set (dev: ws://localhost:8000),
 * otherwise derived from the page origin (ws or wss plus host).
 */
export function wsBase(loc: Pick<Location, "protocol" | "host"> = window.location): string {
  const configured = process.env.NEXT_PUBLIC_WS_BASE;
  if (configured) return configured.replace(/\/+$/, "");
  const scheme = loc.protocol === "https:" ? "wss:" : "ws:";
  return `${scheme}//${loc.host}`;
}

export function roomSocketUrl(roomId: string, afterSeq: number, base: string = wsBase()): string {
  return `${base}/api/ws/rooms/${enc(roomId)}?after_seq=${afterSeq}`;
}
