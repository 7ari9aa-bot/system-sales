// The chat list beside the conversation: how wide it is, and whether it is folded away.
// Pure functions only, so the rules are testable without a browser.

export const SIDEBAR_MIN = 220;
export const SIDEBAR_MAX = 480;
export const SIDEBAR_DEFAULT = 280;
export const SIDEBAR_STEP = 16; // one arrow-key press
export const STORAGE_KEY = "salesos.assistant.sidebar";

/** A width the list may actually have: a whole number between the limits. Anything that is not a
 *  finite number (a missing or damaged saved value) falls back to the default. */
export function clampWidth(value) {
  // only a number or numeric text counts: Number(null) and Number([]) are 0, which would silently
  // become the narrowest width instead of the default
  const usable = typeof value === "number" || (typeof value === "string" && value.trim() !== "");
  const n = usable ? Number(value) : NaN;
  if (!Number.isFinite(n)) return SIDEBAR_DEFAULT;
  return Math.min(SIDEBAR_MAX, Math.max(SIDEBAR_MIN, Math.round(n)));
}

/** The new width while dragging. `dir` is "rtl" or "ltr": the list sits at the start edge, so its
 *  inner edge is on the right in Arabic and on the left in English, and moving the pointer towards
 *  the page's far side widens it in both. */
export function widthFromDrag({ startWidth, startX, currentX, dir }) {
  const moved = currentX - startX;
  // RTL: the list is on the right, the handle on its left edge, so moving LEFT (negative) widens.
  const delta = dir === "rtl" ? -moved : moved;
  return clampWidth(startWidth + delta);
}

/** Width after an arrow key on the handle, or null when the key is not one the handle uses.
 *  The arrow that points away from the list widens it, as dragging that way would. */
export function widthFromKey({ width, key, dir }) {
  const widen = dir === "rtl" ? "ArrowLeft" : "ArrowRight";
  const narrow = dir === "rtl" ? "ArrowRight" : "ArrowLeft";
  if (key === widen) return clampWidth(width + SIDEBAR_STEP);
  if (key === narrow) return clampWidth(width - SIDEBAR_STEP);
  if (key === "Home") return SIDEBAR_MIN;
  if (key === "End") return SIDEBAR_MAX;
  return null;
}

/** What was saved last time, always safe to use. */
export function readSaved(storage) {
  try {
    const raw = storage?.getItem(STORAGE_KEY);
    if (!raw) return { width: SIDEBAR_DEFAULT, collapsed: false };
    const data = JSON.parse(raw);
    return {
      width: clampWidth(data?.width),
      collapsed: data?.collapsed === true,
    };
  } catch {
    return { width: SIDEBAR_DEFAULT, collapsed: false };
  }
}

/** Save the choice. A full or blocked storage must never break the page. */
export function writeSaved(storage, { width, collapsed }) {
  try {
    storage?.setItem(STORAGE_KEY, JSON.stringify({ width: clampWidth(width), collapsed: collapsed === true }));
  } catch {
    /* private mode or quota: the choice just does not outlive this tab */
  }
}
