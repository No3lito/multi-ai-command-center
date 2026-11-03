import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { WorkspaceInfo } from "@/lib/types";
import { familyLabel } from "@/lib/useWorkspace";
import { InboxPanel, ProjectPanel, projectTitle } from "./ProjectPanels";

const MEME = "01-PROJECTS/trading/meme-coin-strategy";
const DESK = "01-PROJECTS/trading/trading-desk";
const ws: WorkspaceInfo = {
  enabled: true,
  structured: true,
  families: ["agent-systems", "trading"],
  projects: [
    {
      path: MEME,
      family: "trading",
      slug: "meme-coin-strategy",
      title: "Meme coin strategy",
      status: "active",
      goal: "",
    },
    { path: DESK, family: "trading", slug: "trading-desk", title: "Trading desk", status: "paper", goal: "" },
  ],
  inbox: [{ name: "desk-notes.md", size: 10, suggested_project: DESK }],
};

describe("project panels", () => {
  it("labels families and finds project titles", () => {
    expect(familyLabel("agent-systems")).toBe("Agent systems");
    expect(projectTitle(ws, MEME)).toBe("Meme coin strategy");
    expect(projectTitle(ws, "01-PROJECTS/x/unknown")).toBe("unknown");
    expect(projectTitle(ws, null)).toBeNull();
  });

  it("files an inbox item into the suggested project with one click", async () => {
    const user = userEvent.setup();
    const onFile = vi.fn().mockResolvedValue(undefined);
    render(<InboxPanel workspace={ws} onFile={onFile} />);
    expect(screen.getByTestId("inbox-project")).toHaveValue(DESK);
    await user.click(screen.getByTestId("inbox-file"));
    expect(onFile).toHaveBeenCalledWith("desk-notes.md", DESK);
  });

  it("hides the inbox when it is empty or there is no workspace", () => {
    const { container } = render(<InboxPanel workspace={{ ...ws, inbox: [] }} onFile={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("links and unlinks the room's project", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn().mockResolvedValue(undefined);
    render(<ProjectPanel workspace={ws} projectPath={MEME} onChange={onChange} />);
    expect(screen.getByTestId("project-panel")).toHaveTextContent("save briefs, decisions and outputs into");
    await user.selectOptions(screen.getByTestId("project-select"), DESK);
    expect(onChange).toHaveBeenCalledWith(DESK);
    await user.selectOptions(screen.getByTestId("project-select"), "");
    expect(onChange).toHaveBeenLastCalledWith(null);
  });
});
