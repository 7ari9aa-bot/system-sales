import { describe, expect, it, vi } from "vitest";
import { createCommentStream, streamUrl } from "@/lib/commentStream";

describe("the stream address", () => {
  it("asks only for the comment stream and carries the short-lived token", () => {
    const url = streamUrl("/api/v1", "tok en");
    expect(url).toBe("/api/v1/realtime/events?streams=social_comment.events&token=tok%20en");
  });
});

/** A fake EventSource the test drives by hand. */
function fakeSource() {
  const made = [];
  const Source = function (url) { this.url = url; this.closed = false; made.push(this); };
  Source.prototype.close = function () { this.closed = true; };
  return { Source, made };
}

describe("opening the stream", () => {
  it("fetches a fresh token before every open, never reusing an old one", async () => {
    const { Source, made } = fakeSource();
    const mint = vi.fn()
      .mockResolvedValueOnce({ stream_token: "one" })
      .mockResolvedValueOnce({ stream_token: "two" });
    const open = createCommentStream({ mint, Source, base: "/api/v1" });
    const a = open();
    await a.ready;
    a.close();
    const b = open();
    await b.ready;
    expect(made.map((s) => s.url.split("token=")[1])).toEqual(["one", "two"]);
  });

  it("passes the stream's events through to the caller's handlers", async () => {
    const { Source, made } = fakeSource();
    const open = createCommentStream({ mint: async () => ({ stream_token: "t" }), Source, base: "/api/v1" });
    const handle = open();
    const got = [];
    handle.onmessage = (e) => got.push(e.data);
    await handle.ready;
    made[0].onmessage({ data: "x" });
    expect(got).toEqual(["x"]);
  });

  it("reports a token failure as an error so the caller backs off and tries again", async () => {
    const { Source, made } = fakeSource();
    const open = createCommentStream({ mint: async () => { throw new Error("401"); }, Source, base: "/api/v1" });
    const handle = open();
    const onerror = vi.fn();
    handle.onerror = onerror;
    await handle.ready;
    expect(onerror).toHaveBeenCalledTimes(1);
    expect(made).toHaveLength(0);
  });

  it("closing before the token arrives opens nothing", async () => {
    const { Source, made } = fakeSource();
    let release;
    const mint = () => new Promise((r) => { release = r; });
    const open = createCommentStream({ mint, Source, base: "/api/v1" });
    const handle = open();
    handle.close();
    release({ stream_token: "late" });
    await handle.ready;
    expect(made).toHaveLength(0);
  });

  it("closing after it opened closes the real stream", async () => {
    const { Source, made } = fakeSource();
    const open = createCommentStream({ mint: async () => ({ stream_token: "t" }), Source, base: "/api/v1" });
    const handle = open();
    await handle.ready;
    handle.close();
    expect(made[0].closed).toBe(true);
  });
});
