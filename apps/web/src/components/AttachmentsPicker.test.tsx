import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import type { FilesListing } from "@/lib/types";
import { AttachmentsPicker, folderLabel, selectedIn, type PickedFile } from "./AttachmentsPicker";

const ROOT: FilesListing = {
  enabled: true,
  path: "",
  max_files: 10,
  max_chars: 300_000,
  entries: [
    { name: "logs", path: "logs", type: "dir", size: null, readable: false },
    { name: "README.md", path: "README.md", type: "file", size: 2048, readable: true },
    { name: "chart.png", path: "chart.png", type: "file", size: 9000, readable: false },
  ],
};
const LOGS: FilesListing = {
  ...ROOT,
  path: "logs",
  entries: [
    { name: "LEARNING-LOG-full.md", path: "logs/LEARNING-LOG-full.md", type: "file", size: 400_000, readable: true },
  ],
};

function Harness({ listFiles }: { listFiles: (p?: string) => Promise<FilesListing> }) {
  const [picked, setPicked] = useState<PickedFile[]>([]);
  return <AttachmentsPicker listFiles={listFiles} selected={picked} onChange={setPicked} />;
}

describe("AttachmentsPicker", () => {
  it("hides itself when no shared folder is configured", async () => {
    const listFiles = vi.fn(async () => ({ ...ROOT, enabled: false, entries: [] }));
    const { container } = render(<Harness listFiles={listFiles} />);
    await waitFor(() => expect(listFiles).toHaveBeenCalled());
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("browses folders, picks text files only, and warns when over the limit", async () => {
    const user = userEvent.setup();
    const listFiles = vi.fn(async (p?: string) => (p === "logs" ? LOGS : ROOT));
    render(<Harness listFiles={listFiles} />);
    await user.click(await screen.findByTestId("attachments-toggle"));
    const boxes = await screen.findAllByTestId("attachment-checkbox");
    expect(boxes[1]).toBeDisabled(); // chart.png is not a text file
    await user.click(boxes[0]!); // README.md
    expect(screen.getAllByTestId("attachment-chip")[0]).toHaveTextContent("README.md");
    expect(screen.getByTestId("attachments-estimate")).toHaveTextContent("About 512 tokens");
    await user.click(screen.getByText("logs/"));
    await user.click(await screen.findByTestId("attachment-checkbox"));
    expect(screen.getAllByTestId("attachment-chip")).toHaveLength(2);
    expect(screen.getByTestId("attachments-estimate")).toHaveTextContent("over the 300,000-character limit");
  });
});

describe("selected files are easy to see", () => {
  const P = "01-PROJECTS/trading/meme-coin-strategy";
  const picked = [
    { path: `${P}/sources/trading-review/FROZEN-SPECS.md`, size: 1024, suggested: ["h123"] },
    { path: `${P}/sources/trading-review/README.md`, size: 512 },
  ];

  it("labels folders in plain words and counts selections per folder", () => {
    expect(folderLabel(picked[0]!.path)).toBe("meme-coin-strategy › sources › trading-review");
    expect(folderLabel("README.md")).toBe("workspace");
    expect(selectedIn(picked, `${P}/sources`)).toBe(2);
    expect(selectedIn(picked, "01-PROJECTS/trading/trading-desk")).toBe(0);
  });

  it("lists every selected file by name and folder, and badges folders that contain them", async () => {
    const user = userEvent.setup();
    const listFiles = vi.fn(async () => ({
      enabled: true,
      path: P,
      entries: [{ name: "sources", path: `${P}/sources`, type: "dir" as const, size: null, readable: false }],
      max_files: 10,
      max_chars: 300_000,
    }));
    render(<AttachmentsPicker listFiles={listFiles} selected={picked} onChange={() => {}} />);
    expect(await screen.findByTestId("attachments-selected-title")).toHaveTextContent("Selected (2)");
    const chips = screen.getAllByTestId("attachment-chip");
    expect(chips[0]).toHaveTextContent("FROZEN-SPECS.md");
    expect(chips[0]).toHaveTextContent("in meme-coin-strategy › sources › trading-review");
    await user.click(screen.getByTestId("attachments-toggle"));
    expect(await screen.findByTestId("folder-selected")).toHaveTextContent("2 selected");
  });
});

it("opens in the room's project folder", async () => {
  const listFiles = vi.fn(async () => ({
    enabled: true,
    path: "01-PROJECTS/x/y",
    entries: [],
    max_files: 10,
    max_chars: 1000,
  }));
  render(<AttachmentsPicker listFiles={listFiles} selected={[]} onChange={() => {}} startPath="01-PROJECTS/x/y" />);
  await waitFor(() => expect(listFiles).toHaveBeenCalledWith("01-PROJECTS/x/y", expect.anything()));
});
