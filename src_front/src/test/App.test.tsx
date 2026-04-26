import { describe, it, expect } from "vitest";

describe("App", () => {
  it("is importable", async () => {
    const mod = await import("../App");
    expect(mod.default).toBeDefined();
  });
});
