import { describe, expect, it } from "vitest";
import {
  MAX_BYTES, CAPTION_MAX, canCaption, checkFile, fileSizeLabel, formatDuration, kindOf, mimeOf, pickRecordingType,
} from "./attachments";

const file = (name, type, size = 1000) => ({ name, type, size });
const MB = 1024 * 1024;

describe("what kind of file it is", () => {
  it.each([
    ["a.jpg", "image/jpeg", "image"], ["a.png", "image/png", "image"], ["a.pdf", "application/pdf", "document"],
    ["a.mp4", "video/mp4", "video"], ["a.ogg", "audio/ogg", "audio"], ["a.txt", "text/plain", "document"],
  ])("%s is a %s", (name, type, kind) => expect(kindOf(file(name, type))).toBe(kind));

  it("treats image/jpg as image/jpeg", () => expect(mimeOf(file("a.jpg", "image/jpg"))).toBe("image/jpeg"));
  it("ignores codec parameters", () => expect(kindOf(file("v.ogg", "audio/ogg; codecs=opus"))).toBe("audio"));

  it("falls back to the extension when the browser gives no type", () => {
    expect(kindOf(file("report.docx", ""))).toBe("document");
    expect(kindOf(file("PHOTO.JPG", ""))).toBe("image");
  });

  it("does not guess for types WhatsApp does not carry", () => {
    for (const [n, t] of [["a.svg", "image/svg+xml"], ["a.html", "text/html"], ["a.zip", "application/zip"], ["a.gif", "image/gif"], ["a.exe", ""]]) {
      expect(kindOf(file(n, t))).toBeNull();
    }
  });

  it("only a WebP can be a sticker", () => {
    expect(kindOf(file("s.webp", "image/webp"), { asSticker: true })).toBe("sticker");
    expect(kindOf(file("s.png", "image/png"), { asSticker: true })).toBe("image");
  });
});

describe("checking a file before upload", () => {
  it("accepts a normal file", () => expect(checkFile(file("a.jpg", "image/jpeg", 2 * MB))).toEqual({ ok: true, kind: "image", mime: "image/jpeg" }));

  it("refuses an unsupported type, in the chosen language", () => {
    expect(checkFile(file("a.zip", "application/zip"), { lang: "ar" }).error).toMatch(/واتساب/);
    expect(checkFile(file("a.zip", "application/zip"), { lang: "en" }).error).toMatch(/cannot be sent/);
  });

  it("refuses an empty file", () => expect(checkFile(file("a.pdf", "application/pdf", 0)).ok).toBe(false));

  it("uses each kind's own limit", () => {
    expect(checkFile(file("a.jpg", "image/jpeg", MAX_BYTES.image + 1)).ok).toBe(false);
    expect(checkFile(file("a.jpg", "image/jpeg", MAX_BYTES.image)).ok).toBe(true);
    expect(checkFile(file("a.pdf", "application/pdf", 20 * MB)).ok).toBe(true);
    expect(checkFile(file("a.pdf", "application/pdf", 26 * MB)).ok).toBe(false);
    expect(checkFile(file("a.mp4", "video/mp4", 17 * MB)).ok).toBe(false);
  });

  it("names the limit in the message", () => {
    expect(checkFile(file("a.jpg", "image/jpeg", 6 * MB), { lang: "en" }).error).toContain("5 MB");
    expect(checkFile(file("a.jpg", "image/jpeg", 6 * MB), { lang: "ar" }).error).toContain("5 ميجابايت");
  });

  it("a sticker must be a small WebP", () => {
    expect(checkFile(file("s.png", "image/png"), { asSticker: true }).ok).toBe(false);
    expect(checkFile(file("s.webp", "image/webp", 101 * 1024), { asSticker: true }).ok).toBe(false);
    expect(checkFile(file("s.webp", "image/webp", 50 * 1024), { asSticker: true })).toMatchObject({ ok: true, kind: "sticker" });
  });
});

describe("captions", () => {
  it("exist for images, videos and documents only", () => {
    expect(["image", "video", "document"].every(canCaption)).toBe(true);
    expect(canCaption("audio")).toBe(false);
    expect(canCaption("sticker")).toBe(false);
  });
  it("match the server's limit", () => expect(CAPTION_MAX).toBe(1024));
});

describe("labels", () => {
  it("formats sizes", () => {
    expect(fileSizeLabel(500)).toBe("500 B");
    expect(fileSizeLabel(2048)).toBe("2 KB");
    expect(fileSizeLabel(1.5 * MB)).toBe("1.5 MB");
    expect(fileSizeLabel(12 * MB)).toBe("12 MB");
  });
  it("formats a recording's length", () => {
    expect(formatDuration(0)).toBe("0:00");
    expect(formatDuration(9.9)).toBe("0:09");
    expect(formatDuration(75)).toBe("1:15");
    expect(formatDuration(-3)).toBe("0:00");
  });
});

describe("choosing a recording format", () => {
  it("prefers ogg/opus, then mp4, and never webm", () => {
    expect(pickRecordingType(() => true)).toBe("audio/ogg;codecs=opus");
    expect(pickRecordingType((t) => t === "audio/mp4")).toBe("audio/mp4");
    expect(pickRecordingType((t) => t === "audio/webm")).toBeNull();
    expect(pickRecordingType(undefined)).toBeNull();
  });
});
