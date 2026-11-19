import { afterEach, describe, expect, it, vi } from "vitest";
import { FB_LIMITS, facebookPostProblem, fbAge, publishFacebookPost, toFacebookComments, toFacebookPost } from "@/lib/facebookApi";
import { api } from "@/lib/api";

vi.mock("@/lib/api", () => ({ api: vi.fn(async () => ({ id: "1_2", scheduled: false })) }));
afterEach(() => vi.mocked(api).mockClear());

const pic = (type = "image/png", bytes = 8) => new File([new Uint8Array(bytes)], "p", { type });

const NOW = Date.UTC(2026, 10, 19, 12, 0, 0);
const at = (minutes) => new Date(NOW + minutes * 60000).toISOString().slice(0, 16);

describe("a Facebook post is checked against Meta's own limits before it is sent", () => {
  it("needs text or a link", () => {
    expect(facebookPostProblem({}, "en", NOW)).toMatch(/Write something/);
    expect(facebookPostProblem({ message: "   " }, "en", NOW)).toMatch(/Write something/);
    expect(facebookPostProblem({ message: "hi" }, "en", NOW)).toBe("");
    expect(facebookPostProblem({ link: "https://a.co" }, "en", NOW)).toBe("");
  });
  it("refuses a link that is not http(s) and a text over the limit", () => {
    expect(facebookPostProblem({ link: "ftp://a.co" }, "en", NOW)).toMatch(/http/);
    expect(facebookPostProblem({ link: "a.co" }, "en", NOW)).toMatch(/http/);
    expect(facebookPostProblem({ message: "x".repeat(FB_LIMITS.maxPostChars + 1) }, "en", NOW)).toMatch(/longer/);
    expect(facebookPostProblem({ message: "x".repeat(FB_LIMITS.maxPostChars) }, "en", NOW)).toBe("");
  });
  it("schedules only from 10 minutes to 30 days ahead", () => {
    const m = { message: "later" };
    expect(facebookPostProblem({ ...m, scheduleAt: at(9) }, "en", NOW)).toMatch(/10 minutes/);
    expect(facebookPostProblem({ ...m, scheduleAt: at(11) }, "en", NOW)).toBe("");
    expect(facebookPostProblem({ ...m, scheduleAt: at(30 * 1440 - 5) }, "en", NOW)).toBe("");
    expect(facebookPostProblem({ ...m, scheduleAt: at(30 * 1440 + 5) }, "en", NOW)).toMatch(/30 days/);
    expect(facebookPostProblem({ ...m, scheduleAt: at(-60) }, "en", NOW)).toMatch(/10 minutes/);
    expect(facebookPostProblem({ ...m, scheduleAt: "garbage" }, "en", NOW)).toMatch(/not valid/);
  });
  it("answers in Arabic too", () => {
    expect(facebookPostProblem({}, "ar", NOW)).toMatch(/اكتب/);
  });
});

describe("comments nest one level and hide what was removed", () => {
  const rows = [
    { id: "c1", username: "Ali", body: "hello", status: "visible", commented_at: new Date(NOW - 120000).toISOString(), like_count: 2 },
    { id: "c2", username: "x", is_page_reply: true, body: "thanks", parent_id: "c1", status: "visible", commented_at: new Date(NOW).toISOString() },
    { id: "c3", username: "Bob", body: "spam", status: "removed" },
    { id: "c4", username: "Eve", body: "orphan", parent_id: "gone", status: "hidden" },
  ];
  it("nests a reply under its parent, shows the Page by its name, drops removed, keeps hidden", () => {
    const out = toFacebookComments(rows, "en", "My Shop");
    expect(out.map((c) => c.id)).toEqual(["c1", "c4"]);
    expect(out[0].replies).toHaveLength(1);
    expect(out[0].replies[0]).toMatchObject({ author: "My Shop", isPage: true, text: "thanks" });
    expect(out[0].likes).toBe(2);
    expect(out[1].hidden).toBe(true);
  });
  it("maps a post to the screen's shape", () => {
    const p = toFacebookPost({ id: "p", message: "m", picture: "u", reactions: 5, comments: 3, posted_at: new Date(NOW).toISOString() }, [], "en");
    expect(p).toMatchObject({ id: "p", text: "m", picture: "u", reactions: 5, commentsCount: 3 });
  });
});

