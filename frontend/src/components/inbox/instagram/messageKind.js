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
  // The heart WE send is stored as a bare heart; Instagram draws it big with no bubble, like the one it receives.
  if (!url && (type === "text" || !type) && /^\s*(\u2764\ufe0f?|\u2665\ufe0f?)\s*$/u.test(m.text || "")) return "heart";
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
