"use client";

import { useEffect, useState } from "react";
import { api, isApiError } from "@/lib/api";
import type { Room, RoomDetail } from "@/lib/types";
import { useOutbox } from "@/lib/useOutbox";
import { useRoomStream } from "@/lib/useRoomStream";
import { Composer } from "./Composer";
import { ConnectionPill } from "./ConnectionPill";
import { MessageList } from "./MessageList";
import { RightPanel } from "./RightPanel";

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
        } else setDetail({ kind: "error", message: isApiError(e) ? e.message : "Could not load the room." });
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
        action={{ label: "Try again", onClick: () => setDetailReload((n) => n + 1) }}
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
        <Composer onSend={outbox.send} disabled={detail.kind !== "ready"} roomName={roomName} />
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
      />
    </>
  );
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
