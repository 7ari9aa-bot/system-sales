import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import FbPostCard, { commentActionLabel, commentSubmitShown } from "@/components/facebook/FbPostCard";

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

// The action bar's Comment button, as drawn: Facebook puts the thread's count on that button itself.
const commentActionOf = (out) => (out.match(/<button[^>]*data-testid="fb-comment-action"[^>]*>.*?<\/button>/) || [""])[0];

describe("the comment count on the action bar", () => {
  it("is named in the Comment button's label, so a screen reader hears it", () => {
    expect(commentActionLabel(3, "en")).toBe("Comment, 3 comments");
    expect(commentActionLabel(1, "en")).toBe("Comment, 1 comment");
    expect(commentActionLabel(0, "en")).toBe("Comment");
    expect(commentActionLabel(3, "ar")).toBe("تعليق، 3 تعليقات");
    expect(commentActionLabel(1, "ar")).toBe("تعليق، تعليق واحد");
    expect(commentActionLabel(0, "ar")).toBe("تعليق");
  });
  it("is a number beside the Comment action, as Facebook shows it", () => {
    const out = html({ commentsCount: 3 });
    const action = commentActionOf(out);
    expect(action).toContain(">Comment<");
    expect(action).toContain('data-testid="fb-comment-count"');
    expect(action).toContain(">3<");
    expect(action).toContain('aria-label="Comment, 3 comments"');
  });
  it("is no longer a separate '3 comments' beside the reactions", () => {
    const out = html({ commentsCount: 3 });
    const countsRow = out.slice(out.indexOf('justify-between'), out.indexOf('grid grid-cols-2'));
    expect(countsRow).not.toContain("comments");
    expect(countsRow).not.toContain("تعليق");
  });
  it("draws no empty counts row when the post has neither reactions nor a separate count", () => {
    const out = html({ reactions: 0, commentsCount: 3 });
    expect(out).not.toContain("justify-between px-4 py-2.5");
  });
  it("stays off the button when the post has no comments", () => {
    const action = commentActionOf(html({ commentsCount: 0 }));
    expect(action).not.toContain('data-testid="fb-comment-count"');
    expect(action).toContain('aria-label="Comment"');
  });
  it("counts the replies already loaded, so the number matches the thread", () => {
    const comments = [{ id: "c1", author: "Mona", text: "hi", timeLabel: "5m", replies: [{ id: "c2", author: "Fihrist", text: "yo", timeLabel: "4m", isPage: true }] }];
    expect(commentActionOf(html({ commentsCount: 0, comments }))).toContain(">2<");
  });
  it("is named in Arabic beside the Arabic action", () => {
    const out = renderToStaticMarkup(<FbPostCard post={{ ...post, commentsCount: 2 }} pageName="Fihrist" lang="ar" actions={{}} />);
    expect(commentActionOf(out)).toContain('aria-label="تعليق، 2 تعليقات"');
    expect(commentActionOf(out)).toContain(">2<");
  });
});

describe("the comment sort menu, as Facebook shows it above a busy thread", () => {
  const cm = (id, at, text) => ({ id, author: "Ann", timeLabel: "1m", commentedAt: at, text, likes: 0, replies: [] });
  const two = [cm("a", "2026-11-21T08:00:00Z", "first one"), cm("b", "2026-11-21T09:00:00Z", "second one")];

  it("is absent when there is nothing to order", () => {
    expect(html({ comments: [] })).not.toContain('data-testid="fb-comment-sort"');
    expect(html({ comments: [two[0]] })).not.toContain('data-testid="fb-comment-sort"');
  });
  it("shows once the thread has two comments, named 'Most relevant' to begin with", () => {
    const out = html({ comments: two });
    expect(out).toContain('data-testid="fb-comment-sort"');
    expect(out).toContain("Most relevant");
  });
  it("is in Arabic with the Arabic labels", () => {
    const out = renderToStaticMarkup(<FbPostCard post={{ ...post, comments: two }} pageName="Fihrist" lang="ar" actions={{}} />);
    expect(out).toContain("الأكثر ملاءمة");
  });
  it("draws the thread oldest first by default", () => {
    const out = html({ comments: two });
    expect(out.indexOf("first one")).toBeLessThan(out.indexOf("second one"));
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
  it("still shows the share count on a post nobody has reacted to", () => {
    const out = html({ reactions: 0, sharesCount: 2 });
    expect(out).toContain("2 shares");
    expect(out).not.toContain('data-kind="LIKE"');
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
