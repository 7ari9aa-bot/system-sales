/**
 * Sending an inbox reply, kept out of the Inbox component so the retry rules
 * can be tested without a DOM.
 *
 * Rules (they mirror backend/app/core/idempotency.py):
 *  - One Idempotency-Key per "this text to this conversation" intention. A retry
 *    after a timeout or a lost reply re-sends the SAME key, so the server
 *    replays the first result instead of messaging the customer twice.
 *  - A success forgets the key. Edited text is a new intention (new key).
 *  - 4xx: nothing ran, the server released the key, ours may be reused.
 *  - 5xx: the outcome is unknown and the server burns the key (409 on reuse),
 *    so drop ours; the user is told to check before sending again.
 *  - Timeout: outcome unknown too, but the key is still valid, so KEEP it:
 *    pressing Send again is safe and cannot duplicate.
 */
import { api as defaultApi } from "@/lib/api";
import { createIntentKeys } from "@/lib/intentKeys";

const sendIntents = createIntentKeys("msg");

export const TIMEOUT_MESSAGE =
  "Sending took too long. It may have gone through: check the conversation before sending again.";

/** @returns {Promise<{ok: true, sent: object|null} | {ok: false, error: string}>} */
export async function sendReply(conversationId, text, { api = defaultApi, intents = sendIntents } = {}) {
  const slot = `send:${conversationId}`;
  const key = intents.take(slot, { text });
  try {
    const sent = await api(`/conversations/${conversationId}/messages`, {
      method: "POST",
      body: { body: text },
      headers: { "Idempotency-Key": key },
    });
    intents.done(slot);
    return { ok: true, sent };
  } catch (e) {
    if (e?.status >= 500) intents.done(slot);
    return {
      ok: false,
      error: e?.code === "timeout" ? TIMEOUT_MESSAGE : (e?.message || "Could not send the message."),
    };
  }
}

/** Add `message` to one conversation in ONE channel; every other channel is untouched.
 *  The channel is passed in explicitly because the caller captured it before the await. */
export function appendLocalMessage(convMap, channelId, conversationId, message, preview) {
  return {
    ...convMap,
    [channelId]: (convMap[channelId] || []).map((row) => row.id === conversationId
      ? { ...row, preview, messages: [...(row.messages || []), message] }
      : row),
  };
}
