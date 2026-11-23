import { describe, expect, it } from "vitest";
import { instagramGroup } from "./igGroup";

const msg = (side, iso, extra = {}) => ({ id: `${side}-${iso}`, side, createdAt: iso, senderType: "customer", ...extra });

describe("instagramGroup", () => {
  it("joins two messages from the same side within a minute", () => {
    const list = [msg("in", "2026-11-23T10:00:00Z"), msg("in", "2026-11-23T10:00:30Z"), msg("in", "2026-11-23T10:05:00Z")];
    expect(instagramGroup(list, 0)).toMatchObject({ first: true, last: false, size: 2 });
    expect(instagramGroup(list, 1)).toMatchObject({ first: false, last: true, size: 2 });
    expect(instagramGroup(list, 2)).toMatchObject({ first: true, last: true, alone: true });
  });

  it("never joins the two sides", () => {
    const list = [msg("in", "2026-11-23T10:00:00Z"), msg("out", "2026-11-23T10:00:10Z")];
    expect(instagramGroup(list, 0).last).toBe(true);
    expect(instagramGroup(list, 1).first).toBe(true);
  });

  it("breaks the run on a system line or a missing timestamp", () => {
    const list = [msg("in", "2026-11-23T10:00:00Z"), msg("in", "", { senderType: "system" }), msg("in", "2026-11-23T10:00:20Z", { createdAt: null })];
    expect(instagramGroup(list, 0).last).toBe(true);
    expect(instagramGroup(list, 2)).toMatchObject({ first: true, last: true });
  });

  it("handles an empty list", () => {
    expect(instagramGroup([], 0)).toMatchObject({ first: true, last: true, size: 1 });
  });
});
