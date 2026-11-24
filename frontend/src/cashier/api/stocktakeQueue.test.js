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

  it("disposing on unmount saves the queued scan instead of dropping it", async () => {
    // Leaving the screen used to be `cancel`, so a scan taken in the last two seconds never
    // reached the sheet at all.
    const { queue, tick, saved } = makeQueue();
    queue.push("v1", 1);
    await queue.dispose();
    tick();
    await flushMicrotasks();
    expect(saved).toHaveLength(1);
    expect(saved[0]).toEqual([{ variant_id: "v1", counted_qty: 1 }]);
  });

  it("flushing waits for the save already on the wire before approving", async () => {
    // The race the report found: scan, the debounce fires and starts a request, then the cashier
    // presses approve. `drain()` cancelled the timer but returned immediately, so approval could
    // reach the server before the count did.
    let release;
    const order = [];
    const { queue, tick, saved } = makeQueue({
      onSave: (counts) => {
        order.push("start");
        saved.push(counts);
        return new Promise((resolve) => {
          release = () => {
            order.push("saved");
            resolve();
          };
        });
      },
    });
    queue.push("v1", 1);
    tick();
    await flushMicrotasks();
    expect(queue.saving).toBe(true);

    const flushed = queue.flushAndWait();
    let done = false;
    flushed.then(() => {
      done = true;
    });
    await flushMicrotasks();
    expect(done).toBe(false);
    expect(order).toEqual(["start"]);

    release();
    expect(await flushed).toBe(true);
    expect(order).toEqual(["start", "saved"]);
    expect(saved).toHaveLength(1);
  });

  it("flushing sends the queued scans once the in-flight save lands", async () => {
    let release;
    const { queue, tick, saved } = makeQueue({
      onSave: (counts) => {
        saved.push(counts);
        if (saved.length === 1) {
          return new Promise((resolve) => {
            release = resolve;
          });
        }
        return Promise.resolve();
      },
    });
    queue.push("v1", 1);
    tick();
    await flushMicrotasks();
    queue.push("v2", 4);

    const flushed = queue.flushAndWait();
    await flushMicrotasks();
    release();
    expect(await flushed).toBe(true);
    expect(saved).toEqual([
      [{ variant_id: "v1", counted_qty: 1 }],
      [{ variant_id: "v2", counted_qty: 4 }],
    ]);
  });

  it("a closed sheet refuses a queued save", async () => {
    const { queue, tick, saved } = makeQueue();
    queue.push("v1", 1);
    queue.close();
    tick();
    await flushMicrotasks();
    expect(saved).toHaveLength(0);
    expect(await queue.flushAndWait()).toBe(false);
    queue.push("v2", 9);
    expect(await queue.flushAndWait()).toBe(false);
    expect(saved).toHaveLength(0);
  });

  it("leaving the page waits for the running save instead of racing it", async () => {
    // The report's fourth blocker: dispose() sent the last batch straight away, replacing the
    // in-flight reference, so count 1 and count 2 could be on the wire together and the older one
    // could land last — writing the stale figure over the newer one.
    const order = [];
    const releases = [];
    const { queue, tick } = makeQueue({
      onSave: (counts) => {
        order.push({ start: counts[0].counted_qty, overlap: order.some((o) => !o.done) });
        const entry = order.at(-1);
        return new Promise((resolve) => {
          releases.push(() => {
            entry.done = true;
            resolve();
          });
        });
      },
    });
    queue.push("v1", 1);
    tick();
    await flushMicrotasks(); // the first save is now on the wire
    queue.push("v1", 2); // a second scan while it is still running

    const disposed = queue.dispose();
    await flushMicrotasks();
    // Only the first request exists so far: leaving did not jump the queue.
    expect(order).toHaveLength(1);

    releases[0]();
    await flushMicrotasks();
    expect(order).toHaveLength(2);
    expect(order[1]).toMatchObject({ start: 2, overlap: false });

    releases[1]();
    await disposed;
  });

  it("reports a failed flush so approval can be refused", async () => {
    const onError = vi.fn();
    const { queue, tick } = makeQueue({
      onSave: () => Promise.reject(new Error("offline")),
    });
    queue.push("v1", 1);
    tick();
    await flushMicrotasks();
    queue.push("v2", 2);
    expect(await queue.flushAndWait()).toBe(false);
  });

  it("a save that is still in flight when approve is pressed is awaited, not skipped", async () => {
    let release;
    const { queue, tick, saved } = makeQueue({
      onSave: (counts) => {
        saved.push(counts);
        return new Promise((resolve) => {
          release = resolve;
        });
      },
    });
    queue.push("v1", 2);
    tick();
    await flushMicrotasks();
    const flushed = queue.flushAndWait();
    await flushMicrotasks();
    expect(saved).toHaveLength(1);
    release();
    expect(await flushed).toBe(true);
    expect(saved).toHaveLength(1);
  });
});
