import { describe, expect, it } from "vitest";
import { CHANNELS } from "@/lib/channels";

// Values read from Instagram's own production stylesheet, not eyeballed.
describe("the Instagram theme uses Instagram's real colours", () => {
  const ig = CHANNELS.find((c) => c.id === "instagram").theme;
  it("sends a flat #4A5DF9 bubble and receives #F3F5F7", () => {
    expect(ig.out.toLowerCase()).toBe("#4a5df9");
    expect(ig.in.toLowerCase()).toBe("#f3f5f7");
  });
  it("keeps the dark values and the 12px bubble corner", () => {
    expect(ig.darkIn.toLowerCase()).toBe("#25292e");
    expect(ig.darkBg.toLowerCase()).toBe("#0c1014");
    expect(ig.bubbleRadius).toBe(12);
  });
  it("uses black primary and #737373 secondary text", () => {
    expect(ig.headerText).toBe("#000000");
    expect(ig.secondaryText).toBe("#737373");
  });
});
