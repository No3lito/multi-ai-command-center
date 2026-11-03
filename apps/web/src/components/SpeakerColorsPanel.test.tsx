import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { reloadSpeakerColors } from "@/lib/speakerColors";
import { senderStyle } from "@/lib/senderStyle";
import { SpeakerColorsPanel } from "./SpeakerColorsPanel";

function row(speaker: string) {
  return screen.getAllByTestId("speaker-color-row").find((r) => r.dataset.speaker === speaker)!;
}
function swatch(speaker: string, color: string) {
  return within(row(speaker)).getAllByTestId("speaker-color-swatch").find((b) => b.dataset.color === color)!;
}
const cssVar = (key: string) => document.documentElement.style.getPropertyValue(`--speaker-${key}`);

describe("Speaker colors", () => {
  beforeEach(() => {
    window.localStorage.clear();
    reloadSpeakerColors();
  });

  it("starts with the default colors and lists Claude, ChatGPT, Grok, Grok Bot and You", () => {
    render(<SpeakerColorsPanel />);
    expect(screen.getAllByTestId("speaker-color-row").map((r) => r.dataset.speaker)).toEqual([
      "claude",
      "gpt",
      "grok",
      "grokbot",
      "owner",
    ]);
    expect(swatch("claude", "orange")).toHaveAttribute("aria-checked", "true");
    expect(cssVar("claude")).toBe("var(--swatch-orange)");
  });

  it("picks a color, applies it, and remembers it", async () => {
    const user = userEvent.setup();
    render(<SpeakerColorsPanel />);
    await user.click(swatch("claude", "pink"));
    expect(swatch("claude", "pink")).toHaveAttribute("aria-checked", "true");
    expect(cssVar("claude")).toBe("var(--swatch-pink)");
    expect(JSON.parse(window.localStorage.getItem("speaker-colors")!).colors.claude).toBe("pink");
  });

  it("grays out a color another speaker already uses", () => {
    render(<SpeakerColorsPanel />);
    expect(swatch("claude", "green")).toBeDisabled();
    expect(swatch("claude", "green")).toHaveAccessibleName("Green (used by ChatGPT)");
  });

  it("locking hides the choices so the color can't change; unlocking brings them back", async () => {
    const user = userEvent.setup();
    render(<SpeakerColorsPanel />);
    const lock = within(row("gpt")).getByTestId("speaker-color-lock");
    await user.click(lock);
    expect(lock).toHaveAttribute("aria-pressed", "true");
    expect(lock).toHaveTextContent("Locked");
    expect(within(row("gpt")).queryAllByTestId("speaker-color-swatch")).toHaveLength(0);
    await user.click(lock);
    expect(within(row("gpt")).getAllByTestId("speaker-color-swatch")).toHaveLength(10);
  });

  it("reset puts unlocked speakers back and leaves locked ones alone", async () => {
    const user = userEvent.setup();
    render(<SpeakerColorsPanel />);
    await user.click(swatch("claude", "red"));
    await user.click(swatch("owner", "teal"));
    await user.click(within(row("owner")).getByTestId("speaker-color-lock"));
    await user.click(screen.getByTestId("colors-reset"));
    expect(cssVar("claude")).toBe("var(--swatch-orange)");
    expect(cssVar("owner")).toBe("var(--swatch-teal)");
  });

  it("Grok and Grok Bot have their own color", () => {
    expect(senderStyle({ kind: "agent", display_name: "Grok" }).color).toBe("var(--speaker-grok)");
    expect(senderStyle({ kind: "external", display_name: "Grok Bot" }).color).toBe("var(--speaker-grokbot)");
  });
});
