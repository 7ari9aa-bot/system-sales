import { afterEach, describe, expect, it, vi } from "vitest";
import { commentOn, mentionHandle, toFacebookComments } from "@/lib/facebookApi";
import { api } from "@/lib/api";

vi.mock("@/lib/api", () => ({ api: vi.fn(async () => ({ id: "c2" })) }));
afterEach(() => vi.mocked(api).mockClear());

/**
 * Facebook's reply box opens with the person's name already in it. The Pages API tags that person
 * (@mention) only by the numeric id of someone who commented, so the comment carries it from the
 * server (`author_ref`) and the reply sends it back as `mention`.
 */
describe("a comment keeps who wrote it, so a reply can tag them", () => {
  const rows = [
    { id: "c1", username: "Sara", author_ref: "123", body: "hi", status: "visible", commented_at: "2026-11-21T01:00:00Z" },
    { id: "c2", username: "page", author_ref: null, is_page_reply: true, parent_id: "c1", body: "hello", status: "visible" },
  ];
  it("carries the author id on people, and none on the Page's own reply", () => {
    const [c1] = toFacebookComments(rows, "en", "Shop");
    expect(c1.authorRef).toBe("123");
    expect(c1.replies[0].authorRef).toBeNull();
  });
});

describe("mentionHandle", () => {
  it("gives the first name as Facebook shows it, and nothing for someone with no id", () => {
    expect(mentionHandle({ author: "Sara Ali", authorRef: "123" })).toEqual({ id: "123", label: "Sara Ali" });
    expect(mentionHandle({ author: "Sara", authorRef: null })).toBeNull();
    expect(mentionHandle({ author: "Page", authorRef: "9", isPage: true })).toBeNull();
    expect(mentionHandle(null)).toBeNull();
  });
});

describe("commentOn", () => {
  it("sends the text alone when nobody is tagged, exactly as before", async () => {
    await commentOn("c1", "thanks");
    expect(vi.mocked(api).mock.calls[0][1].body).toEqual({ text: "thanks" });
  });
  it("sends the ids to tag as `mention`", async () => {
    await commentOn("c1", "thanks", ["123"]);
    expect(vi.mocked(api).mock.calls[0][1].body).toEqual({ text: "thanks", mention: ["123"] });
  });
});

describe("replyMention: what a reply tags", () => {
  it("tags the commenter on a public reply, as Facebook's pre-filled name does", async () => {
    const { replyMention } = await import("@/lib/facebookApi");
    expect(replyMention({ author: "Sara", authorRef: "123" }, { tagged: true, privateReply: false })).toEqual(["123"]);
  });
  it("tags nobody once the owner removed the name, on a private reply, or when there is no id", async () => {
    const { replyMention } = await import("@/lib/facebookApi");
    const c = { author: "Sara", authorRef: "123" };
    expect(replyMention(c, { tagged: false, privateReply: false })).toBeUndefined();
    expect(replyMention(c, { tagged: true, privateReply: true })).toBeUndefined();
    expect(replyMention({ author: "Sara", authorRef: null }, { tagged: true, privateReply: false })).toBeUndefined();
  });
});
