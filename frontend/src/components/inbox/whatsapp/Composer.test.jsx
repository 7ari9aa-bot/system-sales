import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "vitest";
import Composer from "./Composer";

const NOW = new Date("2026-11-17T12:00:00Z");
const ago = (h) => new Date(NOW.getTime() - h * 3600000).toISOString();
const html = (props = {}) => renderToStaticMarkup(React.createElement(Composer, { value: "", onChange() {}, onSend() {}, onToggleEmoji() {}, lastCustomerMessageAt: ago(1), lang: "en", now: NOW, ...props }));

describe("Composer", () => {
  test("is a multi-line field with accessible controls", () => {
    const out = html();
    expect(out).toContain("<textarea");
    for (const name of ["Emoji", "Attach", "Record voice message", "Type a message"]) expect(out).toContain(`aria-label="${name}"`);
  });
  test("shows the mic when empty and the send button when there is text", () => {
    expect(html()).toContain('data-testid="composer-voice"');
    expect(html()).not.toContain('data-testid="composer-send"');
    const typed = html({ value: "hello" });
    expect(typed).toContain('data-testid="composer-send"');
    expect(typed).not.toContain('data-testid="composer-voice"');
  });
  test("a blank message cannot be sent", () => {
    expect(html({ value: "  \n " })).toContain('data-testid="composer-voice"');
  });
  test("replaces the field with the reason once the 24-hour window has closed", () => {
    const out = html({ lastCustomerMessageAt: ago(30), value: "hello" });
    expect(out).toContain('data-testid="composer-closed"');
    expect(out).toContain("approved template is required");
    expect(out).not.toContain("<textarea");
  });
  test("stays usable for a customer who has never written", () => {
    expect(html({ lastCustomerMessageAt: null })).toContain("<textarea");
  });
  test("the reply preview names who is being answered", () => {
    expect(html({ replyingTo: { side: "in", text: "price?" }, customerName: "Sara" })).toMatch(/Sara[\s\S]*price\?/);
    expect(html({ replyingTo: { side: "out", text: "ok" } })).toContain("You");
  });
  test("warns near the length limit and flags going over", () => {
    expect(html({ value: "a".repeat(3800) })).toContain('data-testid="composer-count"');
    expect(html({ value: "a".repeat(100) })).not.toContain("composer-count");
    const over = html({ value: "a".repeat(4100) });
    expect(over).toContain("Over the limit by 4");
    expect(over).toContain('aria-invalid="true"');
  });
  test("the field is read-only while sending", () => {
    expect(html({ sending: true, value: "x" })).toMatch(/<textarea[^>]*readonly/);
  });
  test("speaks Arabic", () => {
    const out = html({ lang: "ar", lastCustomerMessageAt: ago(30) });
    expect(out).toContain("انتهت نافذة الـ 24 ساعة");
  });
});
