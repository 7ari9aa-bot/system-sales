import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import FbPostCard, { commentSubmitShown } from "@/components/facebook/FbPostCard";

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

describe("the Post button in the comment box", () => {
  it("is hidden until there is something in the draft, as Facebook hides it", () => {
    expect(commentSubmitShown("")).toBe(false);
    expect(commentSubmitShown("   ")).toBe(false);
    expect(commentSubmitShown(null)).toBe(false);
    expect(commentSubmitShown(undefined)).toBe(false);
  });
  it("appears as soon as the draft has a word in it", () => {
    expect(commentSubmitShown("h")).toBe(true);
    expect(commentSubmitShown("  hello  ")).toBe(true);
  });
  it("is not in the empty comment box as it first draws", () => {
    const out = html({ timeLabel: "3m" });
    expect(out).toContain("Comment as Fihrist");
    expect(out).not.toContain('data-testid="fb-comment-submit"');
    expect(out).not.toContain(">Post<");
  });
});
