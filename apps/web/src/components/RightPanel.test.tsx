import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RightPanel } from "./RightPanel";

const KEY = "room-details-width";

function panel() {
  return render(
    <RightPanel open detail={null} status="connecting" lastSeq={0} hasRoom={false}>
      <p>Panel content</p>
    </RightPanel>,
  );
}

function viewport(width: number) {
  Object.defineProperty(window, "innerWidth", { configurable: true, value: width });
  act(() => { window.dispatchEvent(new Event("resize")); });
}

function handle() {
  return screen.getByRole("separator", { name: "Resize room details" });
}

class TestPointerEvent extends MouseEvent {
  readonly pointerId: number;

  constructor(type: string, init: PointerEventInit = {}) {
    super(type, init);
    this.pointerId = init.pointerId ?? 1;
  }
}

describe("resizable room details", () => {
  let originalWidth: number;

  beforeEach(() => {
    originalWidth = window.innerWidth;
    window.localStorage.clear();
    viewport(1440);
    vi.stubGlobal("PointerEvent", TestPointerEvent);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    viewport(originalWidth);
    window.localStorage.clear();
  });

  it("supports arrow keys and remembers the width after remounting", () => {
    const first = panel();
    expect(handle()).toHaveAttribute("aria-valuenow", "320");
    expect(handle()).toHaveAttribute("aria-orientation", "vertical");
    expect(handle()).toHaveAttribute("tabindex", "0");

    fireEvent.keyDown(handle(), { key: "ArrowLeft" });
    expect(handle()).toHaveAttribute("aria-valuenow", "330");
    fireEvent.keyDown(handle(), { key: "ArrowRight" });
    expect(window.localStorage.getItem(KEY)).toBe("320");
    fireEvent.keyDown(handle(), { key: "ArrowLeft" });
    first.unmount();

    panel();
    expect(handle()).toHaveAttribute("aria-valuenow", "330");
    expect(screen.getByRole("complementary")).toHaveStyle("--room-details-width: 330px");
  });

  it("drags the left edge and clamps both limits", () => {
    panel();
    const separator = handle();
    const capture = vi.fn();
    Object.defineProperty(separator, "setPointerCapture", { value: capture });

    fireEvent.pointerDown(separator, { pointerId: 7, button: 0, clientX: 1000 });
    expect(capture).toHaveBeenCalledWith(7);
    fireEvent.pointerMove(separator, { pointerId: 8, clientX: 900 });
    expect(separator).toHaveAttribute("aria-valuenow", "320");

    fireEvent.pointerMove(separator, { pointerId: 7, clientX: 900 });
    expect(separator).toHaveAttribute("aria-valuenow", "420");
    fireEvent.pointerMove(separator, { pointerId: 7, clientX: -1000 });
    expect(separator).toHaveAttribute("aria-valuenow", "864");
    fireEvent.pointerMove(separator, { pointerId: 7, clientX: 2000 });
    expect(separator).toHaveAttribute("aria-valuenow", "280");
    expect(window.localStorage.getItem(KEY)).toBe("280");

    fireEvent.pointerUp(separator, { pointerId: 7 });
    fireEvent.pointerMove(separator, { pointerId: 7, clientX: 500 });
    expect(separator).toHaveAttribute("aria-valuenow", "280");
  });

  it.each(["pointerCancel", "lostPointerCapture"] as const)("stops dragging on %s", (event) => {
    panel();
    const separator = handle();
    Object.defineProperty(separator, "setPointerCapture", { value: vi.fn() });
    fireEvent.pointerDown(separator, { pointerId: 1, button: 0, clientX: 1000 });
    fireEvent[event](separator, { pointerId: 1 });
    fireEvent.pointerMove(separator, { pointerId: 1, clientX: 800 });
    expect(separator).toHaveAttribute("aria-valuenow", "320");
  });

  it("clamps keyboard resizing at both limits", () => {
    window.localStorage.setItem(KEY, "280");
    const first = panel();
    fireEvent.keyDown(handle(), { key: "ArrowRight" });
    expect(handle()).toHaveAttribute("aria-valuenow", "280");
    first.unmount();

    window.localStorage.setItem(KEY, "864");
    panel();
    fireEvent.keyDown(handle(), { key: "ArrowLeft" });
    expect(handle()).toHaveAttribute("aria-valuenow", "864");
  });

  it("reclamps on viewport changes without overwriting the saved preference", () => {
    window.localStorage.setItem(KEY, "900");
    panel();
    expect(handle()).toHaveAttribute("aria-valuenow", "864");
    viewport(1280);
    expect(handle()).toHaveAttribute("aria-valuenow", "768");
    expect(handle()).toHaveAttribute("aria-valuemax", "768");
    viewport(1600);
    expect(handle()).toHaveAttribute("aria-valuenow", "900");
    expect(window.localStorage.getItem(KEY)).toBe("900");
  });

  it.each(["invalid", "Infinity", "", "NaN"])("ignores invalid stored width %j", (saved) => {
    window.localStorage.setItem(KEY, saved);
    panel();
    expect(handle()).toHaveAttribute("aria-valuenow", "320");
  });

  it("works when storage reads and writes throw", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("Storage blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("Storage blocked");
    });
    panel();
    fireEvent.keyDown(handle(), { key: "ArrowLeft" });
    expect(handle()).toHaveAttribute("aria-valuenow", "330");
  });

  it("keeps the drawer width and removes resizing below the desktop breakpoint", () => {
    window.localStorage.setItem(KEY, "600");
    viewport(390);
    panel();
    expect(screen.queryByRole("separator")).not.toBeInTheDocument();
    expect(screen.getByRole("complementary")).toHaveStyle("--room-details-width: 320px");
    expect(screen.getByText("Panel content")).toBeInTheDocument();

    viewport(1440);
    expect(handle()).toHaveAttribute("aria-valuenow", "600");
    viewport(1024);
    expect(screen.queryByRole("separator")).not.toBeInTheDocument();
    expect(window.localStorage.getItem(KEY)).toBe("600");
  });
});
