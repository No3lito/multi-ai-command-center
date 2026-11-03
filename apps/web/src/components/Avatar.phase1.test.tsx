import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import * as senderStyles from "@/lib/senderStyle";
import { Avatar } from "./Avatar";

describe("Avatar speaker tokens", () => {
  it("passes the CSS-variable color through the shared tint helper", () => {
    const style = senderStyles.senderStyle({
      kind: "agent",
      display_name: "Claude",
    });
    const tint = vi.spyOn(senderStyles, "tint");
    try {
      const { container } = render(<Avatar style={style} label="Claude" />);
      expect(tint).toHaveBeenCalledWith(style.color, expect.any(Number));
      expect(screen.getByText("C")).toBeInTheDocument();
      expect(container.innerHTML).not.toContain("NaN");
    } finally {
      tint.mockRestore();
    }
  });
});
