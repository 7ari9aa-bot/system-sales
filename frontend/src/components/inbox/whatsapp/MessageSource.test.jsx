/**
 * The bubble footer must never let a reply typed on the merchant's phone read as the AI's.
 *
 * Three writers share one thread on a coexistence number (the AI, a person in FIHRIST, the
 * WhatsApp Business app on the phone). The label is the only thing that tells them apart, so it
 * is decided by one function and tested on its own.
 */
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "vitest";
import MessageSource, { messageSourceLabel, SOURCE_BUSINESS_APP, SOURCE_HISTORY } from "./MessageSource";

const render = (m, lang = "en") => renderToStaticMarkup(React.createElement(MessageSource, { m, lang }));
const out = (extra = {}) => ({ id: "1", side: "out", text: "hi", senderType: "agent", ...extra });

describe("messageSourceLabel", () => {
  test("a phone reply is the Business App, in both languages", () => {
    expect(messageSourceLabel(out({ source: SOURCE_BUSINESS_APP }), "en").text).toBe("Business App");
    expect(messageSourceLabel(out({ source: SOURCE_BUSINESS_APP }), "ar").text).toBe("تطبيق واتساب");
    expect(messageSourceLabel(out({ source: SOURCE_BUSINESS_APP }), "en").key).toBe("business_app");
  });

  test("imported history was written on the phone too, so it carries the same name", () => {
    expect(messageSourceLabel(out({ source: SOURCE_HISTORY }), "en").key).toBe("business_app");
  });

  test("the AI is named as the AI, not as the shop", () => {
    const label = messageSourceLabel(out({ senderType: "ai", ai: true }), "en");
    expect(label).toEqual({ key: "ai", text: "AI" });
  });

  test("a person replying from FIHRIST is FIHRIST", () => {
    expect(messageSourceLabel(out({ senderType: "agent" }), "en").key).toBe("fihrist");
    expect(messageSourceLabel(out({ senderType: "agent" }), "ar").text).toBe("فهرست");
  });

  test("inbound messages, deleted messages and unknown senders get no label", () => {
    expect(messageSourceLabel({ id: "1", side: "in", senderType: "customer" }, "en")).toBeNull();
    expect(messageSourceLabel(out({ deleted: true }), "en")).toBeNull();
    expect(messageSourceLabel(out({ senderType: "system" }), "en")).toBeNull();
    expect(messageSourceLabel(null, "en")).toBeNull();
  });
});

describe("MessageSource", () => {
  test("renders one labelled span carrying the key for styling", () => {
    const html = render(out({ source: SOURCE_BUSINESS_APP }));
    expect(html).toContain('data-testid="message-source"');
    expect(html).toContain('data-source="business_app"');
    expect(html).toContain("Business App");
  });

  test("renders nothing at all when there is no honest label", () => {
    expect(render({ id: "1", side: "in", senderType: "customer" })).toBe("");
  });
});
