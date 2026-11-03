import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { CLAUDE_ID, GPT_ID } from "@/test/fixtures";
import { Composer, type MentionAgent } from "./Composer";

const AGENTS: MentionAgent[] = [
  { id: CLAUDE_ID, display_name: "Claude", detail: "anthropic / claude-sonnet-5-5" },
  { id: GPT_ID, display_name: "GPT", detail: "openai / gpt-5" },
];

function setup() {
  const onSend = vi.fn();
  const user = userEvent.setup();
  render(<Composer onSend={onSend} roomName="General" agents={AGENTS} />);
  return { onSend, user, input: screen.getByTestId("composer-input") };
}

describe("Composer mentions", () => {
  it("shows the hint", () => {
    setup();
    expect(screen.getByText(/Claude will reply\./)).toBeInTheDocument();
  });

  it("opens an autocomplete on @ and filters as you type", async () => {
    const { user, input } = setup();
    await user.type(input, "@");
    expect(screen.getAllByTestId("mention-option")).toHaveLength(2);
    await user.type(input, "g");
    const opts = screen.getAllByTestId("mention-option");
    expect(opts).toHaveLength(1);
    expect(opts[0]).toHaveTextContent("@GPT");
  });

  it("navigates with arrows and picks with Enter without sending", async () => {
    const { user, input, onSend } = setup();
    await user.type(input, "hi @");
    expect(screen.getAllByTestId("mention-option")[0]).toHaveAttribute("aria-selected", "true");
    await user.keyboard("{ArrowDown}");
    expect(screen.getAllByTestId("mention-option")[1]).toHaveAttribute("aria-selected", "true");
    await user.keyboard("{Enter}");
    expect(onSend).not.toHaveBeenCalled();
    expect(input).toHaveValue("hi @GPT ");
    expect(screen.queryByTestId("mention-option")).toBeNull();
  });

  it("picks with Tab, closes with Esc, and sends the mentioned ids", async () => {
    const { user, input, onSend } = setup();
    await user.type(input, "@cl");
    await user.keyboard("{Tab}");
    expect(input).toHaveValue("@Claude ");
    await user.type(input, "and @");
    expect(screen.getAllByTestId("mention-option")).toHaveLength(2);
    await user.keyboard("{Escape}");
    expect(screen.queryByTestId("mention-option")).toBeNull();
    await user.type(input, "{Backspace}hello{Enter}");
    expect(onSend).toHaveBeenCalledWith("@Claude and hello", [CLAUDE_ID]);
  });

  it("drops a mention whose @DisplayName was removed from the text, and matches case-insensitively", async () => {
    const { user, input, onSend } = setup();
    await user.click(screen.getByRole("button", { name: "No one (note)" }));
    await user.type(input, "@Cl");
    await user.keyboard("{Enter}");
    await user.clear(input);
    await user.type(input, "ask @gpt please");
    await user.keyboard("{Escape}");
    await user.click(screen.getByTestId("composer-send"));
    expect(onSend).toHaveBeenCalledWith("ask @gpt please", [GPT_ID]);
  });

  it("picks an option with the mouse", async () => {
    const { user, input } = setup();
    await user.type(input, "@");
    await user.click(screen.getAllByTestId("mention-option")[1]!);
    expect(input).toHaveValue("@GPT ");
  });
});

describe("Send to", () => {
  it("sends to Claude by default, so a plain message gets an answer", async () => {
    window.localStorage.clear();
    const { user, input, onSend } = setup();
    expect(screen.getByRole("button", { name: "Claude" })).toHaveAttribute("aria-pressed", "true");
    await user.type(input, "what do you think?{Enter}");
    expect(onSend).toHaveBeenCalledWith("what do you think?", [CLAUDE_ID]);
  });

  it("sends to the agent picked, to everyone, or to no one, and remembers the choice", async () => {
    window.localStorage.clear();
    const { user, input, onSend } = setup();
    await user.click(screen.getByRole("button", { name: "GPT" }));
    expect(input).toHaveAttribute("placeholder", "Message GPT…");
    await user.type(input, "one{Enter}");
    expect(onSend).toHaveBeenLastCalledWith("one", [GPT_ID]);
    await user.click(screen.getByRole("button", { name: "Everyone" }));
    await user.type(input, "two{Enter}");
    expect(onSend).toHaveBeenLastCalledWith("two", [CLAUDE_ID, GPT_ID]);
    await user.click(screen.getByRole("button", { name: "No one (note)" }));
    expect(screen.getByText(/Nobody replies to a note\./)).toBeInTheDocument();
    await user.type(input, "three{Enter}");
    expect(onSend).toHaveBeenLastCalledWith("three", []);
    expect(window.localStorage.getItem("composer-send-to")).toBe("none");
  });

  it("still adds an agent @mentioned in the text", async () => {
    window.localStorage.clear();
    const { user, input, onSend } = setup();
    await user.type(input, "@GP");
    await user.keyboard("{Enter}");
    await user.type(input, "and you{Enter}");
    expect(onSend).toHaveBeenLastCalledWith("@GPT and you", [CLAUDE_ID, GPT_ID]);
  });
});
