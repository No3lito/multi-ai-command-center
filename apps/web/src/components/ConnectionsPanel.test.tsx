import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { Connection } from "@/lib/types";
import { ROOM_A } from "@/test/fakeWebSocket";
import { ConnectionsPanel, type ConnectionsApi } from "./ConnectionsPanel";

const EXT_ID = `ext_${"a".repeat(32)}`;

function conn(over: Partial<Connection> = {}): Connection {
  return {
    id: EXT_ID,
    display_name: "Grok Bot",
    status: "active",
    created_at: "2026-11-02T21:00:00Z",
    last_used_at: null,
    rooms: [{ id: ROOM_A, name: "General" }],
    token: null,
    mcp_path: "/mcp",
    mcp_port: 8001,
    ...over,
  };
}

function fakeApi(initial: Connection[] = []): ConnectionsApi & { list: Connection[] } {
  const state = { list: [...initial] };
  return {
    get list() {
      return state.list;
    },
    listConnections: vi.fn(async () => state.list.map((c) => ({ ...c, token: null }))),
    createConnection: vi.fn(async (name: string) => {
      const c = conn({ display_name: name, token: "ccx_secret-token-value" });
      state.list.push(c);
      return c;
    }),
    rotateConnection: vi.fn(async () => conn({ token: "ccx_new-token" })),
    revokeConnection: vi.fn(async () => {
      state.list = state.list.map((c) => ({
        ...c,
        status: "disabled" as const,
      }));
      return state.list[0] ?? conn({ status: "disabled" });
    }),
  };
}

const noop = async () => {};

describe("ConnectionsPanel", () => {
  it("creates a connection in the current room and shows its token once", async () => {
    const user = userEvent.setup();
    const api = fakeApi();
    render(<ConnectionsPanel api={api} roomId={ROOM_A} roomName="General" memberIds={new Set()} onAddToRoom={noop} />);
    expect(screen.getByTestId("connection-name")).toHaveValue("Grok Bot");
    await user.click(screen.getByTestId("connection-create"));
    expect(api.createConnection).toHaveBeenCalledWith("Grok Bot", [ROOM_A]);
    expect(await screen.findByTestId("connection-token")).toHaveTextContent("ccx_secret-token-value");
    expect(screen.getByTestId("connection-token")).toHaveTextContent("shown only once");
    await waitFor(() => expect(screen.getAllByTestId("connection-item")).toHaveLength(1));
    await user.click(screen.getByText("I saved it"));
    expect(screen.queryByText(/ccx_secret-token-value/)).not.toBeInTheDocument();
  });

  it("asks for confirmation before disconnecting", async () => {
    const user = userEvent.setup();
    const api = fakeApi([conn()]);
    render(
      <ConnectionsPanel
        api={api}
        roomId={ROOM_A}
        roomName="General"
        memberIds={new Set([EXT_ID])}
        onAddToRoom={noop}
      />,
    );
    await user.click(await screen.findByText("Disconnect"));
    expect(api.revokeConnection).not.toHaveBeenCalled();
    await user.click(screen.getByTestId("connection-revoke-confirm"));
    expect(api.revokeConnection).toHaveBeenCalledWith(EXT_ID);
    await waitFor(() => expect(screen.getByTestId("connection-item")).toHaveAttribute("data-status", "disabled"));
  });

  it("adds an existing connection to another project room", async () => {
    const user = userEvent.setup();
    const api = fakeApi([conn()]);
    const onAddToRoom = vi.fn(async () => {});
    render(
      <ConnectionsPanel
        api={api}
        roomId="room_other"
        roomName="Strategy B"
        memberIds={new Set()}
        onAddToRoom={onAddToRoom}
      />,
    );
    await user.click(await screen.findByText("Add to Strategy B"));
    expect(onAddToRoom).toHaveBeenCalledWith(EXT_ID);
  });
});
