import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "vitest";

import ChannelChat, { formatDuration } from "./ChannelChat";

/**
 * A voice note has to be PLAYABLE, not decorated.
 *
 * The bubble used to be a toggle that flipped an icon over a hardcoded "0:14" and a wave that lit
 * up by index — no audio was ever fetched, so a customer's voice note (the most common message on
 * a coexistence number) could not be heard at all. These render the real chat and assert on the
 * audio element that replaced it.
 */
const theme = { out: "#d9fdd3", outText: "#111", in: "#fff", inText: "#111", chatBg: "#efeae2", tail: true, checkmarks: "#53bdeb" };
const voice = (extra = {}) => ({
  id: "m1",
  side: "in",
  text: "",
  mediaType: "audio",
  mediaUrl: "https://cdn.example.com/voice-1.ogg",
  time: "08:00",
  createdAt: "2026-11-17T06:00:00Z",
  status: "received",
  reactions: [],
  ...extra,
});
const render = (messages) =>
  renderToStaticMarkup(
    React.createElement(ChannelChat, {
      channel: { id: "whatsapp", name: "WhatsApp", theme },
      conversation: { id: "c1", name: "عميل", channel: "whatsapp", messages },
      lang: "ar",
      t: (k, d) => d || k,
      onSend() {},
      onReact() {},
    }),
  );

describe("a voice note in the inbox", () => {
  test("the audio element points at the real media URL", () => {
    expect(render([voice()])).toContain('src="https://cdn.example.com/voice-1.ogg"');
  });

  test("the play control is a real button, not an icon that does nothing", () => {
    const html = render([voice()]);
    expect(html).toContain('data-testid="voice-toggle"');
    expect(html).toContain("Play voice note");
  });

  test("the wave is a progress bar that can be seeked", () => {
    expect(render([voice()])).toContain('data-testid="voice-progress"');
  });

  test("an outbound voice note is playable too", () => {
    const html = render([voice({ side: "out", status: "sent" })]);
    expect(html).toContain('src="https://cdn.example.com/voice-1.ogg"');
  });

  test("a voice note with no URL is disabled instead of pretending to play", () => {
    const html = render([voice({ mediaUrl: null })]);
    expect(html).toContain("disabled");
  });

  test("a real duration is shown, never an invented one", () => {
    // No metadata has loaded during a server render, so the bubble must not claim 0:14.
    expect(render([voice()])).not.toContain("0:14");
    expect(render([voice()])).toContain("0:00");
  });
});

describe("formatDuration", () => {
  test("formats seconds the way a player does", () => {
    expect(formatDuration(0)).toBe("0:00");
    expect(formatDuration(7.4)).toBe("0:07");
    expect(formatDuration(65)).toBe("1:05");
    expect(formatDuration(600)).toBe("10:00");
  });

  test("says nothing rather than NaN for an unknown length", () => {
    expect(formatDuration(NaN)).toBe("");
    expect(formatDuration(Infinity)).toBe("");
    expect(formatDuration(-3)).toBe("");
  });
});
