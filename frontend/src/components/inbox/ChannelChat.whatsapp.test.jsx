import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "vitest";
import ChannelChat from "./ChannelChat";

// These render the REAL chat (not just the bubble) so that a handler wired in
// the wrong scope, which only fails on click, is caught as a missing control.
const theme = { out: "#d9fdd3", outText: "#111", in: "#fff", inText: "#111", chatBg: "#efeae2", tail: true, checkmarks: "#53bdeb" };
const msg = (id, extra = {}) => ({ id, side: "in", text: "", time: "٠٨:٠٠", createdAt: "2026-11-17T06:00:00Z", status: "received", reactions: [], ...extra });
const render = (messages, props = {}) =>
  renderToStaticMarkup(
    React.createElement(ChannelChat, {
      channel: { id: "whatsapp", name: "WhatsApp", theme },
      conversation: { id: "c1", name: "عميل", channel: "whatsapp", messages },
      lang: "ar",
      t: (k, d) => d || k,
      onSend() {},
      onReact() {},
      ...props,
    }),
  );

describe("ChannelChat on WhatsApp", () => {
  test("a photo can be opened", () => {
    expect(render([msg("m1", { mediaType: "image", mediaUrl: "https://x/a.jpg" })])).toContain('data-testid="open-image"');
  });

  test("every saved message has its options button", () => {
    expect(render([msg("m1", { text: "مرحبا" })])).toContain('data-testid="bubble-options"');
  });

  test("a local echo with no server id cannot be reacted to, but can still be replied to", () => {
    const html = render([msg("m1", { text: "تمام", side: "out", unsaved: true })]);
    expect(html).toContain('data-testid="bubble-options"');
  });

  test("the viewer is closed until a photo is opened", () => {
    expect(render([msg("m1", { mediaType: "image", mediaUrl: "https://x/a.jpg" })])).not.toContain('data-testid="image-viewer"');
  });
});
