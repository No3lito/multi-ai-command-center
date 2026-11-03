"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api, isApiError } from "@/lib/api";
import { isRunActive, type Agent, type Room, type RoomDetail } from "@/lib/types";
import { useAgents } from "@/lib/useAgents";
import { useDecisions } from "@/lib/useDecisions";
import { useWorkspace } from "@/lib/useWorkspace";
import { useOutbox } from "@/lib/useOutbox";
import { useRoomStream } from "@/lib/useRoomStream";
import { useRuns } from "@/lib/useRuns";
import { useUsage } from "@/lib/useUsage";
import { AgentsPanel, type RoomAgent } from "./AgentsPanel";
import { ConnectionsPanel } from "./ConnectionsPanel";
import { DecisionsPanel } from "./DecisionsPanel";
import { HistoryPanel } from "./HistoryPanel";
import { InboxPanel, ProjectPanel, projectTitle } from "./ProjectPanels";
import { Modal, RightTabs, type TabId } from "./RightTabs";
import { SummaryPanel, lastSeenFor } from "./SummaryPanel";
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
  const runs = useRuns(detail.kind === "ready" ? roomId : null, stream.messages, streamReady, { limit: 50 });
  const [tab, setTab] = useState<TabId>("decide");
  const [goalOpen, setGoalOpen] = useState(false);
  const { workspace, reload: reloadWorkspace } = useWorkspace(api, `${roomId}:${tab}`);
  const usage = useUsage(stream.messages, streamReady);
  const decisions = useDecisions(detail.kind === "ready" ? roomId : null, runs.runs);
  const { answer: answerDecision } = decisions;
  const { addRun } = runs;
  const archiveRun = useCallback(async (runId: string) => addRun(await api.archiveRun(runId)), [addRun]);
  const closeGoal = useCallback(() => setGoalOpen(false), []);
  const fileInbox = useCallback(
    async (name: string, projectPath: string) => {
      await api.fileInboxItem(name, projectPath);
      reloadWorkspace();
    },
    [reloadWorkspace],
  );
  const setProject = useCallback(
    async (projectPath: string | null) => {
      if (!roomId) return;
      const updated = await api.setRoomProject(roomId, projectPath);
      setDetail({ kind: "ready", detail: updated });
    },
    [roomId],
  );
  const onAnswer = useCallback(
    async (id: string, body: Parameters<typeof answerDecision>[1]) => {
      const result = await answerDecision(id, body);
      if (result.follow_up_run) addRun(result.follow_up_run);
      return result;
    },
    [answerDecision, addRun],
  );
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
            {roomDetail?.project_path && (
              <span
                data-testid="room-project"
                title={roomDetail.project_path}
                className="shrink-0 rounded bg-panel-2 px-1.5 py-px text-[11px] text-muted"
              >
                Project: {projectTitle(workspace, roomDetail.project_path)}
              </span>
            )}
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
      {roomId && !notFound && detail.kind === "ready" && (
        <button
          type="button"
          data-testid="new-goal"
          onClick={() => setGoalOpen(true)}
          className="shrink-0 rounded-md bg-accent px-2.5 py-1 text-xs font-semibold text-white hover:opacity-90"
        >
          New goal
        </button>
      )}
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
          runs={runs.runs}
          onArchive={archiveRun}
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
        showDetails={tab === "setup"}
      >
        {roomDetail && !notFound && roomId && (
          <RightTabs
            tab={tab}
            onChange={setTab}
            badges={{
              decide: decisions.decisions.filter((d) => d.status === "pending").length,
              runs: runs.runs.filter((r) => isRunActive(r) && !r.archived_at).length,
            }}
          />
        )}
        {roomDetail && !notFound && roomId && tab === "decide" && (
          <div role="tabpanel" id="tabpanel-decide" aria-labelledby="tab-decide">
            <SummaryPanel
              runs={runs.runs}
              decisions={decisions.decisions}
              usage={usage.usage}
              since={lastSeenFor(roomId)}
              agentName={agentName}
            />
            <DecisionsPanel runs={runs.runs} decisions={decisions.decisions} onAnswer={onAnswer} />
            <InboxPanel workspace={workspace} onFile={fileInbox} />
          </div>
        )}
        {(tab === "runs" || !roomDetail || notFound) && (
          <div role="tabpanel" id="tabpanel-runs" aria-labelledby="tab-runs">
            <RunsPanel
              hasRoom={!!roomDetail && !notFound}
              runs={runs.runs}
              loaded={runs.loaded}
              error={runs.error}
              agentName={agentName}
              onCancel={runs.cancel}
              onRetry={runs.reload}
            />
          </div>
        )}
        {roomDetail && !notFound && roomId && tab === "history" && (
          <div role="tabpanel" id="tabpanel-history" aria-labelledby="tab-history">
            <HistoryPanel
              roomId={roomId}
              client={api}
              onRunChanged={addRun}
              refreshKey={runs.runs
                .filter((r) => !isRunActive(r))
                .map((r) => `${r.id}:${r.updated_at}`)
                .join(",")}
            />
          </div>
        )}
        {tab === "setup" && (
          <div role="tabpanel" id="tabpanel-setup" aria-labelledby="tab-setup">
            {roomDetail && !notFound && (
              <ProjectPanel workspace={workspace} projectPath={roomDetail.project_path ?? null} onChange={setProject} />
            )}
            <AgentsPanel
              hasRoom={!!roomDetail && !notFound}
              loading={agentsHook.state.kind === "loading"}
              error={agentsHook.state.kind === "error" ? agentsHook.state.message : null}
              roomAgents={roomAgents}
              otherAgents={otherAgents}
              onAdd={addAgent}
              onRetry={agentsHook.reload}
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
          </div>
        )}
      </RightPanel>
      {goalOpen && roomDetail && !notFound && roomId && (
        <Modal title="New goal" onClose={closeGoal}>
          <CollabForm
            roomId={roomId}
            roomAgents={roomAgents}
            externals={externals}
            createRun={api.createRun}
            listFiles={api.listFiles}
            projectTitle={projectTitle(workspace, roomDetail.project_path)}
            projectPath={roomDetail.project_path ?? null}
            noProjectHint={workspace.structured && !roomDetail.project_path}
            suggestFiles={
              roomDetail.project_path ? (goal, signal) => api.suggestFiles(roomId, goal, signal) : undefined
            }
            onStarted={(run) => {
              addRun(run);
              setGoalOpen(false);
              setTab("runs");
            }}
          />
        </Modal>
      )}
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
