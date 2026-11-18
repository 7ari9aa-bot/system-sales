import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "vitest";
import { InstagramBubble } from "./InstagramBubble";
import { instagramKind, safeHttps } from "./messageKind";

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
