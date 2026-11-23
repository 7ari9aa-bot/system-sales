import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

const data = { lang: "ar", posts: [], postsLoading: false, postsError: null };

vi.mock("./useInstagramData", () => ({
  useInstagramData: () => data,
  needsAnswer: (comment) => Boolean(comment && comment.text && !comment.isPage),
}));

const { default: InstagramActivityPage } = await import("./InstagramActivityPage");

const post = (comments) => ({
  id: "m1",
  mediaUrl: "https://cdn.example/x.jpg",
  mediaType: "image",
  comments,
});

const html = () => renderToStaticMarkup(<MemoryRouter><InstagramActivityPage /></MemoryRouter>);

describe("the Instagram activity list", () => {
  it("shows a comment with its author and text", () => {
    data.posts = [post([{ id: "c1", author: "hhamd.d", text: "بكام؟", commentedAt: new Date().toISOString() }])];
    const out = html();
    expect(out).toContain("hhamd.d");
    expect(out).toContain("بكام؟");
    expect(out).toContain("علّق:");
  });

  it("tells the merchant they were mentioned when Meta sends ids only", () => {
    // A mention row: author_name and body are both null, only the media id arrives.
    data.posts = [post([{ id: "mention:c9", author: null, handle: null, text: "", commentedAt: new Date().toISOString() }])];
    const out = html();
    expect(out).toContain("أشار إليك أحدهم");
    expect(out).not.toContain("علّق:");
  });
});
