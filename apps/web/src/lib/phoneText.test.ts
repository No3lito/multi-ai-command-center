import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

// vitest runs from apps/web.
const read = (p: string) => readFileSync(resolve(process.cwd(), p), "utf8");

describe("phone body text", () => {
  it("is 16px below 768px", () => {
    expect(read("src/app/tokens.css")).toMatch(/--text-body-phone:\s*16px/);
    const globals = read("src/app/globals.css");
    expect(globals).toMatch(/@media \(max-width: 767px\) \{\s*body \{\s*font-size: var\(--text-body-phone\);/);
  });
});
