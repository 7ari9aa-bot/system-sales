/** The anonymous website visitor id: ONE definition shared by the tracker and signup.
 *
 *  The tracker writes it to localStorage on the first visit; signup sends the same value
 *  so the owner console can tie "this visitor" to "the merchant they became". If the two
 *  ever read different keys the link silently breaks, so neither file owns the key.
 *  The id is random and carries no personal data. */

export const VISITOR_KEY = "fihrist:visitorId";
export const SESSION_KEY = "fihrist:visitorSession";

export function randomId() {
  if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
  return `v-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

export function getOrCreate(storage, key) {
  try {
    const existing = storage.getItem(key);
    if (existing) return existing;
    const next = randomId();
    storage.setItem(key, next);
    return next;
  } catch {
    return randomId();
  }
}

/** The id to attach to a signup. NEVER creates one: a visitor who has no id was not
 *  tracked, and inventing one at signup would "attribute" a merchant to nobody.
 *  Returns null when storage is unavailable or empty. */
export function currentVisitorId() {
  try {
    return localStorage.getItem(VISITOR_KEY) || null;
  } catch {
    return null;
  }
}
