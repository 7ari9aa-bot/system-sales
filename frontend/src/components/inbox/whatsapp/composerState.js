// What the WhatsApp input bar may do right now, decided in one place so the bar
// never offers something the server will refuse or that the customer will not
// actually receive.

import { replyWindow } from "./replyWindow";

export const MAX_LENGTH = 4096; // the server's limit on a message body
export const MAX_ROWS = 5; // the field grows to this many lines, then scrolls

/**
 * @returns {{ canType: boolean, reason: "closed"|"never"|"sending"|null }}
 * A closed window means a free-form reply is refused by the server (an approved
 * template is required), so the bar says so instead of letting the agent type a
 * message that will only fail.
 */
export function composerAvailability({ lastCustomerMessageAt, sending = false, now = new Date() }) {
  const win = replyWindow(lastCustomerMessageAt, now);
  if (win.state === "closed") return { canType: false, reason: "closed", window: win };
  if (sending) return { canType: false, reason: "sending", window: win };
  return { canType: true, reason: null, window: win };
}

/** Whether Enter sends (Shift+Enter, or Enter while composing IME text, does not). */
export function enterSends(event) {
  if (event.key !== "Enter") return false;
  if (event.shiftKey) return false;
  if (event.isComposing || event.nativeEvent?.isComposing || event.keyCode === 229) return false;
  return true;
}

/** How many text rows the field should show for `value`, 1 to MAX_ROWS. */
export function rowsFor(value) {
  const lines = String(value ?? "").split("\n").length;
  return Math.min(MAX_ROWS, Math.max(1, lines));
}

/** A message the server would accept: non-empty after trimming and within the limit. */
export function sendable(value) {
  const body = String(value ?? "").trim();
  return body.length > 0 && body.length <= MAX_LENGTH;
}

/** How close to the limit the agent is: show a counter only in the last 10%. */
export function lengthWarning(value) {
  const n = String(value ?? "").length;
  return n >= MAX_LENGTH * 0.9 ? { n, left: MAX_LENGTH - n, over: n > MAX_LENGTH } : null;
}
