import { describe, expect, it } from "vitest";
import { COMMENTS_PER_STEP, commentWindow } from "@/lib/facebookApi";

/**
 * Facebook shows a post's first few comments and a "View more comments" line that opens the next
 * few. The whole thread is already here (the server follows every page of it), so this only decides
 * how much of it to draw.
 */
const make = (n) => Array.from({ length: n }, (_, i) => ({ id: `c${i}`, replies: [] }));

describe("commentWindow", () => {
  it("shows everything when the thread is short, with nothing more to open", () => {
    const w = commentWindow(make(3), 0);
    expect(w.shown).toHaveLength(3);
    expect(w.hidden).toBe(0);
  });

  it("shows the first step and counts what is left", () => {
    const w = commentWindow(make(23), 0);
    expect(w.shown).toHaveLength(COMMENTS_PER_STEP);
    expect(w.hidden).toBe(23 - COMMENTS_PER_STEP);
  });

  it("opens one more step each time, then stops at the end", () => {
    const list = make(23);
    expect(commentWindow(list, 1).shown).toHaveLength(COMMENTS_PER_STEP * 2);
    const all = commentWindow(list, 10);
    expect(all.shown).toHaveLength(23);
    expect(all.hidden).toBe(0);
  });

  it("keeps the newest comments at the end of what is shown, as Facebook does", () => {
    const w = commentWindow(make(12), 0);
    expect(w.shown.map((c) => c.id)).toEqual(make(12).slice(-COMMENTS_PER_STEP).map((c) => c.id));
  });

  it("copes with no comments at all", () => {
    expect(commentWindow(undefined, 0)).toEqual({ shown: [], hidden: 0, next: 0 });
  });

  it("says how many the next click opens, never more than are left", () => {
    expect(commentWindow(make(23), 0).next).toBe(COMMENTS_PER_STEP);
    expect(commentWindow(make(23), 1).next).toBe(COMMENTS_PER_STEP); // 13 still folded, a click opens 5
    expect(commentWindow(make(23), 3).next).toBe(3); // 3 left: opens just those
    expect(commentWindow(make(23), 4).next).toBe(0); // nothing left
  });
});
