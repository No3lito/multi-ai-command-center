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

  it("has a polite live region", () => {
    const { container } = render(
      <MessageList messages={[]} pending={[]} loading={false} onRetry={() => {}} onDiscard={() => {}} />,
    );
    expect(container.querySelector('[aria-live="polite"]')).not.toBeNull();
    expect(screen.getByText("No messages yet")).toBeInTheDocument();
  });
});
