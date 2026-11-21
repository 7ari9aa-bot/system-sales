import { afterEach, describe, expect, it, vi } from "vitest";
import { FB_LIMITS, facebookPostProblem, publishFacebookPost } from "@/lib/facebookApi";
import { api } from "@/lib/api";

vi.mock("@/lib/api", () => ({ api: vi.fn(async () => ({ id: "1_2", scheduled: false })) }));
afterEach(() => vi.mocked(api).mockClear());

const pic = (type = "image/png", bytes = 8, name = "p") => new File([new Uint8Array(bytes)], name, { type });

/** A Facebook post can carry several pictures (an album, up to Meta's limit here), never a link too. */
describe("an album is checked before anything is uploaded", () => {
  it("allows up to the album limit and refuses one more", () => {
    const ok = Array.from({ length: FB_LIMITS.maxPictures }, () => pic());
    expect(facebookPostProblem({ pictures: ok }, "en")).toBe("");
    expect(facebookPostProblem({ pictures: [...ok, pic()] }, "en")).toMatch(/at most 10/);
  });
  it("judges every file, not only the first", () => {
    expect(facebookPostProblem({ pictures: [pic(), pic("application/pdf")] }, "en")).toMatch(/JPEG/);
    expect(facebookPostProblem({ pictures: [pic(), pic("image/png", FB_LIMITS.maxPictureBytes + 1)] }, "en")).toMatch(/4 MB/);
  });
  it("is not a post with a link, and an album alone is enough to post", () => {
    expect(facebookPostProblem({ pictures: [pic(), pic()], link: "https://a.co" }, "en")).toMatch(/picture or a link/);
    expect(facebookPostProblem({ pictures: [pic(), pic()] }, "en")).toBe("");
  });
  it("keeps the single `picture` working as before", () => {
    expect(facebookPostProblem({ picture: pic() }, "en")).toBe("");
  });
});

describe("publishing an album", () => {
  it("sends every picture as base64 in `pictures`, and no single `picture`", async () => {
    await publishFacebookPost({ message: "new", pictures: [pic("image/png", 3, "a"), pic("image/jpeg", 3, "b")] });
    const body = vi.mocked(api).mock.calls[0][1].body;
    expect(body.pictures).toHaveLength(2);
    expect(body.pictures.every((p) => typeof p === "string" && p.length > 0)).toBe(true);
    expect(body.picture).toBeNull();
    expect(body.link).toBeNull();
    expect(body.message).toBe("new");
  });
  it("sends a single picture exactly as before", async () => {
    await publishFacebookPost({ message: "x", picture: pic() });
    const body = vi.mocked(api).mock.calls[0][1].body;
    expect(body.picture).toEqual(expect.any(String));
    expect("pictures" in body).toBe(false);
  });
});

describe("addPictures: what picking more files does to the album", () => {
  it("adds to what is already there, in the order picked", async () => {
    const { addPictures } = await import("@/lib/facebookApi");
    const a = pic("image/png", 1, "a");
    const b = pic("image/png", 1, "b");
    const c = pic("image/png", 1, "c");
    expect(addPictures([a], [b, c]).map((f) => f.name)).toEqual(["a", "b", "c"]);
  });
  it("stops at the album limit and says how many were left out", async () => {
    const { addPictures } = await import("@/lib/facebookApi");
    const have = Array.from({ length: 8 }, (_, i) => pic("image/png", 1, `h${i}`));
    const more = Array.from({ length: 5 }, (_, i) => pic("image/png", 1, `m${i}`));
    const out = addPictures(have, more);
    expect(out).toHaveLength(FB_LIMITS.maxPictures);
    expect(out.left).toBe(3);
  });
  it("does not add the same file twice", async () => {
    const { addPictures } = await import("@/lib/facebookApi");
    const a = pic("image/png", 5, "a");
    expect(addPictures([a], [pic("image/png", 5, "a")])).toHaveLength(1);
  });
  it("ignores an empty pick", async () => {
    const { addPictures } = await import("@/lib/facebookApi");
    expect(addPictures([], undefined)).toHaveLength(0);
  });
});
