import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "vitest";
import { ChoiceBody, ContactBody, DocumentBody, InteractiveBody, LocationBody, PhotoBody, StickerBody, UnsupportedBody, VideoBody } from "./MessageBodies";

const r = (el) => renderToStaticMarkup(el);

describe("message bodies", () => {
  test("a location shows the place and address, and no invented map", () => {
    const out = r(<LocationBody body="📍 Cairo Tower, Gezira, Cairo" lang="en" />);
    expect(out).toContain("Cairo Tower");
    expect(out).toContain("Gezira, Cairo");
    expect(out).not.toMatch(/<img|<iframe|maps\./);
  });
  test("a contact shows the name and number", () => {
    const out = r(<ContactBody body="Ali Hassan +20 100 123 4567" lang="en" />);
    expect(out).toContain("Ali Hassan");
    expect(out).toContain("+20 100 123 4567");
  });
  test("a contact with no number says so instead of leaving a gap", () => {
    expect(r(<ContactBody body="Ali Hassan" lang="en" />)).toContain("No number");
    expect(r(<ContactBody body="[contacts]" lang="en" />)).toContain("Contact");
  });
  test("a document has its name, type badge and a real download link", () => {
    const out = r(<DocumentBody src="https://cdn.x/a/Invoice%20May.pdf" lang="en" />);
    expect(out).toContain("Invoice May.pdf");
    expect(out).toContain("PDF");
    expect(out).toMatch(/<a [^>]*href="https:\/\/cdn.x\/a\/Invoice%20May.pdf"[^>]*rel="noopener noreferrer"/);
    expect(out).toContain('aria-label="Download Invoice May.pdf"');
  });
  test("a document with no link offers no download button", () => {
    expect(r(<DocumentBody label="x.pdf" lang="en" />)).not.toContain("document-download");
  });
  test("a photo is a lazy image; a sticker has no caption chrome", () => {
    expect(r(<PhotoBody src="https://x/p.jpg" lang="en" />)).toContain('loading="lazy"');
    expect(r(<StickerBody src="https://x/s.webp" lang="en" />)).toContain('data-testid="sticker"');
  });
  test("a video waits for a tap before loading anything", () => {
    const out = r(<VideoBody src="https://x/v.mp4" lang="en" />);
    expect(out).toContain('data-testid="play-video"');
    expect(out).not.toContain("<video");
  });
  test("a button tap and a list choice are labelled as the customer's choice", () => {
    expect(r(<ChoiceBody body="Yes, confirm" kind="buttons" lang="en" />)).toContain("Button reply");
    expect(r(<ChoiceBody body="Size M" kind="list" lang="en" />)).toContain("List choice");
  });
  test("an unsupported type says so and offers no raw data", () => {
    const out = r(<UnsupportedBody lang="en" />);
    expect(out).toContain("not supported");
    expect(r(<UnsupportedBody lang="ar" />)).toContain("غير مدعومة");
  });
});


describe("DocumentBody actions (as in the real app)", () => {
  test("shows Open and Save as... under the card, and no round download button", () => {
    const html = r(<DocumentBody src="https://x.test/a.pdf" label="a.pdf" lang="en" out />);
    expect(html).toContain('data-testid="document-open"');
    expect(html).toContain(">Open<");
    expect(html).toContain(">Save as...<");
    expect(html).toContain('download="a.pdf"');
  });
  test("shows no actions when the link has expired (no src)", () => {
    const html = r(<DocumentBody label="a.pdf" lang="en" />);
    expect(html).not.toContain("document-open");
    expect(html).not.toContain("Save as");
  });
});

// These three are exactly what the server returns for a sent message (built by the same code that
// builds what Meta receives), so the screen and the server cannot drift apart unnoticed.
const SENT = {"buttons": {"type": "button", "body": {"text": "تأكيد الطلب؟"}, "header": {"type": "text", "text": "Order #7"}, "footer": {"text": "شكرًا"}, "action": {"buttons": [{"type": "reply", "reply": {"id": "yes", "title": "تأكيد"}}, {"type": "reply", "reply": {"id": "no", "title": "إلغاء"}}]}}, "list": {"type": "list", "body": {"text": "اختر الشحن"}, "action": {"button": "الخيارات", "sections": [{"title": "الشحن", "rows": [{"id": "fast", "title": "سريع", "description": "يوم واحد"}, {"id": "slow", "title": "عادي"}]}]}}, "cta": {"type": "cta_url", "body": {"text": "تابع طلبك"}, "action": {"name": "cta_url", "parameters": {"display_text": "فتح", "url": "https://fihrist.world/o/1"}}}};

describe("an interactive message we sent", () => {
  test("reply buttons show the text, header, footer and every button title in order", () => {
    const out = r(<InteractiveBody message={SENT.buttons} lang="en" />);
    expect(out).toContain("Order #7");
    expect(out).toContain("تأكيد الطلب؟");
    expect(out).toContain("شكرًا");
    expect(out.match(/data-testid="interactive-choice"/g)).toHaveLength(2);
    expect(out.indexOf("تأكيد</span>")).toBeLessThan(out.indexOf("إلغاء"));
  });
  test("reply buttons are not clickable here: the agent is not the customer", () => {
    const out = r(<InteractiveBody message={SENT.buttons} lang="en" />);
    expect(out).not.toMatch(/<button|<a /);
  });
  test("a list shows its button AND every section and row, so the agent can see what was offered", () => {
    const out = r(<InteractiveBody message={SENT.list} lang="en" />);
    expect(out).toContain("الخيارات");
    expect(out).toContain("الشحن");
    expect(out.match(/data-testid="interactive-row"/g)).toHaveLength(2);
    expect(out).toContain("يوم واحد");
    expect(out).toContain("<details");
  });
  test("a link button is a real link that opens safely in a new tab", () => {
    const out = r(<InteractiveBody message={SENT.cta} lang="en" />);
    expect(out).toContain('href="https://fihrist.world/o/1"');
    expect(out).toContain('target="_blank"');
    expect(out).toContain('rel="noopener noreferrer"');
    expect(out).toContain("فتح");
  });
  test("a message with no choices still shows its text and draws no empty frame", () => {
    const out = r(<InteractiveBody message={{ type: "button", body: { text: "Hi" }, action: { buttons: [] } }} lang="en" />);
    expect(out).toContain("Hi");
    expect(out).not.toContain("interactive-choice");
    expect(out).not.toContain("border-t");
  });
  test("nothing is shown for an empty message instead of crashing", () => {
    expect(() => r(<InteractiveBody message={null} lang="en" />)).not.toThrow();
  });
  test("text is escaped, not injected", () => {
    const evil = { type: "button", body: { text: "<img src=x onerror=alert(1)>" }, action: { buttons: [] } };
    expect(r(<InteractiveBody message={evil} lang="en" />)).not.toContain("<img");
  });
});
