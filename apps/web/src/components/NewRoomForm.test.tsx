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

function fakeServer(workspace: unknown) {
  const posts: unknown[] = [];
  setFetchImpl(async (input: string, init?: RequestInit) => {
    if (input === "/api/workspace") return json(200, workspace);
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
