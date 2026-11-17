import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "vitest";
import ChatHeader from "./ChatHeader";

const NOW = new Date("2026-11-17T12:00:00Z");
const ago = (h, m = 0) => new Date(NOW.getTime() - (h * 60 + m) * 60000).toISOString();
const conv = (o = {}) => ({ id: "c1", customer: "أحمد علي", initials: "أح", color: "#ddd", phone: "201001234567", lastCustomerMessageAt: ago(1), ...o });
const html = (props = {}) => renderToStaticMarkup(React.createElement(ChatHeader, { conversation: conv(), lang: "en", now: NOW, onOpenInfo() {}, onToggleSearch() {}, onChange() {}, ...props }));

describe("ChatHeader", () => {
  test("shows the name and the real, formatted number", () => {
    const out = html();
    expect(out).toContain("أحمد علي");
    expect(out).toContain("+20 100 123 4567");
  });
  test("never claims the customer is online or was last seen", () => {
    for (const lang of ["en", "ar"]) {
      const out = html({ lang });
      expect(out).not.toMatch(/online|last seen|typing|متصل|آخر ظهور|يكتب/i);
    }
  });
  test("is quiet while the reply window is comfortably open", () => {
    const out = html();
    expect(out).toContain('data-window="open"');
    expect(out).not.toContain("Reply window");
  });
  test("warns in the last two hours, with the time left", () => {
    const out = html({ conversation: conv({ lastCustomerMessageAt: ago(22, 30) }) });
    expect(out).toContain('data-window="closing"');
    expect(out).toContain("Reply window ends in 1h 30m");
  });
  test("says plainly when the window has closed", () => {
    const out = html({ conversation: conv({ lastCustomerMessageAt: ago(30) }) });
    expect(out).toContain('data-window="closed"');
    expect(out).toContain("Reply window closed");
  });
  test("has no subtitle when there is nothing true to say", () => {
    expect(html({ conversation: conv({ phone: "", lastCustomerMessageAt: null }) })).not.toContain("header-subtitle");
  });
  test("pin and mute marks follow the chat", () => {
    const out = html({ conversation: conv({ pinnedAt: "2026-11-01T00:00:00Z", mutedUntil: "9999-12-31T00:00:00Z" }) });
    expect(out).toContain("Pinned chat");
    expect(out).toContain("Notifications muted");
    expect(html()).not.toContain("Pinned chat");
  });
  test("every control is a named button; the back button only when there is somewhere to go", () => {
    const out = html({ onBack() {} });
    for (const name of ["Back to chats", "Search messages", "More"]) expect(out).toContain(`aria-label="${name}"`);
    // contact info opens from the name and avatar, like WhatsApp, not from a separate icon
    expect(out).toContain('data-testid="header-identity"');
    expect(out).not.toContain("header-info");
    expect(html()).not.toContain("header-back");
  });
  test("the search button reports whether search is open", () => {
    expect(html({ searchOpen: true })).toMatch(/aria-pressed="true"[^>]*data-testid="header-search"|data-testid="header-search"[^>]*aria-pressed="true"/);
  });
  test("renders nothing without a conversation", () => {
    expect(html({ conversation: null })).toBe("");
  });
  test("speaks Arabic", () => {
    const out = html({ lang: "ar", conversation: conv({ lastCustomerMessageAt: ago(30) }) });
    expect(out).toContain("انتهت نافذة الرد");
    expect(out).toContain('aria-label="بحث في الرسائل"');
  });
});
