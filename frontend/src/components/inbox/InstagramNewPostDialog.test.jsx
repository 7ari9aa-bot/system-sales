import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

const { default: InstagramNewPostDialog } = await import("./InstagramNewPostDialog");

const html = (props = {}) =>
  renderToStaticMarkup(
    <InstagramNewPostDialog lang="ar" onPublish={vi.fn()} onClose={vi.fn()} {...props} />,
  );

describe("the Instagram composer", () => {
  it("offers Instagram's three choices: post, Reel and story", () => {
    const out = html();
    expect(out).toContain("منشور");
    expect(out).toContain("ريل");
    expect(out).toContain("ستوري");
    expect(out).toContain('data-testid="ig-kind-post"');
  });

  it("starts on a normal post, with the caption box", () => {
    const out = html();
    expect(out).toContain('aria-selected="true" data-testid="ig-kind-post"');
    expect(out).toContain('data-testid="ig-caption"');
    expect(out).not.toContain('data-testid="ig-share-to-feed"');
  });
});

describe("the publish rules per kind", () => {
  it("a Reel is one video and offers sharing to the profile", async () => {
    const { reelProblem, storyProblem, publishProblem } = await import("@/lib/socialApi");
    const mp4 = { type: "video/mp4", size: 10 * 1024 * 1024 };
    expect(reelProblem(mp4, "ريل", "ar")).toBe("");
    expect(reelProblem({ type: "image/jpeg", size: 10 }, "", "ar")).toContain("MP4");
    expect(reelProblem(null, "", "ar")).toContain("فيديو");
    // a story takes a picture or a video, and no caption at all
    expect(storyProblem({ type: "image/jpeg", size: 1000 }, "ar")).toBe("");
    expect(storyProblem({ type: "video/mp4", size: 1000 }, "ar")).toBe("");
    expect(storyProblem({ type: "image/png", size: 1000 }, "ar")).toContain("JPEG");
    // a normal post is still JPEG only
    expect(publishProblem([{ type: "video/mp4", size: 1000 }], "", "ar")).toContain("JPEG");
  });
});
