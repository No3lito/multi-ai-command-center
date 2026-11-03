import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { msg } from "@/test/fakeWebSocket";
import { agentMsg, coordMsg } from "@/test/fixtures";
import { MessageList } from "./MessageList";

const renderList = (messages: Parameters<typeof MessageList>[0]["messages"]) =>
  render(<MessageList messages={messages} pending={[]} loading={false} onRetry={() => {}} onDiscard={() => {}} />);

describe("MessageList with agents", () => {
  it("shows a SIMULATED badge, provider/model and usage on simulated agent messages", () => {
    renderList([agentMsg(1)]);
    const item = screen.getByTestId("message-item");
    expect(within(item).getByTestId("simulated-badge")).toHaveTextContent(/simulated/i);
    // Look A1: model, tokens and cost sit in the time's tooltip, not on screen.
    const details = within(item).getByTestId("message-time").getAttribute("title") ?? "";
    expect(details).toContain("anthropic / claude-sonnet-5-5");
    expect(details).toContain("200 tokens");
    expect(details).toContain("no cost (simulated)");
  });

  it("shows cost and no badge on live agent messages", () => {
    renderList([
      agentMsg(1, { usage: { input_tokens: 10, output_tokens: 5, cost_usd: 0.0123 } }, { simulated: false }),
    ]);
    expect(screen.queryByTestId("simulated-badge")).toBeNull();
    expect(screen.getByTestId("message-time").getAttribute("title")).toContain("$0.0123");
  });

  it("does not badge human messages, even if data claims simulated", () => {
    const m = msg(1);
    renderList([{ ...m, body: { text: "hi", data: { simulated: false } } }]);
    expect(screen.queryByTestId("simulated-badge")).toBeNull();
    expect(screen.queryByTestId("message-usage")).toBeNull();
  });

  it("renders coordinator task messages as compact notes and errors as red notes, with safe text", () => {
    renderList([
      coordMsg(1, "task.assign", "Claude: write a plan"),
      coordMsg(2, "task.result", "Run finished <b>ok</b>"),
      coordMsg(3, "error", "Provider failed"),
    ]);
    const items = screen.getAllByTestId("message-item");
    expect(items[0]).toHaveAttribute("data-note-kind", "task.assign");
    expect(items[0]).toHaveTextContent("Claude: write a plan");
    expect(items[1]).toHaveTextContent("Run finished <b>ok</b>");
    expect(items[1]!.querySelector("b")).toBeNull();
    expect(items[2]).toHaveAttribute("data-note-kind", "error");
    // Errors are action notes; globals.css paints .system-action[data-note-kind="error"] red.
    expect(items[2]!.className).toContain("system-action");
    expect(items[0]!.getAttribute("data-note-kind")).not.toBe("error");
  });
});
