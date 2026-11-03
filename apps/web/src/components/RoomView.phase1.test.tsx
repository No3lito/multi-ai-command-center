import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { RoomView } from "./RoomView";

const state = vi.hoisted(() => ({
  runs: [] as { id: string; status: string; archived_at: null }[],
}));

vi.mock("@/lib/api", () => ({
  api: {
    getRoom: vi.fn(async () => ({
      id: "room-1",
      name: "General",
      member_count: 2,
      project_path: null,
      members: [
        { id: "noel", kind: "owner", display_name: "Noel" },
        { id: "claude", kind: "agent", display_name: "Claude" },
      ],
    })),
  },
  isApiError: () => false,
}));

vi.mock("@/lib/useRoomStream", () => ({
  useRoomStream: () => ({
    phase: "ready",
    status: "connected",
    messages: [],
    fatal: null,
    error: null,
    lastSeq: 0,
    ingest: vi.fn(),
    reload: vi.fn(),
  }),
}));
vi.mock("@/lib/useOutbox", () => ({
  useOutbox: () => ({
    pending: [],
    send: vi.fn(),
    retry: vi.fn(),
    discard: vi.fn(),
  }),
}));
vi.mock("@/lib/useAgents", () => ({
  useAgents: () => ({ agents: [], state: { kind: "ready" }, reload: vi.fn() }),
}));
vi.mock("@/lib/useRuns", () => ({
  useRuns: () => ({ runs: state.runs, loaded: true, addRun: vi.fn() }),
}));
vi.mock("@/lib/useDecisions", () => ({
  useDecisions: () => ({ decisions: [], answer: vi.fn() }),
}));
vi.mock("@/lib/useWorkspace", () => ({
  useWorkspace: () => ({ workspace: { structured: false }, reload: vi.fn() }),
}));
vi.mock("@/lib/useUsage", () => ({
  useUsage: () => ({ usage: {}, error: null }),
}));

// Isolate RoomView composition from the existing management-panel implementations.
vi.mock("./AgentsPanel", () => ({ AgentsPanel: () => null }));
vi.mock("./ConnectionsPanel", () => ({ ConnectionsPanel: () => null }));
vi.mock("./DecisionsPanel", () => ({ DecisionsPanel: () => null }));
vi.mock("./HistoryPanel", () => ({ HistoryPanel: () => null }));
vi.mock("./ProjectPanels", () => ({
  InboxPanel: () => null,
  ProjectPanel: () => null,
  projectTitle: () => "",
}));
vi.mock("./RightTabs", () => ({
  RightTabs: () => null,
  Modal: () => null,
}));
vi.mock("./SummaryPanel", () => ({
  SummaryPanel: () => <p>Existing task summary</p>,
  lastSeenFor: () => null,
}));
vi.mock("./CollabForm", () => ({ CollabForm: () => null }));
vi.mock("./ConnectionPill", () => ({ ConnectionPill: () => null }));
vi.mock("./RunsPanel", () => ({ RunsPanel: () => null }));
vi.mock("./UsagePanel", () => ({ UsagePanel: () => null }));
vi.mock("./RightPanel", () => ({
  RightPanel: ({ children }: { children?: import("react").ReactNode }) => (
    <aside aria-label="Room details">{children}</aside>
  ),
}));

function renderRoom() {
  return render(
    <RoomView
      roomId="room-1"
      roomSummary={null}
      roomsLoaded
      hasRooms
      rightOpen={false}
      onToggleLeft={vi.fn()}
      onToggleRight={vi.fn()}
      onRoomMissing={vi.fn()}
    />,
  );
}

describe("RoomView Phase 1 composition", () => {
  beforeEach(() => {
    state.runs = [];
  });

  it("moves members into one named participant strip outside the header", async () => {
    const { container } = renderRoom();
    const strip = await screen.findByRole("list", { name: "Participants" });
    expect(strip).toHaveAttribute("data-testid", "room-members");
    expect(within(strip).getByText("Noel")).toBeVisible();
    expect(within(strip).getByText("Claude")).toBeVisible();
    expect(strip.closest("header")).toBeNull();
    expect(screen.getAllByTestId("room-members")).toHaveLength(1);
    const header = container.querySelector("header");
    expect(header).not.toBeNull();
    expect(header).toHaveTextContent("2 members");
    expect(header?.querySelector('[data-testid="room-members"]')).toBeNull();
    expect(strip.querySelector('[role="status"]')).toBeNull();
  });

  it("omits the task/progress disclosure when no task data exists", async () => {
    renderRoom();
    await screen.findByRole("list", { name: "Participants" });
    expect(screen.queryByText("Tasks and progress")).not.toBeInTheDocument();
    expect(screen.queryByText("Existing task summary")).not.toBeInTheDocument();
  });

  it("shows populated task information in a keyboard-operable disclosure", async () => {
    state.runs = [{ id: "run-1", status: "completed", archived_at: null }];
    renderRoom();
    const summary = await screen.findByText("Tasks and progress");
    const details = summary.closest("details");
    expect(summary.tagName).toBe("SUMMARY");
    expect(details).toHaveAttribute("open");
    expect(details).toHaveTextContent("Existing task summary");
  });
});
