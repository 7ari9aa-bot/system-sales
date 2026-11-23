import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "vitest";
import { InstagramBubble } from "./InstagramBubble";
import { instagramKind, instagramQuoteText, safeHttps } from "./messageKind";

const th = { out: "#4A5DF9", outText: "#ffffff", in: "#F3F5F7", inText: "#000000", bubbleRadius: 18 };
const msg = (over = {}) => ({ id: "1", side: "in", text: "", contentType: "text", mediaUrl: null, mediaType: null, card: null, reactions: [], ...over });
const html = (m, props = {}) => renderToStaticMarkup(<InstagramBubble m={msg(m)} th={th} lang="en" {...props} />);

describe("instagramKind", () => {
  test.each([
    [{ contentType: "text", text: "hi" }, "text"],
    [{ contentType: "image", mediaUrl: "https://c/a.jpg" }, "image"],
    [{ contentType: "video", mediaUrl: "https://c/a.mp4" }, "video"],
    [{ contentType: "voice", mediaUrl: "https://c/a.m4a" }, "voice"],
    [{ contentType: "file", mediaUrl: "https://c/a.pdf" }, "file"],
    [{ contentType: "sticker", mediaUrl: "https://c/s.png" }, "sticker"],
    [{ contentType: "sticker", text: "❤️" }, "heart"],
    [{ contentType: "deleted" }, "deleted"],
    [{ deleted: true, contentType: "text" }, "deleted"],
    [{ contentType: "unsupported" }, "unsupported"],
    [{ contentType: "share", card: { type: "share" } }, "share"],
    [{ contentType: "story_reply", card: { type: "story_reply" } }, "story_reply"],
    [{ contentType: "text", card: { type: "story_reply" } }, "story_reply"],
    [{ contentType: "story_mention", card: { type: "story_mention" } }, "story_mention"],
  ])("%j is %s", (m, kind) => expect(instagramKind(msg(m))).toBe(kind));

  test("only an https link gets through", () => {
    expect(safeHttps("https://x/y")).toBe("https://x/y");
    for (const bad of ["javascript:alert(1)", "http://x", "data:text/html,1", "", null, undefined, 5]) expect(safeHttps(bad)).toBe("");
  });
});

