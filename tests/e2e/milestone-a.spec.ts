import { expect, test, type Page } from "@playwright/test";

const PASSWORD = process.env.E2E_OWNER_PASSWORD ?? "e2e-owner-password";

async function signIn(page: Page) {
  await page.goto("/");
  await page.getByTestId("login-password").fill(PASSWORD);
  await page.getByTestId("login-submit").click();
  await expect(page.getByTestId("room-list")).toBeVisible();
}

async function openRoom(page: Page, name: string) {
  await page.getByTestId("room-item").filter({ hasText: name }).first().click();
  await expect(page.getByTestId("connection-status")).toHaveText(/live/i, { timeout: 10_000 });
}

async function send(page: Page, text: string) {
  await page.getByTestId("composer-input").fill(text);
  await page.getByTestId("composer-input").press("Enter");
}

test("rejects a wrong password", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("login-password").fill("definitely-wrong-password");
  await page.getByTestId("login-submit").click();
  await expect(page.getByText(/incorrect|invalid|wrong/i)).toBeVisible();
  await expect(page.getByTestId("room-list")).toHaveCount(0);
});

test("sign in, chat, live updates across tabs, persistence and reconnect", async ({ browser }) => {
  const context = await browser.newContext();
  // Test hook: record sockets, and optionally send new connections to a dead path to hold reconnects.
  await context.addInitScript(() => {
    const Native = window.WebSocket;
    const w = window as unknown as { __holdWs: boolean; __sockets: WebSocket[] };
    w.__holdWs = false;
    w.__sockets = [];
    class Tracked extends Native {
      constructor(url: string | URL, protocols?: string | string[]) {
        const target = w.__holdWs ? String(url).replace("/api/ws/", "/api/ws-held/") : url;
        super(target, protocols);
        w.__sockets.push(this);
      }
    }
    window.WebSocket = Tracked;
  });
  const a = await context.newPage();
  await signIn(a);
  await openRoom(a, "General");

  // A second tab (same session) watching the same room.
  const b = await context.newPage();
  await b.goto("/");
  await expect(b.getByTestId("room-list")).toBeVisible();
  await openRoom(b, "General");

  // Message from tab A shows up live in tab B, without a reload.
  const first = `hello from A ${Date.now()}`;
  await send(a, first);
  await expect(a.getByTestId("message-item").filter({ hasText: first })).toHaveCount(1);
  await expect(b.getByTestId("message-item").filter({ hasText: first })).toHaveCount(1, { timeout: 3_000 });

  // Shift+Enter makes a newline instead of sending.
  await a.getByTestId("composer-input").fill("line one");
  await a.getByTestId("composer-input").press("Shift+Enter");
  await a.getByTestId("composer-input").pressSequentially("line two");
  await expect(a.getByTestId("composer-input")).toHaveValue("line one\nline two");
  await a.getByTestId("composer-send").click();
  await expect(b.getByTestId("message-item").filter({ hasText: "line two" })).toHaveCount(1);

  // Reconnect: drop B's socket and block reconnects while another session posts, then release.
  // B must catch up from its last seq, without a reload and without duplicates.
  const poster = await browser.newContext();
  const c = await poster.newPage();
  await signIn(c);
  await openRoom(c, "General");
  await b.evaluate(() => {
    const w = window as unknown as { __holdWs: boolean; __sockets: WebSocket[] };
    w.__holdWs = true;
    w.__sockets.forEach((s) => s.close());
  });
  await expect(b.getByTestId("connection-status")).not.toHaveText(/live/i, { timeout: 10_000 });
  const missed = `sent while B disconnected ${Date.now()}`;
  await send(c, missed);
  await expect(c.getByTestId("message-item").filter({ hasText: missed })).toHaveCount(1);
  await b.waitForTimeout(1_500);
  await expect(b.getByTestId("message-item").filter({ hasText: missed })).toHaveCount(0);
  await b.evaluate(() => {
    (window as unknown as { __holdWs: boolean }).__holdWs = false;
  });
  await expect(b.getByTestId("connection-status")).toHaveText(/live/i, { timeout: 45_000 });
  await expect(b.getByTestId("message-item").filter({ hasText: missed })).toHaveCount(1, { timeout: 10_000 });
  await poster.close();

  // Each message appears exactly once in B (no duplicates after reconnect).
  await expect(b.getByTestId("message-item").filter({ hasText: first })).toHaveCount(1);

  // Create a room, then reload: rooms and messages persist.
  const roomName = `E2E ${Date.now()}`;
  await a.getByTestId("new-room-name").fill(roomName);
  await a.getByTestId("new-room-submit").click();
  await openRoom(a, roomName);
  await send(a, "first message in the new room");
  await a.reload();
  await expect(a.getByTestId("room-list")).toBeVisible();
  await openRoom(a, roomName);
  await expect(a.getByTestId("message-item").filter({ hasText: "first message in the new room" })).toHaveCount(1);

  // Untrusted text renders as text, not HTML.
  const xss = `<img src=x onerror="window.__pwned=1"> ${Date.now()}`;
  await send(a, xss);
  await expect(a.getByTestId("message-item").filter({ hasText: "<img src=x" })).toHaveCount(1);
  expect(await a.evaluate(() => (window as unknown as { __pwned?: number }).__pwned)).toBeUndefined();

  await context.close();
});
