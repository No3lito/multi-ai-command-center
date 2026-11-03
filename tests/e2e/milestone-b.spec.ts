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

async function tab(page: Page, name: "decide" | "runs" | "history" | "setup") {
  await page.getByTestId(`tab-${name}`).click();
  await expect(page.getByTestId(`tab-${name}`)).toHaveAttribute("aria-selected", "true");
}

async function openGoal(page: Page) {
  await page.getByTestId("new-goal").click();
  await expect(page.getByTestId("modal")).toBeVisible();
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

  // The right panel opens on Decide; agents, usage and connections live under Setup.
  await expect(page.getByTestId("tab-decide")).toHaveAttribute("aria-selected", "true");
  await expect(page.getByTestId("summary-panel")).toBeVisible();
  await tab(page, "setup");

  // Seeded agents are room members and clearly marked as simulated.
  for (const name of ["Claude", "GPT"]) {
    const item = roomAgent(page, name);
    await expect(item).toHaveCount(1, { timeout: 10_000 });
    await expect(item.getByTestId("agent-status")).toHaveText("Simulated");
    await expect(item.getByTestId("agent-status")).toHaveAttribute("data-value", "simulated");
  }

  // Start a collab run from the New goal pop-up: planner Claude, critic GPT, default budget.
  await openGoal(page);
  await page.getByTestId("collab-goal").fill("Create a basic login interface");
  await page.getByTestId("collab-workflow").selectOption("collab");
  await page.getByTestId("collab-planner").selectOption({ label: "Claude" });
  await page.getByTestId("collab-critic").selectOption({ label: "GPT" });
  await expect(page.getByTestId("collab-budget")).toHaveValue("0.50");
  await expect(page.getByTestId("collab-start")).toBeEnabled();
  await page.getByTestId("collab-start").click();
  await expect(page.getByTestId("modal")).toHaveCount(0);
  await expect(page.getByTestId("tab-runs")).toHaveAttribute("aria-selected", "true");

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

  // The run ends with a decision brief, shown under Decide.
  await tab(page, "decide");
  await expect(page.getByTestId("summary-finished")).toContainText("1 run finished");
  const decisions = page.getByTestId("decisions-panel");
  await expect(decisions.getByTestId("decision-latest")).toBeVisible();
  await expect(decisions.getByTestId("decision-waiting")).toBeVisible();

  // Coordinator: four task.assign notes (plan, critique, revise, brief) and one task.result.
  const notes = messages(page, { senderKind: "system", correlationId: runId! });
  await expect(notes).toHaveCount(5, { timeout: 10_000 });
  await expect(notes.and(page.locator('[data-note-kind="task.assign"]'))).toHaveCount(4);
  await expect(notes.and(page.locator('[data-note-kind="task.result"]'))).toHaveCount(1);

  // Agents: plan (Claude), critique (GPT), revise (Claude), decision brief (Claude), each SIMULATED.
  const agentMsgs = messages(page, { senderKind: "agent", correlationId: runId! });
  await expect(agentMsgs).toHaveCount(4);
  for (let i = 0; i < 4; i += 1) {
    await expect(agentMsgs.nth(i).getByTestId("simulated-badge")).toHaveText("SIMULATED");
  }
  await expect(
    messages(page, { senderKind: "system", correlationId: runId! }).getByTestId("simulated-badge"),
  ).toHaveCount(0);

  // The brief raised a decision card; answering it records the answer and tells the room.
  const card = decisions.getByTestId("decision-card");
  await expect(card).toHaveCount(1, { timeout: 10_000 });
  await expect(card).toContainText("[Simulated] Example decision");
  await expect(card.getByTestId("decision-plan")).toContainText("Nothing more runs");
  await expect(card.getByTestId("decision-why")).toContainText("simulated example");
  await expect(card.getByTestId("decision-note")).toHaveValue("Simulated test: record my answer only.");
  await card.getByTestId("decision-note").fill("Looks good");
  await card.getByTestId("decision-follow").click();
  await expect(card.getByTestId("decision-what-happens")).toContainText("Nothing more runs");
  await card.getByTestId("decision-confirm").click();
  await expect(decisions.getByTestId("decision-card")).toHaveCount(0);
  const decided = decisions.getByTestId("decision-decided-item");
  await expect(decided).toContainText("Approved");
  await expect(decided).toContainText("Note: Looks good");
  await expect(
    messages(page, { senderKind: "system", correlationId: runId! }).filter({ hasText: "Owner APPROVED" }),
  ).toHaveCount(1, { timeout: 10_000 });

  // Usage: simulated calls counted separately, no real spend.
  await tab(page, "setup");
  const usagePanel = page.getByTestId("usage-panel");
  await expect(usagePanel.getByTestId("usage-spent")).toHaveText("$0.00");
  await expect(usagePanel.getByTestId("usage-cap")).toHaveText(/^\$\d+\.\d{2}$/);
  await expect
    .poll(
      async () => Number((await usagePanel.getByTestId("usage-simulated-calls").textContent())?.replace(/,/g, "")),
      {
        timeout: 35_000,
      },
    )
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
  await tab(page, "runs");
  await expect(page.locator(`[data-testid="run-item"][data-run-id="${replyRunId}"]`)).toHaveAttribute(
    "data-status",
    "completed",
    { timeout: 30_000 },
  );
  await tab(page, "setup");
  await expect(usagePanel.getByTestId("usage-spent")).toHaveText("$0.00");

  // The finished run is one card in the chat. Archiving hides it; History brings it back.
  const fold = page.locator(`[data-testid="run-fold"][data-run-id="${runId}"]`);
  await expect(fold).toHaveCount(1);
  await expect(fold.getByTestId("run-fold-line")).toBeVisible();
  await fold.getByTestId("run-fold-archive").click();
  await expect(fold).toHaveCount(0);
  await tab(page, "history");
  await page.getByTestId("history-archived").check();
  const archived = page.locator(`[data-testid="history-run"][data-run-id="${runId}"]`);
  await expect(archived).toContainText("archived");
  await archived.getByTestId("history-archive-toggle").click();
  await expect(fold).toHaveCount(1);
});

