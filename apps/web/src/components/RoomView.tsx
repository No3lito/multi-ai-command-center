"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api, isApiError } from "@/lib/api";
import type { Agent, Room, RoomDetail } from "@/lib/types";
import { useAgents } from "@/lib/useAgents";
import { useOutbox } from "@/lib/useOutbox";
import { useRoomStream } from "@/lib/useRoomStream";
import { useRuns } from "@/lib/useRuns";
import { useUsage } from "@/lib/useUsage";
import { AgentsPanel, type RoomAgent } from "./AgentsPanel";
import { ConnectionsPanel } from "./ConnectionsPanel";
import { DecisionsPanel } from "./DecisionsPanel";
import { CollabForm } from "./CollabForm";
import { Composer, type MentionAgent } from "./Composer";
import { ConnectionPill } from "./ConnectionPill";
import { MessageList } from "./MessageList";
import { RightPanel } from "./RightPanel";
import { RunsPanel } from "./RunsPanel";
import { UsagePanel } from "./UsagePanel";

type DetailState =
  | { kind: "loading" }
  | { kind: "ready"; detail: RoomDetail }
  | { kind: "not_found" }
  | { kind: "error"; message: string };

interface Props {
  roomId: string | null;
  roomSummary: Room | null;
  roomsLoaded: boolean;
  hasRooms: boolean;
  rightOpen: boolean;
  onToggleLeft: () => void;
  onToggleRight: () => void;
  onRoomMissing: () => void;
}

export function RoomView(props: Props) {
  const { roomId, roomSummary, roomsLoaded, hasRooms, rightOpen, onToggleLeft, onToggleRight, onRoomMissing } = props;
  const [detail, setDetail] = useState<DetailState>({ kind: "loading" });
  const [detailReload, setDetailReload] = useState(0);
  const stream = useRoomStream(detail.kind === "ready" ? roomId : null);
  const outbox = useOutbox(roomId, stream.ingest);
  const streamReady = stream.phase === "ready";
  const agentsHook = useAgents();
  const runs = useRuns(detail.kind === "ready" ? roomId : null, stream.messages, streamReady);
  const usage = useUsage(stream.messages, streamReady);
  const roomDetail = detail.kind === "ready" ? detail.detail : null;

  const { roomAgents, otherAgents } = useMemo(
    () => splitAgents(roomDetail, agentsHook.agents),
    [roomDetail, agentsHook.agents],
  );
  const externals = useMemo(
    () => (roomDetail ? roomDetail.members.filter((m) => m.kind === "external") : []),
    [roomDetail],
  );
  const memberIds = useMemo(() => new Set(roomDetail?.members.map((m) => m.id) ?? []), [roomDetail]);
  const reloadDetail = useCallback(() => {
    if (!roomId) return;
    api
      .getRoom(roomId)
      .then((d) => setDetail({ kind: "ready", detail: d }))
      .catch(() => {});
  }, [roomId]);

  const mentionAgents = useMemo<MentionAgent[]>(
    () =>
      roomAgents.map(({ member, agent }) => ({
        id: member.id,
        display_name: member.display_name,
        detail: agent ? `${agent.provider} / ${agent.model}` : undefined,
      })),
    [roomAgents],
  );

  const agentName = useCallback(
    (id: string | null) => {
      if (!id) return null;
      return (
        roomDetail?.members.find((m) => m.id === id)?.display_name ??
        agentsHook.agents.find((a) => a.id === id)?.display_name ??
        null
      );
    },
    [roomDetail, agentsHook.agents],
  );

  const addAgent = useCallback(
    async (agentId: string) => {
      if (!roomId) return;
      const updated = await api.addRoomMember(roomId, agentId);
      setDetail({ kind: "ready", detail: updated });
    },
    [roomId],
  );

  useEffect(() => {
    if (!roomId) return;
    const abort = new AbortController();
    api
      .getRoom(roomId, abort.signal)
      .then((d) => setDetail({ kind: "ready", detail: d }))
      .catch((e: unknown) => {
        if (abort.signal.aborted) return;
        if (isApiError(e) && e.status === 404) {
          setDetail({ kind: "not_found" });
          onRoomMissing();
        } else
          setDetail({
            kind: "error",
            message: isApiError(e) ? e.message : "Could not load the room.",
          });
      });
    return () => abort.abort();
  }, [roomId, detailReload, onRoomMissing]);

  const notFound = detail.kind === "not_found" || stream.fatal === 4404;
  const roomName = detail.kind === "ready" ? detail.detail.name : (roomSummary?.name ?? "");
  const memberCount = detail.kind === "ready" ? detail.detail.member_count : roomSummary?.member_count;

  const header = (
    <header className="flex h-12 shrink-0 items-center gap-2 border-b border-line bg-panel px-3">
      <button
        type="button"
        onClick={onToggleLeft}
        aria-controls="left-sidebar"
        aria-label="Show rooms"
        className="rounded-md p-1.5 text-muted hover:bg-panel-2 hover:text-fg lg:hidden"
      >
        <MenuIcon />
      </button>
      <div className="min-w-0 flex-1">
        {roomId && roomName ? (
          <h1 className="flex items-baseline gap-2 truncate">
            <span className="truncate font-semibold">
              <span aria-hidden="true" className="mr-1 font-mono text-muted">
                #
              </span>
              {roomName}
            </span>
            {memberCount !== undefined && (
              <span className="shrink-0 text-xs text-muted">
                {memberCount} {memberCount === 1 ? "member" : "members"}
              </span>
            )}
          </h1>
        ) : (
          <h1 className="font-semibold text-muted">No room selected</h1>
        )}
      </div>
      {roomId && !notFound && <ConnectionPill status={detail.kind === "ready" ? stream.status : "connecting"} />}
      <button
        type="button"
        onClick={onToggleRight}
        aria-controls="right-sidebar"
        aria-expanded={rightOpen}
        aria-label="Show room details"
        className="rounded-md p-1.5 text-muted hover:bg-panel-2 hover:text-fg xl:hidden"
      >
        <PanelIcon />
      </button>
    </header>
  );

  let body: React.ReactNode;
  if (!roomId) {
    body = (
      <EmptyState
        title={roomsLoaded && !hasRooms ? "No rooms yet" : roomsLoaded ? "Pick a room" : "Loading rooms"}
        text={
          roomsLoaded && !hasRooms
            ? "Create a room from the sidebar to start a conversation."
            : "Choose a room from the sidebar."
        }
      />
    );
  } else if (notFound) {
    body = <EmptyState title="Room not found" text="This room does not exist or was removed. Pick another room." />;
  } else if (detail.kind === "error") {
    body = (
      <EmptyState
        title="Could not load this room"
        text={detail.message}
        action={{
          label: "Try again",
          onClick: () => setDetailReload((n) => n + 1),
        }}
      />
    );
  } else if (stream.phase === "error") {
    body = (
      <EmptyState
        title="Could not load messages"
        text={stream.error?.message ?? "The server did not respond."}
        action={{ label: "Try again", onClick: stream.reload }}
      />
    );
  } else {
    body = (
      <>
        {stream.fatal !== null && stream.fatal !== 4404 && stream.error && (
          <p role="alert" className="border-b border-line bg-danger-soft px-4 py-2 text-sm text-danger">
            {stream.error.message}
          </p>
        )}
        <MessageList
          messages={stream.messages}
          pending={outbox.pending}
          loading={detail.kind === "loading" || stream.phase === "loading"}
          onRetry={outbox.retry}
          onDiscard={outbox.discard}
        />
        <Composer onSend={outbox.send} disabled={detail.kind !== "ready"} roomName={roomName} agents={mentionAgents} />
      </>
    );
  }

  return (
    <>
      <main className="flex min-w-0 flex-1 flex-col bg-bg">
        {header}
        {body}
      </main>
      <RightPanel
        open={rightOpen}
        detail={detail.kind === "ready" ? detail.detail : null}
        status={stream.status}
        lastSeq={stream.lastSeq}
        hasRoom={!!roomId && !notFound}
      >
        {roomDetail && !notFound && <DecisionsPanel runs={runs.runs} />}
        <AgentsPanel
          hasRoom={!!roomDetail && !notFound}
          loading={agentsHook.state.kind === "loading"}
          error={agentsHook.state.kind === "error" ? agentsHook.state.message : null}
          roomAgents={roomAgents}
          otherAgents={otherAgents}
          onAdd={addAgent}
          onRetry={agentsHook.reload}
        />
        {roomDetail && !notFound && (
          <CollabForm
            roomId={roomId}
            roomAgents={roomAgents}
            externals={externals}
            createRun={api.createRun}
            listFiles={api.listFiles}
            onStarted={runs.addRun}
          />
        )}
        <RunsPanel
          hasRoom={!!roomDetail && !notFound}
          runs={runs.runs}
          loaded={runs.loaded}
          error={runs.error}
          agentName={agentName}
          onCancel={runs.cancel}
          onRetry={runs.reload}
        />
        <UsagePanel usage={usage.usage} error={usage.error} />
        <ConnectionsPanel
          api={api}
          roomId={roomDetail && !notFound ? roomId : null}
          roomName={roomDetail?.name ?? null}
          memberIds={memberIds}
          onAddToRoom={addAgent}
          onChanged={reloadDetail}
        />
      </RightPanel>
    </>
  );
}

