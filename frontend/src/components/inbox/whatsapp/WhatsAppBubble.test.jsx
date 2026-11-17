import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "vitest";
import WhatsAppBubble, { quotePreview, WHATSAPP_FONT } from "./WhatsAppBubble";

const th = { out: "#d9fdd3", outText: "#111", in: "#fff", inText: "#111", tail: true };
const base = { id: "1", side: "in", text: "مرحبا", time: "٠٨:٣١ م", status: "received", reactions: [] };
const render = (m, lang = "ar") => renderToStaticMarkup(React.createElement(WhatsAppBubble, { m: { ...base, ...m }, th, lang }));

describe("WhatsAppBubble", () => {
  test("uses the WhatsApp text stack, not the app font", () => {
    expect(WHATSAPP_FONT.startsWith('"Segoe UI"')).toBe(true);
    expect(render({})).toContain("Segoe UI");
    expect(render({})).not.toContain("IBM Plex");
  });

  test("an outgoing bubble is green and an incoming one is white", () => {
    expect(render({ side: "out", status: "read" })).toContain("#d9fdd3");
    expect(render({ side: "in" })).toContain("background:#fff");
  });

  test("only outgoing bubbles carry a delivery mark", () => {
    expect(render({ side: "in" })).not.toContain("data-status");
    expect(render({ side: "out", status: "delivered" })).toContain('data-status="delivered"');
  });

  test("a failed outgoing message is flagged, not shown as sent", () => {
    const html = render({ side: "out", status: "failed" });
    expect(html).toContain('data-status="failed"');
    expect(html).not.toContain('data-status="sent"');
  });

  test("a deleted message shows the placeholder and none of its text", () => {
    const html = render({ deleted: true, text: "رقمي السري 0100" });
    expect(html).toContain("تم حذف هذه الرسالة");
    expect(html).not.toContain("0100");
  });

  test("a deleted message shows no reactions either", () => {
    expect(render({ deleted: true, reactions: ["👍"] })).not.toContain('data-testid="reactions"');
  });

  test("an edited message says so", () => {
    expect(render({ edited: true })).toContain("معدّلة");
    expect(render({ edited: true }, "en")).toContain("Edited");
    expect(render({ edited: false })).not.toContain("معدّلة");
  });

  test("reactions render under the bubble", () => {
    const html = render({ reactions: ["👍", "❤️"] });
    expect(html).toContain('data-testid="reactions"');
    expect(html).toContain("👍❤️");
  });

  test("a reply shows the quoted text above its own", () => {
    const html = render({ replyTo: { id: "x", available: true, direction: "outbound", content_type: "text", body: "السعر ٢٠٠" } });
    expect(html).toContain('data-testid="quoted-reply"');
    expect(html.indexOf("السعر ٢٠٠")).toBeLessThan(html.indexOf("مرحبا"));
    expect(html).toContain("أنت");
  });

  test("a quote we never stored says it is unavailable", () => {
    expect(render({ replyTo: { id: null, available: false } })).toContain("الرسالة غير متاحة");
  });

  test("the text is bidi-neutral so Arabic and English both lay out right", () => {
    expect(render({})).toContain('dir="auto"');
  });
});

describe("quotePreview", () => {
  test("a quoted photo with no caption names itself", () => {
    expect(quotePreview({ available: true, content_type: "image", body: "" }, "ar").text).toBe("صورة");
    expect(quotePreview({ available: true, content_type: "voice", body: null }, "en").text).toBe("Voice message");
  });
  test("a quote with a caption keeps the caption", () => {
    expect(quotePreview({ available: true, content_type: "image", body: "المنتج" }, "ar").text).toBe("المنتج");
  });
  test("an unknown quoted kind is not left blank", () => {
    expect(quotePreview({ available: true, content_type: "weird", body: "" }, "en").text).toBe("Unsupported message");
  });
});

describe("WhatsAppBubble reply button", () => {
  const withReply = (m, lang = "ar") =>
    renderToStaticMarkup(React.createElement(WhatsAppBubble, { m: { ...base, ...m }, th, lang, onReply: () => {} }));

  test("is offered on a normal message, labelled for the reader", () => {
    expect(withReply({})).toContain('data-testid="bubble-options"');
    expect(withReply({})).toContain('aria-label="خيارات الرسالة"');
    expect(withReply({}, "en")).toContain('aria-label="Message options"');
  });

  test("is not shown without a handler", () => {
    expect(render({})).not.toContain("bubble-options");
  });

  test("is not offered on a deleted message", () => {
    expect(withReply({ deleted: true })).not.toContain("bubble-options");
  });

  test("an outgoing bubble keeps its own side", () => {
    expect(withReply({ side: "out", status: "sent" })).toContain("flex-row-reverse");
    expect(withReply({ side: "in" })).not.toContain("flex-row-reverse");
  });
});
