import { describe, expect, it } from "vitest";
import { formatUsd } from "./format";

describe("formatUsd", () => {
  it("uses 4 decimals for small amounts and 2 for whole cents", () => {
    expect(formatUsd(0.0123)).toBe("$0.0123");
    expect(formatUsd(0.5)).toBe("$0.50");
    expect(formatUsd(10)).toBe("$10.00");
    expect(formatUsd(0)).toBe("$0.00");
    expect(formatUsd(0.00001)).toBe("<$0.0001");
    expect(formatUsd(1.2345)).toBe("$1.23");
  });
});
