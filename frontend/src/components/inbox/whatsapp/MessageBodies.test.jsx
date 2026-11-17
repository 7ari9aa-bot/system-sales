import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "vitest";
import { ChoiceBody, ContactBody, DocumentBody, LocationBody, PhotoBody, StickerBody, UnsupportedBody, VideoBody } from "./MessageBodies";

const r = (el) => renderToStaticMarkup(el);

describe("message bodies", () => {
  test("a location shows the place and address, and no invented map", () => {
    const out = r(<LocationBody body="📍 Cairo Tower, Gezira, Cairo" lang="en" />);
    expect(out).toContain("Cairo Tower");
    expect(out).toContain("Gezira, Cairo");
    expect(out).not.toMatch(/<img|<iframe|maps\./);
  });
  test("a contact shows the name and number", () => {
    const out = r(<ContactBody body="Ali Hassan +20 100 123 4567" lang="en" />);
    expect(out).toContain("Ali Hassan");
    expect(out).toContain("+20 100 123 4567");
  });
  test("a contact with no number says so instead of leaving a gap", () => {
    expect(r(<ContactBody body="Ali Hassan" lang="en" />)).toContain("No number");
    expect(r(<ContactBody body="[contacts]" lang="en" />)).toContain("Contact");
  });
  test("a document has its name, type badge and a real download link", () => {
    const out = r(<DocumentBody src="https://cdn.x/a/Invoice%20May.pdf" lang="en" />);
    expect(out).toContain("Invoice May.pdf");
    expect(out).toContain("PDF");
    expect(out).toMatch(/<a [^>]*href="https:\/\/cdn.x\/a\/Invoice%20May.pdf"[^>]*rel="noopener noreferrer"/);
    expect(out).toContain('aria-label="Download Invoice May.pdf"');
  });
  test("a document with no link offers no download button", () => {
    expect(r(<DocumentBody label="x.pdf" lang="en" />)).not.toContain("document-download");
  });
  test("a photo is a lazy image; a sticker has no caption chrome", () => {
    expect(r(<PhotoBody src="https://x/p.jpg" lang="en" />)).toContain('loading="lazy"');
    expect(r(<StickerBody src="https://x/s.webp" lang="en" />)).toContain('data-testid="sticker"');
  });
  test("a video waits for a tap before loading anything", () => {
    const out = r(<VideoBody src="https://x/v.mp4" lang="en" />);
    expect(out).toContain('data-testid="play-video"');
    expect(out).not.toContain("<video");
  });
  test("a button tap and a list choice are labelled as the customer's choice", () => {
    expect(r(<ChoiceBody body="Yes, confirm" kind="buttons" lang="en" />)).toContain("Button reply");
    expect(r(<ChoiceBody body="Size M" kind="list" lang="en" />)).toContain("List choice");
  });
  test("an unsupported type says so and offers no raw data", () => {
    const out = r(<UnsupportedBody lang="en" />);
    expect(out).toContain("not supported");
    expect(r(<UnsupportedBody lang="ar" />)).toContain("غير مدعومة");
  });
});
