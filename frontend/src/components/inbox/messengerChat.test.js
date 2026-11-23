import { describe, it, expect } from "vitest";
import {
  MESSENGER_BUBBLE_RADIUS,
  MESSENGER_JOIN_RADIUS,
  messengerBubbleBackground,
  messengerBubbleCorners,
  messengerGroup,
  messengerSeen,
  messengerSeenMessageId,
} from "./messengerChat";

const at = (minutes, extra = {}) => ({
  id: `m${minutes}`,
  side: "out",
  createdAt: new Date(Date.UTC(2026, 10, 22, 10, minutes)).toISOString(),
  ...extra,
});

describe("messengerGroup", () => {
  it("joins two own messages sent within the gap and squares only the touching corners", () => {
    const list = [at(0), at(1), at(1, { side: "in", id: "in1" })];
    const first = messengerGroup(list, 0);
    const second = messengerGroup(list, 1);
    expect(first).toMatchObject({ first: true, last: false, size: 2 });
    expect(second).toMatchObject({ first: false, last: true, size: 2 });
    expect(messengerBubbleCorners({ out: true, ...first })).toBe("rounded-ee-[4px]");
    expect(messengerBubbleCorners({ out: true, ...second })).toBe("rounded-se-[4px]");
  });

  it("never joins a message across the 3 minute gap", () => {
    const list = [at(0), at(5)];
    expect(messengerGroup(list, 1)).toMatchObject({ first: true, last: true, alone: true });
  });

  it("never joins across sides or around a system message", () => {
    const list = [at(0), at(1, { side: "in" })];
    expect(messengerGroup(list, 1)).toMatchObject({ alone: true });
    const withSystem = [at(0), at(1, { senderType: "system" }), at(2)];
    expect(messengerGroup(withSystem, 2)).toMatchObject({ first: true });
  });

  it("treats a missing timestamp as its own group", () => {
    const list = [{ id: "a", side: "out" }, { id: "b", side: "out" }];
    expect(messengerGroup(list, 1)).toMatchObject({ alone: true });
  });
});

describe("messengerBubbleCorners", () => {
  it("squares the inline-start corners for a received group", () => {
    expect(messengerBubbleCorners({ out: false, first: true, last: false })).toBe("rounded-es-[4px]");
    expect(messengerBubbleCorners({ out: false, first: false, last: true })).toBe("rounded-ss-[4px]");
  });

  it("draws a lone bubble with no squared corner", () => {
    expect(messengerBubbleCorners({ out: true, first: true, last: true })).toBe("");
  });

  it("keeps Messenger's 18px bubble and 4px join", () => {
    expect(MESSENGER_BUBBLE_RADIUS).toBe(18);
    expect(MESSENGER_JOIN_RADIUS).toBe(4);
  });
});

describe("messengerBubbleBackground", () => {
  const theme = { accent: "#0084FF", gradient: ["#00B2FF", "#006AFF"], in: "#F0F0F0" };

  it("paints an outgoing bubble with the theme gradient", () => {
    expect(messengerBubbleBackground(theme, true)).toBe("linear-gradient(135deg, #00B2FF, #006AFF)");
  });

  it("paints an incoming bubble flat grey", () => {
    expect(messengerBubbleBackground(theme, false)).toBe("#F0F0F0");
  });

  it("falls back to the accent when a theme carries no gradient", () => {
    expect(messengerBubbleBackground({ accent: "#8B5CF6" }, true)).toBe("#8B5CF6");
    expect(messengerBubbleBackground(null, true)).toBe("#0084FF");
  });
});

describe("messengerSeen", () => {
  it("only counts read, because Messenger draws no delivered tick", () => {
    expect(messengerSeen("read")).toBe(true);
    expect(messengerSeen("delivered")).toBe(false);
    expect(messengerSeen("sent")).toBe(false);
  });

  it("marks the newest own message that was read", () => {
    const list = [
      { id: "a", side: "out", status: "read" },
      { id: "b", side: "out", status: "sent" },
      { id: "c", side: "in", status: "read" },
    ];
    expect(messengerSeenMessageId(list)).toBeNull();
    expect(messengerSeenMessageId([...list.slice(0, 2), { id: "d", side: "out", status: "read" }])).toBe("d");
  });
});


