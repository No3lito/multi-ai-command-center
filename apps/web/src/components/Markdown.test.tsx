import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { Folded, Markdown, isLong } from "./Markdown";

describe("Markdown", () => {
  it("renders bold, lists and tables instead of raw symbols", () => {
    const { container } = render(
      <Markdown text={"**Bottom line:** go\n\n- one\n- two\n\n| a | b |\n|---|---|\n| 1 | 2 |"} />,
    );
    expect(container.querySelector("strong")).toHaveTextContent("Bottom line:");
    expect(container.querySelectorAll("li")).toHaveLength(2);
    expect(container.querySelector("table")).toBeInTheDocument();
    expect(container.textContent).not.toContain("**");
  });

  it("never renders HTML, scripts or unsafe links, and shows images as text", () => {
    const { container } = render(
      <Markdown
        text={
          "<script>alert(1)</script>\n\n[bad](javascript:alert(1)) [ok](https://x.com) ![pic](https://x.com/a.png) <b>hi</b>"
        }
      />,
    );
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("b")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(container).toHaveTextContent("<script>alert(1)</script>");
    const links = [...container.querySelectorAll("a")].map((a) => a.getAttribute("href"));
    expect(links).toEqual(["https://x.com"]);
    expect(screen.getByText("[image: pic]")).toBeInTheDocument();
  });

  it("folds long answers behind Show more", async () => {
    const user = userEvent.setup();
    const long = Array.from({ length: 20 }, (_, i) => `line ${i}`).join("\n");
    expect(isLong(long)).toBe(true);
    expect(isLong("short")).toBe(false);
    render(
      <Folded text={long}>
        <Markdown text={long} />
      </Folded>,
    );
    expect(screen.getByTestId("folded")).toHaveAttribute("data-open", "false");
    await user.click(screen.getByTestId("fold-toggle"));
    expect(screen.getByTestId("folded")).toHaveAttribute("data-open", "true");
    expect(screen.getByTestId("fold-toggle")).toHaveTextContent("Show less");
  });
});
