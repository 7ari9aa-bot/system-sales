import { describe, expect, it } from "vitest";
import { FB_LIMITS, facebookPostProblem, fbAge, toFacebookComments, toFacebookPost } from "@/lib/facebookApi";

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
