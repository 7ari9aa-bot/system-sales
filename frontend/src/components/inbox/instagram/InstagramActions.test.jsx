import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test, vi } from "vitest";
import { InstagramBubble } from "./InstagramBubble";
import { InstagramMessageActions, QUICK_REACTIONS } from "./InstagramMessageActions";
import { InstagramReplyBar } from "./InstagramReplyBar";
import { instagramKind } from "./messageKind";

const th = { out: "#4A5DF9", outText: "#ffffff", in: "#F3F5F7", inText: "#000000", bubbleRadius: 18 };
const msg = (over = {}) => ({ id: "1", side: "in", text: "hello", contentType: "text", mediaUrl: null, mediaType: null, card: null, reactions: [], ...over });
const fn = () => vi.fn();

describe("message actions on a bubble", () => {
  test("a saved message shows react, reply and more", () => {
    const h = renderToStaticMarkup(<InstagramBubble m={msg()} th={th} lang="en" onReply={fn()} onReact={fn()} onCopy={fn()} />);
    expect(h).toContain('data-testid="ig-react"');
    expect(h).toContain('data-testid="ig-reply"');
    expect(h).toContain('data-testid="ig-more"');
  });

  test.each([
    ["deleted", { deleted: true }],
    ["not yet saved", { unsaved: true }],
    ["failed", { failed: true }],
  ])("a %s message has no actions", (_n, over) => {
    const h = renderToStaticMarkup(<InstagramBubble m={msg(over)} th={th} lang="en" onReply={fn()} onReact={fn()} onCopy={fn()} />);
    expect(h).not.toContain("ig-actions");
  });

  test("without handlers nothing is drawn", () => {
    expect(renderToStaticMarkup(<InstagramBubble m={msg()} th={th} lang="en" />)).not.toContain("ig-actions");
  });

  test("only the handlers given get a button", () => {
    const h = renderToStaticMarkup(<InstagramMessageActions m={msg()} lang="en" onReply={fn()} />);
    expect(h).toContain("ig-reply");
    expect(h).not.toContain("ig-react");
    expect(h).not.toContain("ig-more");
  });

  test("buttons are named in Arabic too", () => {
    const h = renderToStaticMarkup(<InstagramMessageActions m={msg()} lang="ar" onReply={fn()} onReact={fn()} onCopy={fn()} />);
    expect(h).toContain('aria-label="رد"');
    expect(h).toContain('aria-label="تفاعل"');
  });

  test("actions sit on the inner side of the bubble", () => {
    const sent = renderToStaticMarkup(<InstagramMessageActions m={msg({ side: "out" })} lang="en" onReply={fn()} />);
    const got = renderToStaticMarkup(<InstagramMessageActions m={msg({ side: "in" })} lang="en" onReply={fn()} />);
    expect(sent).toContain("order-first");
    expect(got).toContain("order-last");
  });

  test("six quick reactions, hearts first", () => {
    expect(QUICK_REACTIONS).toHaveLength(6);
    expect(QUICK_REACTIONS[0]).toBe("❤️");
  });
});

describe("reply bar", () => {
  test("names who is being answered and quotes the text", () => {
    const h = renderToStaticMarkup(<InstagramReplyBar replyingTo={msg({ text: "Is it open?" })} customerName="Sara" lang="en" onCancel={fn()} />);
    expect(h).toContain("Replying to");
    expect(h).toContain("Sara");
    expect(h).toContain("Is it open?");
    expect(h).toContain('data-testid="ig-cancel-reply"');
  });

  test("answering our own message says yourself", () => {
    const h = renderToStaticMarkup(<InstagramReplyBar replyingTo={msg({ side: "out" })} customerName="Sara" lang="en" onCancel={fn()} />);
    expect(h).toContain("yourself");
    expect(h).not.toContain("Sara");
  });

  test("a message with no text is called an attachment", () => {
    expect(renderToStaticMarkup(<InstagramReplyBar replyingTo={msg({ text: "" })} lang="en" onCancel={fn()} />)).toContain("Attachment");
  });

  test("nothing is drawn when no message is selected", () => {
    expect(renderToStaticMarkup(<InstagramReplyBar replyingTo={null} lang="en" onCancel={fn()} />)).toBe("");
  });

  test("Arabic wording", () => {
    const h = renderToStaticMarkup(<InstagramReplyBar replyingTo={msg()} customerName="سارة" lang="ar" onCancel={fn()} />);
    expect(h).toContain("الرد على");
    expect(h).toContain("سارة");
  });
});

describe("the heart we send", () => {
  test.each(["❤️", "❤", "♥️", " ❤️ "])("a bare %j is a heart, drawn without a bubble", (text) => {
    const m = msg({ side: "out", text });
    expect(instagramKind(m)).toBe("heart");
    expect(renderToStaticMarkup(<InstagramBubble m={m} th={th} lang="en" />)).not.toContain("border-radius:18px");
  });

  test.each(["❤️ thanks", "love ❤️", "❤️❤️", "hello"])("%j stays text", (text) => {
    expect(instagramKind(msg({ text }))).toBe("text");
  });

  test("a heart with a picture is not a heart", () => {
    expect(instagramKind(msg({ text: "❤️", mediaUrl: "https://c/a.jpg", contentType: "image" }))).toBe("image");
  });
});
