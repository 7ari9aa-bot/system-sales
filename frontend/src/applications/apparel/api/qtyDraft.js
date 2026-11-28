/**
 * What a quantity box shows WHILE the cashier is typing.
 *
 * The line's quantity is always a clamped whole number (at least 1, at most the stock). Feeding
 * every keystroke through that clamp made typing impossible: clearing "1" and typing "5" showed
 * "1" then "15", and typing "12" with 50 in stock jumped to "50". On a till that sells the wrong
 * number of pieces. So the box keeps what was typed and only the committed number is clamped, once,
 * when the cashier leaves the box or presses Enter.
 */
import { clampQty } from "./checkout";

/** Keep only digits while typing: a quantity is a whole number, so "-", "." and "e" are never valid. */
export function typedQty(raw) {
  return String(raw ?? "").replace(/\D+/g, "").slice(0, 4);
}

/**
 * The quantity to commit from what is in the box. An empty box means "I changed my mind": keep the
 * line's current quantity rather than silently turning it into 1.
 */
export function committedQty(draft, current, stock) {
  const text = typedQty(draft);
  if (text === "") return current;
  return clampQty(Number(text), stock) || current;
}

/** What to show: the draft while typing, otherwise the line's real quantity. */
export function shownQty(draft, current) {
  return draft === null ? String(current) : draft;
}
