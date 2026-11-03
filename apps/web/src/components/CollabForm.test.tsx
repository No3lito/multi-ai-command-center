import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";
import { ROOM_A } from "@/test/fakeWebSocket";
import { CLAUDE, CLAUDE_ID, GEMINI_ID, GPT, GPT_ID, agent, member, run } from "@/test/fixtures";
import type { RoomAgent } from "./AgentsPanel";
import { CollabForm, validateCollab } from "./CollabForm";

const both: RoomAgent[] = [
  { member: member(CLAUDE), agent: CLAUDE },
  { member: member(GPT), agent: GPT },
];

const GROK = agent(GEMINI_ID, "Grok", {
  provider: "xai",
  model: "grok-build-0.1",
  role: "Builder",
});
const three: RoomAgent[] = [
  { member: member(GROK), agent: GROK },
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

  it("defaults to design & build with three agents: Claude and GPT design, the Builder builds", async () => {
    const user = userEvent.setup();
    const createRun = vi.fn(async () => run({ kind: "build" }));
    const onStarted = vi.fn();
    render(<CollabForm roomId={ROOM_A} roomAgents={three} createRun={createRun} onStarted={onStarted} />);
    expect(screen.getByTestId("collab-workflow")).toHaveValue("build");
    expect(screen.getByLabelText("Designer")).toHaveValue(CLAUDE_ID);
    expect(screen.getByLabelText("Co-designer")).toHaveValue(GPT_ID);
    expect(screen.getByTestId("collab-builder")).toHaveValue(GEMINI_ID);
    await user.type(screen.getByTestId("collab-goal"), "A tip calculator");
    await user.click(screen.getByTestId("collab-start"));
    await waitFor(() => expect(onStarted).toHaveBeenCalled());
    expect(createRun).toHaveBeenCalledWith(ROOM_A, {
      goal: "A tip calculator",
      workflow: "build",
      planner_id: CLAUDE_ID,
      critic_id: GPT_ID,
      builder_id: GEMINI_ID,
      budget_usd: 0.5,
      max_turns: 8,
    });
  });

  it("keeps the builder separate from the designers and can switch back to plan & review", async () => {
    const user = userEvent.setup();
    const createRun = vi.fn(async () => run());
    render(<CollabForm roomId={ROOM_A} roomAgents={three} createRun={createRun} onStarted={() => {}} />);
    await user.type(screen.getByTestId("collab-goal"), "g");
    await user.selectOptions(screen.getByLabelText("Designer"), CLAUDE_ID);
    await user.selectOptions(screen.getByTestId("collab-builder"), CLAUDE_ID);
    await user.click(screen.getByTestId("collab-start"));
    expect(await screen.findByText("The builder must be a different agent from the designers.")).toBeInTheDocument();
    expect(createRun).not.toHaveBeenCalled();

    await user.selectOptions(screen.getByTestId("collab-workflow"), "collab");
    expect(screen.queryByTestId("collab-builder")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Planner")).toBeInTheDocument();
  });

  it("needs three usable agents for design & build", async () => {
    const user = userEvent.setup();
    render(<CollabForm roomId={ROOM_A} roomAgents={both} createRun={vi.fn()} onStarted={() => {}} />);
    expect(screen.getByTestId("collab-workflow")).toHaveValue("collab");
    await user.selectOptions(screen.getByTestId("collab-workflow"), "build");
    expect(screen.getByTestId("collab-start")).toBeDisabled();
    expect(screen.getByTestId("collab-blocked")).toHaveTextContent("three agents");
  });

  it("defaults to review & improve with a connected Grok Bot as the worker", async () => {
    const user = userEvent.setup();
    const createRun = vi.fn(async () => run({ kind: "review" }));
    const grokBot = {
      id: `ext_${"b".repeat(32)}`,
      kind: "external" as const,
      display_name: "Grok Bot",
    };
    render(
      <CollabForm roomId={ROOM_A} roomAgents={both} externals={[grokBot]} createRun={createRun} onStarted={() => {}} />,
    );
    expect(screen.getByTestId("collab-workflow")).toHaveValue("review");
    expect(screen.getByLabelText("Lead reviewer")).toHaveValue(CLAUDE_ID);
    expect(screen.getByLabelText("Co-reviewer")).toHaveValue(GPT_ID);
    expect(screen.getByTestId("collab-builder")).toHaveValue(grokBot.id);
    expect(screen.getByRole("option", { name: "Grok Bot (connected)" })).toBeInTheDocument();
    await user.type(screen.getByTestId("collab-goal"), "Review the meme coin strategy");
    await user.click(screen.getByTestId("collab-start"));
    await waitFor(() => expect(createRun).toHaveBeenCalled());
    expect(createRun).toHaveBeenCalledWith(ROOM_A, {
      goal: "Review the meme coin strategy",
      workflow: "review",
      planner_id: CLAUDE_ID,
      critic_id: GPT_ID,
      builder_id: grokBot.id,
      budget_usd: 0.5,
      max_turns: 8,
    });
  });

  it("sends picked attachments and can skip the decision brief", async () => {
    const user = userEvent.setup();
    const createRun = vi.fn(async () => run());
    const listFiles = vi.fn(async () => ({
      enabled: true,
      path: "",
      max_files: 10,
      max_chars: 300_000,
      entries: [{ name: "README.md", path: "README.md", type: "file" as const, size: 100, readable: true }],
    }));
    render(
      <CollabForm roomId={ROOM_A} roomAgents={both} createRun={createRun} listFiles={listFiles} onStarted={() => {}} />,
    );
    await user.type(screen.getByTestId("collab-goal"), "Review the log");
    await user.click(await screen.findByTestId("attachments-toggle"));
    await user.click(await screen.findByTestId("attachment-checkbox"));
    await user.click(screen.getByTestId("collab-brief"));
    await user.click(screen.getByTestId("collab-start"));
    await waitFor(() => expect(createRun).toHaveBeenCalled());
    expect(createRun).toHaveBeenCalledWith(
      ROOM_A,
      expect.objectContaining({ attachments: ["README.md"], brief: false }),
    );
  });
});

