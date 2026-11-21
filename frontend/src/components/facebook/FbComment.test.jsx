import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import FbComment from "@/components/facebook/FbComment";

const base = { id: "c1", author: "Fihrist", text: "hello there", timeLabel: "5m", likes: 0, replies: [] };
const html = (comment = {}, props = {}) => renderToStaticMarkup(
  <FbComment comment={{ ...base, ...comment }} postId="1_2" pageName="Fihrist" lang="en" actions={{}} {...props} />,
);

describe("a comment written by the Page", () => {
  it("wears Facebook's 'Author' badge, not the page name twice", () => {
    const out = html({ isPage: true });
    expect(out).toContain(">Author<");
    expect(out).not.toContain("· Page");
  });
  it("wears 'كاتب المنشور' in Arabic, as Facebook words it", () => {
    const out = html({ isPage: true }, { lang: "ar" });
    expect(out).toContain(">كاتب المنشور<");
    expect(out).not.toContain("· الصفحة");
  });
  it("leaves the badge off a comment from anyone else", () => {
    expect(html({ isPage: false })).not.toContain(">Author<");
    expect(html({ isPage: false }, { lang: "ar" })).not.toContain("كاتب المنشور");
  });
});
