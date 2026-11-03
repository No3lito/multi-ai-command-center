import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";
import type { Message } from "@/lib/types";
import { useOutbox } from "@/lib/useOutbox";
import { ROOM_A, msg } from "@/test/fakeWebSocket";
import { Composer, composerDeliveryState } from "./Composer";
import { MessageList } from "./MessageList";

describe("Composer", () => {
  it("sends on Enter and clears the input", async () => {
    const onSend = vi.fn();
    const user = userEvent.setup();
    render(<Composer onSend={onSend} roomName="General" />);
    const input = screen.getByTestId("composer-input");
    await user.type(input, "hello{Enter}");
    expect(onSend).toHaveBeenCalledWith("hello", []);
    expect(input).toHaveValue("");
  });

  it("inserts a newline on Shift+Enter without sending", async () => {
    const onSend = vi.fn();
    const user = userEvent.setup();
    render(<Composer onSend={onSend} />);
    const input = screen.getByTestId("composer-input");
    await user.type(input, "line 1{Shift>}{Enter}{/Shift}line 2");
    expect(onSend).not.toHaveBeenCalled();
    expect(input).toHaveValue("line 1\nline 2");
    await user.click(screen.getByTestId("composer-send"));
    expect(onSend).toHaveBeenCalledWith("line 1\nline 2", []);
  });

  it("disables send while empty or whitespace only", async () => {
    const onSend = vi.fn();
    const user = userEvent.setup();
    render(<Composer onSend={onSend} />);
    const send = screen.getByTestId("composer-send");
    expect(send).toBeDisabled();
    await user.type(screen.getByTestId("composer-input"), "   {Enter}");
    expect(send).toBeDisabled();
    expect(onSend).not.toHaveBeenCalled();
  });

  it("reports disabled, sending, and delivery-error states without replacing outbox retry", () => {
    const { container, rerender } = render(<Composer onSend={() => {}} disabled />);
    expect(container.querySelector("form")).toHaveAttribute("data-state", "disabled");
    expect(screen.getByTestId("composer-input")).toBeDisabled();
    rerender(<Composer onSend={() => {}} sending />);
    expect(container.querySelector("form")).toHaveAttribute("data-state", "sending");
    expect(screen.getByRole("status")).toHaveTextContent("Sending…");
    rerender(<Composer onSend={() => {}} deliveryError />);
    expect(container.querySelector("form")).toHaveAttribute("data-state", "error");
    expect(screen.getByRole("status")).toHaveTextContent("Use Retry or Discard");
    expect(screen.getByText(/Enter to send, Shift\+Enter for a new line\./)).toBeInTheDocument();
  });

  it("has an accessible label", () => {
    render(<Composer onSend={() => {}} roomName="General" />);
    expect(screen.getByLabelText("Message #General")).toBe(screen.getByTestId("composer-input"));
  });
});

function Harness({ postMessage, delivered }: { postMessage: (r: string, t: string, k: string) => Promise<Message>; delivered: Message[] }) {
  const outbox = useOutbox(ROOM_A, (m) => delivered.push(m), { postMessage });
  return (
    <>
      <MessageList messages={[]} pending={outbox.pending} loading={false} onRetry={outbox.retry} onDiscard={outbox.discard} />
      <Composer onSend={outbox.send} {...composerDeliveryState(outbox.pending)} />
    </>
  );
}

describe("Composer with outbox", () => {
  it("shows a pending message, then reuses the same idempotency key on retry", async () => {
    const user = userEvent.setup();
    const keys: string[] = [];
    const delivered: Message[] = [];
    let attempt = 0;
    const postMessage = vi.fn(async (_room: string, _text: string, key: string) => {
      keys.push(key);
      attempt += 1;
      if (attempt === 1) throw new ApiError(0, "network_error", "Cannot reach the Command Center server.");
      return msg(1, ROOM_A, "retry me");
    });

    render(<Harness postMessage={postMessage} delivered={delivered} />);
    await user.type(screen.getByTestId("composer-input"), "retry me{Enter}");

    const failed = await screen.findByText("Not sent");
    expect(failed).toBeInTheDocument();
    expect(screen.getByTestId("message-item")).toHaveAttribute("data-pending", "failed");
    expect(screen.getByRole("status")).toHaveTextContent("Use Retry or Discard");
    expect(screen.getByTestId("message-item")).toHaveClass("speaker-card", "speaker-owner");

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Retry" }));
    });

    await waitFor(() => expect(postMessage).toHaveBeenCalledTimes(2));
    expect(keys[0]).toMatch(/^[0-9a-f-]{36}$/);
    expect(keys[1]).toBe(keys[0]);
    await waitFor(() => expect(screen.queryByTestId("message-item")).toBeNull());
    expect(delivered.map((m) => m.id)).toEqual([msg(1).id]);
  });

  it("derives sending from the outbox and clears it after delivery", async () => {
    const user = userEvent.setup();
    let resolvePost!: (message: Message) => void;
    const postMessage = vi.fn(() => new Promise<Message>((resolve) => {
      resolvePost = resolve;
    }));
    render(<Harness postMessage={postMessage} delivered={[]} />);
    await user.type(screen.getByTestId("composer-input"), "hello{Enter}");
    expect(screen.getByRole("status")).toHaveTextContent("Sending…");
    expect(screen.getByTestId("composer-input").closest("form")).toHaveAttribute("data-state", "sending");

    await act(async () => {
      resolvePost(msg(1, ROOM_A, "hello"));
    });

    await waitFor(() => {
      expect(screen.getByTestId("composer-input").closest("form")).toHaveAttribute("data-state", "default");
    });
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
  });

  it("keeps one composer live region through state changes", () => {
    const { rerender } = render(<Composer onSend={() => {}} />);
    expect(screen.getAllByRole("status")).toHaveLength(1);
    rerender(<Composer onSend={() => {}} sending />);
    expect(screen.getAllByRole("status")).toHaveLength(1);
    rerender(<Composer onSend={() => {}} deliveryError />);
    expect(screen.getAllByRole("status")).toHaveLength(1);
  });

  it("uses a fresh idempotency key for each new message", async () => {
    const user = userEvent.setup();
    const keys: string[] = [];
    let seq = 0;
    const postMessage = vi.fn(async (_r: string, text: string, key: string) => {
      keys.push(key);
      seq += 1;
      return msg(seq, ROOM_A, text);
    });
    render(<Harness postMessage={postMessage} delivered={[]} />);
    const input = screen.getByTestId("composer-input");
    await user.type(input, "one{Enter}");
    await user.type(input, "two{Enter}");
    await waitFor(() => expect(keys).toHaveLength(2));
    expect(keys[0]).not.toBe(keys[1]);
  });
});
