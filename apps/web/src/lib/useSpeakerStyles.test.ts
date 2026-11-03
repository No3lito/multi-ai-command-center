import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useSpeakerStyles } from "./useSpeakerStyles";

describe("useSpeakerStyles", () => {
  it("reuses the allocation for fresh arrays containing identical metadata", () => {
    const { result, rerender } = renderHook(
      ({ name }) => useSpeakerStyles([
        { id: "claude", kind: "agent", display_name: name },
      ]),
      { initialProps: { name: "Claude" } },
    );
    const first = result.current;
    rerender({ name: "Claude" });
    expect(result.current).toBe(first);
    expect(first.size).toBe(1);
    expect(first.has("owner:pending-owner")).toBe(false);
  });

  it("adds a fallback owner only when delivery is pending", () => {
    const { result, rerender } = renderHook(
      ({ pending }) => useSpeakerStyles([], pending),
      { initialProps: { pending: false } },
    );
    expect(result.current.size).toBe(0);
    rerender({ pending: true });
    expect(result.current.get("owner:pending-owner")?.color).toBe("var(--speaker-owner)");
  });

  it("uses the real human for pending delivery when one is known", () => {
    const { result } = renderHook(() => useSpeakerStyles([
      { id: "noel", kind: "owner", display_name: "Noel" },
    ], true));
    expect(result.current.size).toBe(1);
    expect(result.current.has("owner:noel")).toBe(true);
    expect(result.current.has("owner:pending-owner")).toBe(false);
  });

  it("preserves allocations when another identity arrives", () => {
    const { result, rerender } = renderHook(
      ({ second }) => useSpeakerStyles([
        { id: "first", kind: "agent", display_name: "First" },
        ...(second ? [{ id: "second", kind: "agent", display_name: "Second" }] : []),
      ]),
      { initialProps: { second: false } },
    );
    const first = result.current.get("agent:first");
    rerender({ second: true });
    expect(result.current.get("agent:first")).toEqual(first);
    expect(result.current.get("agent:second")?.color).not.toBe(first?.color);
  });
});
