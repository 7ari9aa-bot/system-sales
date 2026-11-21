import { describe, expect, it } from "vitest";
import { groupNotifications, NEW_WINDOW_MS, FIRST_SHOWN } from "@/pages/facebook/notificationGroups";

const NOW = new Date("2026-11-21T12:00:00Z").getTime();
const hoursAgo = (h) => new Date(NOW - h * 3600_000).toISOString();
const item = (id, h, waiting = false) => ({ comment: { id, commentedAt: hoursAgo(h) }, post: { id: "p" }, waiting });

describe("Notifications grouped the way Facebook lists them", () => {
  it("puts what is recent under 'new' and the rest under 'earlier', newest first", () => {
    const g = groupNotifications([item("old", 80), item("a", 2), item("b", 1)], { now: NOW });
    expect(g.fresh.map((x) => x.comment.id)).toEqual(["b", "a"]);
    expect(g.earlier.map((x) => x.comment.id)).toEqual(["old"]);
  });

  it("'recent' is the last day: 23h is new, 25h is earlier", () => {
    expect(NEW_WINDOW_MS).toBe(24 * 3600_000);
    const g = groupNotifications([item("in", 23), item("out", 25)], { now: NOW });
    expect(g.fresh.map((x) => x.comment.id)).toEqual(["in"]);
    expect(g.earlier.map((x) => x.comment.id)).toEqual(["out"]);
  });

  it("the Unread tab keeps only comments still waiting for an answer, in both groups", () => {
    const rows = [item("a", 1, true), item("b", 2, false), item("c", 50, true), item("d", 60, false)];
    const g = groupNotifications(rows, { now: NOW, onlyUnread: true });
    expect(g.fresh.map((x) => x.comment.id)).toEqual(["a"]);
    expect(g.earlier.map((x) => x.comment.id)).toEqual(["c"]);
  });

  it("shows a first batch and holds the rest behind 'See previous notifications'", () => {
    const many = Array.from({ length: FIRST_SHOWN + 7 }, (_, i) => item(`o${i}`, 30 + i));
    const g = groupNotifications(many, { now: NOW });
    expect(g.earlier).toHaveLength(FIRST_SHOWN);
    expect(g.hiddenCount).toBe(7);
    const all = groupNotifications(many, { now: NOW, showAll: true });
    expect(all.earlier).toHaveLength(FIRST_SHOWN + 7);
    expect(all.hiddenCount).toBe(0);
  });

  it("new ones are never held back, only the older ones are", () => {
    const fresh = Array.from({ length: FIRST_SHOWN + 3 }, (_, i) => item(`n${i}`, 1 + i / 100));
    const g = groupNotifications(fresh, { now: NOW });
    expect(g.fresh).toHaveLength(FIRST_SHOWN + 3);
  });

  it("a comment with no time counts as earlier, and nothing yields empty groups", () => {
    const g = groupNotifications([{ comment: { id: "x" }, post: { id: "p" }, waiting: false }], { now: NOW });
    expect(g.earlier).toHaveLength(1);
    expect(groupNotifications([], { now: NOW })).toEqual({ fresh: [], earlier: [], hiddenCount: 0 });
  });
});
