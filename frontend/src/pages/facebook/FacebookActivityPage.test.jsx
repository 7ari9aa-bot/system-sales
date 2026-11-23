import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

const data = { lang: "ar", posts: [], postsLoading: false, postsError: null };

vi.mock("./useFacebookData", () => ({
  useFacebookData: () => data,
  needsAnswer: (comment) => Boolean(comment && comment.text && !comment.isPage),
}));

const { default: FacebookActivityPage } = await import("./FacebookActivityPage");

const post = (comments) => ({ id: "p1", comments });

const html = () => renderToStaticMarkup(<MemoryRouter><FacebookActivityPage /></MemoryRouter>);

describe("the Facebook activity list", () => {
  it("shows a comment with its author and text", () => {
    data.posts = [post([{ id: "c1", author: "حامد عادل", text: "بكام؟", timeLabel: "قبل ساعة" }])];
    const out = html();
    expect(out).toContain("حامد عادل");
    expect(out).toContain("بكام؟");
    expect(out).toContain("علّق:");
  });

  it("tells the merchant they were mentioned when Meta sends ids only", () => {
    // A Page mention row: no author name and no text, only the post id arrives.
    data.posts = [post([{ id: "mention:p9", author: null, text: "", timeLabel: "قبل ساعة" }])];
    const out = html();
    expect(out).toContain("أشار إليك أحدهم");
    expect(out).not.toContain("علّق:");
  });
});
