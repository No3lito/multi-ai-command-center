import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { senderStyle } from "./senderStyle";

const css = readFileSync(new URL("../app/tokens.css", import.meta.url), "utf8");

function section(start: string): string {
  const i = css.indexOf(start);
  expect(i).toBeGreaterThan(-1);
  return css.slice(i, css.indexOf("}", i));
}
const dark = section(":root {");
const light = section(':root[data-theme="light"] {');
const lightMedia = section(':root:not([data-theme="dark"]) {');

function token(block: string, name: string): string {
  const m = new RegExp(`${name}:\\s*(#[0-9a-fA-F]{6})`).exec(block);
  expect(m, name).not.toBeNull();
  return m![1]!;
}

function luminance(hex: string): number {
  const n = parseInt(hex.slice(1), 16);
  const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  }) as [number, number, number];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
export function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

describe("tokens.css", () => {
  it("holds the spec values", () => {
    expect(css).toMatch(/--page-pad: 24px/);
    expect(css).toMatch(/--radius-card: 12px/);
    expect(css).toMatch(/--radius-control: 8px/);
    expect(css).toMatch(/--lh-body: 24px/);
    expect(token(dark, "--bg")).toBe("#0f1115");
    expect(token(light, "--panel-2")).toBe("#f0f2f5");
    expect(token(dark, "--accent")).toBe("#5b8def");
  });

  it("keeps the light theme identical for the media query and the data attribute", () => {
    for (const name of ["--bg", "--sidebar", "--panel", "--panel-2", "--border", "--text", "--muted", "--disabled"]) {
      expect(token(lightMedia, name)).toBe(token(light, name));
    }
  });

  it("meets contrast for text in both themes", () => {
    for (const theme of [dark, light]) {
      for (const text of ["--text", "--muted"]) {
        for (const surface of ["--bg", "--panel", "--panel-2"]) {
          expect(contrast(token(theme, text), token(theme, surface)), `${text} on ${surface}`).toBeGreaterThanOrEqual(4.5);
        }
      }
    }
  });

  it("keeps the filled accent label readable and accent text readable on light cards", () => {
    expect(contrast(token(dark, "--accent-fg"), token(dark, "--accent"))).toBeGreaterThanOrEqual(4.5);
    expect(contrast(token(light, "--accent-ink"), token(light, "--panel"))).toBeGreaterThanOrEqual(4.5);
  });

  it("keeps agent dots visible against dark cards (3:1)", () => {
    for (const who of ["Claude", "GPT", "Grok"]) {
      const color = senderStyle({ kind: "agent", display_name: who }).color;
      expect(contrast(color, token(dark, "--panel")), who).toBeGreaterThanOrEqual(3);
    }
  });

  it("leaves agent colors unchanged", () => {
    expect(senderStyle({ kind: "agent", display_name: "Claude" }).color).toBe("#E8955A");
    expect(senderStyle({ kind: "agent", display_name: "GPT" }).color).toBe("#34C79A");
    expect(senderStyle({ kind: "agent", display_name: "Grok" }).color).toBe("#A78BFA");
    expect(senderStyle({ kind: "owner", display_name: "Noel" }).color).toBe("#4C9AFF");
  });
});
