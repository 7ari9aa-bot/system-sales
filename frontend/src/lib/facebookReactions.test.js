import { describe, expect, it, vi } from "vitest";
import { REACTION_KINDS, REACTION_LABEL, fetchReactionBreakdown, topReactions } from "@/lib/facebookApi";
import { api } from "@/lib/api";

vi.mock("@/lib/api", () => ({ api: vi.fn(async () => ({ id: "1_2", total: 7, kinds: { LIKE: 4, LOVE: 3 } })) }));

/** Facebook's summary line: the few most-used kinds as small icons, then the total. */
describe("topReactions", () => {
  it("lists the kinds that have any, most used first, at most three", () => {
    const out = topReactions({ LIKE: 10, LOVE: 4, HAHA: 2, WOW: 7, SAD: 0, ANGRY: 1 });
    expect(out.map((r) => r.kind)).toEqual(["LIKE", "WOW", "LOVE"]);
    expect(out[0].count).toBe(10);
  });
  it("leaves out kinds nobody used", () => {
    expect(topReactions({ LIKE: 0, LOVE: 0 })).toEqual([]);
    expect(topReactions({ LIKE: 2, LOVE: 0 }).map((r) => r.kind)).toEqual(["LIKE"]);
  });
  it("breaks a tie in Facebook's own order", () => {
    expect(topReactions({ LIKE: 2, LOVE: 2, HAHA: 2 }).map((r) => r.kind)).toEqual(["LIKE", "LOVE", "HAHA"]);
  });
  it("copes with nothing at all", () => {
    expect(topReactions(undefined)).toEqual([]);
    expect(topReactions({})).toEqual([]);
  });
});

describe("the reaction kinds", () => {
  it("are Meta's six, in Facebook's order, each with an Arabic and an English name", () => {
    expect(REACTION_KINDS).toEqual(["LIKE", "LOVE", "HAHA", "WOW", "SAD", "ANGRY"]);
    for (const k of REACTION_KINDS) {
      expect(REACTION_LABEL[k].ar).toBeTruthy();
      expect(REACTION_LABEL[k].en).toBeTruthy();
    }
  });
});

describe("fetchReactionBreakdown", () => {
  it("reads one object's counts from the reactions route", async () => {
    const out = await fetchReactionBreakdown("111_9/x");
    expect(vi.mocked(api).mock.calls[0][0]).toBe("/facebook/objects/111_9%2Fx/reactions");
    expect(out).toEqual({ total: 7, kinds: { LIKE: 4, LOVE: 3 } });
  });
});
