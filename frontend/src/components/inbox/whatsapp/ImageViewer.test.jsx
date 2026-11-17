import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "vitest";
import ImageViewer from "./ImageViewer";

const slide = (id, extra = {}) => ({ id, url: `https://x/${id}.jpg`, caption: "", time: "٠٨:٠٠", side: "in", ...extra });
const render = (props) => renderToStaticMarkup(React.createElement(ImageViewer, { lang: "ar", onClose() {}, ...props }));

describe("ImageViewer", () => {
  test("opens on the image that was clicked, as a modal dialog", () => {
    const html = render({ gallery: [slide("a"), slide("b"), slide("c")], startId: "b" });
    expect(html).toContain('role="dialog"');
    expect(html).toContain('aria-modal="true"');
    expect(html).toContain("https://x/b.jpg");
    expect(html).not.toContain("https://x/a.jpg");
  });

  test("shows the position, and nothing about position for a single photo", () => {
    expect(render({ gallery: [slide("a"), slide("b"), slide("c")], startId: "b" })).toContain("2 من 3");
    const single = render({ gallery: [slide("a")], startId: "a" });
    expect(single).not.toContain("من 1");
    expect(single).not.toContain("viewer-prev");
    expect(single).not.toContain("viewer-next");
  });

  test("disables the arrow that has nowhere to go", () => {
    const first = render({ gallery: [slide("a"), slide("b")], startId: "a" });
    expect(first).toMatch(/<button[^>]*disabled=""[^>]*data-testid="viewer-prev"|data-testid="viewer-prev"[^>]*disabled=""/);
    expect(first).not.toMatch(/data-testid="viewer-next"[^>]*disabled=""/);
  });

  test("labels who sent it, with the caption and a download link to the file", () => {
    const html = render({ gallery: [slide("a", { side: "out", caption: "السعر النهائي" })], startId: "a" });
    expect(html).toContain("أنت");
    expect(html).toContain("السعر النهائي");
    expect(html).toMatch(/href="https:\/\/x\/a\.jpg"[^>]*download|download[^>]*href="https:\/\/x\/a\.jpg"/);
    expect(html).toContain('rel="noopener noreferrer"');
  });

  test("an incoming photo is attributed to the customer", () => {
    expect(render({ gallery: [slide("a")], startId: "a" })).toContain("العميل");
  });

  test("follows the language: Arabic reads right to left, English left to right", () => {
    expect(render({ gallery: [slide("a")], startId: "a" })).toContain('dir="rtl"');
    const en = render({ gallery: [slide("a")], startId: "a", lang: "en" });
    expect(en).toContain('dir="ltr"');
    expect(en).toContain('aria-label="Close"');
  });

  test("falls back to the first photo when the opened one is not in the gallery", () => {
    expect(render({ gallery: [slide("a"), slide("b")], startId: "gone" })).toContain("https://x/a.jpg");
  });

  test("renders nothing for an empty gallery rather than an empty dark screen", () => {
    expect(render({ gallery: [], startId: "a" })).toBe("");
  });
});
