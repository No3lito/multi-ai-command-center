import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";
import { ROOM_A } from "@/test/fakeWebSocket";
import { CLAUDE, CLAUDE_ID, GPT, GPT_ID, agent, member, run } from "@/test/fixtures";
import type { RoomAgent } from "./AgentsPanel";
import { CollabForm, validateCollab } from "./CollabForm";

const both: RoomAgent[] = [
  { member: member(CLAUDE), agent: CLAUDE },
  { member: member(GPT), agent: GPT },
];

describe("validateCollab", () => {
  const ok = { goal: "x", plannerId: "a", criticId: "b", budget: "0.50" };
  it("accepts a valid input", () => expect(validateCollab(ok)).toEqual({}));
  it("requires a goal", () => expect(validateCollab({ ...ok, goal: "  " }).goal).toBeTruthy());
  it("rejects planner equal to critic", () =>
    expect(validateCollab({ ...ok, criticId: "a" }).criticId).toMatch(/different/));
  it("enforces budget limits", () => {
    expect(validateCollab({ ...ok, budget: "5.00" })).toEqual({});
    expect(validateCollab({ ...ok, budget: "5.01" }).budget).toMatch(/at most \$5\.00/);
    expect(validateCollab({ ...ok, budget: "0" }).budget).toBeTruthy();
    expect(validateCollab({ ...ok, budget: "" }).budget).toBeTruthy();
    expect(validateCollab({ ...ok, budget: "abc" }).budget).toBeTruthy();
  });
});

describe("CollabForm", () => {
  it("defaults budget to 0.50 and planner/critic to different agents, then posts the run", async () => {
    const user = userEvent.setup();
    const createRun = vi.fn(async () => run());
    const onStarted = vi.fn();
    render(<CollabForm roomId={ROOM_A} roomAgents={both} createRun={createRun} onStarted={onStarted} />);
    expect(screen.getByTestId("collab-budget")).toHaveValue(0.5);
    expect(screen.getByTestId("collab-planner")).toHaveValue(CLAUDE_ID);
    expect(screen.getByTestId("collab-critic")).toHaveValue(GPT_ID);
    await user.type(screen.getByTestId("collab-goal"), "Create a basic login interface");
    await user.click(screen.getByTestId("collab-start"));
    await waitFor(() => expect(onStarted).toHaveBeenCalled());
    expect(createRun).toHaveBeenCalledWith(ROOM_A, {
      goal: "Create a basic login interface",
      planner_id: CLAUDE_ID,
      critic_id: GPT_ID,
      budget_usd: 0.5,
      max_turns: 8,
    });
    expect(screen.getByTestId("collab-goal")).toHaveValue("");
  });

  it("blocks planner equal to critic and budgets over $5.00 without calling the server", async () => {
    const user = userEvent.setup();
    const createRun = vi.fn(async () => run());
    render(<CollabForm roomId={ROOM_A} roomAgents={both} createRun={createRun} onStarted={() => {}} />);
    await user.type(screen.getByTestId("collab-goal"), "g");
    await user.selectOptions(screen.getByTestId("collab-critic"), CLAUDE_ID);
    await user.click(screen.getByTestId("collab-start"));
    expect(await screen.findByText("Planner and critic must be different agents.")).toBeInTheDocument();

    await user.selectOptions(screen.getByTestId("collab-critic"), GPT_ID);
    await user.clear(screen.getByTestId("collab-budget"));
    await user.type(screen.getByTestId("collab-budget"), "6");
    await user.click(screen.getByTestId("collab-start"));
    expect(await screen.findByText("Budget can be at most $5.00.")).toBeInTheDocument();
    expect(createRun).not.toHaveBeenCalled();
  });

  it("requires a goal", async () => {
    const user = userEvent.setup();
    const createRun = vi.fn(async () => run());
    render(<CollabForm roomId={ROOM_A} roomAgents={both} createRun={createRun} onStarted={() => {}} />);
    await user.click(screen.getByTestId("collab-start"));
    expect(await screen.findByText("Describe the goal.")).toBeInTheDocument();
    expect(createRun).not.toHaveBeenCalled();
  });

  it("disables Start and explains why with fewer than two usable agents", () => {
    const noKey = agent(GPT_ID, "GPT", { status: "missing_key" });
    render(
      <CollabForm
        roomId={ROOM_A}
        roomAgents={[
          { member: member(CLAUDE), agent: CLAUDE },
          { member: member(noKey), agent: noKey },
        ]}
        createRun={vi.fn()}
        onStarted={() => {}}
      />,
    );
    expect(screen.getByTestId("collab-start")).toBeDisabled();
    expect(screen.getByTestId("collab-blocked")).toHaveTextContent(/at least two agents/);
  });

  it("shows 409 and 422 errors from the server", async () => {
    const user = userEvent.setup();
    const createRun = vi
      .fn()
      .mockRejectedValueOnce(new ApiError(409, "run_active", "A run is already active in this room."))
      .mockRejectedValueOnce(new ApiError(422, "validation_error", "Critic is not a member of this room."));
    render(<CollabForm roomId={ROOM_A} roomAgents={both} createRun={createRun} onStarted={() => {}} />);
    await user.type(screen.getByTestId("collab-goal"), "g");
    await user.click(screen.getByTestId("collab-start"));
    expect(await screen.findByText("A run is already active in this room.")).toBeInTheDocument();
    await user.click(screen.getByTestId("collab-start"));
    expect(await screen.findByText("Critic is not a member of this room.")).toBeInTheDocument();
    expect(screen.getByTestId("collab-goal")).toHaveValue("g");
  });
});
