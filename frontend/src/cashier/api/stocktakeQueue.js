/**
 * The stocktake scan queue: scans are gathered for a moment and then saved in one request, because
 * one request per scan fights the scanner.
 *
 * The bug this exists to make impossible: the timer kept running through a manual save or an
 * APPROVE. A scan taken a second earlier then fired its own request for the same line after the
 * sheet had already been saved (a second count of the same piece, a phantom recount), and after
 * approval it wrote against a CLOSED stocktake. So there is exactly one way out of the queue —
 * `drain()` — and the timer, a manual save and an approve all go through it. Draining cancels the
 * timer and returns the queued counts, so they ride along with the save instead of chasing it.
 */

/**
 * @param {object} opts
 * @param {(queued: Record<string, number>) => Array<object>} opts.merge  queued scans -> the rows
 *        to POST (the caller folds in whatever is typed but not yet queued).
 * @param {(counts: Array<object>) => Promise<unknown>} opts.onSave  the request itself.
 * @param {number} [opts.delay]  how long scans are gathered (default 2000ms).
 * @param {number} [opts.retryDelay]  how long to wait while a save is still in flight.
 * @param {{set: Function, clear: Function}} [opts.timers]  injectable for tests.
 * @param {(error: unknown) => void} [opts.onError]
 */
export function createCountQueue({
  merge,
  onSave,
  delay = 2000,
  retryDelay = 1000,
  timers = { set: setTimeout, clear: clearTimeout },
  onError = () => {},
}) {
  let queued = {};
  let timer = null;
  let saving = false;

  function cancel() {
    if (timer !== null) {
      timers.clear(timer);
      timer = null;
    }
  }

  /** One way out: cancel the timer, hand back what was waiting, and empty the queue. */
  function drain() {
    cancel();
    const waiting = queued;
    queued = {};
    return merge(waiting);
  }

  function run() {
    timer = null;
    // One save at a time: a second request would land on the sheet the first is about to replace.
    if (saving) {
      timer = timers.set(run, retryDelay);
      return;
    }
    const counts = drain();
    if (!counts.length) return;
    saving = true;
    Promise.resolve()
      .then(() => onSave(counts))
      .catch(onError)
      .finally(() => {
        saving = false;
      });
  }

  return {
    /** Record a scan and (re)start the gathering window. */
    push(variantId, countedQty) {
      queued[variantId] = countedQty;
      cancel();
      timer = timers.set(run, delay);
    },
    /** Used by a manual save and by approve: nothing may fire after this returns. */
    drain,
    dispose: cancel,
    get pending() {
      return { ...queued };
    },
    get scheduled() {
      return timer !== null;
    },
  };
}
