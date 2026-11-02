import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";
import { CLAUDE, GEMINI_ID, GPT, agent, member } from "@/test/fixtures";
import { ROOM_A } from "@/test/fakeWebSocket";
import { AgentsPanel } from "./AgentsPanel";
import { splitAgents } from "./RoomView";

describe("AgentsPanel", () => {
  it("lists room agents with provider, model and status pills", () => {
    const live = agent("agt_live", "Live One", { status: "live" });
    const noKey = agent("agt_nokey", "No Key", { status: "missing_key" });
    const noPrice = agent("agt_noprice", "No Price", { status: "unknown_price" });
    const off = agent("agt_off", "Off", { status: "disabled" });
    const all = [CLAUDE, live, noKey, noPrice, off];
    render(
      <AgentsPanel
        hasRoom
        loading={false}
        error={null}
        roomAgents={all.map((a) => ({ member: member(a), agent: a }))}
        otherAgents={[]}
        onAdd={vi.fn()}
        onRetry={vi.fn()}
      />,
    );
    const pills = screen.getAllByTestId("agent-status").map((p) => [p.textContent, p.getAttribute("data-tone")]);
    expect(pills).toEqual([
      ["Simulated", "warn"],
      ["Live", "ok"],
      ["No API key", "danger"],
      ["No price", "danger"],
      ["Disabled", "muted"],
    ]);
    expect(screen.getAllByTestId("agent-item")[0]).toHaveTextContent("anthropic / claude-sonnet-5-5");
  });

  it("adds an agent that is not in the room and shows errors", async () => {
    const user = userEvent.setup();
    const gemini = agent(GEMINI_ID, "Gemini", { provider: "simulated", model: "sim" });
    const onAdd = vi.fn().mockRejectedValueOnce(new ApiError(404, "not_found", "Agent not found.")).mockResolvedValue(undefined);
    render(
      <AgentsPanel
        hasRoom
        loading={false}
        error={null}
        roomAgents={[{ member: member(CLAUDE), agent: CLAUDE }]}
        otherAgents={[gemini]}
        onAdd={onAdd}
        onRetry={vi.fn()}
      />,
    );
    const item = screen.getAllByTestId("agent-item").find((el) => el.getAttribute("data-in-room") === "false")!;
    await user.click(within(item).getByTestId("add-agent-to-room"));
    expect(await screen.findByText("Agent not found.")).toBeInTheDocument();
    await user.click(within(item).getByTestId("add-agent-to-room"));
    await waitFor(() => expect(onAdd).toHaveBeenCalledTimes(2));
    expect(onAdd).toHaveBeenCalledWith(GEMINI_ID);
  });

  it("splits agents into room members and others", () => {
    const gemini = agent(GEMINI_ID, "Gemini");
    const detail = {
      id: ROOM_A,
      name: "General",
      created_at: "",
      member_count: 3,
      last_seq: 0,
      members: [{ id: "usr_1", kind: "owner" as const, display_name: "Noel" }, member(CLAUDE), member(GPT)],
    };
    const { roomAgents, otherAgents } = splitAgents(detail, [CLAUDE, GPT, gemini]);
    expect(roomAgents.map((r) => r.member.display_name)).toEqual(["Claude", "GPT"]);
    expect(otherAgents.map((a) => a.display_name)).toEqual(["Gemini"]);
  });
});
