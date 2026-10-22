import { describe, expect, it } from "vitest";
import { clearedIfStill, createScanQueue } from "./scanQueue";

describe("scan queue", () => {
  it("runs lookups strictly in order even when the first answers last", async () => {
    const q = createScanQueue();
    const seen = [];
    const slow = () => new Promise((r) => setTimeout(() => { seen.push("A"); r(); }, 30));
    const fast = async () => { seen.push("B"); };
    q.push(slow);
    await q.push(fast);
    expect(seen).toEqual(["A", "B"]);
  });
  it("a failing lookup does not block the next one", async () => {
    const q = createScanQueue();
    const seen = [];
    q.push(async () => { throw new Error("network"); });
    await q.push(async () => { seen.push("B"); });
    expect(seen).toEqual(["B"]);
  });
});

describe("clearedIfStill", () => {
  it("clears the field when it still holds the handled code", () => {
    expect(clearedIfStill("6301", "6301")).toBe("");
    expect(clearedIfStill(" 6301 ", "6301")).toBe("");
  });
  it("keeps a newer code typed while the lookup was running", () => {
    expect(clearedIfStill("6302", "6301")).toBe("6302");
  });
});
