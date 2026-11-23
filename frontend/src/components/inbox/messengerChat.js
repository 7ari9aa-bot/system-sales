// Messenger-only presentation rules, kept as pure functions so the chat can be
// tested without a browser. Values follow Messenger's own web chat:
//   - a sent bubble is the blue-to-purple brand gradient, a received one is #F0F0F0;
//   - bubbles are 18px round, but two bubbles that belong together are squared to
//     4px on the edge where they meet, on the sender's side only;
//   - Messenger has no ticks: nothing for sent, and the reader's avatar once seen;
//   - a run of messages from one person is one group, and the avatar sits on the
//     last bubble of the group.
// Everything here is derived from what the server already sends us; nothing is
// invented and nothing is fetched.

export const MESSENGER_BUBBLE_RADIUS = 18;
export const MESSENGER_JOIN_RADIUS = 4;
// Messenger joins messages that arrive close together into one visual group.
export const MESSENGER_GROUP_GAP_MS = 3 * 60 * 1000;

const sideOf = (message) => (message?.side === "out" ? "out" : "in");

/**
 * Where the message at `index` sits inside its run of same-side messages.
 * `first`/`last` are true at the ends of the run; a lone message is both.
 */
export function messengerGroup(messages, index, gapMs = MESSENGER_GROUP_GAP_MS) {
  const list = Array.isArray(messages) ? messages : [];
  const current = list[index];
  if (!current) return { first: true, last: true, alone: true, size: 1 };
  const side = sideOf(current);
  const at = (i) => {
    const message = list[i];
    if (!message) return false;
    if (sideOf(message) !== side) return false;
    if (message.senderType === "system" || current.senderType === "system") return false;
    const a = new Date(current.createdAt || 0).getTime();
    const b = new Date(message.createdAt || 0).getTime();
    // A missing or unparsable timestamp never joins two messages.
    if (!a || !b) return false;
    return Math.abs(a - b) <= gapMs;
  };
  const first = !at(index - 1);
  const last = !at(index + 1);
  let size = 1;
  for (let i = index - 1; at(i); i -= 1) size += 1;
  for (let i = index + 1; at(i); i += 1) size += 1;
  return { first, last, alone: size === 1, size };
}

/**
 * Corner classes for one bubble. Own messages always sit at the inline end, so
 * the corners that square off are the two on that end; received messages sit at
 * the inline start and square off there. Logical corners keep this correct in
 * Arabic without a second rule set.
 */
export function messengerBubbleCorners({ out, first, last }) {
  const classes = [];
  if (!last) classes.push(out ? "rounded-ee-[4px]" : "rounded-es-[4px]");
  if (!first) classes.push(out ? "rounded-se-[4px]" : "rounded-ss-[4px]");
  return classes.join(" ");
}

/** A sent bubble wears the chat theme's gradient; a received one is flat grey. */
export function messengerBubbleBackground(theme, out) {
  if (!out) return theme?.in || "#F0F0F0";
  const gradient = theme?.gradient;
  if (Array.isArray(gradient) && gradient.length >= 2) {
    return `linear-gradient(135deg, ${gradient[0]}, ${gradient[1]})`;
  }
  return theme?.accent || theme?.out || "#0084FF";
}

/**
 * Messenger draws no delivery ticks. A message the other side has opened is
 * shown by their avatar, so only "read" produces a mark.
 */
export function messengerSeen(status) {
  return String(status || "").toLowerCase() === "read";
}

/** Which message carries the reader's avatar: the newest sent one that was read. */
export function messengerSeenMessageId(messages) {
  const list = Array.isArray(messages) ? messages : [];
  for (let i = list.length - 1; i >= 0; i -= 1) {
    const message = list[i];
    if (sideOf(message) !== "out" || message.senderType === "system") continue;
    return messengerSeen(message.status) ? message.id : null;
  }
  return null;
}

/**
 * Messenger prints "Active now" while the person is writing to us. We only know
 * the last message they sent, so that is the only thing we claim; outside the
 * window we say nothing rather than guess.
 */
export function messengerPresence(lastCustomerMessageAt, now = Date.now(), windowMs = 5 * 60 * 1000) {
  const at = new Date(lastCustomerMessageAt || 0).getTime();
  if (!at) return null;
  return now - at <= windowMs ? "activeNow" : null;
}

// Messenger draws a lone emoji (a thumbs-up above all) large and with no bubble around it.
// Up to five emoji and nothing else; any letter, digit or longer run is an ordinary bubble.
const EMOJI_RUN = /^(?:\p{Extended_Pictographic}(?:\uFE0F|\u200D\p{Extended_Pictographic}|[\u{1F3FB}-\u{1F3FF}])*){1,5}$/u;

export function messengerIsBigEmoji(text) {
  const value = String(text ?? "").replace(/\s+/g, "");
  return value.length > 0 && EMOJI_RUN.test(value);
}

const QUOTE_KINDS = {
  image: ["صورة", "Photo"],
  photo: ["صورة", "Photo"],
  video: ["فيديو", "Video"],
  audio: ["رسالة صوتية", "Voice message"],
  voice: ["رسالة صوتية", "Voice message"],
  file: ["ملف", "File"],
  document: ["ملف", "File"],
  sticker: ["ملصق", "Sticker"],
};

/**
 * The line shown in the grey quote above a reply. It is the quoted message's own words; a media
 * message is named by its kind, and a message the provider no longer has shows an ellipsis
 * rather than text we do not have.
 */
export function messengerQuoteText(quote, lang = "ar") {
  if (!quote || typeof quote !== "object") return "";
  if (quote.available === false) return "…";
  const words = String(quote.body || quote.text || "").trim();
  if (words) return words;
  const kind = QUOTE_KINDS[String(quote.content_type || quote.contentType || "").toLowerCase()];
  if (kind) return lang === "ar" ? kind[0] : kind[1];
  return "…";
}

// Messenger prints a centred time only after a pause, never inside a bubble.
export const MESSENGER_TIME_GAP_MS = 15 * 60 * 1000;

/** True when a centred time stamp belongs above the message at `index`. */
export function messengerTimeDivider(messages, index, gapMs = MESSENGER_TIME_GAP_MS) {
  const list = Array.isArray(messages) ? messages : [];
  if (index <= 0) return true;
  const now = new Date(list[index]?.createdAt || 0).getTime();
  const before = new Date(list[index - 1]?.createdAt || 0).getTime();
  // A time we cannot read is never treated as "close": hiding a real gap is the worse error.
  if (!now || !before) return true;
  return now - before >= gapMs;
}
