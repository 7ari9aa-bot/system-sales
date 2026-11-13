/**
 * Pure rules for the assistant's memory screen. The server is the authority (it refuses secrets,
 * instructions, duplicates and a full memory); these rules only keep the screen from sending what
 * can never succeed and from showing a misleading state.
 */

/** A note as the screen shows it: who wrote it, in words. */
export function sourceLabel(source, isAr = true) {
  if (source === "inferred") return isAr ? "استنتجتها من كلامك" : "Inferred from your chats";
  return isAr ? "قلتلي أفتكرها" : "You asked me to remember";
}

/** Trimmed text a note would be saved with, or null when there is nothing worth sending. */
export function cleanNote(text, maxChars) {
  const value = typeof text === "string" ? text.trim() : "";
  if (!value) return null;
  if (Number.isFinite(maxChars) && value.length > maxChars) return null;
  return value;
}

/** What the add box should say about the text typed so far. */
export function noteDraftState(text, maxChars) {
  const length = typeof text === "string" ? text.trim().length : 0;
  const over = Number.isFinite(maxChars) && length > maxChars;
  return {
    length,
    remaining: Number.isFinite(maxChars) ? maxChars - length : null,
    over,
    canSend: length > 0 && !over,
  };
}

/** True when the memory has no room for another note. */
export function isFull(count, maxNotes) {
  return Number.isFinite(maxNotes) && count >= maxNotes;
}

/**
 * The message to show for a failed call. The server already writes the reason in Arabic, so it is
 * used as it is; only a failure with no message of its own falls back to a generic line. The text of
 * the note is never part of an error, so nothing the owner typed is echoed back.
 */
export function memoryErrorMessage(error, isAr = true) {
  const own = typeof error?.message === "string" ? error.message.trim() : "";
  if (own && error?.status >= 400 && error?.status < 500) return own;
  return isAr ? "حصلت مشكلة. جرّب تاني بعد شوية." : "Something went wrong. Try again in a moment.";
}

/** The notes in the order the server sent them (newest first), without ever mutating the input. */
export function visibleNotes(notes) {
  return Array.isArray(notes) ? [...notes] : [];
}
