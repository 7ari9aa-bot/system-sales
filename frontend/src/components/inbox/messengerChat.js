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

/**
 * The small line Messenger prints above a quoted message: who replied to whom. `side` is the
 * side of the message that carries the reply, and the quote knows whether the message being
 * quoted came from the Page or from the customer.
 */
export function messengerReplyLabel(quote, side, customerName, lang = "ar") {
  if (!quote || typeof quote !== "object") return "";
  const ar = lang === "ar";
  const who = String(customerName || "").trim() || (ar ? "العميل" : "the customer");
  if (side === "out") return ar ? `ردّيت على ${who}` : `You replied to ${who}`;
  return ar ? `${who} ردّ على رسالتك` : `${who} replied to you`;
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

const URL_IN_TEXT = /https?:\/\/[^\s<>"')]+/giu;

/**
 * What the "Media, files and links" section of the details panel lists: only what the thread
 * really contains. Photos and videos are media; any other attachment is a file; a link is a
 * web address a message's text carries.
 */
export function messengerSharedItems(messages) {
  const out = { media: [], files: [], links: [] };
  for (const m of Array.isArray(messages) ? messages : []) {
    const kind = String(m?.contentType || m?.mediaType || "").toLowerCase();
    if (m?.mediaUrl) {
      if (kind.startsWith("image") || kind === "photo" || kind.startsWith("video")) out.media.push(m);
      else out.files.push(m);
    }
    for (const url of String(m?.text || "").match(URL_IN_TEXT) || []) out.links.push({ id: m.id, url });
  }
  return out;
}

// The marker the backend stores for a reaction that was taken back.
const REACTION_WITHDRAWN = "\u200b-";

/**
 * The small badge under a bubble: each emoji once, plus the total number of reactions. A
 * withdrawn reaction counts for nothing, so taking one back removes the badge.
 */
export function messengerReactionSummary(reactions) {
  const live = (Array.isArray(reactions) ? reactions : []).filter((r) => typeof r === "string" && r.trim() && r !== REACTION_WITHDRAWN);
  if (!live.length) return null;
  return { emojis: [...new Set(live)], count: live.length };
}

const STATUS_WORDS = {
  sent: { ar: "تم الإرسال", en: "Sent" },
  delivered: { ar: "تم التسليم", en: "Delivered" },
  read: { ar: "تمت المشاهدة", en: "Seen" },
};

function ago(ms, lang) {
  const minutes = Math.floor(ms / 60000);
  if (minutes < 1) return lang === "ar" ? "الآن" : "just now";
  if (minutes < 60) return lang === "ar" ? `منذ ${minutes} د` : `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return lang === "ar" ? `منذ ${hours} س` : `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return lang === "ar" ? `منذ ${days} يوم` : `${days}d ago`;
}

/**
 * The grey line Messenger prints under the newest message we sent: "Sent / Delivered / Seen" and
 * how long ago. Only a state the platform really recorded is named. Once the customer has written
 * after our message the line is gone, as in Messenger, and a failed or pending message has none.
 */
export function messengerStatusLine(messages, lang = "ar", now = Date.now()) {
  const list = Array.isArray(messages) ? messages : [];
  const last = list[list.length - 1];
  if (!last || sideOf(last) !== "out" || last.senderType === "system") return null;
  const words = STATUS_WORDS[String(last.status || "").toLowerCase()];
  if (!words) return null;
  const at = new Date(last.createdAt || 0).getTime();
  if (!at) return null;
  const when = ago(Math.max(0, now - at), lang);
  return lang === "ar" ? `${words.ar} ${when}` : `${words.en} ${when}`;
}

/** The grey line under a name in the Messenger list: "You: …" when the newest message is ours. */
export function messengerRowPreview(conversation, lang = "ar") {
  const text = String(conversation?.preview || "").trim();
  if (!text) return "";
  return conversation?.lastDirection === "outbound" ? `${lang === "ar" ? "أنت" : "You"}: ${text}` : text;
}

/**
 * How one message is drawn in Messenger. A photo, video or sticker stands on the page with no
 * bubble; a file is a card; a removed message is a grey line; a system line is centred grey text.
 * Anything whose address has not arrived yet stays a plain bubble, so nothing is drawn from air.
 */
export function messengerMessageShape(m) {
  if (m?.senderType === "system") return "system";
  if (m?.deleted) return "deleted";
  const text = String(m?.text || "");
  const url = m?.mediaUrl || "";
  if (m?.mediaType === "audio" || text.startsWith("🎤")) return "audio";
  if (url) {
    if (m.mediaType === "sticker") return "sticker";
    if (m.mediaType === "video" || /^video(\/|$)/i.test(String(m.contentType || "")) || /\.(mp4|mov|webm|3gp)(\?|#|$)/i.test(url)) return "video";
    if (m.mediaType === "image" || /^image(\/|$)/i.test(String(m.contentType || "")) || /\.(jpe?g|png|webp|gif|bmp)(\?|#|$)/i.test(url)) return "photo";
    return "file";
  }
  return messengerIsBigEmoji(text) ? "bigEmoji" : "text";
}

const LINK_SPLIT = /(https?:\/\/[^\s<>"')]+)/giu;

/**
 * A Messenger bubble keeps its words and turns each web address into a link. Splitting the text
 * here keeps the rendering honest: only an address the sender really wrote becomes a link.
 */
export function messengerLinkParts(text) {
  const value = String(text || "");
  if (!value) return [];
  return value
    .split(LINK_SPLIT)
    .filter((part) => part !== "")
    .map((part) => (/^https?:\/\//i.test(part) ? { type: "link", value: part } : { type: "text", value: part }));
}

/** The site an address points at, as Messenger labels a preview: the host without "www.". */
export function messengerLinkHost(url) {
  try {
    const parsed = new URL(String(url));
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return "";
    return parsed.hostname.replace(/^www\./i, "");
  } catch {
    return "";
  }
}