describe("InstagramBubble", () => {
  test("our message is Instagram blue with 18px corners, theirs is grey", () => {
    const mine = html({ side: "out", text: "hello" });
    expect(mine).toMatch(/background:\s*#4A5DF9|background:rgb\(74, 93, 249\)/i);
    expect(mine).toContain("border-radius:18px");
    expect(html({ text: "hello" })).toMatch(/background:\s*#F3F5F7|background:rgb\(243, 245, 247\)/i);
  });

  test("a shared post is a card with its title and a safe link", () => {
    const out = html({ contentType: "share", card: { type: "share", kind: "ig_post", url: "https://ig/p/1", title: "New shoes" } });
    expect(out).toContain('data-testid="ig-card-share"');
    expect(out).toContain("New shoes");
    expect(out).toContain('href="https://ig/p/1"');
    expect(out).toContain('rel="noopener noreferrer"');
  });

  test("a javascript: link never becomes a link", () => {
    const out = html({ contentType: "share", card: { type: "share", url: "javascript:alert(1)" } });
    expect(out).not.toContain("<a ");
    expect(out).not.toContain("javascript:");
  });

  test("a reel says so, and an expired story is not a blank card", () => {
    expect(html({ contentType: "share", card: { type: "share", kind: "ig_reel", url: "https://ig/r/1" } })).toContain("Shared a reel");
    const story = html({ contentType: "story_reply", text: "love it", card: { type: "story_reply", url: null } });
    expect(story).toContain("Replied to your story");
    expect(story).toContain("Story no longer available");
    expect(story).toContain("love it");
  });

  test("the like heart has no bubble colour around it", () => {
    const out = html({ contentType: "sticker", text: "❤️" });
    expect(out).toContain('data-testid="ig-heart"');
    expect(out).not.toMatch(/background/);
  });

  test("an unsent message shows a note, not its old text or media", () => {
    const out = html({ deleted: true, text: "secret", mediaUrl: "https://c/a.jpg", contentType: "image" });
    expect(out).toContain('data-testid="ig-deleted"');
    expect(out).not.toContain("secret");
    expect(out).not.toContain("ig-image");
  });

  test("Seen shows only when asked and only on our own message", () => {
    expect(html({ side: "out", text: "x" }, { showSeen: true })).toContain(">Seen<");
    expect(html({ side: "out", text: "x" })).not.toContain("ig-seen");
    expect(html({ side: "in", text: "x" }, { showSeen: true })).not.toContain("ig-seen");
  });

  test("Seen speaks Arabic when the app does", () => {
    expect(html({ side: "out", text: "x" }, { showSeen: true, lang: "ar" })).toContain("تمت المشاهدة");
  });

  test("reactions sit on the bubble", () => {
    expect(html({ text: "x", reactions: ["❤️", "😂"] })).toContain("❤️😂");
  });

  test("media renders its element, and a file with a bad link is not clickable", () => {
    expect(html({ contentType: "image", mediaUrl: "https://c/a.jpg" })).toContain('data-testid="ig-image"');
    expect(html({ contentType: "video", mediaUrl: "https://c/a.mp4" })).toContain("<video");
    expect(html({ contentType: "voice", mediaUrl: "https://c/a.m4a" })).toContain("<audio");
    expect(html({ contentType: "file", mediaUrl: "javascript:1", fileName: "a.pdf" })).not.toContain("<a ");
  });
});

describe("reply-to (Send API reply_to)", () => {
  test("a reply affordance appears on both sides and is absent without a handler", () => {
    expect(html({ text: "hi" }, { onReply: () => {} })).toContain('data-testid="ig-reply"');
    expect(html({ side: "out", text: "hi" }, { onReply: () => {} })).toContain('data-testid="ig-reply"');
    expect(html({ text: "hi" })).not.toContain('data-testid="ig-reply"');
  });

  test("a bare heart or a deleted message is never quoted", () => {
    expect(html({ contentType: "sticker", text: "\u2764\ufe0f" }, { onReply: () => {} })).not.toContain('data-testid="ig-reply"');
    expect(html({ contentType: "deleted" }, { onReply: () => {} })).not.toContain('data-testid="ig-reply"');
  });

  test("the quote bar names media instead of printing a blank", () => {
    expect(instagramQuoteText(msg({ contentType: "image" }), "ar")).toBe("صورة");
    expect(instagramQuoteText(msg({ contentType: "voice" }), "en")).toBe("Voice message");
    expect(instagramQuoteText(msg({ text: "سلام" }), "ar")).toBe("سلام");
  });
});

describe("InstagramBubble reply quote", () => {
  const quoted = (over = {}, props = {}) => html({ text: "بكرة", replyTo: { id: "q1", direction: "inbound", body: "السعر كام؟" }, ...over }, props);

  test("the quote sits inside the bubble, named after who wrote it", () => {
    const out = quoted({}, { peerName: "Nour" });
    const quote = out.indexOf('data-testid="ig-quote"');
    const bubble = out.indexOf('data-testid="ig-bubble"');
    const text = out.indexOf("بكرة");
    expect(quote).toBeGreaterThan(bubble);
    expect(quote).toBeLessThan(text);
    expect(out).toContain("Nour");
    expect(out).toContain("السعر كام؟");
  });

  test("quoting our own message says You, and falls back to the customer name", () => {
    expect(html({ text: "hi", replyTo: { id: "q", direction: "outbound", body: "أهلاً" } })).toContain("You");
    expect(html({ text: "hi", replyTo: { id: "q", direction: "inbound", body: "أهلاً" } }, { lang: "ar" })).toContain("العميل");
  });

  test("an unavailable original is said, not left blank", () => {
    expect(html({ text: "hi", replyTo: { id: "q", direction: "inbound", available: false } })).toContain("Message unavailable");
  });

  test("a photo reply keeps the quote as a pill above it", () => {
    const out = html({ contentType: "image", mediaUrl: "https://c/a.jpg", replyTo: { id: "q", direction: "inbound", body: "شوف" } });
    expect(out.indexOf('data-testid="ig-quote"')).toBeLessThan(out.indexOf('data-testid="ig-bubble"'));
  });
});
