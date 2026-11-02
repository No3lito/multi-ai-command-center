import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, roomSocketUrl, setFetchImpl, setUnauthorizedHandler, wsBase } from "./api";

function jsonResponse(status: number, body?: unknown): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function mockFetch(res: Response | (() => Promise<Response>)) {
  const fn = vi.fn<(input: string, init?: RequestInit) => Promise<Response>>(async () => (typeof res === "function" ? res() : res.clone()));
  setFetchImpl(fn);
  return fn;
}

afterEach(() => {
  setFetchImpl((i, init) => globalThis.fetch(i, init));
  setUnauthorizedHandler(null);
  vi.unstubAllEnvs();
});

describe("api client", () => {
  it("sends X-CC-CSRF and credentials on POST, with a JSON body", async () => {
    const fetchFn = mockFetch(jsonResponse(201, { id: "room_x", name: "Ops" }));
    await api.createRoom("Ops");
    const [url, init] = fetchFn.mock.calls[0]!;
    expect(url).toBe("/api/rooms");
    expect(init?.method).toBe("POST");
    expect(init?.credentials).toBe("include");
    const headers = init?.headers as Record<string, string>;
    expect(headers["X-CC-CSRF"]).toBe("1");
    expect(headers["Content-Type"]).toBe("application/json");
    expect(JSON.parse(init?.body as string)).toEqual({ name: "Ops" });
  });

  it("sends CSRF on logout (POST without body) but not on GET", async () => {
    const fetchFn = mockFetch(jsonResponse(204));
    await api.logout();
    expect((fetchFn.mock.calls[0]![1]?.headers as Record<string, string>)["X-CC-CSRF"]).toBe("1");

    const getFn = mockFetch(jsonResponse(200, []));
    await api.listRooms();
    const init = getFn.mock.calls[0]![1];
    expect((init?.headers as Record<string, string>)["X-CC-CSRF"]).toBeUndefined();
    expect(init?.credentials).toBe("include");
  });

  it("posts chat messages in the contract shape", async () => {
    const fetchFn = mockFetch(jsonResponse(201, { id: "msg_1" }));
    await api.postMessage("room_abc", "hi\nthere", "key-12345678");
    const [url, init] = fetchFn.mock.calls[0]!;
    expect(url).toBe("/api/rooms/room_abc/messages");
    expect(JSON.parse(init?.body as string)).toEqual({
      kind: "chat",
      body: { text: "hi\nthere" },
      reply_to: null,
      mentions: [],
      idempotency_key: "key-12345678",
    });
  });

  it("maps the error envelope to ApiError with status and code", async () => {
    mockFetch(jsonResponse(409, { error: { code: "room_exists", message: "Room already exists" } }));
    const err = await api.createRoom("General").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 409, code: "room_exists", message: "Room already exists" });
  });

  it("maps 401 and 429 on login without triggering the global 401 handler", async () => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    mockFetch(jsonResponse(401, { error: { code: "invalid_credentials", message: "Invalid password" } }));
    await expect(api.login("x")).rejects.toMatchObject({ status: 401, code: "invalid_credentials" });
    mockFetch(jsonResponse(429, { error: { code: "rate_limited", message: "Slow down" } }));
    await expect(api.login("x")).rejects.toMatchObject({ status: 429, code: "rate_limited" });
    expect(handler).not.toHaveBeenCalled();
  });

  it("calls the unauthorized handler on 401 from authenticated endpoints", async () => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    mockFetch(jsonResponse(401, { error: { code: "unauthenticated", message: "Sign in" } }));
    await expect(api.listRooms()).rejects.toMatchObject({ status: 401 });
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("falls back to a generic error when the body is not the error envelope", async () => {
    mockFetch(new Response("<html>Bad gateway</html>", { status: 502 }));
    await expect(api.listRooms()).rejects.toMatchObject({ status: 502, code: "server_error" });
  });

  it("maps network failures to network_error", async () => {
    mockFetch(() => Promise.reject(new TypeError("Failed to fetch")));
    await expect(api.me()).rejects.toMatchObject({ status: 0, code: "network_error" });
  });
});

describe("websocket url", () => {
  it("derives ws/wss from the page location when NEXT_PUBLIC_WS_BASE is unset", () => {
    vi.stubEnv("NEXT_PUBLIC_WS_BASE", "");
    expect(wsBase({ protocol: "http:", host: "localhost:8000" })).toBe("ws://localhost:8000");
    expect(wsBase({ protocol: "https:", host: "cc.example" })).toBe("wss://cc.example");
  });

  it("uses NEXT_PUBLIC_WS_BASE when set", () => {
    vi.stubEnv("NEXT_PUBLIC_WS_BASE", "ws://localhost:8000/");
    expect(wsBase({ protocol: "http:", host: "localhost:3000" })).toBe("ws://localhost:8000");
  });

  it("builds the room socket path with after_seq", () => {
    expect(roomSocketUrl("room_1", 42, "ws://h")).toBe("ws://h/api/ws/rooms/room_1?after_seq=42");
  });
});
