import { fireEvent, render, screen, within } from "@testing-library/react";
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

  it("keeps names, initials and roles visible without depending on color", () => {
    const speakers = [
      { id: "owner", kind: "owner" as const, display_name: "Noel" },
      { id: "claude", kind: "agent" as const, display_name: "Claude" },
      { id: "gpt", kind: "agent" as const, display_name: "GPT" },
      { id: "external", kind: "external" as const, display_name: "External tool" },
    ];
    render(
      <MessageList
        messages={speakers.map((sender, index) => ({ ...msg(index + 1), sender }))}
        pending={[]}
        loading={false}
        onRetry={() => {}}
        onDiscard={() => {}}
      />,
    );
    const rows = screen.getAllByTestId("message-item");
    speakers.forEach((speaker, index) => {
      expect(within(rows[index]!).getByText(speaker.display_name)).toBeVisible();
      expect(rows[index]!.querySelector(".speaker-role")).toHaveTextContent(
        speaker.kind === "owner" ? "You" : speaker.kind === "agent" ? "AI" : "System",
      );
      expect(rows[index]!.querySelector(".speaker-role")).toBeVisible();
    });
  });

  it("uses allocated colors for duplicate names and exposes rose as an accent", () => {
    const speakers = [
      { id: "claude-1", kind: "agent" as const, display_name: "Claude" },
      { id: "claude-2", kind: "agent" as const, display_name: "Claude" },
      ...Array.from({ length: 3 }, (_, index) => ({
        id: `other-${index}`, kind: "agent" as const, display_name: `Other ${index}`,
      })),
    ];
    render(
      <MessageList
        messages={speakers.map((sender, index) => ({ ...msg(index + 1), sender }))}
        pending={[]}
        loading={false}
        onRetry={() => {}}
        onDiscard={() => {}}
      />,
    );
    const rows = screen.getAllByTestId("message-item");
    expect(new Set(rows.map((row) => row.style.getPropertyValue("--speaker-color"))).size).toBe(5);
    expect(rows[4]).toHaveAttribute("data-accent", "rose");
    expect(rows[4]!.style.getPropertyValue("--speaker-color")).toBe("var(--speaker-rose)");
  });

  it("preserves allocated identities when new speakers arrive", () => {
    const first = { ...msg(1), sender: { id: "first", kind: "agent" as const, display_name: "First" } };
    const second = { ...msg(2), sender: { id: "second", kind: "agent" as const, display_name: "Second" } };
    const props = { pending: [], loading: false, onRetry: () => {}, onDiscard: () => {} };
    const { rerender } = render(<MessageList {...props} messages={[first]} />);
    const color = screen.getByTestId("message-item").style.getPropertyValue("--speaker-color");
    rerender(<MessageList {...props} messages={[first, second]} />);
    expect(screen.getAllByTestId("message-item")[0]!.style.getPropertyValue("--speaker-color")).toBe(color);
  });

  it("does not pull a scrolled-up reader down when a new message arrives", () => {
    const props = { pending: [], loading: false, onRetry: () => {}, onDiscard: () => {} };
    const { rerender } = render(<MessageList {...props} messages={[msg(1)]} />);
    const log = screen.getByTestId("message-list");
    Object.defineProperties(log, {
      scrollHeight: { configurable: true, value: 1800 },
      clientHeight: { configurable: true, value: 400 },
    });
    log.scrollTop = 100;
    fireEvent.scroll(log);
    rerender(<MessageList {...props} messages={[msg(1), msg(2)]} />);
    expect(log.scrollTop).toBe(100);
    const jump = screen.getByRole("button", { name: "New messages ↓" });
    fireEvent.click(jump);
    expect(screen.queryByRole("button", { name: "New messages ↓" })).not.toBeInTheDocument();
  });

  it("has a polite live region", () => {
    const { container } = render(
      <MessageList messages={[]} pending={[]} loading={false} onRetry={() => {}} onDiscard={() => {}} />,
    );
    expect(container.querySelector('[aria-live="polite"]')).not.toBeNull();
    expect(screen.getByText("No messages yet")).toBeInTheDocument();
  });
});
