import { expect, test, type Locator, type Page } from "@playwright/test";

// Milestone B end to end. Assumes the e2e server runs with PROVIDER_MODE=simulated,
// so every agent turn uses the free local stand-in and is labeled SIMULATED.

const PASSWORD = process.env.E2E_OWNER_PASSWORD ?? "e2e-owner-password";

test.use({ viewport: { width: 1440, height: 1000 } });

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

function roomAgent(page: Page, name: string): Locator {
  return page
    .locator('[data-testid="agent-item"][data-in-room="true"]')
    .filter({ has: page.locator("span", { hasText: new RegExp(`^${name}$`) }) });
}

function messages(page: Page, opts: { senderKind: string; correlationId?: string; replyTo?: string }): Locator {
  let sel = `[data-testid="message-item"][data-sender-kind="${opts.senderKind}"]`;
  if (opts.correlationId) sel += `[data-correlation-id="${opts.correlationId}"]`;
  if (opts.replyTo) sel += `[data-reply-to="${opts.replyTo}"]`;
  return page.locator(sel);
}

test("simulated collaboration run, usage, and an @mention reply", async ({ page }) => {
  test.setTimeout(120_000);
  await signIn(page);
  await openRoom(page, "General");

  // Seeded agents are room members and clearly marked as simulated.
  for (const name of ["Claude", "GPT"]) {
    const item = roomAgent(page, name);
    await expect(item).toHaveCount(1, { timeout: 10_000 });
    await expect(item.getByTestId("agent-status")).toHaveText("Simulated");
    await expect(item.getByTestId("agent-status")).toHaveAttribute("data-value", "simulated");
  }

  // Start a collab run: planner Claude, critic GPT, default budget.
  await page.getByTestId("collab-goal").fill("Create a basic login interface");
  await page.getByTestId("collab-planner").selectOption({ label: "Claude" });
  await page.getByTestId("collab-critic").selectOption({ label: "GPT" });
  await expect(page.getByTestId("collab-budget")).toHaveValue("0.50");
  await expect(page.getByTestId("collab-start")).toBeEnabled();
  await page.getByTestId("collab-start").click();

  // The new run is listed first (newest first); remember its id.
  const firstRun = page.getByTestId("run-item").first();
  await expect(firstRun).toContainText("Create a basic login interface", { timeout: 10_000 });
  const runId = await firstRun.getAttribute("data-run-id");
  expect(runId).toMatch(/^run_/);
  const runItem = page.locator(`[data-testid="run-item"][data-run-id="${runId}"]`);
  await expect(runItem.getByTestId("run-simulated")).toBeVisible();

  // Wait for completion (driven by correlated room messages, with a 10 s poll as backup).
  await expect(runItem).toHaveAttribute("data-status", "completed", { timeout: 45_000 });
  await expect(runItem.getByTestId("run-status")).toHaveText("Completed");
  await expect(runItem.getByTestId("run-cancel")).toHaveCount(0);
  await expect(runItem.getByTestId("run-spent")).toHaveText("$0.00 of $0.50");

  // Coordinator: three task.assign notes (plan, critique, revise) and one task.result.
  const notes = messages(page, { senderKind: "system", correlationId: runId! });
  await expect(notes).toHaveCount(4, { timeout: 10_000 });
  await expect(notes.and(page.locator('[data-note-kind="task.assign"]'))).toHaveCount(3);
  await expect(notes.and(page.locator('[data-note-kind="task.result"]'))).toHaveCount(1);

  // Agents: plan (Claude), critique (GPT), revise (Claude), each badged SIMULATED.
  const agentMsgs = messages(page, { senderKind: "agent", correlationId: runId! });
  await expect(agentMsgs).toHaveCount(3);
  for (let i = 0; i < 3; i += 1) {
    await expect(agentMsgs.nth(i).getByTestId("simulated-badge")).toHaveText("SIMULATED");
  }
  await expect(messages(page, { senderKind: "system", correlationId: runId! }).getByTestId("simulated-badge")).toHaveCount(0);

  // Usage: simulated calls counted separately, no real spend.
  const usagePanel = page.getByTestId("usage-panel");
  await expect(usagePanel.getByTestId("usage-spent")).toHaveText("$0.00");
  await expect(usagePanel.getByTestId("usage-cap")).toHaveText(/^\$\d+\.\d{2}$/);
  await expect
    .poll(async () => Number((await usagePanel.getByTestId("usage-simulated-calls").textContent())?.replace(/,/g, "")), {
      timeout: 35_000,
    })
    .toBeGreaterThanOrEqual(3);
  await expect(usagePanel.getByTestId("usage-simulated")).toContainText("not real API usage");
  await expect(usagePanel.getByTestId("usage-table")).toHaveCount(0);

  // Mention Claude through the autocomplete, then expect a SIMULATED reply to that message.
  const input = page.getByTestId("composer-input");
  await input.click();
  await input.pressSequentially("@Cl");
  const option = page.getByTestId("mention-option").filter({ hasText: "@Claude" });
  await expect(option).toHaveCount(1);
  await input.press("Enter");
  await expect(input).toHaveValue("@Claude ");
  await input.pressSequentially("hello");
  await input.press("Enter");
  await expect(input).toHaveValue("");

  const mine = messages(page, { senderKind: "owner" }).filter({ hasText: "@Claude hello" }).last();
  await expect(mine).toBeVisible();
  const myId = await mine.getAttribute("data-message-id");
  expect(myId).toMatch(/^msg_/);

  const reply = messages(page, { senderKind: "agent", replyTo: myId! });
  await expect(reply).toHaveCount(1, { timeout: 30_000 });
  await expect(reply).toContainText("Claude");
  await expect(reply.getByTestId("simulated-badge")).toHaveText("SIMULATED");

  // A reply run shows up in the run list and completes.
  const replyRunId = await reply.getAttribute("data-correlation-id");
  expect(replyRunId).toMatch(/^run_/);
  await expect(page.locator(`[data-testid="run-item"][data-run-id="${replyRunId}"]`)).toHaveAttribute(
    "data-status",
    "completed",
    { timeout: 30_000 },
  );
  await expect(usagePanel.getByTestId("usage-spent")).toHaveText("$0.00");
});