/** Room members of kind agent (with their profile), and the other known agents that are not in the room. */
export function splitAgents(
  detail: RoomDetail | null,
  agents: readonly Agent[],
): { roomAgents: RoomAgent[]; otherAgents: Agent[] } {
  if (!detail) return { roomAgents: [], otherAgents: [] };
  const byId = new Map(agents.map((a) => [a.id, a]));
  const roomAgents = detail.members
    .filter((m) => m.kind === "agent")
    .map((member) => ({ member, agent: byId.get(member.id) ?? null }));
  const inRoom = new Set(roomAgents.map((r) => r.member.id));
  const otherAgents = agents.filter((a) => !inRoom.has(a.id));
  return { roomAgents, otherAgents };
}

function EmptyState({
  title,
  text,
  action,
}: {
  title: string;
  text: string;
  action?: { label: string; onClick: () => void };
}) {
  return (
    <div className="flex flex-1 items-center justify-center p-6">
      <div className="max-w-sm text-center">
        <h2 className="font-semibold">{title}</h2>
        <p className="mt-1 text-muted">{text}</p>
        {action && (
          <button
            type="button"
            onClick={action.onClick}
            className="mt-3 rounded-md border border-line bg-panel px-3 py-1.5 text-sm font-medium hover:bg-panel-2"
          >
            {action.label}
          </button>
        )}
      </div>
    </div>
  );
}

function MenuIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
      <path d="M2 4h14M2 9h14M2 14h14" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

function PanelIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true" fill="none">
      <rect x="2" y="3" width="14" height="12" rx="2" stroke="currentColor" strokeWidth="1.6" />
      <path d="M11 3v12" stroke="currentColor" strokeWidth="1.6" />
    </svg>
  );
}
