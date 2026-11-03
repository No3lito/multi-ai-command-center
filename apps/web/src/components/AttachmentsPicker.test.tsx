import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import type { FilesListing } from "@/lib/types";
import { AttachmentsPicker, type PickedFile } from "./AttachmentsPicker";

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
