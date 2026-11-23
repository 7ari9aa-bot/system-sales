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

  test("the composer has Messenger's blue image button, limited to images", () => {
    const html = render([msg("m1", { text: "hi" })]);
    expect(html).toContain('data-testid="messenger-image-button"');
    expect(html).toContain('accept="image/jpeg,image/png,image/gif,image/webp"');
  });

  test("a customer's reactions show as a badge under the bubble", () => {
    const html = render([msg("m1", { text: "hi", side: "out", reactions: ["❤️", "😂", "❤️"] })]);
    expect(html).toContain('data-testid="messenger-reactions"');
    expect(html).toContain("❤️");
    expect(html).toContain("😂");
  });

  test("no reactions, no badge; a withdrawn reaction leaves no badge", () => {
    expect(render([msg("m1", { text: "hi" })])).not.toContain('data-testid="messenger-reactions"');
    expect(render([msg("m1", { text: "hi", reactions: ["\u200b-"] })])).not.toContain('data-testid="messenger-reactions"');
  });

  test("a saved message has reply and copy next to it, as Messenger shows on hover", () => {
    const html = render([msg("m1", { text: "hi" })]);
    expect(html).toContain('data-testid="messenger-hover-reply"');
    expect(html).toContain('data-testid="messenger-hover-copy"');
  });

  test("it offers no reaction button, because Messenger's Send API cannot react as a Page", () => {
    expect(render([msg("m1", { text: "hi" })])).not.toContain("messenger-hover-react");
  });

  test("no reply bar until a reply is started", () => {
    expect(render([msg("m1", { text: "hi" })])).not.toContain('data-testid="messenger-reply-bar"');
  });

  test("the newest sent message carries the grey Sent line", () => {
    const html = render([msg("m1", { text: "hi", side: "out", status: "sent", createdAt: new Date(Date.now() - 5 * 60e3).toISOString() })]);
    expect(html).toContain('data-testid="messenger-status-line"');
    expect(html).toContain("تم الإرسال منذ 5 د");
  });

  test("no status line when the customer wrote last", () => {
    expect(render([msg("m1", { text: "hi", side: "in" })])).not.toContain('data-testid="messenger-status-line"');
  });

  test("a photo stands on the page with no bubble around it", () => {
    const html = render([msg("m1", { mediaType: "image", mediaUrl: "https://cdn.example/a.jpg" })]);
    expect(html).toContain('data-testid="messenger-photo"');
    expect(html).toContain("https://cdn.example/a.jpg");
  });

  test("a file is a card with its name, linked to the file", () => {
    const html = render([msg("m1", { contentType: "file", mediaUrl: "https://cdn.example/price.pdf", fileName: "price.pdf" })]);
    expect(html).toContain('data-testid="messenger-file"');
    expect(html).toContain("price.pdf");
    expect(html).toContain('href="https://cdn.example/price.pdf"');
  });

  test("a video shows a player with controls", () => {
    const html = render([msg("m1", { mediaType: "video", mediaUrl: "https://cdn.example/a.mp4" })]);
    expect(html).toContain('data-testid="messenger-video"');
    expect(html).toContain("<video");
  });

  test("a removed message is a grey line, and its old text is not shown", () => {
    const html = render([msg("m1", { text: "secret", deleted: true })]);
    expect(html).toContain('data-testid="messenger-deleted"');
    expect(html).not.toContain("secret");
  });

  test("a system line is centred grey text, not a bubble", () => {
    const html = render([msg("m1", { text: "تم تعيين المحادثة", senderType: "system" })]);
    expect(html).toContain('data-testid="messenger-system"');
    expect(html).toContain("تم تعيين المحادثة");
  });

  test("the customer's small avatar sits by the last bubble of their run", () => {
    const html = render([msg("m1", { text: "a" }), msg("m2", { text: "b", side: "out", createdAt: "2026-11-22T23:34:00Z" })]);
    expect(html).toContain('data-testid="messenger-incoming-avatar"');
  });

  test("no avatar by a bubble that is not the end of the customer's run", () => {
    const html = render([msg("m1", { text: "a" }), msg("m2", { text: "b", createdAt: "2026-11-22T23:34:00Z" })]);
    expect(html.match(/data-testid="messenger-incoming-avatar"/g)?.length).toBe(1);
  });

  test("a photo is the picture itself, with no bubble behind it", () => {
    const html = render([msg("m1", { side: "out", contentType: "image", mediaUrl: "https://x/a.jpg" })]);
    expect(html).toContain('data-testid="messenger-photo"');
    expect(html).toContain("https://x/a.jpg");
  });

  test("a clip is a player and a document is a card with its name", () => {
    const clip = render([msg("m1", { side: "in", contentType: "video", mediaUrl: "https://x/v.mp4" })]);
    expect(clip).toContain('data-testid="messenger-video"');
    const doc = render([msg("m2", { side: "in", contentType: "file", mediaUrl: "https://x/f.pdf", fileName: "Invoice.pdf" })]);
    expect(doc).toContain('data-testid="messenger-file"');
    expect(doc).toContain("Invoice.pdf");
  });

  test("a system line is centred text, not a bubble", () => {
    const html = render([msg("m1", { senderType: "system", text: "You started a conversation" })]);
    expect(html).toContain('data-testid="messenger-system"');
    expect(html).not.toContain('data-testid="messenger-photo"');
  });

  test("a message that failed to send shows a red mark and says so, with no fake retry", () => {
    const html = render([msg("m1", { text: "hi", side: "out", status: "failed" })]);
    expect(html).toContain('data-testid="messenger-failed"');
    expect(html).toContain("لم يتم الإرسال");
    expect(html).not.toContain("messenger-retry");
  });

  test("a message that was sent has no failure mark", () => {
    expect(render([msg("m1", { text: "hi", side: "out", status: "sent" })])).not.toContain('data-testid="messenger-failed"');
  });

  test("an empty thread shows the customer's avatar and name, like Messenger, not a system sentence", () => {
    const html = render([]);
    expect(html).toContain('data-testid="messenger-empty"');
    expect(html).toContain("Ahmed Adel");
  });

  test("a web address in a bubble is a real link", () => {
    const html = render([msg("m1", { text: "شوف https://shop.example/p/1" })]);
    expect(html).toContain('href="https://shop.example/p/1"');
    expect(html).toContain('data-testid="messenger-link"');
  });

  test("a message that is only a link shows the site's name, as Messenger previews it", () => {
    const html = render([msg("m1", { text: "https://www.shop.example/p/1" })]);
    expect(html).toContain('data-testid="messenger-link-preview"');
    expect(html).toContain("shop.example");
  });

  test("the thread adds no blanket gap between children, so a run of messages can sit 2px apart", () => {
    const html = render([msg("m1", { text: "a" })]);
    const scroller = html.match(/<div class="([^"]*overflow-y-auto[^"]*)"/)?.[1] || "";
    expect(scroller).not.toContain("space-y-2");
  });

  test("the composer follows the language direction, so in Arabic the like sits at the far left", () => {
    const html = render([msg("m1", { text: "a" })]);
    expect(html).toMatch(/dir="rtl"[^>]*data-testid="messenger-composer"|data-testid="messenger-composer"[^>]*dir="rtl"/);
  });

  test("every composer button has an accessible name and the attach button says it opens a menu", () => {
    const html = render([msg("m1", { text: "a" })]);
    const composer = html.slice(html.indexOf('data-testid="messenger-composer"'));
    const buttons = composer.match(/<button[^>]*>/g) || [];
    expect(buttons.length).toBeGreaterThanOrEqual(3);
    for (const b of buttons) expect(b).toMatch(/aria-label="[^"]+"/);
    expect(composer).toContain('aria-haspopup="menu"');
  });

  test("never claims the customer is active now: Meta gives a Page no presence data", () => {
    const recent = new Date(Date.now() - 60_000).toISOString();
    const html = renderToStaticMarkup(
      React.createElement(ChannelChat, {
        channel: { id: "messenger", name: "Messenger", theme },
        conversation: { id: "c1", name: "Ahmed Adel", channel: "messenger", lastCustomerMessageAt: recent, messages: [msg("m1", { text: "a", createdAt: recent })] },
        lang: "ar",
        t: (k, d) => d || k,
        onSend() {},
        onReact() {},
      }),
    );
    expect(html).not.toContain("نشط الآن");
    expect(html).not.toContain("Active now");
  });
});
