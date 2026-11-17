import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "vitest";
import ContactInfoPanel from "./ContactInfoPanel";

const conv = (o = {}) => ({ id: "c1", customer: "أحمد علي", initials: "أح", color: "#ddd", phone: "201001234567", messages: [], ...o });
const html = (props = {}) =>
  renderToStaticMarkup(React.createElement(ContactInfoPanel, { conversation: conv(), lang: "en", onClose() {}, onChange() {}, ...props }));

describe("ContactInfoPanel", () => {
  test("shows the customer's real name and a formatted number", () => {
    const out = html();
    expect(out).toContain("أحمد علي");
    expect(out).toContain("+20 100 123 4567");
  });
  test("never invents a phone number when the customer has none", () => {
    const out = html({ conversation: conv({ phone: "" }) });
    expect(out).not.toContain('data-testid="contact-phone"');
    expect(out).not.toContain("101 234 5678");
  });
  test("makes no claim about features this inbox does not have", () => {
    const out = html({ lang: "en" });
    for (const claim of [/encrypt/i, /disappearing/i, /starred/i, /Hey there/i, /I am using WhatsApp/i]) expect(out).not.toMatch(claim);
    const ar = html({ lang: "ar" });
    for (const claim of ["التشفير", "ذاتية الاختفاء", "بنجمة"]) expect(ar).not.toContain(claim);
  });
  test("counts what was actually shared", () => {
    const messages = [
      { id: "1", contentType: "image", mediaUrl: "u1", createdAt: "2026-11-17T08:00:00Z" },
      { id: "2", text: "https://a.io/x", createdAt: "2026-11-17T09:00:00Z" },
    ];
    const out = html({ conversation: conv({ messages }) });
    expect(out).toMatch(/Media[^<]*<span[^>]*>1</);
    expect(out).toMatch(/Links[^<]*<span[^>]*>1</);
    expect(out).toMatch(/Docs[^<]*<span[^>]*>0</);
  });
  test("lists shared photos on the Media tab", () => {
    const messages = [{ id: "1", contentType: "image", mediaUrl: "https://cdn/x.jpg", createdAt: "2026-11-17T08:00:00Z" }];
    const out = html({ conversation: conv({ messages }) });
    expect(out).toContain('data-testid="info-media"');
    expect(out).toContain("https://cdn/x.jpg");
  });
  test("says so when nothing is shared", () => {
    expect(html()).toContain("No shared media");
  });
  test("chat settings follow the chat's state", () => {
    const out = html({ conversation: conv({ pinnedAt: "2026-11-01T00:00:00Z", archivedAt: "2026-11-02T00:00:00Z", mutedUntil: "9999-12-31T00:00:00Z" }) });
    expect(out).toContain("Unpin chat");
    expect(out).toContain("Unarchive chat");
    expect(out).toContain("Unmute notifications");
    expect(out).toContain("Muted always");
    const plain = html();
    expect(plain).toContain("Pin chat");
    expect(plain).toContain("Mute notifications");
  });
  test("says the settings are shared by the team and not shown to the customer", () => {
    expect(html()).toContain("never shown to the customer");
  });
  test("shows the store record only when the customer was loaded", () => {
    expect(html()).not.toContain('data-testid="info-profile"');
    const out = html({ customer: { email: "a@b.co", lifetime_value: "1250", is_blocked: false } });
    expect(out).toContain('data-testid="info-profile"');
    expect(out).toContain("a@b.co");
    expect(out).toContain('data-testid="info-spend"');
  });
  test("a purchase block is explained as not affecting messages", () => {
    const out = html({ customer: { lifetime_value: "0", is_blocked: true }, onToggleBuyBlock() {} });
    expect(out).toContain('data-testid="info-blocked"');
    expect(out).toContain("Messages are not affected");
    expect(out).toContain("Allow purchases");
    expect(html({ customer: { lifetime_value: "0", is_blocked: false }, onToggleBuyBlock() {} })).toContain("Block purchases");
  });
  test("is a labelled region in the reader's direction", () => {
    const out = html({ lang: "ar" });
    expect(out).toContain('role="complementary"');
    expect(out).toContain('dir="rtl"');
    expect(out).toContain("معلومات جهة الاتصال");
  });
  test("renders nothing without a conversation", () => {
    expect(html({ conversation: null })).toBe("");
  });
});
