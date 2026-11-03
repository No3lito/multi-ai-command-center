import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import * as senderStyles from "@/lib/senderStyle";
import { Avatar } from "./Avatar";

describe("Avatar speaker tokens", () => {
  it("paints the speaker's CSS-variable color without broken values", () => {
    const style = senderStyles.senderStyle({
      kind: "agent",
      display_name: "Claude",
    });
    const { container } = render(<Avatar style={style} label="Claude" />);
    expect(screen.getByTestId("avatar").style.background).toBe(style.color);
    expect(screen.getByText("C")).toBeInTheDocument();
    expect(container.innerHTML).not.toContain("NaN");
  });
});