describe("CollabForm in a project room", () => {
  it("lets the lead agent pick project files by default, and can turn it off", async () => {
    const user = userEvent.setup();
    const createRun = vi.fn(async () => run());
    render(
      <CollabForm
        roomId={ROOM_A}
        roomAgents={both}
        createRun={createRun}
        onStarted={() => {}}
        projectTitle="Meme coin strategy"
      />,
    );
    expect(screen.getByTestId("collab-agent-files-box")).toHaveTextContent("Meme coin strategy");
    expect(screen.getByTestId("collab-agent-files")).toBeChecked();
    await user.click(screen.getByTestId("collab-agent-files"));
    await user.type(screen.getByTestId("collab-goal"), "Review it");
    await user.click(screen.getByTestId("collab-start"));
    await waitFor(() => expect(createRun).toHaveBeenCalled());
    expect(createRun).toHaveBeenCalledWith(ROOM_A, expect.objectContaining({ agent_files: false }));
  });

  it("shows no project option outside project rooms", () => {
    render(<CollabForm roomId={ROOM_A} roomAgents={both} createRun={vi.fn()} onStarted={() => {}} />);
    expect(screen.queryByTestId("collab-agent-files-box")).not.toBeInTheDocument();
  });
});

describe("CollabForm file suggestions", () => {
  const listing = { enabled: true, path: "", entries: [], max_files: 10, max_chars: 300_000 };
  const P = "01-PROJECTS/trading/meme-coin-strategy";

  it("pre-selects files matching the goal, keeps removals removed, and sends them with the run", async () => {
    const user = userEvent.setup();
    const suggestFiles = vi.fn(async () => ({
      project_path: P,
      always: [`${P}/PROJECT.md`, "02-REFERENCE/owner-rules.md"],
      suggested: [
        { path: `${P}/sources/trading-review/HYPOTHESIS-REVIEW.md`, size: 2048, matched: ["hypothesis"] },
        { path: `${P}/sources/trading-review/FROZEN-SPECS.md`, size: 1024, matched: ["h123"] },
      ],
    }));
    const createRun = vi.fn(async () => run());
    render(
      <CollabForm
        roomId={ROOM_A}
        roomAgents={both}
        createRun={createRun}
        onStarted={() => {}}
        listFiles={vi.fn(async () => listing)}
        projectTitle="Meme coin strategy"
        suggestFiles={suggestFiles}
        suggestDelayMs={0}
      />,
    );
    await user.type(screen.getByTestId("collab-goal"), "Check hypothesis H123");
    await waitFor(() => expect(screen.getAllByTestId("attachment-chip")).toHaveLength(2));
    expect(screen.getByTestId("collab-always")).toHaveTextContent("Always included: PROJECT.md, owner-rules.md");
    expect(screen.getAllByTestId("attachment-chip")[0]).toHaveAttribute("data-suggested", "true");
    await user.click(screen.getAllByTestId("attachment-remove")[1]!);
    await user.type(screen.getByTestId("collab-goal"), " again");
    await waitFor(() => expect(suggestFiles.mock.calls.length).toBeGreaterThan(1));
    expect(screen.getAllByTestId("attachment-chip")).toHaveLength(1);
    await user.click(screen.getByTestId("collab-start"));
    await waitFor(() => expect(createRun).toHaveBeenCalled());
    expect(createRun).toHaveBeenCalledWith(
      ROOM_A,
      expect.objectContaining({ attachments: [`${P}/sources/trading-review/HYPOTHESIS-REVIEW.md`] }),
    );
  });
});
