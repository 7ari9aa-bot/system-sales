import { describe, expect, it, vi } from "vitest";
import { createCountQueue } from "./stocktakeQueue";

/** A queue with a hand-driven clock, so "2 seconds later" is a decision, not a sleep. */
function makeQueue({ onSave } = {}) {
  const timers = new Map();
  let nextId = 1;
  const fake = {
    set: vi.fn((fn, ms) => {
      const id = nextId++;
      timers.set(id, { fn, ms });
      return id;
    }),
    clear: vi.fn((id) => timers.delete(id)),
  };
  const saved = [];
  const queue = createCountQueue({
    merge: (queued) =>
      Object.entries(queued).map(([variant_id, counted_qty]) => ({ variant_id, counted_qty })),
    onSave:
      onSave ??
      ((counts) => {
        saved.push(counts);
        return Promise.resolve();
      }),
    timers: fake,
    delay: 2000,
    retryDelay: 1000,
  });
  /** Fire whatever is scheduled, the way the browser would after the window elapsed. */
  const tick = () => {
    const entries = [...timers.entries()];
    timers.clear();
    for (const [, t] of entries) t.fn();
  };
  return { queue, tick, saved, fake, timers };
}

const flushMicrotasks = () => new Promise((r) => setTimeout(r, 0));

describe("the stocktake scan queue", () => {
  it("gathers scans into one save instead of one request per scan", async () => {
    const { queue, tick, saved } = makeQueue();
    queue.push("v1", 3);
    queue.push("v2", 5);
    expect(saved).toHaveLength(0);
    tick();
    await flushMicrotasks();
    expect(saved).toEqual([
      [
        { variant_id: "v1", counted_qty: 3 },
        { variant_id: "v2", counted_qty: 5 },
      ],
    ]);
  });

  it("a scan of the same line twice keeps only the latest count", async () => {
    const { queue, tick, saved } = makeQueue();
    queue.push("v1", 3);
    queue.push("v1", 4);
    tick();
    await flushMicrotasks();
    expect(saved).toEqual([[{ variant_id: "v1", counted_qty: 4 }]]);
  });

  it("a manual save drains the queue, so the timer never fires a second request", async () => {
    const { queue, tick, saved, fake } = makeQueue();
    queue.push("v1", 3);
    // The cashier presses Save before the 2s window elapses.
    const drained = queue.drain();
    expect(drained).toEqual([{ variant_id: "v1", counted_qty: 3 }]);
    expect(queue.scheduled).toBe(false);
    expect(fake.clear).toHaveBeenCalled();

    // Nothing is left to fire: the old timer cannot re-save the same line.
    tick();
    await flushMicrotasks();
    expect(saved).toHaveLength(0);
  });

  it("after an approve nothing is queued and nothing can fire", async () => {
    const { queue, tick, saved } = makeQueue();
    queue.push("v1", 2);
    queue.drain(); // approve saves and then closes the sheet
    tick();
    await flushMicrotasks();
    expect(saved).toHaveLength(0);
    expect(queue.pending).toEqual({});
  });

  it("waits while a save is in flight instead of overlapping it", async () => {
    let release;
    const { queue, tick, saved } = makeQueue({
      onSave: (counts) =>
        new Promise((resolve) => {
          saved.push(counts);
          release = resolve;
        }),
    });
    queue.push("v1", 1);
    tick();
    await flushMicrotasks();
    expect(saved).toHaveLength(1);

    // A scan arrives while the first save is still running: it must NOT start a second request.
    queue.push("v2", 2);
    tick();
    await flushMicrotasks();
    expect(saved).toHaveLength(1);

    release();
    await flushMicrotasks();
    tick();
    await flushMicrotasks();
    expect(saved).toHaveLength(2);
    expect(saved[1]).toEqual([{ variant_id: "v2", counted_qty: 2 }]);
  });

  it("a failed save is reported, not swallowed", async () => {
    const onError = vi.fn();
    const timers = new Map();
    let id = 1;
    const queue = createCountQueue({
      merge: () => [{ variant_id: "v1", counted_qty: 1 }],
      onSave: () => Promise.reject(new Error("boom")),
      timers: {
        set: (fn) => {
          timers.set(id, fn);
          return id++;
        },
        clear: (timer) => timers.delete(timer),
      },
      onError,
    });
    queue.push("v1", 1);
    for (const fn of [...timers.values()]) fn();
    await flushMicrotasks();
    expect(onError).toHaveBeenCalled();
  });

  it("disposing on unmount cancels the pending save", async () => {
    const { queue, tick, saved } = makeQueue();
    queue.push("v1", 1);
    queue.dispose();
    tick();
    await flushMicrotasks();
    expect(saved).toHaveLength(0);
  });
});
