/**
 * Keeps one Idempotency-Key per user INTENTION.
 *
 * Same request content, sent again  -> the SAME key, so the server replays instead of doing it twice
 *                                      (a double tap, or a retry after the response was lost).
 * Different content under that slot -> a NEW key. The user fixed something after a refusal, so this is a new
 *                                      intention; re-using the old key with a new body is a guaranteed 409
 *                                      ("key reused with a different body") that the user could never get out of.
 * A call that SUCCEEDS forgets its key, so the next deliberate action starts fresh.
 */
import { newIntent } from "./posApi";

/** Order-independent, stable text for a JSON-able value. */
export function fingerprint(value) {
  if (value === null || typeof value !== "object") return JSON.stringify(value) ?? "undefined";
  if (Array.isArray(value)) return `[${value.map(fingerprint).join(",")}]`;
  return `{${Object.keys(value)
    .sort()
    .map((k) => `${JSON.stringify(k)}:${fingerprint(value[k])}`)
    .join(",")}}`;
}

export function createIntentStore(make = newIntent) {
  const slots = new Map(); // slot -> { print, intent }
  return {
    /** The intent to send for this slot and content. */
    take(slot, content) {
      const print = fingerprint(content);
      const held = slots.get(slot);
      if (held && held.print === print) return held.intent;
      const intent = make();
      slots.set(slot, { print, intent });
      return intent;
    },
    /** Call after a call SUCCEEDED. */
    done(slot) {
      slots.delete(slot);
    },
    size: () => slots.size,
  };
}
