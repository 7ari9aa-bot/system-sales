import { describe, expect, test } from "vitest";
import { galleryOf, indexOfMessage, isViewableImage, step } from "./mediaGallery";

const img = (id, extra = {}) => ({ id, mediaType: "image", mediaUrl: `https://x/${id}.jpg`, text: "", time: "٠٨:٠٠", side: "in", ...extra });

describe("isViewableImage", () => {
  test("accepts an image with an address, by type or by extension", () => {
    expect(isViewableImage(img("a"))).toBe(true);
    expect(isViewableImage({ id: "b", mediaUrl: "https://x/p.PNG?sig=1" })).toBe(true);
  });
  test("rejects deleted, address-less and non-image messages", () => {
    expect(isViewableImage(img("a", { deleted: true }))).toBe(false);
    expect(isViewableImage(img("a", { mediaUrl: null }))).toBe(false);
    expect(isViewableImage({ id: "d", mediaType: "document", mediaUrl: "https://x/f.pdf" })).toBe(false);
    expect(isViewableImage({ id: "t", text: "hi" })).toBe(false);
  });
  test("a local preview opens", () => {
    expect(isViewableImage({ id: "p", mediaType: "image", mediaUrl: "blob:http://x/1" })).toBe(true);
  });
});

describe("galleryOf", () => {
  test("keeps only images, in order, with caption and side", () => {
    const g = galleryOf([img("a", { text: "السعر" }), { id: "t", text: "hello" }, img("b", { side: "out" })]);
    expect(g.map((s) => s.id)).toEqual(["a", "b"]);
    expect(g[0].caption).toBe("السعر");
    expect(g[1].side).toBe("out");
  });
  test("does not show a filename or a blob address as the caption", () => {
    expect(galleryOf([img("a", { text: "blob:http://x/1" })])[0].caption).toBe("");
    expect(galleryOf([img("a", { text: "image" })])[0].caption).toBe("");
  });
  test("is empty for no messages", () => {
    expect(galleryOf(undefined)).toEqual([]);
  });
});

describe("indexOfMessage and step", () => {
  const g = galleryOf([img("a"), img("b"), img("c")]);
  test("finds a message, or -1", () => {
    expect(indexOfMessage(g, "b")).toBe(1);
    expect(indexOfMessage(g, "zzz")).toBe(-1);
  });
  test("moves one at a time and stops at both ends", () => {
    expect(step(0, 1, 3)).toBe(1);
    expect(step(2, 1, 3)).toBe(2);
    expect(step(0, -1, 3)).toBe(0);
    expect(step(1, -1, 3)).toBe(0);
  });
  test("an empty gallery has no position", () => {
    expect(step(0, 1, 0)).toBe(-1);
  });
});