describe("fbAge", () => {
  it("is short and Facebook-like", () => {
    const ago = (m) => new Date(Date.now() - m * 60000).toISOString();
    expect(fbAge(ago(0), "en")).toBe("Just now");
    expect(fbAge(ago(5), "en")).toBe("5m");
    expect(fbAge(ago(180), "en")).toBe("3h");
    expect(fbAge(ago(2 * 1440), "en")).toBe("2d");
    expect(fbAge("", "en")).toBe("");
    expect(fbAge("nope", "en")).toBe("");
  });
});

describe("a Facebook post can carry a picture", () => {
  it("accepts a picture alone, with no text", () => {
    expect(facebookPostProblem({ picture: pic() }, "en", NOW)).toBe("");
  });
  it("takes only the types Facebook takes", () => {
    for (const t of ["image/jpeg", "image/png", "image/gif", "image/bmp", "image/webp"]) {
      expect(facebookPostProblem({ picture: pic(t) }, "en", NOW)).toBe("");
    }
    expect(facebookPostProblem({ picture: pic("application/pdf") }, "en", NOW)).toMatch(/JPEG, PNG/);
    expect(facebookPostProblem({ picture: pic("image/svg+xml") }, "en", NOW)).toMatch(/JPEG, PNG/);
  });
  it("stops at 4 MB, and exactly 4 MB is fine", () => {
    expect(facebookPostProblem({ picture: pic("image/png", FB_LIMITS.maxPictureBytes) }, "en", NOW)).toBe("");
    expect(facebookPostProblem({ picture: pic("image/png", FB_LIMITS.maxPictureBytes + 1) }, "en", NOW)).toMatch(/4 MB/);
  });
  it("never carries a picture and a link together", () => {
    expect(facebookPostProblem({ picture: pic(), link: "https://a.co" }, "en", NOW)).toMatch(/not both/);
  });
  it("still applies the schedule window to a picture post", () => {
    expect(facebookPostProblem({ picture: pic(), scheduleAt: at(9) }, "en", NOW)).toMatch(/10 minutes/);
    expect(facebookPostProblem({ picture: pic(), scheduleAt: at(30) }, "en", NOW)).toBe("");
  });
  it("answers in Arabic too", () => {
    expect(facebookPostProblem({ picture: pic("image/png", FB_LIMITS.maxPictureBytes + 1) }, "ar", NOW)).toMatch(/4 ميغابايت/);
  });
  it("sends the picture as base64 and drops the link", async () => {
    await publishFacebookPost({ message: " hi ", link: "https://a.co", picture: new File([new Uint8Array([1, 2, 3])], "p.png", { type: "image/png" }) });
    const [path, opts] = vi.mocked(api).mock.calls[0];
    expect(path).toBe("/facebook/posts");
    expect(opts.body).toEqual({ message: "hi", link: null, picture: "AQID", schedule_at: null });
  });
  it("sends a plain text or link post exactly as before", async () => {
    await publishFacebookPost({ message: "hi", link: " https://a.co " });
    expect(vi.mocked(api).mock.calls[0][1].body).toEqual({ message: "hi", link: "https://a.co", picture: null, schedule_at: null });
  });
});

describe("a large picture is encoded without overflowing the stack", () => {
  it("round-trips 4 MB", async () => {
    const { readPictureAsBase64 } = await import("@/lib/facebookApi");
    const bytes = new Uint8Array(4 * 1024 * 1024).map((_, i) => i % 251);
    const b64 = await readPictureAsBase64(new File([bytes], "big.png", { type: "image/png" }));
    expect(Buffer.from(b64, "base64").equals(Buffer.from(bytes))).toBe(true);
  });
});
