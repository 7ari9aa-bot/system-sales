import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "vitest";
import ChannelChat from "./ChannelChat";

// The REAL chat, rendered as Messenger: these fail if a Messenger helper is written but the
// chat never calls it.
const theme = { out: "#0084ff", outText: "#fff", in: "#f0f0f0", inText: "#050505", chatBg: "#fff", headerBg: "#fff", headerText: "#050505", divider: "#e4e6eb", inputBg: "#fff", inputBorder: "#e4e6eb" };
const msg = (id, extra = {}) => ({ id, side: "in", text: "", time: "٠١:٣٣", createdAt: "2026-11-22T23:33:00Z", status: "received", reactions: [], ...extra });
const render = (messages) =>
  renderToStaticMarkup(
    React.createElement(ChannelChat, {
      channel: { id: "messenger", name: "Messenger", theme },
      conversation: { id: "c1", name: "Ahmed Adel", channel: "messenger", messages },
      lang: "ar",
      t: (k, d) => d || k,
      onSend() {},
      onReact() {},
    }),
  );

describe("ChannelChat on Messenger", () => {
  test("the time is not printed inside the bubble", () => {
    const html = render([msg("m1", { text: "اهلا", time: "٠١:٣٣" })]);
    expect(html).toContain("اهلا");
    // the time appears once, in the centred divider, and as the hover title; never as bubble text
    expect(html.match(/٠١:٣٣/g)?.length).toBe(2);
    expect(html).toContain('data-testid="messenger-time-divider"');
  });

  test("a second message a minute later gets no divider of its own", () => {
    const html = render([
      msg("m1", { text: "a" }),
      msg("m2", { text: "b", createdAt: "2026-11-22T23:34:00Z", time: "٠١:٣٤" }),
    ]);
    expect(html.match(/data-testid="messenger-time-divider"/g)?.length).toBe(1);
  });

  test("a message after a long pause gets a new divider", () => {
    const html = render([
      msg("m1", { text: "a" }),
      msg("m2", { text: "b", createdAt: "2026-11-22T23:59:00Z", time: "٠١:٥٩" }),
    ]);
    expect(html.match(/data-testid="messenger-time-divider"/g)?.length).toBe(2);
  });

  test("a lone thumbs-up is a big emoji with no bubble", () => {
    const html = render([msg("m1", { text: "👍", side: "out" })]);
    expect(html).toContain('data-testid="messenger-big-emoji"');
  });

  test("ordinary text keeps its bubble", () => {
    expect(render([msg("m1", { text: "ok 👍" })])).not.toContain('data-testid="messenger-big-emoji"');
  });

  test("a reply shows the message it answers", () => {
    const html = render([msg("m1", { text: "تمام", side: "out", replyTo: { id: "x", body: "السعر كام؟" } })]);
    expect(html).toContain('data-testid="messenger-quote"');
    expect(html).toContain("السعر كام؟");
  });

  test("a message with no reply has no quote", () => {
    expect(render([msg("m1", { text: "hi" })])).not.toContain('data-testid="messenger-quote"');
  });

  test("the composer is the grey Messenger pill with Aa", () => {
    const html = render([msg("m1", { text: "hi" })]);
    expect(html).toContain('data-testid="messenger-composer"');
    expect(html).toContain('placeholder="Aa"');
  });
});
