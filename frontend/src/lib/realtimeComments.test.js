import { describe, expect, it, vi } from "vitest";
import { backoffMs, postIdOfFrame, startCommentPush } from "@/lib/realtimeComments";

const frame = (over = {}) => JSON.stringify({
  stream: "social_comment.events",
  id: "1-0",
  payload: { platform: "facebook", post_id: "p-1", comment_id: "c-1", verb: "add", ...over },
});

describe("which frames wake a post", () => {
  it("names the post of a Facebook comment frame", () => {
    expect(postIdOfFrame(frame())).toBe("p-1");
  });
  it("ignores other streams, other platforms and frames with no post", () => {
    expect(postIdOfFrame(JSON.stringify({ stream: "message.events", payload: { post_id: "p-1" } }))).toBeNull();
    expect(postIdOfFrame(frame({ platform: "instagram" }))).toBeNull();
    expect(postIdOfFrame(frame({ post_id: "" }))).toBeNull();
  });
  it("never throws on a broken frame", () => {
    expect(postIdOfFrame("{not json")).toBeNull();
    expect(postIdOfFrame("")).toBeNull();
    expect(postIdOfFrame(undefined)).toBeNull();
    expect(postIdOfFrame("null")).toBeNull();
  });
});

describe("reconnect delay", () => {
  it("grows, then stops growing", () => {
    expect(backoffMs(0)).toBe(1000);
    expect(backoffMs(1)).toBe(2000);
    expect(backoffMs(2)).toBe(4000);
    expect(backoffMs(20)).toBe(30000);
  });
});

/** A hand-moved clock and a fake stream, so the push is tested with no browser. */
function world() {
  const w = { timers: [], source: null, opened: 0 };
  w.deps = {
    setTimer: (fn, ms) => { const t = { fn, ms, live: true }; w.timers.push(t); return t; },
    clearTimer: (t) => { t.live = false; },
    open: () => {
      w.opened += 1;
      w.source = { onmessage: null, onerror: null, onopen: null, closed: false, close() { this.closed = true; } };
      return w.source;
    },
  };
  w.fire = (t) => { t.live = false; return t.fn(); };
  w.live = () => w.timers.filter((t) => t.live);
  return w;
}

describe("the open screen learns of a comment as it is stored", () => {
  it("reloads the post named by the frame", () => {
    const w = world();
    const reload = vi.fn();
    startCommentPush({ reload, ...w.deps });
    w.source.onmessage({ data: frame() });
    w.fire(w.live().pop()); // the short settle window
    expect(reload).toHaveBeenCalledWith("p-1");
  });

  it("folds a burst on one post into a single reload", () => {
    const w = world();
    const reload = vi.fn();
    startCommentPush({ reload, ...w.deps });
    w.source.onmessage({ data: frame({ comment_id: "c-1" }) });
    w.source.onmessage({ data: frame({ comment_id: "c-2" }) });
    w.source.onmessage({ data: frame({ comment_id: "c-3" }) });
    w.live().forEach((t) => w.fire(t));
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("reloads each post once when a burst spans two", () => {
    const w = world();
    const reload = vi.fn();
    startCommentPush({ reload, ...w.deps });
    w.source.onmessage({ data: frame({ post_id: "p-1" }) });
    w.source.onmessage({ data: frame({ post_id: "p-2" }) });
    w.live().forEach((t) => w.fire(t));
    expect(reload.mock.calls.map((c) => c[0]).sort()).toEqual(["p-1", "p-2"]);
  });

  it("does nothing for a frame that is not a Facebook comment", () => {
    const w = world();
    const reload = vi.fn();
    startCommentPush({ reload, ...w.deps });
    w.source.onmessage({ data: JSON.stringify({ stream: "order.events", payload: {} }) });
    expect(w.live()).toHaveLength(0);
    expect(reload).not.toHaveBeenCalled();
  });

  it("reconnects after a drop, later each time, and starts over once it hears again", () => {
    const w = world();
    startCommentPush({ reload: vi.fn(), ...w.deps });
    w.source.onerror();
    expect(w.source.closed).toBe(true);
    const first = w.live().pop();
    expect(first.ms).toBe(1000);
    w.fire(first);
    expect(w.opened).toBe(2);
    w.source.onerror();
    expect(w.live().pop().ms).toBe(2000);
    w.fire(w.live().pop());
    w.source.onopen();
    w.source.onerror();
    expect(w.live().pop().ms).toBe(1000);
  });

  it("stop() closes the stream and cancels everything pending", () => {
    const w = world();
    const reload = vi.fn();
    const stop = startCommentPush({ reload, ...w.deps });
    w.source.onmessage({ data: frame() });
    stop();
    expect(w.source.closed).toBe(true);
    expect(w.live()).toHaveLength(0);
    w.source.onerror?.();
    expect(w.live()).toHaveLength(0);
    expect(reload).not.toHaveBeenCalled();
  });

  it("a failed reload is dropped, the screen keeps what it has", async () => {
    const w = world();
    const reload = vi.fn().mockRejectedValue(new Error("down"));
    startCommentPush({ reload, ...w.deps });
    w.source.onmessage({ data: frame() });
    await expect(Promise.resolve(w.fire(w.live().pop()))).resolves.not.toThrow();
  });
});
