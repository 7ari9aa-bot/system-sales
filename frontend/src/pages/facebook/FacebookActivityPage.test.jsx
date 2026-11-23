import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

const data = { lang: "ar", posts: [], postsLoading: false, postsError: null };
const feed = { items: [], unread: 0 };

vi.mock("./useFacebookData", () => ({
  useFacebookData: () => data,
  needsAnswer: (comment) => Boolean(comment && comment.text && !comment.isPage),
}));

// The Page's own events come from the server now, not from the post list and not from
// localStorage: the hook is fed from the query cache so this stays a pure render test.
vi.mock("@/lib/facebookApi", () => ({
  fetchPageActivity: () => Promise.resolve(feed),
  markPageActivityRead: () => Promise.resolve({ marked: 0 }),
}));

const { default: FacebookActivityPage } = await import("./FacebookActivityPage");

const post = (comments) => ({ id: "p1", comments });

const html = () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(["facebook", "activity"], feed);
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <FacebookActivityPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
};

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

  it("shows the server's own Page events: a new post, an edit, a delete, a reaction", () => {
    data.posts = [];
    feed.items = [
      { id: "a1", kind: "post", object_id: "P1", summary: "منشور جديد على الصفحة", occurred_at: new Date().toISOString(), read: false },
      { id: "a2", kind: "post_edit", object_id: "P1", summary: "تم تعديل منشور", occurred_at: new Date().toISOString(), read: false },
      { id: "a3", kind: "post_delete", object_id: "P2", summary: "تم حذف منشور", occurred_at: new Date().toISOString(), read: true },
      { id: "a4", kind: "reaction", object_id: "P1", summary: "تفاعل جديد على منشور", occurred_at: new Date().toISOString(), read: false },
    ];
    const out = html();
    expect(out).toContain("منشور جديد على الصفحة");
    expect(out).toContain("تم تعديل منشور");
    expect(out).toContain("تم حذف منشور");
    expect(out).toContain("تفاعل جديد على منشور");
  });

  it("does not show a comment twice: the post list already carries it", () => {
    data.posts = [post([{ id: "c1", author: "سارة", text: "متوفر؟", timeLabel: "قبل ساعة" }])];
    feed.items = [
      { id: "a9", kind: "comment", object_id: "c1", summary: "تعليق جديد", occurred_at: new Date().toISOString(), read: false },
    ];
    const out = html();
    expect(out.match(/تعليق جديد/g)).toBeNull();
    expect(out).toContain("متوفر؟");
  });
});
