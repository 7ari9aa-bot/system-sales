import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "vitest";
import MessageMenu, { QUICK_REACTIONS } from "./MessageMenu";
import WhatsAppBubble from "./WhatsAppBubble";

const th = { out: "#d9fdd3", outText: "#111", in: "#fff", inText: "#111", tail: true };
const base = { id: "1", side: "in", text: "مرحبا", time: "٠٨:٣١ م", status: "received", reactions: [] };
const menu = (props = {}, m = {}, lang = "ar") =>
  renderToStaticMarkup(React.createElement(MessageMenu, { m: { ...base, ...m }, lang, onReply() {}, onCopy() {}, onReact() {}, ...props }));

describe("MessageMenu", () => {
  test("offers the six quick reactions, then Reply and Copy", () => {
    const html = menu();
    expect(QUICK_REACTIONS).toHaveLength(6);
    for (const e of QUICK_REACTIONS) expect(html).toContain(e);
    expect(html).toContain('data-testid="menu-reply"');
    expect(html).toContain('data-testid="menu-copy"');
  });

  test("is labelled in the reader's language", () => {
    expect(menu({}, {}, "ar")).toContain("نسخ");
    expect(menu({}, {}, "en")).toContain("Copy");
  });

  test("offers no Copy for a message with no text (an image with no caption)", () => {
    expect(menu({}, { text: "" })).not.toContain("menu-copy");
    expect(menu({}, { text: "blob:http://x/1" })).not.toContain("menu-copy");
  });

  test("hides the reaction row when reacting is not possible", () => {
    expect(menu({ canReact: false })).not.toContain("quick-reaction");
    expect(menu({ canReact: false })).toContain("menu-reply");
  });

  test("marks the emoji we already reacted with, and offers to withdraw it", () => {
    const html = menu({ mine: "👍" });
    expect(html).toContain('aria-pressed="true"');
    expect(html).toContain("إزالة التفاعل 👍");
    expect(menu({ mine: "" })).not.toContain('aria-pressed="true"');
  });
});

describe("WhatsAppBubble menu entry", () => {
  const bubble = (m, props) =>
    renderToStaticMarkup(React.createElement(WhatsAppBubble, { m: { ...base, ...m }, th, lang: "ar", ...props }));

  test("shows the options button when any action is available", () => {
    expect(bubble({}, { onReply() {} })).toContain('data-testid="bubble-options"');
    expect(bubble({}, { onReact() {} })).toContain('data-testid="bubble-options"');
  });

  test("shows nothing when there is no action, and never on a deleted message", () => {
    expect(bubble({}, {})).not.toContain("bubble-options");
    expect(bubble({ deleted: true }, { onReply() {}, onReact() {} })).not.toContain("bubble-options");
  });

  test("the menu starts closed", () => {
    expect(bubble({}, { onReply() {}, onReact() {} })).not.toContain('role="menu"');
  });
});