import {
  messengerIsBigEmoji,
  messengerQuoteText,
  messengerTimeDivider,
} from "./messengerChat";

describe("messengerIsBigEmoji", () => {
  it("is true for a lone thumbs-up or a short run of emoji, which Messenger draws without a bubble", () => {
    expect(messengerIsBigEmoji("👍")).toBe(true);
    expect(messengerIsBigEmoji(" 👍 ")).toBe(true);
    expect(messengerIsBigEmoji("😂😂😂")).toBe(true);
  });

  it("is false for text, mixed text and emoji, empty values and long runs", () => {
    expect(messengerIsBigEmoji("ok 👍")).toBe(false);
    expect(messengerIsBigEmoji("")).toBe(false);
    expect(messengerIsBigEmoji(null)).toBe(false);
    expect(messengerIsBigEmoji("😂😂😂😂😂😂")).toBe(false);
    expect(messengerIsBigEmoji("123")).toBe(false);
  });
});

describe("messengerQuoteText", () => {
  it("uses the quoted body, then its text", () => {
    expect(messengerQuoteText({ body: "hello" })).toBe("hello");
    expect(messengerQuoteText({ text: "hi" })).toBe("hi");
  });

  it("names a media quote by its kind instead of printing nothing", () => {
    expect(messengerQuoteText({ content_type: "image" }, "ar")).toBe("صورة");
    expect(messengerQuoteText({ content_type: "image" }, "en")).toBe("Photo");
    expect(messengerQuoteText({ content_type: "voice" }, "en")).toBe("Voice message");
  });

  it("says nothing about a message the provider no longer has", () => {
    expect(messengerQuoteText({ available: false })).toBe("…");
    expect(messengerQuoteText(null)).toBe("");
  });
});

describe("messengerTimeDivider", () => {
  const msg = (iso) => ({ createdAt: iso });

  it("shows a divider before the first message", () => {
    expect(messengerTimeDivider([msg("2026-11-22T10:00:00Z")], 0)).toBe(true);
  });

  it("shows none while messages are less than 15 minutes apart", () => {
    const list = [msg("2026-11-22T10:00:00Z"), msg("2026-11-22T10:10:00Z")];
    expect(messengerTimeDivider(list, 1)).toBe(false);
  });

  it("shows one after a longer pause, as Messenger does", () => {
    const list = [msg("2026-11-22T10:00:00Z"), msg("2026-11-22T10:20:00Z")];
    expect(messengerTimeDivider(list, 1)).toBe(true);
  });

  it("shows one when the clock is unreadable, never hides a gap it cannot measure", () => {
    expect(messengerTimeDivider([msg("2026-11-22T10:00:00Z"), {}], 1)).toBe(true);
  });
});

import { messengerSharedItems } from "./messengerChat";

describe("messengerSharedItems", () => {
  const list = [
    { id: "1", text: "hi" },
    { id: "2", mediaType: "image", mediaUrl: "https://x/a.jpg" },
    { id: "3", contentType: "video", mediaUrl: "https://x/v.mp4" },
    { id: "4", contentType: "file", mediaUrl: "https://x/f.pdf", fileName: "f.pdf" },
    { id: "5", text: "see https://shop.example/p/1 now" },
    { id: "6", contentType: "voice", mediaUrl: "https://x/a.ogg" },
  ];

  it("splits the thread into media, files and links from what was really sent", () => {
    const out = messengerSharedItems(list);
    expect(out.media.map((m) => m.id)).toEqual(["2", "3"]);
    expect(out.files.map((m) => m.id)).toEqual(["4", "6"]);
    expect(out.links).toEqual([{ id: "5", url: "https://shop.example/p/1" }]);
  });

  it("is empty for a thread with nothing shared, and never invents items", () => {
    expect(messengerSharedItems([{ id: "1", text: "hi" }])).toEqual({ media: [], files: [], links: [] });
    expect(messengerSharedItems(null)).toEqual({ media: [], files: [], links: [] });
  });
});

