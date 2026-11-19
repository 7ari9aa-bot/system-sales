import { describe, expect, it } from "vitest";
import { ACCEPT, checkFile, mimeOf } from "./channelAttachments";

const MB = 1024 * 1024;
const file = (name, type, size = 1000) => ({ name, type, size });
const ok = (f, channel) => checkFile(f, { channel, lang: "en" });

describe("Messenger accepts any file and says how big", () => {
  it("classifies images, audio, video and documents", () => {
    expect(ok(file("a.png", "image/png"), "messenger")).toMatchObject({ ok: true, kind: "image" });
    expect(ok(file("a.mp3", "audio/mpeg"), "messenger")).toMatchObject({ ok: true, kind: "audio" });
    expect(ok(file("a.mp4", "video/mp4"), "messenger")).toMatchObject({ ok: true, kind: "video" });
    expect(ok(file("a.pdf", "application/pdf"), "messenger")).toMatchObject({ ok: true, kind: "document" });
  });
  it("carries any other type as a plain document, including Word", () => {
    const docx = file("o.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document");
    expect(ok(docx, "messenger")).toMatchObject({ ok: true, kind: "document" });
  });
  it("refuses a page, a script or a program", () => {
    for (const type of ["text/html", "image/svg+xml", "application/x-msdownload"]) {
      expect(ok(file("x", type), "messenger").ok).toBe(false);
    }
  });
  it("limits an image to 8 MB and the rest to 25 MB", () => {
    expect(ok(file("a.png", "image/png", 8 * MB), "messenger").ok).toBe(true);
    expect(ok(file("a.png", "image/png", 8 * MB + 1), "messenger")).toMatchObject({ ok: false, error: expect.stringContaining("8 MB") });
    expect(ok(file("a.pdf", "application/pdf", 25 * MB), "messenger").ok).toBe(true);
    expect(ok(file("a.pdf", "application/pdf", 25 * MB + 1), "messenger")).toMatchObject({ ok: false, error: expect.stringContaining("25 MB") });
    expect(ok(file("a.mp4", "video/mp4", 9 * MB), "messenger").ok).toBe(true);
  });
});

describe("Telegram accepts only what it delivers from a link", () => {
  it("takes images, mp4, mp3 and m4a, pdf and zip", () => {
    for (const [name, type] of [["a.jpg", "image/jpeg"], ["a.webp", "image/webp"], ["a.mp4", "video/mp4"], ["a.mp3", "audio/mpeg"], ["a.m4a", "audio/mp4"], ["a.pdf", "application/pdf"], ["a.zip", "application/zip"]]) {
      expect(ok(file(name, type), "telegram").ok, name).toBe(true);
    }
  });
  it("refuses Word, Excel, plain text and a MOV, and names what works", () => {
    for (const [name, type] of [["o.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"], ["o.xlsx", "application/vnd.ms-excel"], ["o.txt", "text/plain"], ["a.mov", "video/quicktime"]]) {
      const r = ok(file(name, type), "telegram");
      expect(r.ok, name).toBe(false);
      expect(r.error).toContain("PDF");
    }
  });
  it("limits a photo to 5 MB and the rest to 20 MB", () => {
    expect(ok(file("a.png", "image/png", 5 * MB), "telegram").ok).toBe(true);
    expect(ok(file("a.png", "image/png", 5 * MB + 1), "telegram")).toMatchObject({ ok: false, error: expect.stringContaining("5 MB") });
    expect(ok(file("a.mp4", "video/mp4", 6 * MB), "telegram").ok).toBe(true);
    expect(ok(file("a.mp4", "video/mp4", 20 * MB + 1), "telegram")).toMatchObject({ ok: false, error: expect.stringContaining("20 MB") });
  });
});

describe("shared rules", () => {
  it("refuses an empty file and an unknown channel", () => {
    expect(ok(file("a.pdf", "application/pdf", 0), "telegram")).toMatchObject({ ok: false, error: "The file is empty." });
    expect(ok(file("a.pdf", "application/pdf"), "whatsapp").ok).toBe(false);
  });
  it("reads the type from the extension when the browser leaves it empty", () => {
    expect(mimeOf(file("scan.PDF", ""))).toBe("application/pdf");
    expect(mimeOf(file("x.jpg", "application/octet-stream"))).toBe("image/jpeg");
    expect(mimeOf(file("x.jpg", "image/jpg"))).toBe("image/jpeg");
    expect(ok(file("scan.pdf", ""), "telegram").ok).toBe(true);
  });
  it("answers in Arabic", () => {
    expect(checkFile(file("a.png", "image/png", 6 * MB), { channel: "telegram", lang: "ar" }).error).toMatch(/تيليجرام.*5 ميجابايت/);
  });
  it("gives the Telegram picker only what it delivers, and Messenger's picker everything", () => {
    expect(ACCEPT.telegram).toContain(".pdf");
    expect(ACCEPT.telegram).not.toContain(".docx");
    expect(ACCEPT.messenger).toBe("");
  });
});
