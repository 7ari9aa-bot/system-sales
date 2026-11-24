import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "vitest";
import IgAttachPreview from "./IgAttachPreview";

const file = { name: "price-list.pdf", size: 2048, type: "application/pdf" };
const html = (props = {}) => renderToStaticMarkup(<IgAttachPreview file={file} kind="document" {...props} />);

describe("Instagram attachment preview", () => {
  test("carries a caption field, as Instagram's own preview does", () => {
    expect(html()).toContain('data-testid="ig-attach-caption"');
    expect(html({ lang: "en" })).toContain("Write a caption...");
    expect(html({ lang: "ar" })).toContain("اكتب تعليقًا...");
  });

  test("the send button stays put beside the caption", () => {
    const markup = html({ lang: "en" });
    expect(markup).toContain('data-testid="ig-attach-send"');
    expect(markup.indexOf('data-testid="ig-attach-caption"')).toBeLessThan(markup.indexOf('data-testid="ig-attach-send"'));
  });

  test("a busy upload locks the caption field too", () => {
    expect(html({ busy: true })).toContain("disabled");
  });
});
