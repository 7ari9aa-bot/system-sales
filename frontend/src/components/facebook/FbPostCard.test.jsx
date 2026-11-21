import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { COMMENT_SORTS } from "@/lib/facebookApi";
import FbPostCard, { commentActionLabel, commentSortShown, commentSubmitShown } from "@/components/facebook/FbPostCard";

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
    expect(action).toContain('data-testid="fb-comment-count"');
    expect(action).toContain(">3<");
    expect(action).toContain('aria-label="Comment, 3 comments"');
  });
  it("is no longer a separate '3 comments' beside the reactions", () => {
    const out = html({ commentsCount: 3 });
    const countsRow = out.match(/<div[^>]*data-testid="fb-engagement-row"[\s\S]*?<\/div>/)?.[0] || "";
    expect(countsRow).toContain('data-testid="fb-comment-count"');
    const visible = countsRow.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
    expect(visible).not.toMatch(/comments/i);
    expect(visible).not.toContain("تعليق");
  });
  it("draws no reactions badge when there are none, but keeps the one row of actions", () => {
    const out = html({ reactions: 0, commentsCount: 3 });
    expect(out).not.toContain('data-kind="LIKE"');
    expect(out).toContain('data-testid="fb-engagement-row"');
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
  it("shows once the thread has two comments and none are folded away", () => {
    expect(commentSortShown(two, 0)).toBe(true);
    expect(commentSortShown(two, 1)).toBe(false);
    expect(commentSortShown([two[0]], 0)).toBe(false);
    expect(commentSortShown(undefined, 0)).toBe(false);
  });
  it("is named 'Most relevant' to begin with, in Arabic too", () => {
    expect(COMMENT_SORTS[0]).toMatchObject({ ar: "الأكثر ملاءمة", en: "Most relevant" });
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
    expect(out).toMatch(/fb-share-count[^>]*>4<span class="sr-only">shares</);
  });
  it("says 1 share in the singular", () => {
    expect(html({ sharesCount: 1 })).toMatch(/fb-share-count[^>]*>1<span class="sr-only">share</);
  });
  it("still shows the share count on a post nobody has reacted to", () => {
    const out = html({ reactions: 0, sharesCount: 2 });
    expect(out).toMatch(/fb-share-count[^>]*>2<span class="sr-only">shares</);
    expect(out).not.toContain('data-kind="LIKE"');
  });
  it("draws nothing when nobody shared, as Facebook does", () => {
    expect(html({ sharesCount: 0 })).not.toContain("fb-share-count");
    expect(html({})).not.toContain("fb-share-count");
  });
  it("speaks Arabic on the Arabic screen", () => {
    const out = renderToStaticMarkup(<FbPostCard post={{ ...post, sharesCount: 3 }} pageName="Fihrist" lang="ar" actions={{}} />);
    expect(out).toMatch(/fb-share-count[^>]*>3<span class="sr-only">مشاركات</);
  });
});

describe("a Page post card, as Facebook draws it on the Page home", () => {
  const withComments = (n) => Array.from({ length: n }, (_, i) => ({ id: `c${i}`, text: `t${i}`, from: "Fihrist OS", commentedAt: `2026-11-21T1${i}:00:00Z`, replies: [] }));
  const row = (extra) => html({ reactions: 1, ...extra }).match(/<div[^>]*data-testid="fb-engagement-row"[\s\S]*?<\/div>/)?.[0] || "";

  it("puts likes, comments and shares in one row of counters", () => {
    const r = row({ comments: withComments(3), commentsCount: 3, sharesCount: 2 });
    expect(r).toContain('data-kind="LIKE"');
    expect(r).toContain('data-testid="fb-comment-count"');
    expect(r).toContain('data-testid="fb-share-count"');
  });
  it("has a Like button that is an icon named like Facebook's, not a text row under a divider", () => {
    const out = html({ reactions: 1 });
    expect(out).toContain('aria-label="Like"');
    expect(out).not.toMatch(/<button[^>]*>(?:<svg[\s\S]*?<\/svg>)?Like<\/button>/);
  });
  it("still opens the comment box from the comment counter", () => {
    expect(html({ comments: withComments(3), commentsCount: 3 })).toMatch(/data-testid="fb-comment-action"[^>]*aria-pressed/);
  });
  it("shows only the newest comment first, with View more comments", () => {
    const out = html({ comments: withComments(3), commentsCount: 3 });
    expect(out).toContain("t2");
    expect(out).not.toContain(">t0<");
    expect(out).toContain("View more comments");
  });
});

describe("a Page post card, measured side by side with the real Page home", () => {
  const some = (n) => Array.from({ length: n }, (_, i) => ({ id: `c${i}`, text: `t${i}`, from: "Fihrist OS", commentedAt: `2026-11-21T1${i}:00:00Z`, replies: [] }));
  it("shows the comment order menu when the whole short thread is in view", () => {
    expect(html({ comments: some(1), commentsCount: 1 })).not.toContain('data-testid="fb-comment-sort"');
  });
  it("keeps the order menu off while comments are folded, as Facebook does; it shows once more are opened", () => {
    expect(html({ comments: some(3), commentsCount: 3 })).not.toContain('data-testid="fb-comment-sort"');
  });
  it("says 'View more comments' with no number, as Facebook does", () => {
    const out = html({ comments: some(3), commentsCount: 3 });
    expect(out).toContain("View more comments");
    expect(out).not.toContain("View 2 more comments");
  });
  it("says it in Arabic without a number too", () => {
    const out = renderToStaticMarkup(<FbPostCard post={{ ...post, comments: some(3), commentsCount: 3 }} pageName="Fihrist" lang="ar" actions={{}} />);
    expect(out).toContain("عرض المزيد من التعليقات");
  });
  it("draws Facebook's share arrow in the row even before anyone shared, as a non-clickable mark", () => {
    const out = html({ reactions: 1, sharesCount: 0 });
    expect(out).toContain('data-testid="fb-share-mark"');
    expect(out).not.toMatch(/<button[^>]*data-testid="fb-share-mark"/);
  });
});
