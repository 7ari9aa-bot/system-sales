/**
 * Looks again, now and then, at something the server already holds, so what arrives while a screen is
 * open (a comment the webhook stored) shows up without a reload. Quiet on purpose:
 *  - only while the tab is showing, and once more the moment it comes back;
 *  - never two looks at the same time;
 *  - a failed look is dropped, the screen keeps what it has and the next one tries again.
 * The clock and the tab are passed in, so it is tested without React or a browser.
 * Returns stop().
 */
export function startQuietRefresh({ look, everyMs, setTimer, clearTimer, isVisible, onVisibilityChange }) {
  let timer = null;
  let running = false;
  let stopped = false;

  async function once() {
    if (stopped || running || !isVisible()) return;
    running = true;
    try { await look(); } catch { /* keep what is on screen */ } finally { running = false; }
  }
  function arm() {
    if (stopped) return;
    timer = setTimer(async () => { await once(); arm(); }, everyMs);
  }
  const unsubscribe = onVisibilityChange(() => { void once(); });
  arm();

  return function stop() {
    stopped = true;
    if (timer) clearTimer(timer);
    unsubscribe();
  };
}

/** The browser's own clock and tab, for the screens. */
export const browserWorld = () => ({
  setTimer: (fn, ms) => setTimeout(fn, ms),
  clearTimer: (t) => clearTimeout(t),
  isVisible: () => typeof document === "undefined" || document.visibilityState !== "hidden",
  onVisibilityChange: (cb) => {
    if (typeof document === "undefined") return () => {};
    document.addEventListener("visibilitychange", cb);
    return () => document.removeEventListener("visibilitychange", cb);
  },
});
