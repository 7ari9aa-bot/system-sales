// Blue ticks / Seen and "typing…" on the CUSTOMER's phone (WhatsApp and Instagram).
//
// Opening a chat tells the channel the customer's messages were read. Typing tells it
// we are writing a reply; Meta clears that after 25 seconds, so one signal per 20
// seconds keeps it alive without a request per keystroke. Both are courtesies:
// they never block the agent and a failure is silent.

import { replyWindow } from "./replyWindow";

/** Meta drops the indicator after 25s (WhatsApp and Instagram alike); refresh a little earlier. */
export const TYPING_REFRESH_MS = 20000;

/** True when a typing signal may go out right now. */
export function shouldSignalTyping({ text, lastSentAt, now = Date.now(), lastCustomerMessageAt }) {
  if (!String(text || "").trim()) return false; // an emptied box is not "typing"
  const state = replyWindow(lastCustomerMessageAt, new Date(now)).state;
  if (state === "closed" || state === "never") return false;
  return lastSentAt == null || now - lastSentAt >= TYPING_REFRESH_MS;
}

/** The request body for the server route. */
export const readSignalBody = (typing) => ({ typing: Boolean(typing) });

const SIGNAL_CHANNELS = ["whatsapp", "instagram", "messenger"];

/** WhatsApp, Instagram and Messenger all have these signals, and only for a chat that is open. */
export const supportsReadSignal = (conversation) =>
  Boolean(conversation?.id) &&
  (SIGNAL_CHANNELS.includes(conversation.channel) || SIGNAL_CHANNELS.includes(conversation.channelId));
