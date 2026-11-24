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
  // An approved or cancelled sheet takes no more counts, and says so, instead of the till
  // reporting a save the server will never accept.
  let closed = false;
  // The request currently in flight, so a manual save or an APPROVE can wait for it instead of
  // racing it. `saving` is only the fast guard; this is the thing worth awaiting.
  let inFlight = null;

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

  /** Send one batch and keep the promise, so anyone may await the money landing. */
  function send(counts) {
    inFlight = Promise.resolve()
      .then(() => onSave(counts))
      .finally(() => {
        inFlight = null;
      });
    return inFlight;
  }

  function run() {
    timer = null;
    // One save at a time: a second request would land on the sheet the first is about to replace.
    if (inFlight) {
      timer = timers.set(run, retryDelay);
      return;
    }
    const counts = drain();
    if (!counts.length) return;
    send(counts).catch(onError);
  }

  /**
   * The real flush: cancel the timer, WAIT for the request already on the wire, then send
   * everything still queued and wait for that too.
   *
   * ``drain()`` alone was not enough. It cancelled the timer and handed back the queue, but the
   * request a scan had already started was still running, so an approve could land first and the
   * count it depended on arrived afterwards — against a sheet the server had already closed.
   * Resolves true only when every pending count is confirmed saved.
   */
  async function flushAndWait() {
    cancel();
    if (closed) return false;
    if (inFlight) {
      try {
        await inFlight;
      } catch {
        // The in-flight save reported itself through onError; the caller still must not approve.
        return false;
      }
    }
    const counts = drain();
    if (!counts.length) return true;
    try {
      await send(counts);
      return true;
    } catch (error) {
      onError(error);
      return false;
    }
  }

  /**
   * Leaving the screen: save what is waiting instead of dropping it.
   *
   * ``dispose`` used to be ``cancel``, so a scan taken in the last two seconds of the page's life
   * was silently lost — the count simply never reached the sheet. It now sends that batch; a
   * failure is reported through ``onError`` rather than swallowed.
   */
  function dispose() {
    cancel();
    const counts = drain();
    if (!counts.length) return null;
    const pendingSave = send(counts);
    pendingSave.catch(onError);
    return pendingSave;
  }

  return {
    /** Record a scan and (re)start the gathering window. */
    push(variantId, countedQty) {
      if (closed) return;
      queued[variantId] = countedQty;
      cancel();
      timer = timers.set(run, delay);
    },
    /** The sheet was approved or cancelled: no count may be sent after this. */
    close() {
      closed = true;
      cancel();
      queued = {};
    },
    /** Used by a manual save and by approve: nothing may fire after this returns. */
    drain,
    /** Await everything, including the request already in flight. */
    flushAndWait,
    dispose,
    get pending() {
      return { ...queued };
    },
    get scheduled() {
      return timer !== null;
    },
    get saving() {
      return inFlight !== null;
    },
  };
}
