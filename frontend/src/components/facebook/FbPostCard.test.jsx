import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import FbPostCard from "@/components/facebook/FbPostCard";

const post = { id: "1_2", text: "hello", picture: "", createdAt: "2026-11-21T08:00:00Z", reactions: 3, comments: [] };
const html = (extra = {}) => renderToStaticMarkup(<FbPostCard post={{ ...post, ...extra }} pageName="Fihrist" lang="en" actions={{}} />);

describe("a Page post card", () => {
  it("renders a real post without crashing the page", () => {
    expect(() => html()).not.toThrow();
  });
  it("shows the post text and the reactions summary", () => {
    const out = html();
    expect(out).toContain("hello");
    expect(out).toContain('data-kind="LIKE"');
  });
  it("shows no reactions summary when the post has none", () => {
    expect(html({ reactions: 0 })).not.toContain('data-kind="LIKE"');
  });
});

describe("a Page post card, as Facebook draws an empty thread", () => {
  it("always shows the comment box, as Facebook does, not only after pressing Comment", () => {
    const out = html({ timeLabel: "3m" });
    expect(out).toContain("Comment as Fihrist");
  });
  it("says there are no comments yet and invites the first one", () => {
    const out = html({ timeLabel: "3m" });
    expect(out).toContain("No comments yet");
    expect(out).toContain("Be the first to comment");
  });
  it("invites the first comment in Arabic too", () => {
    const out = renderToStaticMarkup(<FbPostCard post={{ ...post }} pageName="Fihrist" lang="ar" actions={{}} />);
    expect(out).toContain("لا توجد تعليقات حتى الآن");
    expect(out).toContain("كن أول من يعلّق");
  });
});

describe("the share counter, as Facebook draws it beside the comment count", () => {
  it("shows how many times the post was shared", () => {
    const out = html({ sharesCount: 4 });
    expect(out).toContain('data-testid="fb-share-count"');
    expect(out).toContain("4 shares");
  });
  it("says 1 share in the singular", () => {
    expect(html({ sharesCount: 1 })).toContain("1 share<");
  });
  it("draws nothing when nobody shared, as Facebook does", () => {
    expect(html({ sharesCount: 0 })).not.toContain("fb-share-count");
    expect(html({})).not.toContain("fb-share-count");
  });
  it("speaks Arabic on the Arabic screen", () => {
    const out = renderToStaticMarkup(<FbPostCard post={{ ...post, sharesCount: 3 }} pageName="Fihrist" lang="ar" actions={{}} />);
    expect(out).toContain("3 مشاركات");
  });
});
