import { describe, expect, it } from "vitest";
import { toWorkspaceComments, toWorkspacePost } from "@/lib/socialApi";

const c = (id, extra = {}) => ({ id, post_id: "p1", body: `t${id}`, username: `u${id}`, status: "visible", commented_at: new Date().toISOString(), ...extra });

describe("comments from the API become the workspace shape", () => {
  it("nests replies under their parent and keeps order", () => {
    const out = toWorkspaceComments([c("1"), c("2", { parent_id: "1" }), c("3")]);
    expect(out.map((x) => x.id)).toEqual(["1", "3"]);
    expect(out[0].replies.map((x) => x.id)).toEqual(["2"]);
  });
  it("shows an orphan reply at the top instead of losing it", () => {
    expect(toWorkspaceComments([c("9", { parent_id: "missing" })]).map((x) => x.id)).toEqual(["9"]);
  });
  it("drops removed comments, keeps hidden ones flagged", () => {
    const out = toWorkspaceComments([c("1", { status: "removed" }), c("2", { status: "hidden" })]);
    expect(out).toHaveLength(1);
    expect(out[0]).toMatchObject({ id: "2", hidden: true });
  });
  it("labels the store's own reply as the page", () => {
    const [x] = toWorkspaceComments([c("1", { is_page_reply: true, username: null })], "en", "myshop");
    expect(x).toMatchObject({ isPage: true, author: "myshop" });
  });
  it("carries private-reply state so the button can be disabled", () => {
    const [x] = toWorkspaceComments([c("1", { private_replied_at: "2026-11-17T10:00:00Z" })]);
    expect(x.privateRepliedAt).toBe("2026-11-17T10:00:00Z");
  });
});

describe("posts", () => {
  it("flags reels and falls back to the thumbnail", () => {
    const p = toWorkspacePost({ id: "p", media_type: "REELS", thumbnail_url: "t.jpg", like_count: 3 }, []);
    expect(p).toMatchObject({ isReel: true, mediaType: "video", mediaUrl: "t.jpg", likes: 3 });
  });
  it("treats comments as enabled unless the API says otherwise", () => {
    expect(toWorkspacePost({ id: "p" }, []).commentsEnabled).toBe(true);
    expect(toWorkspacePost({ id: "p", comments_enabled: false }, []).commentsEnabled).toBe(false);
  });
});
