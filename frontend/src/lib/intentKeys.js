/**
 * One Idempotency-Key per user INTENTION, for writes outside the cashier.
 *
 * Same content sent again -> the SAME key, so the server replays the first
 * result instead of doing it twice (a retry after a timeout or a lost reply).
 * Different content under the slot -> a NEW key (the user edited something; a
 * reused key with a new body is a guaranteed 409).
 * A call that SUCCEEDED forgets its key so the next deliberate action is fresh.
 *
 * The cashier keeps its own copy (cashier/api/intentStore.js) on purpose: that
 * module is frozen while the POS layer is being finished.
 */

/** Order-independent, stable text for a JSON-able value. */
export function fingerprint(value) {
  if (value === null || typeof value !== "object") return JSON.stringify(value) ?? "undefined";
  if (Array.isArray(value)) return `[${value.map(fingerprint).join(",")}]`;
  return `{${Object.keys(value)
    .sort()
    .map((k) => `${JSON.stringify(k)}:${fingerprint(value[k])}`)
    .join(",")}}`;
}

export function newKey(prefix = "op") {
  const rand =
    globalThis.crypto?.randomUUID?.() ??
    `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`;
  return `${prefix}-${rand}`;
}

export function createIntentKeys(prefix = "op", make = newKey) {
  const slots = new Map(); // slot -> { print, key }
  return {
    /** The key to send for this slot and content. */
    take(slot, content) {
      const print = fingerprint(content);
      const held = slots.get(slot);
      if (held && held.print === print) return held.key;
      const key = make(prefix);
      slots.set(slot, { print, key });
      return key;
    },
    /** Call after the call SUCCEEDED (or when the server burned the key). */
    done(slot) {
      slots.delete(slot);
    },
    size: () => slots.size,
  };
}
