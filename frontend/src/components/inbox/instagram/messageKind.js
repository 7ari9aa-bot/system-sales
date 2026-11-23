// What an Instagram message is, decided from what the server stored. Kept apart from the
// component so it is cheap to test and the bubble stays a thin layer over it.
const IMAGE_EXT = /\.(jpe?g|png|gif|webp|heic)(\?|$)/i;
const VIDEO_EXT = /\.(mp4|mov|webm|m4v)(\?|$)/i;
const AUDIO_EXT = /\.(mp3|m4a|aac|ogg|oga|opus|wav)(\?|$)/i;

export function instagramKind(m) {
  if (!m) return "text";
  if (m.deleted || m.contentType === "deleted") return "deleted";
  if (m.card?.type === "story_mention") return "story_mention";
  if (m.card?.type === "story_reply") return "story_reply";
  if (m.card?.type === "share") return "share";
  if (m.contentType === "unsupported") return "unsupported";
  const type = m.contentType;
  const media = m.mediaType;
  const url = m.mediaUrl || "";
  // The heart Instagram sends for a "like" arrives as a sticker whose text is the heart itself.
  if (type === "sticker" && !url) return "heart";
  if (type === "sticker") return "sticker";
  if (type === "voice" || media === "audio" || (url && AUDIO_EXT.test(url))) return "voice";
  if (type === "video" || media === "video" || (url && VIDEO_EXT.test(url))) return "video";
  if (type === "file" || media === "file" || media === "document") return "file";
  if (type === "image" || media === "image" || (url && IMAGE_EXT.test(url))) return "image";
  return "text";
}

/** Only an https link is ever opened from a card. */
export function safeHttps(url) {
  return typeof url === "string" && /^https:\/\//i.test(url) ? url : "";
}

// What the reply bar prints for the message being quoted: Instagram shows an icon for media
// and the text for anything written, never the whole body.
const QUOTE_LABEL = {
  image: { ar: "صورة", en: "Photo" },
  video: { ar: "فيديو", en: "Video" },
  voice: { ar: "رسالة صوتية", en: "Voice message" },
  file: { ar: "ملف", en: "File" },
  heart: { ar: "قلب", en: "Heart" },
  sticker: { ar: "ملصق", en: "Sticker" },
  share: { ar: "منشور", en: "Post" },
  story_reply: { ar: "رد على ستوري", en: "Story reply" },
  story_mention: { ar: "إشارة في ستوري", en: "Story mention" },
  deleted: { ar: "رسالة محذوفة", en: "Deleted message" },
  unsupported: { ar: "مرفق غير مدعوم", en: "Unsupported attachment" },
};

export function instagramQuoteText(m, lang = "ar") {
  const kind = instagramKind(m);
  const label = QUOTE_LABEL[kind];
  const text = String(m?.text || "").trim();
  if (label) return `${label[lang === "ar" ? "ar" : "en"]}${text && kind !== "heart" && kind !== "deleted" ? ` · ${text}` : ""}`;
  return text || (lang === "ar" ? "رسالة" : "Message");
}