test("simulated design & build: Claude and GPT design, Grok builds and applies fixes", async ({ page }) => {
  test.setTimeout(120_000);
  await signIn(page);
  await openRoom(page, "General");
  await tab(page, "setup");
  for (const name of ["Claude", "GPT", "Grok"]) {
    await expect(roomAgent(page, name)).toHaveCount(1, { timeout: 10_000 });
  }

  await openGoal(page);
  // With three usable agents the form opens on design & build with the seeded roles.
  await expect(page.getByTestId("collab-workflow")).toHaveValue("build");
  await expect(page.getByTestId("collab-builder").locator("option:checked")).toHaveText("Grok");
  await page.getByTestId("collab-goal").fill("A tip calculator web page");
  await page.getByTestId("collab-start").click();

  const firstRun = page.getByTestId("run-item").first();
  await expect(firstRun).toContainText("A tip calculator web page", { timeout: 10_000 });
  await expect(firstRun).toContainText("Claude and GPT design, Grok builds");
  const runId = await firstRun.getAttribute("data-run-id");
  const runItem = page.locator(`[data-testid="run-item"][data-run-id="${runId}"]`);
  await expect(runItem).toHaveAttribute("data-status", "completed", { timeout: 60_000 });

  // Simulated answers never say APPROVED, so all 7 steps run, in this order.
  const agentMsgs = messages(page, { senderKind: "agent", correlationId: runId! });
  await expect(agentMsgs).toHaveCount(8, { timeout: 10_000 });
  const order = ["Claude", "GPT", "Grok", "Claude", "Grok", "GPT", "Grok", "Claude"];
  for (let i = 0; i < order.length; i += 1) {
    await expect(agentMsgs.nth(i)).toContainText(order[i]);
    await expect(agentMsgs.nth(i).getByTestId("simulated-badge")).toHaveText("SIMULATED");
  }
  const notes = messages(page, { senderKind: "system", correlationId: runId! });
  await expect(notes.and(page.locator('[data-note-kind="task.result"]'))).toHaveCount(1);
  await expect(notes.first()).toContainText("Step 1 of 7: @Claude, draft the design for: A tip calculator web page");
});

test("connect Grok Bot from the dashboard; a review run waits for it", async ({ page }) => {
  test.setTimeout(90_000);
  await signIn(page);
  await openRoom(page, "General");

  await tab(page, "setup");
  const panel = page.getByTestId("connections-panel");
  await panel.getByTestId("connection-name").fill("Grok Bot E2E");
  await panel.getByTestId("connection-create").click();
  const token = panel.getByTestId("connection-token");
  await expect(token).toContainText("ccx_");
  await expect(token).toContainText("shown only once");
  await panel.getByText("I saved it").click();
  await expect(token).toHaveCount(0);
  await expect(panel.getByTestId("connection-item").filter({ hasText: "Grok Bot E2E" })).toHaveAttribute(
    "data-status",
    "active",
  );

  // With a connection in the room, the form offers review & improve with it as the worker.
  await openGoal(page);
  await page.getByTestId("collab-workflow").selectOption("review");
  await page.getByTestId("collab-builder").selectOption({ label: "Grok Bot E2E (connected)" });
  await page.getByTestId("collab-goal").fill("Review the strategy work");
  await page.getByTestId("collab-start").click();
  const runItem = page.getByTestId("run-item").filter({ hasText: "Review the strategy work" }).first();
  await expect(runItem).toHaveAttribute("data-status", "waiting", { timeout: 20_000 });
  await expect(runItem.getByTestId("run-status")).toHaveText("Waiting for Grok Bot E2E");
  await expect(runItem).toContainText("Grok Bot E2E's work, reviewed by Claude and GPT");

  await runItem.getByTestId("run-cancel").click();
  await expect(runItem).toHaveAttribute("data-status", "cancelled", { timeout: 10_000 });

  // A second review is wrapped up instead: it stops waiting and concludes with a brief.
  await openGoal(page);
  await page.getByTestId("collab-workflow").selectOption("review");
  await page.getByTestId("collab-builder").selectOption({ label: "Grok Bot E2E (connected)" });
  await page.getByTestId("collab-goal").fill("Review and conclude");
  await page.getByTestId("collab-start").click();
  const second = page.getByTestId("run-item").filter({ hasText: "Review and conclude" }).first();
  await expect(second).toHaveAttribute("data-status", "waiting", { timeout: 20_000 });
  await second.getByTestId("run-wrap-up").click();
  await expect(second).toHaveAttribute("data-status", "completed", { timeout: 30_000 });
  await expect(second.getByTestId("verdict")).toHaveText("Needs you");

  await tab(page, "setup");
  const item = panel.getByTestId("connection-item").filter({ hasText: "Grok Bot E2E" });
  await item.getByText("Disconnect").click();
  await item.getByTestId("connection-revoke-confirm").click();
  await expect(item).toHaveAttribute("data-status", "disabled");
});

