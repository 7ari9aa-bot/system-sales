import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import FacebookNewPostDialog from "@/components/facebook/FacebookNewPostDialog";

const html = (lang = "en") => renderToStaticMarkup(<FacebookNewPostDialog lang={lang} onPublish={() => {}} onClose={() => {}} />);

describe("the Create post box", () => {
  it("is a labelled dialog that cannot post an empty post", () => {
    const out = html();
    expect(out).toContain('role="dialog"');
    expect(out).toContain('aria-label="Create post"');
    expect([...out.matchAll(/<button\b[^>]*type="submit"[^>]*>/g)][0][0]).toContain("disabled");
  });
  it("lets several pictures be picked at once, for an album", () => {
    const input = html().match(/<input\b[^>]*data-testid="fb-picture-input"[^>]*>/)[0];
    expect(input).toContain("multiple");
    expect(input).toContain("image/jpeg");
  });
  it("shows no album until a picture is chosen", () => {
    expect(html()).not.toContain('data-testid="fb-album"');
  });
  it("is the same box in Arabic", () => {
    expect(html("ar")).toContain('aria-label="إنشاء منشور"');
  });
});