import { messengerReactionSummary } from "./messengerChat";

describe("messengerReactionSummary", () => {
  it("lists each emoji once, in order, with how many people used it", () => {
    expect(messengerReactionSummary(["❤️", "😂", "❤️"])).toEqual({ emojis: ["❤️", "😂"], count: 3 });
  });

  it("ignores empty and withdrawn markers, so a removed reaction leaves no badge", () => {
    expect(messengerReactionSummary(["\u200b-", "", null, "👍"])).toEqual({ emojis: ["👍"], count: 1 });
    expect(messengerReactionSummary(["\u200b-"])).toBeNull();
  });

  it("is null when there is nothing to show", () => {
    expect(messengerReactionSummary([])).toBeNull();
    expect(messengerReactionSummary(undefined)).toBeNull();
  });
});

import { messengerStatusLine } from "./messengerChat";

describe("messengerStatusLine", () => {
  const now = Date.UTC(2026, 10, 23, 12, 0);
  const ago = (ms) => new Date(now - ms).toISOString();
  const sent = (status, ms, extra = {}) => ({ id: "m", side: "out", status, createdAt: ago(ms), ...extra });

  it("names only the state the platform really knows, with how long ago", () => {
    expect(messengerStatusLine([sent("sent", 5 * 60e3)], "ar", now)).toBe("تم الإرسال منذ 5 د");
    expect(messengerStatusLine([sent("delivered", 3 * 3600e3)], "ar", now)).toBe("تم التسليم منذ 3 س");
    expect(messengerStatusLine([sent("read", 2 * 86400e3)], "ar", now)).toBe("تمت المشاهدة منذ 2 يوم");
    expect(messengerStatusLine([sent("sent", 5 * 60e3)], "en", now)).toBe("Sent 5m ago");
    expect(messengerStatusLine([sent("read", 60e3)], "en", now)).toBe("Seen 1m ago");
  });

  it("says 'just now' inside the first minute", () => {
    expect(messengerStatusLine([sent("sent", 20e3)], "ar", now)).toBe("تم الإرسال الآن");
    expect(messengerStatusLine([sent("sent", 20e3)], "en", now)).toBe("Sent just now");
  });

  it("looks at the newest sent message only, and says nothing once the customer wrote after it", () => {
    const list = [sent("read", 9e5), { id: "c", side: "in", createdAt: ago(1e5) }];
    expect(messengerStatusLine(list, "ar", now)).toBeNull();
  });

  it("says nothing for a failed, pending or system message, or an empty thread", () => {
    expect(messengerStatusLine([sent("failed", 6e4)], "ar", now)).toBeNull();
    expect(messengerStatusLine([sent("queued", 6e4)], "ar", now)).toBeNull();
    expect(messengerStatusLine([sent("sent", 6e4, { senderType: "system" })], "ar", now)).toBeNull();
    expect(messengerStatusLine([], "ar", now)).toBeNull();
  });
});

import { messengerRowPreview } from "./messengerChat";

describe("messengerRowPreview", () => {
  it("puts 'You:' before a message we sent, as the Messenger list does", () => {
    expect(messengerRowPreview({ preview: "تمام", lastDirection: "outbound" }, "ar")).toBe("أنت: تمام");
    expect(messengerRowPreview({ preview: "ok", lastDirection: "outbound" }, "en")).toBe("You: ok");
  });

  it("leaves a customer's message as it is", () => {
    expect(messengerRowPreview({ preview: "السلام", lastDirection: "inbound" }, "ar")).toBe("السلام");
    expect(messengerRowPreview({ preview: "hi" }, "en")).toBe("hi");
  });

  it("is empty when there is no preview, never just 'You:'", () => {
    expect(messengerRowPreview({ preview: "", lastDirection: "outbound" }, "ar")).toBe("");
    expect(messengerRowPreview(null, "ar")).toBe("");
  });
});

import { messengerMessageShape } from "./messengerChat";

