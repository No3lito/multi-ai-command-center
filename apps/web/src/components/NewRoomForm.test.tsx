import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { setFetchImpl } from "@/lib/api";
import { NewRoomForm } from "./NewRoomForm";

const MEME = "01-PROJECTS/trading/meme-coin-strategy";
const WS = {
  enabled: true,
  structured: true,
  families: ["trading"],
  projects: [
    {
      path: MEME,
      family: "trading",
      slug: "meme-coin-strategy",
      title: "Meme coin strategy",
      status: "active",
      goal: "",
    },
  ],
  inbox: [],
};
const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const agent = (id: string, name: string, provider: string, status: string) => ({
  id,
  kind: "agent",
  display_name: name,
  role: "Co-designer",
  provider,
  model: "m",
  system_prompt: "",
  max_output_tokens: 1000,
  enabled: true,
  status,
  price: null,
});
const AGENTS = [
  agent("agt_c", "Claude", "anthropic", "live"),
  agent("agt_g", "GPT", "openai", "live"),
  agent("agt_x", "Grok", "xai", "missing_key"),
];
const MEMBERS = [
  { id: "usr_n", kind: "owner", display_name: "Noel" },
  { id: "agt_c", kind: "agent", display_name: "Claude" },
  { id: "agt_g", kind: "agent", display_name: "GPT" },
];
const runs: Record<string, unknown>[] = [];
const failRun = { next: false };

function fakeServer(workspace: unknown) {
  runs.length = 0;
  const posts: unknown[] = [];
  setFetchImpl(async (input: string, init?: RequestInit) => {
    if (input === "/api/workspace") return json(200, workspace);
    if (input === "/api/agents") return json(200, AGENTS);
    if (input.startsWith("/api/rooms/room_x") && input.endsWith("/runs") && init?.method === "POST") {
      runs.push(JSON.parse(String(init.body)));
      if (failRun.next) {
        failRun.next = false;
        return json(500, { error: { code: "boom", message: "provider down" } });
      }
      return json(201, { id: "run_1" });
    }
    if (input === "/api/rooms/room_x")
      return json(200, { id: "room_x", name: "x", created_at: "", member_count: 3, last_seq: 0, members: MEMBERS });
    if (input === "/api/rooms" && init?.method === "POST") {
      const body = JSON.parse(String(init.body));
      posts.push(body);
      return json(201, { id: "room_x", name: body.name, created_at: "", member_count: 1, last_seq: 0 });
    }
    return json(404, { error: { code: "not_found", message: "no" } });
  });
  return posts;
}

afterEach(() => setFetchImpl((i, init) => globalThis.fetch(i, init)));

describe("NewRoomForm with a workspace", () => {
  it("creates a new project folder for a new room by default", async () => {
    const user = userEvent.setup();
    const posts = fakeServer(WS);
    const onCreated = vi.fn();
    render(<NewRoomForm onCreated={onCreated} />);
    await user.type(screen.getByTestId("new-room-name"), "Polymarket bot");
    expect(await screen.findByTestId("new-room-project")).toHaveValue("__new__");
    expect(screen.getByTestId("new-room-family")).toHaveValue("trading");
    await user.click(screen.getByTestId("new-room-submit"));
    await waitFor(() => expect(onCreated).toHaveBeenCalled());
    expect(posts).toEqual([{ name: "Polymarket bot", new_project: { family: "trading", name: "Polymarket bot" } }]);
  });

  it("links an existing project, or none", async () => {
    const user = userEvent.setup();
    const posts = fakeServer(WS);
    render(<NewRoomForm onCreated={() => {}} />);
    await user.type(screen.getByTestId("new-room-name"), "Meme 2");
    await user.selectOptions(await screen.findByTestId("new-room-project"), MEME);
    await user.click(screen.getByTestId("new-room-submit"));
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toEqual({ name: "Meme 2", project_path: MEME });
  });

  it("asks for a family name when starting a new family", async () => {
    const user = userEvent.setup();
    const posts = fakeServer(WS);
    render(<NewRoomForm onCreated={() => {}} />);
    await user.type(screen.getByTestId("new-room-name"), "Draft helper");
    await user.selectOptions(await screen.findByTestId("new-room-family"), "__new_family__");
    await user.click(screen.getByTestId("new-room-submit"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Enter a family name");
    await user.type(screen.getByTestId("new-room-new-family"), "Fantasy sports");
    await user.click(screen.getByTestId("new-room-submit"));
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toEqual({ name: "Draft helper", new_project: { family: "Fantasy sports", name: "Draft helper" } });
  });

  it("works as before without a workspace", async () => {
    const user = userEvent.setup();
    const posts = fakeServer({ enabled: false, structured: false, families: [], projects: [], inbox: [] });
    render(<NewRoomForm onCreated={() => {}} />);
    await user.type(screen.getByTestId("new-room-name"), "Ops");
    expect(screen.queryByTestId("new-room-project")).not.toBeInTheDocument();
    await user.click(screen.getByTestId("new-room-submit"));
    await waitFor(() => expect(posts).toEqual([{ name: "Ops" }]));
  });
});

describe("New project: create and start", () => {
  it("creates the project room and starts Claude and GPT on the goal in one click", async () => {
    const user = userEvent.setup();
    const posts = fakeServer(WS);
    const onCreated = vi.fn();
    const onDone = vi.fn();
    render(<NewRoomForm onCreated={onCreated} onDone={onDone} />);
    await user.type(screen.getByTestId("new-room-name"), "Polymarket bot");
    expect(screen.getByTestId("new-room-start")).toBeDisabled();
    await user.type(screen.getByTestId("new-room-goal"), "Find three strategies to paper test");
    expect(screen.getByTestId("new-room-preview")).toHaveTextContent("collaborate on it right away");
    await user.click(screen.getByTestId("new-room-start"));
    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(posts).toEqual([
      {
        name: "Polymarket bot",
        new_project: { family: "trading", name: "Polymarket bot", goal: "Find three strategies to paper test" },
      },
    ]);
    expect(runs).toEqual([
      expect.objectContaining({
        goal: "Find three strategies to paper test",
        workflow: "collab",
        planner_id: "agt_c",
        critic_id: "agt_g",
      }),
    ]);
    expect(onCreated).toHaveBeenCalledTimes(1);
  });

  it("keeps the room when the run fails, and Retry starts only the run", async () => {
    const user = userEvent.setup();
    const posts = fakeServer(WS);
    failRun.next = true;
    const onDone = vi.fn();
    render(<NewRoomForm onCreated={() => {}} onDone={onDone} />);
    await user.type(screen.getByTestId("new-room-name"), "Bot");
    await user.type(screen.getByTestId("new-room-goal"), "Do it");
    await user.click(screen.getByTestId("new-room-start"));
    expect(await screen.findByRole("alert")).toHaveTextContent("The room was created, but the run did not start");
    expect(screen.getByTestId("new-room-start")).toHaveTextContent("Retry starting the run");
    await user.click(screen.getByTestId("new-room-start"));
    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(posts).toHaveLength(1);
    expect(runs).toHaveLength(2);
  });
});
