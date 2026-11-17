import { describe, expect, test } from "vitest";
import {
  badgeCount,
  isMuted,
  isMutedForever,
  isUnread,
  listTimestamp,
  matchesQuery,
  normalizeSearch,
  orderRows,
  tabCounts,
  visibleRows,
} from "./chatListState";

const row = (o) => ({ id: o.id, customer: "x", status: "waiting", unread: 0, ...o });

describe("mute", () => {
  const now = Date.parse("2026-11-17T10:00:00Z");
  test("a future date mutes, a past one does not, none does not", () => {
    expect(isMuted({ mutedUntil: "2026-11-17T18:00:00Z" }, now)).toBe(true);
    expect(isMuted({ mutedUntil: "2026-11-17T09:00:00Z" }, now)).toBe(false);
    expect(isMuted({ mutedUntil: null }, now)).toBe(false);
    expect(isMuted({ mutedUntil: "not a date" }, now)).toBe(false);
  });
  test("year 9999 is muted forever", () => {
    expect(isMutedForever({ mutedUntil: "9999-12-31T00:00:00Z" }, now)).toBe(true);
    expect(isMutedForever({ mutedUntil: "2026-11-17T18:00:00Z" }, now)).toBe(false);
  });
});

describe("unread", () => {
  test("a count or a manual mark makes a chat unread", () => {
    expect(isUnread(row({ id: 1, unread: 2 }))).toBe(true);
    expect(isUnread(row({ id: 1, markedUnread: true }))).toBe(true);
    expect(isUnread(row({ id: 1 }))).toBe(false);
  });
  test("a manual mark shows a dot, not a number", () => {
    expect(badgeCount(row({ id: 1, markedUnread: true }))).toBeNull();
    expect(badgeCount(row({ id: 1, unread: 3 }))).toBe(3);
  });
});

describe("search", () => {
  test("folds Arabic spelling variants and digits", () => {
    expect(normalizeSearch("أحمد")).toBe(normalizeSearch("احمد"));
    expect(normalizeSearch("مدرسة")).toBe(normalizeSearch("مدرسه"));
    expect(normalizeSearch("مُحَمَّد")).toBe(normalizeSearch("محمد"));
    expect(normalizeSearch("٠١٠٠١٢٣")).toBe("0100123");
  });
  test("finds a chat by name, phone or preview", () => {
    const r = row({ id: 1, customer: "أحمد علي", phone: "+20100123", preview: "السعر كام" });
    expect(matchesQuery(r, "احمد")).toBe(true);
    expect(matchesQuery(r, "٠١٠٠١٢٣")).toBe(true);
    expect(matchesQuery(r, "سعر")).toBe(true);
    expect(matchesQuery(r, "zzz")).toBe(false);
    expect(matchesQuery(r, "   ")).toBe(true);
  });
});

describe("ordering", () => {
  test("pinned first (newest pin first), the rest keep the server order", () => {
    const rows = [
      row({ id: "a" }),
      row({ id: "p1", pinnedAt: "2026-11-01T00:00:00Z" }),
      row({ id: "b" }),
      row({ id: "p2", pinnedAt: "2026-11-05T00:00:00Z" }),
    ];
    expect(orderRows(rows).map((r) => r.id)).toEqual(["p2", "p1", "a", "b"]);
  });
  test("does not mutate its input", () => {
    const rows = [row({ id: "a" }), row({ id: "p", pinnedAt: "2026-11-01T00:00:00Z" })];
    orderRows(rows);
    expect(rows.map((r) => r.id)).toEqual(["a", "p"]);
  });
});

describe("tabs and archive", () => {
  const rows = [
    row({ id: "1", unread: 2 }),
    row({ id: "2", status: "resolved" }),
    row({ id: "3", status: "approval" }),
    row({ id: "4", archivedAt: "2026-11-01T00:00:00Z", unread: 5 }),
  ];
  test("the default view never shows archived chats", () => {
    expect(visibleRows(rows).map((r) => r.id)).toEqual(["1", "2", "3"]);
  });
  test("the archive view shows only archived chats", () => {
    expect(visibleRows(rows, { archived: true }).map((r) => r.id)).toEqual(["4"]);
  });
  test("each tab filters", () => {
    expect(visibleRows(rows, { tab: "unread" }).map((r) => r.id)).toEqual(["1"]);
    expect(visibleRows(rows, { tab: "waiting" }).map((r) => r.id)).toEqual(["1"]);
    expect(visibleRows(rows, { tab: "approvals" }).map((r) => r.id)).toEqual(["3"]);
  });
  test("counts leave archived chats out of the tabs", () => {
    expect(tabCounts(rows)).toEqual({ all: 3, unread: 1, waiting: 1, approvals: 1, archived: 1 });
  });
});

describe("listTimestamp", () => {
  const now = new Date(2026, 10, 17, 12, 0, 0);
  test("today is a time, yesterday is a word", () => {
    expect(listTimestamp(new Date(2026, 10, 17, 9, 5).toISOString(), "en", now)).toMatch(/09:05/);
    expect(listTimestamp(new Date(2026, 10, 16, 23, 0).toISOString(), "en", now)).toBe("Yesterday");
    expect(listTimestamp(new Date(2026, 10, 16, 23, 0).toISOString(), "ar", now)).toBe("أمس");
  });
  test("an old date is a date and bad input is empty", () => {
    expect(listTimestamp(new Date(2026, 9, 1).toISOString(), "en", now)).toMatch(/01\/10\/2026/);
    expect(listTimestamp(null, "en", now)).toBe("");
    expect(listTimestamp("nope", "en", now)).toBe("");
  });
});