test("projects: a new room gets its own project folder, and inbox files are filed with one click", async ({ page }) => {
  await signIn(page);
  const roomName = `Polymarket bot ${Date.now()}`;
  await page.getByTestId("new-project-open").click();
  await page.getByTestId("new-room-name").fill(roomName);
  await expect(page.getByTestId("new-room-project")).toHaveValue("__new__");
  await expect(page.getByTestId("new-room-family")).toHaveValue("trading");
  await page.getByTestId("new-room-submit").click();
  await openRoom(page, roomName);
  await expect(page.getByTestId("room-project")).toContainText(`Project: ${roomName}`);

  await tab(page, "setup");
  await expect(page.getByTestId("project-select")).toHaveValue(/^01-PROJECTS\/trading\/polymarket-bot-/);
  await expect(page.getByTestId("project-panel")).toContainText("save briefs, decisions and outputs into");

  await openGoal(page);
  await expect(page.getByTestId("collab-agent-files")).toBeChecked();
  await page.getByTestId("modal-close").click();

  await tab(page, "decide");
  const item = page.getByTestId("inbox-item").filter({ hasText: "demo-notes.md" });
  await expect(item.getByTestId("inbox-project")).toHaveValue("01-PROJECTS/trading/demo-strategy");
  await item.getByTestId("inbox-file").click();
  await expect(page.getByTestId("inbox-panel")).toHaveCount(0);
});

test("new project in two clicks: Claude and GPT join and start on the goal", async ({ page }) => {
  test.setTimeout(90_000);
  await signIn(page);
  const name = `Draft helper ${Date.now()}`;
  await page.getByTestId("new-project-open").click(); // click 1
  await page.getByTestId("new-room-name").fill(name);
  await page.getByTestId("new-room-goal").fill("Plan a tiny demo");
  await page.getByTestId("new-room-start").click(); // click 2
  await expect(page.getByTestId("modal")).toHaveCount(0, { timeout: 15_000 });
  await openRoom(page, name);
  // Every agent that can answer joins (in simulated mode that includes Grok).
  const members = page.getByTestId("room-members");
  await expect(members.locator('[data-sender="claude"]')).toHaveCount(1);
  await expect(members.locator('[data-sender="gpt"]')).toHaveCount(1);
  // The run starts by itself; when it finishes, Claude's and GPT's messages carry their colors.
  await tab(page, "runs");
  const run = page.getByTestId("run-item").filter({ hasText: "Plan a tiny demo" }).first();
  await expect(run).toHaveAttribute("data-status", "completed", { timeout: 45_000 });
  const fold = page.getByTestId("run-fold").first();
  if ((await fold.getAttribute("data-open")) !== "true") await fold.getByTestId("run-fold-toggle").click();
  await expect(page.locator('[data-testid="message-item"][data-sender-style="claude"]').first()).toBeVisible();
  await expect(page.locator('[data-testid="message-item"][data-sender-style="gpt"]').first()).toBeVisible();
  await expect(page).toHaveTitle(/^\(1\) Multi-AI Command Center$/);
});

test("phone width: no sideways scrolling, readable text", async ({ browser }) => {
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await page.goto("/");
  await page.getByTestId("login-password").fill(PASSWORD);
  await page.getByTestId("login-submit").click();
  await page.getByLabel("Show rooms").click();
  await page.getByTestId("room-item").filter({ hasText: "General" }).first().click();
  await expect(page.getByTestId("connection-status")).toHaveText(/live/i, { timeout: 10_000 });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
  const size = await page.evaluate(() => getComputedStyle(document.body).fontSize);
  expect(size).toBe("16px");
  await page.close();
});
