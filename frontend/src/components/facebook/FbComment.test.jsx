import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import FbComment, { commentActions, commentHeader } from "@/components/facebook/FbComment";

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

// Facebook keeps the age of a comment on the name's line, inside the bubble; only Like · Reply
// stay on the line under it. The bubble runs from its rounded box to the action row that follows.
const bubbleOf = (out) => out.slice(out.indexOf("rounded-[18px]"), out.indexOf("mt-0.5 flex flex-wrap"));
const actionRowOf = (out) => out.slice(out.indexOf("mt-0.5 flex flex-wrap"));

describe("a comment's age", () => {
  it("sits on the author's line, right after the name", () => {
    expect(commentHeader({ author: "Mona", timeLabel: "5m" }, "en").map((p) => p.kind)).toEqual(["author", "time"]);
    expect(commentHeader({ author: "Mona", timeLabel: "5m" }, "en").map((p) => p.text)).toEqual(["Mona", "5m"]);
  });
  it("comes after the Author badge on a Page's own comment", () => {
    expect(commentHeader({ author: "Fihrist", isPage: true, timeLabel: "5m" }, "en").map((p) => p.kind)).toEqual(["author", "badge", "time"]);
  });
  it("is drawn inside the bubble and no longer under it", () => {
    const out = html({ author: "Mona", timeLabel: "5m" });
    const bubble = bubbleOf(out);
    expect(bubble).toContain("Mona");
    expect(bubble).toContain("5m");
    expect(actionRowOf(out)).not.toContain("5m");
  });
  it("is drawn in Arabic on the name's line too", () => {
    const out = html({ author: "منى", timeLabel: "5 د" }, { lang: "ar" });
    expect(bubbleOf(out)).toContain("5 د");
    expect(actionRowOf(out)).not.toContain("5 د");
  });
});

describe("which actions a comment offers", () => {
  const theirs = { id: "c1", author: "Sara", isPage: false, hidden: false };
  const pages = { id: "c2", author: "Fihrist", isPage: true, hidden: false };
  it("offers Reply on the Page's own comment too, as Facebook does", () => {
    expect(commentActions(pages, 0).reply).toBe(true);
  });
  it("offers Reply on someone else's comment", () => {
    expect(commentActions(theirs, 0).reply).toBe(true);
  });
  it("offers no Reply inside a reply (threads are one level deep) or on a hidden comment", () => {
    expect(commentActions(theirs, 1).reply).toBe(false);
    expect(commentActions({ ...theirs, hidden: true }, 0).reply).toBe(false);
  });
  it("offers Like on the Page's own comment, as Facebook does", () => {
    expect(commentActions(pages, 0).like).toBe(true);
    expect(commentActions(theirs, 0).like).toBe(true);
  });
  it("draws the Like button on the Page's own comment", () => {
    const out = renderToStaticMarkup(<FbComment comment={pages} postId="p1" pageName="Fihrist" lang="en" actions={{}} />);
    expect(out).toContain(">Like<");
  });
  it("never offers Hide or a private message on the Page's own comment", () => {
    const a = commentActions(pages, 0);
    expect(a.hide).toBe(false);
    expect(a.privateReply).toBe(false);
  });
  it("draws the Reply button on the Page's own comment", () => {
    const out = renderToStaticMarkup(<FbComment comment={pages} postId="p1" pageName="Fihrist" lang="en" actions={{}} />);
    expect(out).toContain(">Reply<");
  });
});

