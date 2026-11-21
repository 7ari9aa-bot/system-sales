import { describe, expect, it, vi } from "vitest";
import { startQuietRefresh } from "@/lib/quietRefresh";

/** A clock the test moves by hand, and a tab it shows or hides by hand. */
function world({ visible = true } = {}) {
  const w = { visible, timers: [], onVisible: null };
  w.deps = {
    setTimer: (fn, ms) => { const t = { fn, ms, live: true }; w.timers.push(t); return t; },
    clearTimer: (t) => { t.live = false; },
    isVisible: () => w.visible,
    onVisibilityChange: (cb) => { w.onVisible = cb; return () => { w.onVisible = null; }; },
  };
  w.tick = async () => { const t = w.timers.filter((x) => x.live).pop(); t.live = false; await t.fn(); };
  w.live = () => w.timers.filter((t) => t.live).length;
  return w;
}

describe("looking again at what the webhook stored, without bothering anyone", () => {
  it("looks once per interval while the tab is showing, and keeps going", async () => {
    const w = world();
    const look = vi.fn().mockResolvedValue(undefined);
    startQuietRefresh({ look, everyMs: 30000, ...w.deps });
    expect(look).not.toHaveBeenCalled(); // the screen's own first load covers the start
    await w.tick(); await w.tick(); await w.tick();
    expect(look).toHaveBeenCalledTimes(3);
    expect(w.timers.every((t) => t.ms === 30000)).toBe(true);
  });

  it("does not look while the tab is hidden, but keeps its place to look again", async () => {
    const w = world({ visible: false });
    const look = vi.fn().mockResolvedValue(undefined);
    startQuietRefresh({ look, everyMs: 30000, ...w.deps });
    await w.tick(); await w.tick();
    expect(look).not.toHaveBeenCalled();
    expect(w.live()).toBe(1);
  });

  it("looks right away when the tab comes back, so a comment that came meanwhile is there", async () => {
    const w = world({ visible: false });
    const look = vi.fn().mockResolvedValue(undefined);
    startQuietRefresh({ look, everyMs: 30000, ...w.deps });
    w.visible = true; await w.onVisible();
    expect(look).toHaveBeenCalledTimes(1);
  });

  it("does not stack two looks when one is still running", async () => {
    const w = world();
    let finish; const look = vi.fn(() => new Promise((r) => { finish = r; }));
    startQuietRefresh({ look, everyMs: 30000, ...w.deps });
    const first = w.tick();
    await w.onVisible(); // the tab flickers while the first look is still out
    expect(look).toHaveBeenCalledTimes(1);
    finish(); await first;
  });

  it("a failing look does not stop the next one and never throws", async () => {
    const w = world();
    const look = vi.fn().mockRejectedValueOnce(new Error("network")).mockResolvedValue(undefined);
    startQuietRefresh({ look, everyMs: 30000, ...w.deps });
    await expect(w.tick()).resolves.not.toThrow();
    await w.tick();
    expect(look).toHaveBeenCalledTimes(2);
  });

  it("stop() ends it: no timer left, no listener left, no look after", async () => {
    const w = world();
    const look = vi.fn().mockResolvedValue(undefined);
    const stop = startQuietRefresh({ look, everyMs: 30000, ...w.deps });
    stop();
    expect(w.live()).toBe(0);
    expect(w.onVisible).toBe(null);
  });
});