describe("messengerMessageShape", () => {
  it("a MIME type such as image/jpeg or video/mp4 is media even when the address has no extension", () => {
    expect(messengerMessageShape({ mediaUrl: "https://cdn.example/abc", contentType: "image/jpeg" })).toBe("photo");
    expect(messengerMessageShape({ mediaUrl: "https://cdn.example/abc", contentType: "video/mp4" })).toBe("video");
    expect(messengerMessageShape({ mediaUrl: "https://cdn.example/abc", contentType: "application/pdf" })).toBe("file");
  });

  it("a system line is centred grey text, whatever else it carries", () => {
    expect(messengerMessageShape({ senderType: "system", text: "x" })).toBe("system");
  });

  it("a deleted message is the 'removed' line, even if it still has media", () => {
    expect(messengerMessageShape({ deleted: true, text: "x", mediaUrl: "https://x/a.jpg" })).toBe("deleted");
  });

  it("a photo or video stands without a bubble; a file is a card; a sticker is bare", () => {
    expect(messengerMessageShape({ mediaUrl: "https://x/a.jpg", mediaType: "image" })).toBe("photo");
    expect(messengerMessageShape({ mediaUrl: "https://x/a.mp4", mediaType: "video" })).toBe("video");
    expect(messengerMessageShape({ mediaUrl: "https://x/a.pdf", contentType: "file" })).toBe("file");
    expect(messengerMessageShape({ mediaUrl: "https://x/s.png", mediaType: "sticker" })).toBe("sticker");
  });

  it("a photo that has not finished uploading has no URL yet and stays a bubble", () => {
    expect(messengerMessageShape({ text: "caption", mediaType: "image" })).toBe("text");
  });

  it("audio, a lone emoji and plain text keep their own looks", () => {
    expect(messengerMessageShape({ mediaType: "audio", mediaUrl: "https://x/a.ogg" })).toBe("audio");
    expect(messengerMessageShape({ text: "🎤 0:03" })).toBe("audio");
    expect(messengerMessageShape({ text: "👍" })).toBe("bigEmoji");
    expect(messengerMessageShape({ text: "hello" })).toBe("text");
  });
});

import { messengerLinkParts, messengerLinkHost } from "./messengerChat";

describe("links inside a Messenger bubble", () => {
  it("splits the words from the web addresses so only the address is a link", () => {
    expect(messengerLinkParts("شوف https://shop.example/p/1 ده")).toEqual([
      { type: "text", value: "شوف " },
      { type: "link", value: "https://shop.example/p/1" },
      { type: "text", value: " ده" },
    ]);
  });

  it("leaves plain text and an empty message alone", () => {
    expect(messengerLinkParts("اهلا")).toEqual([{ type: "text", value: "اهلا" }]);
    expect(messengerLinkParts("")).toEqual([]);
    expect(messengerLinkParts(null)).toEqual([]);
  });

  it("names the site without www, and nothing when the address is unreadable", () => {
    expect(messengerLinkHost("https://www.shop.example/p/1")).toBe("shop.example");
    expect(messengerLinkHost("https://shop.example")).toBe("shop.example");
    expect(messengerLinkHost("not a url")).toBe("");
    expect(messengerLinkHost("javascript:alert(1)")).toBe("");
  });
});

import { messengerClockTime } from "./messengerChat";

describe("messengerClockTime", () => {
  it("prints a 12-hour time with no leading zero and the day period, like Messenger", () => {
    // 2026-11-23T00:37:52Z is 02:37 in Cairo (UTC+2)
    expect(messengerClockTime("2026-11-23T00:37:52Z", "ar", "Africa/Cairo")).toMatch(/^[2٢]:[3٣][7٧] ص$/);
    expect(messengerClockTime("2026-11-23T00:37:52Z", "en", "Africa/Cairo")).toBe("2:37 AM");
    expect(messengerClockTime("2026-11-23T13:05:00Z", "en", "Africa/Cairo")).toBe("3:05 PM");
  });

  it("returns an empty string for a missing or unreadable time", () => {
    expect(messengerClockTime(null, "ar")).toBe("");
    expect(messengerClockTime("not a date", "en")).toBe("");
  });
});

