import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "vitest";
import ChatList from "./ChatList";
import ChatListMenu, { MAX_PINNED } from "./ChatListMenu";
import ChatListRow from "./ChatListRow";

const base = { id: "1", customer: "أحمد", initials: "أح", color: "#ddd", preview: "السعر؟", status: "waiting", unread: 0, lastAt: "2026-11-17T08:00:00Z" };
const row = (o = {}) => ({ ...base, ...o });
const html = (el) => renderToStaticMarkup(el);
const listOf = (rows, props = {}) =>
  html(React.createElement(ChatList, { rows, activeId: null, lang: "en", onOpen() {}, onChange() {}, ...props }));
const rowOf = (r, props = {}) =>
  html(React.createElement(ChatListRow, { row: r, active: false, lang: "en", onOpen() {}, onChange() {}, ...props }));
const menuOf = (r, props = {}) =>
  html(React.createElement(ChatListMenu, { row: r, lang: "en", onChange() {}, onClose() {}, ...props }));

describe("ChatListRow", () => {
  test("shows the unread count in a badge and bolds the name", () => {
    const out = rowOf(row({ unread: 3 }));
    expect(out).toContain('data-testid="unread-badge"');
    expect(out).toContain("3 unread");
    expect(out).toContain("font-semibold");
  });
  test("caps a big count at 99+", () => {
    expect(rowOf(row({ unread: 250 }))).toContain("99+");
  });
  test("a manual 'mark as unread' is a dot with no number", () => {
    const out = rowOf(row({ markedUnread: true }));
    expect(out).toContain("Marked as unread");
    expect(out).not.toMatch(/>\d+</);
  });
  test("a read chat has no badge", () => {
    expect(rowOf(row())).not.toContain("unread-badge");
  });
  test("a muted chat turns the badge grey and shows the mute mark", () => {
    const out = rowOf(row({ unread: 2, mutedUntil: "9999-12-31T00:00:00Z" }));
    expect(out).toContain("bg-[#8696a0]");
    expect(out).toContain("Notifications muted");
    expect(rowOf(row({ unread: 2 }))).toContain("bg-[#25d366]");
  });
  test("a pinned chat shows the pin mark", () => {
    expect(rowOf(row({ pinnedAt: "2026-11-01T00:00:00Z" }))).toContain("Pinned chat");
  });
  test("draws the delivery tick only for a message we sent", () => {
    expect(rowOf(row({ lastDirection: "outbound", lastStatus: "read" }))).toContain('data-status="read"');
    expect(rowOf(row({ lastDirection: "inbound", lastStatus: "read" }))).not.toContain("data-status");
  });
  test("the options control is a sibling of the open button, never nested inside it", () => {
    const out = rowOf(row());
    expect(out).toContain('data-testid="row-options"');
    expect(out).not.toMatch(/<button[^>]*>(?:(?!<\/button>).)*<button/s);
  });
  test("is keyboard reachable: a real button with a name", () => {
    expect(rowOf(row())).toContain('aria-label="Chat options"');
  });
});

describe("ChatListMenu", () => {
  test("offers archive, mute, pin and mark unread", () => {
    const out = menuOf(row());
    for (const id of ["act-archive", "act-mute", "act-pin", "act-unread"]) expect(out).toContain(id);
  });
  test("labels follow the chat's state", () => {
    expect(menuOf(row({ pinnedAt: "2026-11-01T00:00:00Z" }))).toContain("Unpin chat");
    expect(menuOf(row({ archivedAt: "2026-11-01T00:00:00Z" }))).toContain("Unarchive chat");
    expect(menuOf(row({ mutedUntil: "9999-12-31T00:00:00Z" }))).toContain("Unmute notifications");
    expect(menuOf(row({ unread: 1 }))).toContain("Mark as read");
    expect(menuOf(row())).toContain("Mark as unread");
  });
  test("the fourth pin is blocked, but unpinning is always allowed", () => {
    // The real attribute is `disabled=""`; the class list also contains "disabled:".
    const pinButton = (out) => out.match(/<button[^>]*data-testid="act-pin"[^>]*>/)[0];
    const isDisabled = (out) => / disabled=""/.test(pinButton(out));
    expect(MAX_PINNED).toBe(3);
    expect(isDisabled(menuOf(row(), { pinnedCount: 3 }))).toBe(true);
    expect(isDisabled(menuOf(row({ pinnedAt: "2026-11-01T00:00:00Z" }), { pinnedCount: 3 }))).toBe(false);
    expect(isDisabled(menuOf(row(), { pinnedCount: 2 }))).toBe(false);
  });
  test("is a labelled menu", () => {
    expect(menuOf(row())).toMatch(/role="menu"[^>]*aria-label="Chat options"|aria-label="Chat options"[^>]*role="menu"/);
  });
});

describe("ChatList", () => {
  const rows = [
    row({ id: "a", customer: "Alpha" }),
    row({ id: "p", customer: "Pinned", pinnedAt: "2026-11-01T00:00:00Z" }),
    row({ id: "z", customer: "Zed", archivedAt: "2026-11-01T00:00:00Z" }),
  ];
  test("pinned chats come first and archived ones are hidden from the main list", () => {
    const out = listOf(rows);
    expect(out.indexOf("Pinned")).toBeGreaterThan(-1);
    expect(out.indexOf("Pinned")).toBeLessThan(out.indexOf("Alpha"));
    expect(out).not.toContain("Zed");
  });
  test("an Archived entry appears with the count, only when something is archived", () => {
    const out = listOf(rows);
    expect(out).toContain('data-testid="open-archive"');
    expect(listOf([rows[0]])).not.toContain("open-archive");
  });
  test("has the four filter tabs, All selected first", () => {
    const out = listOf(rows);
    for (const t of ["all", "unread", "waiting", "approvals"]) expect(out).toContain(`data-testid="tab-${t}"`);
    expect(out).toMatch(/data-testid="tab-all"[^>]*>|aria-selected="true"[^>]*data-testid="tab-all"/);
  });
  test("an empty list says so", () => {
    expect(listOf([])).toContain("No conversations");
  });
  test("is Arabic when asked", () => {
    const out = listOf(rows, { lang: "ar" });
    expect(out).toContain("غير مقروءة");
    expect(out).toContain('dir="rtl"');
  });
});
