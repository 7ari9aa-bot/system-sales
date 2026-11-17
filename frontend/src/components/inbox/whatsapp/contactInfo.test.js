import { describe, expect, test } from "vitest";
import { countsOf, displayPhone, docsOf, hostOf, linksIn, mediaOf, sharedLinksOf } from "./contactInfo";

const m = (o) => ({ id: o.id, text: "", createdAt: "2026-11-17T10:00:00Z", ...o });

describe("linksIn", () => {
  test("finds links and leaves sentence punctuation out of them", () => {
    expect(linksIn("شوف https://shop.example.com/p/1، وكمان http://a.io/x.")).toEqual(["https://shop.example.com/p/1", "http://a.io/x"]);
  });
  test("ignores text with no link and bad input", () => {
    expect(linksIn("no link here")).toEqual([]);
    expect(linksIn(null)).toEqual([]);
  });
  test("does not treat a bare domain as a link", () => {
    expect(linksIn("visit example.com now")).toEqual([]);
  });
});

describe("hostOf", () => {
  test("drops www and survives garbage", () => {
    expect(hostOf("https://www.example.com/a?b=1")).toBe("example.com");
    expect(hostOf("not a url")).toBe("not a url");
  });
});

describe("mediaOf", () => {
  const msgs = [
    m({ id: "1", contentType: "image", mediaUrl: "u1", createdAt: "2026-11-17T08:00:00Z" }),
    m({ id: "2", contentType: "video", mediaUrl: "u2", createdAt: "2026-11-17T09:00:00Z" }),
    m({ id: "3", contentType: "image", mediaUrl: "u3", deleted: true }),
    m({ id: "4", contentType: "image", mediaUrl: null }),
    m({ id: "5", contentType: "voice", mediaUrl: "u5" }),
  ];
  test("keeps photos and videos, newest first, and skips deleted, missing and voice", () => {
    expect(mediaOf(msgs).map((x) => x.id)).toEqual(["2", "1"]);
    expect(mediaOf(msgs)[0].kind).toBe("video");
  });
});

describe("docsOf", () => {
  test("keeps files that have a url and are not deleted", () => {
    const out = docsOf([m({ id: "1", contentType: "file", mediaUrl: "d1", text: "invoice.pdf" }), m({ id: "2", contentType: "file", mediaUrl: null }), m({ id: "3", contentType: "file", mediaUrl: "d3", deleted: true })]);
    expect(out.map((d) => d.id)).toEqual(["1"]);
    expect(out[0].name).toBe("invoice.pdf");
  });
});

describe("sharedLinksOf", () => {
  test("lists each link once, newest first, skipping deleted messages and reactions", () => {
    const out = sharedLinksOf([
      m({ id: "1", text: "https://a.io/x", createdAt: "2026-11-17T08:00:00Z" }),
      m({ id: "2", text: "again https://a.io/x and https://b.io", createdAt: "2026-11-17T09:00:00Z" }),
      m({ id: "3", text: "https://hidden.io", deleted: true }),
      m({ id: "4", text: "https://react.io", contentType: "reaction" }),
    ]);
    expect(out.map((l) => l.url)).toEqual(["https://a.io/x", "https://b.io"]);
    expect(out[0].host).toBe("a.io");
  });
});

describe("countsOf and displayPhone", () => {
  test("counts each tab", () => {
    expect(countsOf([m({ id: "1", contentType: "image", mediaUrl: "u" }), m({ id: "2", text: "https://a.io" })])).toEqual({ media: 1, docs: 0, links: 1 });
    expect(countsOf(undefined)).toEqual({ media: 0, docs: 0, links: 0 });
  });
  test("formats an Egyptian mobile and never invents a number", () => {
    expect(displayPhone("201001234567")).toBe("+20 100 123 4567");
    expect(displayPhone("+201001234567")).toBe("+20 100 123 4567");
    expect(displayPhone("+14155550123")).toBe("+14155550123");
    expect(displayPhone("")).toBe("");
    expect(displayPhone(null)).toBe("");
  });
});
