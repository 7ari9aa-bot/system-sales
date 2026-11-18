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
export async function sendReply(conversationId, text, { api = defaultApi, intents = sendIntents, replyToId = null, mediaId = null, heart = false, sharePostId = null } = {}) {
  const slot = `send:${conversationId}`;
  // Which message is being answered, and which uploaded file goes with it, are
  // part of the intention: the same words with a different file (or as a reply
  // to a different message) must be a new send, not a replay.
  const key = intents.take(slot, { text, replyToId, mediaId, heart, sharePostId });
  try {
    const body = {};
    if (text) body.body = text;
    if (replyToId) body.reply_to_message_id = replyToId;
    if (mediaId) body.media_id = mediaId;
    // Instagram only: the heart sticker, or one of the shop's own posts, sent as a card.
    if (heart) body.instagram_heart = true;
    if (sharePostId) body.instagram_share_post_id = String(sharePostId);
    const sent = await api(`/conversations/${conversationId}/messages`, {
      method: "POST",
      body,
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

/**
 * Upload a file the agent is about to send. The raw file is the body; its name
 * travels percent-encoded so an Arabic name survives a header. Nothing reaches
 * the customer from here: the returned `media_id` goes to sendReply.
 *
 * @returns {Promise<{ok: true, media: {media_id: string, kind: string, filename: string, size: number}} | {ok: false, error: string}>}
 */
export async function uploadMedia(conversationId, file, { api = defaultApi, asSticker = false, signal } = {}) {
  try {
    const media = await api(`/conversations/${conversationId}/media`, {
      method: "POST",
      body: file,
      rawBody: true,
      contentType: file.type || "application/octet-stream",
      headers: {
        "X-Filename": encodeURIComponent(file.name || "file"),
        ...(asSticker ? { "X-As-Sticker": "true" } : {}),
      },
      signal,
    });
    return { ok: true, media };
  } catch (e) {
    if (e?.name === "AbortError") return { ok: false, error: "", aborted: true };
    return {
      ok: false,
      error: e?.code === "timeout" ? "The upload took too long. Check your connection and try again." : (e?.message || "Could not upload the file."),
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

/** Show OUR reaction on one message right away (an empty emoji clears it).
 *  Only that message in that conversation changes; the other person's reaction
 *  stays. Returns the previous value so a refused request can be put back. */
export function setMyReaction(convMap, channelId, conversationId, messageId, emoji, previous = "") {
  return {
    ...convMap,
    [channelId]: (convMap[channelId] || []).map((row) => row.id !== conversationId
      ? row
      : {
          ...row,
          messages: (row.messages || []).map((m) => {
            if (m.id !== messageId) return m;
            const without = previous ? removeOnce(m.reactions || [], previous) : (m.reactions || []);
            return { ...m, myReaction: emoji, reactions: emoji ? [...without, emoji] : without };
          }),
        }),
  };
}

function removeOnce(list, value) {
  const at = list.indexOf(value);
  return at < 0 ? list : [...list.slice(0, at), ...list.slice(at + 1)];
}

/** React to one message with an emoji; an empty emoji withdraws our reaction.
 *  A reaction is idempotent by nature (the newest one per person wins), so no
 *  Idempotency-Key is needed and a retry is harmless.
 *  @returns {Promise<{ok: true} | {ok: false, error: string}>} */
export async function sendReaction(conversationId, messageId, emoji, { api = defaultApi } = {}) {
  try {
    await api(`/conversations/${conversationId}/messages/${messageId}/reaction`, {
      method: "POST",
      body: { emoji },
    });
    return { ok: true };
  } catch (e) {
    return { ok: false, error: e?.message || "Could not send the reaction." };
  }
}