// The Page's own like state comes from Meta's `user_likes`, so the button starts pressed when the
// Page already liked the comment. The stored count already includes that like, so the screen must
// not add it a second time.
describe("the Page's like on a comment", () => {
  it("starts pressed when Meta says the Page already liked it", () => {
    expect(html({ pageLiked: true })).toContain('aria-pressed="true"');
    expect(html({ pageLiked: false })).toContain('aria-pressed="false"');
    expect(html({})).toContain('aria-pressed="false"');
  });
  it("shows the stored count as is when nothing changed on screen", async () => {
    const { shownLikeCount } = await import("@/components/facebook/FbComment");
    expect(shownLikeCount({ likes: 2, pageLiked: true }, true)).toBe(2);
    expect(shownLikeCount({ likes: 1, pageLiked: false }, false)).toBe(1);
  });
  it("adds one for a like pressed now, and takes one off for an un-like of a stored like", async () => {
    const { shownLikeCount } = await import("@/components/facebook/FbComment");
    expect(shownLikeCount({ likes: 1, pageLiked: false }, true)).toBe(2);
    expect(shownLikeCount({ likes: 2, pageLiked: true }, false)).toBe(1);
  });
  it("never goes below zero on a stale count", async () => {
    const { shownLikeCount } = await import("@/components/facebook/FbComment");
    expect(shownLikeCount({ likes: 0, pageLiked: true }, false)).toBe(0);
  });
});

// The comment mounts with its id as the key, and Meta's answer can arrive after it was first drawn
// (the sync updates the row). A Like state frozen at mount stays un-pressed for good, so the pressed
// state must follow Meta's answer until the person presses the button on this screen.
describe("the pressed state follows Meta until the person presses it", () => {
  it("is Meta's answer when nothing was pressed here", async () => {
    const { likedNow } = await import("@/components/facebook/FbComment");
    expect(likedNow({ pageLiked: true }, null)).toBe(true);
    expect(likedNow({ pageLiked: false }, null)).toBe(false);
    expect(likedNow({}, null)).toBe(false);
  });
  it("follows a later answer from Meta that arrives after the first draw", async () => {
    const { likedNow } = await import("@/components/facebook/FbComment");
    expect(likedNow({ pageLiked: false }, null)).toBe(false);
    expect(likedNow({ pageLiked: true }, null)).toBe(true);
  });
  it("is what the person pressed once they pressed it, whatever Meta said", async () => {
    const { likedNow } = await import("@/components/facebook/FbComment");
    expect(likedNow({ pageLiked: true }, false)).toBe(false);
    expect(likedNow({ pageLiked: false }, true)).toBe(true);
  });
});

// Facebook's own comment (read from its page): "Like" (or "Remove like" once pressed), then "Reply",
// then the like count as a plain number in that same row, zero included. No floating bubble.
describe("the like count on a comment", () => {
  it("is a number in the action row, even at zero, like Facebook", () => {
    const row = actionRowOf(html({ likes: 0 }));
    expect(row).toMatch(/data-testid="comment-like-count"[\s\S]*?<\/span>0<\/span>/);
  });
  it("shows the real count there, and no bubble floats over the comment", () => {
    const out = html({ likes: 2 });
    expect(actionRowOf(out)).toMatch(/data-testid="comment-like-count"[\s\S]*?<\/span>2<\/span>/);
    expect(bubbleOf(out)).not.toContain("absolute -bottom-2.5");
  });
  it("comes after Reply in the row", () => {
    const row = actionRowOf(html({ likes: 2 }, { actions: {} }));
    expect(row.indexOf(">Reply<")).toBeGreaterThan(-1);
    expect(row.indexOf("comment-like-count")).toBeGreaterThan(row.indexOf(">Reply<"));
  });
});

describe("the like button once the Page has liked the comment", () => {
  it("reads 'Remove like', as Facebook words it", () => {
    const out = html({ likes: 1, pageLiked: true, isPage: true });
    expect(out).toContain(">Remove like<");
  });
  it("reads 'إزالة أعجبني' in Arabic", () => {
    const out = html({ likes: 1, pageLiked: true, isPage: true }, { lang: "ar" });
    expect(out).toContain(">إزالة أعجبني<");
  });
  it("reads 'Like' before the Page has liked it", () => {
    expect(html({ likes: 0, pageLiked: false, isPage: true })).toContain(">Like<");
  });
});
