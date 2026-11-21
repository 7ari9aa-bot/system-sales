import { describe, expect, it } from "vitest";
import { COMMENT_SORTS, sortComments } from "@/lib/facebookApi";

const c = (id, at, replies = []) => ({ id, commentedAt: at, replies });
const list = [c("a", "2026-11-21T08:00:00Z"), c("b", "2026-11-21T09:00:00Z"), c("c", "2026-11-21T07:00:00Z")];

describe("sortComments", () => {
  it("offers the three choices Facebook lists, newest and oldest working on our own data", () => {
    expect(COMMENT_SORTS.map((s) => s.id)).toEqual(["relevant", "newest", "all"]);
  });
  it("newest puts the latest comment first", () => {
    expect(sortComments(list, "newest").map((x) => x.id)).toEqual(["b", "a", "c"]);
  });
  it("oldest-first ('all comments') puts the earliest first", () => {
    expect(sortComments(list, "all").map((x) => x.id)).toEqual(["c", "a", "b"]);
  });
  it("relevant keeps Facebook's own order, which is oldest first from the Graph API", () => {
    expect(sortComments(list, "relevant").map((x) => x.id)).toEqual(["a", "b", "c"]);
  });
  it("does not mutate its input and keeps replies under their parent", () => {
    const withReply = [c("p", "2026-11-21T08:00:00Z", [c("r1", "2026-11-21T08:30:00Z"), c("r0", "2026-11-21T08:10:00Z")])];
    const out = sortComments(withReply, "newest");
    expect(out[0].replies.map((x) => x.id)).toEqual(["r1", "r0"]);
    expect(withReply[0].replies.map((x) => x.id)).toEqual(["r1", "r0"]);
  });
  it("tolerates empty, missing dates and unknown sort ids", () => {
    expect(sortComments(null, "newest")).toEqual([]);
    expect(sortComments([c("x", null), c("y", "2026-11-21T08:00:00Z")], "newest").map((x) => x.id)).toEqual(["y", "x"]);
    expect(sortComments(list, "nonsense").map((x) => x.id)).toEqual(["a", "b", "c"]);
  });
});
