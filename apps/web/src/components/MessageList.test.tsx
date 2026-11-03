import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { msg } from "@/test/fakeWebSocket";
import { MessageList } from "./MessageList";

describe("MessageList", () => {
  it("renders text safely as plain text with preserved newlines", () => {
    const evil = msg(1, undefined, '<img src=x onerror="alert(1)">\nsecond line');
    render(<MessageList messages={[evil]} pending={[]} loading={false} onRetry={() => {}} onDiscard={() => {}} />);
    const item = screen.getByTestId("message-item");
    expect(item.querySelector("img")).toBeNull();
    expect(item).toHaveTextContent('<img src=x onerror="alert(1)">');
    const p = item.querySelector("p");
    expect(p?.textContent).toBe('<img src=x onerror="alert(1)">\nsecond line');
    expect(p?.className).toMatch(/whitespace-pre/);
    expect(screen.getByText("owner")).toBeInTheDocument();
  });

  it("groups the same identity without grouping different ids with the same name", () => {
    const first = msg(1);
    const second = { ...msg(2), sender: { ...first.sender } };
    const third = { ...msg(3), sender: { ...first.sender, id: "different-principal" } };
    render(
      <MessageList messages={[first, second, third]} pending={[]} loading={false} onRetry={() => {}} onDiscard={() => {}} />,
    );
    const rows = screen.getAllByTestId("message-item");
    expect(rows[0]).not.toHaveAttribute("data-grouped");
    expect(rows[1]).toHaveAttribute("data-grouped", "true");
    expect(rows[2]).not.toHaveAttribute("data-grouped");
    expect(screen.getAllByText("You")).toHaveLength(2);
  });

  it("distinguishes routine system events from assignments and errors", () => {
    const system = { ...msg(1).sender, kind: "system" as const, display_name: "Coordinator" };
    const messages = [
      { ...msg(1), sender: system, kind: "task.status" as const },
      { ...msg(2), sender: system, kind: "task.assign" as const },
      { ...msg(3), sender: system, kind: "error" as const },
    ];
    render(<MessageList messages={messages} pending={[]} loading={false} onRetry={() => {}} onDiscard={() => {}} />);
    const rows = screen.getAllByTestId("message-item");
    expect(rows.map((row) => row.getAttribute("data-system-tier"))).toEqual(["routine", "action", "action"]);
    expect(screen.getByText("Assignment")).toBeInTheDocument();
    expect(screen.getByText("Error")).toBeInTheDocument();
  });

  it("has a polite live region", () => {
    const { container } = render(
      <MessageList messages={[]} pending={[]} loading={false} onRetry={() => {}} onDiscard={() => {}} />,
    );
    expect(container.querySelector('[aria-live="polite"]')).not.toBeNull();
    expect(screen.getByText("No messages yet")).toBeInTheDocument();
  });
});
