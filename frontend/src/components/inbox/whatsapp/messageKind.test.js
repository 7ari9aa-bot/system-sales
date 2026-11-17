import { describe, expect, test } from "vitest";
import { displayBody, fileExtension, fileNameOf, messageKind, parseContact, parseLocation } from "./messageKind";

describe("messageKind", () => {
  test.each([
    [{ contentType: "text" }, "text"],
    [{}, "text"],
    [{ contentType: "location", text: "📍 x" }, "location"],
    [{ contentType: "contact" }, "contact"],
    [{ contentType: "buttons" }, "buttons"],
    [{ contentType: "list" }, "list"],
    [{ contentType: "unsupported", text: '{"type":"order"}' }, "unsupported"],
    [{ contentType: "voice", mediaType: "audio" }, "voice"],
    [{ contentType: "image", mediaType: "sticker" }, "sticker"],
    [{ contentType: "video" }, "video"],
    [{ contentType: "file", mediaType: "document" }, "document"],
    [{ contentType: "image", mediaType: "image" }, "image"],
  ])("%j is %s", (m, kind) => expect(messageKind(m)).toBe(kind));

  test("falls back to the file extension when the type is missing", () => {
    expect(messageKind({ mediaUrl: "https://x/y/photo.JPG?sig=1" })).toBe("image");
    expect(messageKind({ mediaUrl: "https://x/y/clip.mp4" })).toBe("video");
    expect(messageKind({ mediaUrl: "https://x/y/note.ogg" })).toBe("voice");
    expect(messageKind({ mediaUrl: "https://x/y/invoice.pdf" })).toBe("document");
  });
  test("a sticker is told apart from a photo by its media type", () => {
    expect(messageKind({ contentType: "image", mediaType: "sticker", mediaUrl: "https://x/s.webp" })).toBe("sticker");
  });
});

describe("parseLocation", () => {
  test("splits the title from the address and drops the emoji", () => {
    expect(parseLocation("📍 Cairo Tower, Gezira, Cairo")).toEqual({ title: "Cairo Tower", address: "Gezira, Cairo" });
    expect(parseLocation("📍 Home")).toEqual({ title: "Home", address: "" });
  });
  test("handles an empty or missing body", () => {
    expect(parseLocation("")).toEqual({ title: "", address: "" });
    expect(parseLocation(undefined)).toEqual({ title: "", address: "" });
    expect(parseLocation("📍")).toEqual({ title: "", address: "" });
  });
});

describe("parseContact", () => {
  test("separates the name from the number", () => {
    expect(parseContact("Ali Hassan +20 100 123 4567")).toEqual({ name: "Ali Hassan", phone: "+20 100 123 4567" });
    expect(parseContact("Mona 01001234567")).toEqual({ name: "Mona", phone: "01001234567" });
  });
  test("keeps a name with no number, and treats the placeholder as empty", () => {
    expect(parseContact("Ali Hassan")).toEqual({ name: "Ali Hassan", phone: "" });
    expect(parseContact("[contacts]")).toEqual({ name: "", phone: "" });
    expect(parseContact("")).toEqual({ name: "", phone: "" });
  });
  test("does not mistake a short number inside a name for a phone", () => {
    expect(parseContact("Shop 24")).toEqual({ name: "Shop 24", phone: "" });
  });
});

describe("fileNameOf / fileExtension", () => {
  test("reads a decoded name from a URL", () => {
    expect(fileNameOf("https://cdn.x/a/Invoice%20May.pdf?sig=abc")).toBe("Invoice May.pdf");
    expect(fileNameOf("", "Document")).toBe("Document");
    expect(fileNameOf(null, "Document")).toBe("Document");
  });
  test("names the extension for the badge", () => {
    expect(fileExtension("Invoice May.pdf")).toBe("PDF");
    expect(fileExtension("noext")).toBe("");
  });
});

describe("displayBody", () => {
  test("never shows the raw JSON of a provider type we do not understand", () => {
    expect(displayBody({ contentType: "unsupported", text: '{"type":"order","order":{}}' })).toBe("");
    expect(displayBody({ contentType: "text", text: "hello" })).toBe("hello");
    expect(displayBody({ text: undefined })).toBe("");
  });
});

import { looksLikeFileName } from "./messageKind";
describe("looksLikeFileName", () => {
  test("recognises a bare file name but not a sentence", () => {
    expect(looksLikeFileName("Invoice.pdf")).toBe(true);
    expect(looksLikeFileName("report_2026.xlsx")).toBe(true);
    expect(looksLikeFileName("here is the invoice.pdf")).toBe(false);
    expect(looksLikeFileName("Thanks.")).toBe(false);
    expect(looksLikeFileName("")).toBe(false);
  });
});
