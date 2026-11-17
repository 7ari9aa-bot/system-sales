// Decides what a WhatsApp message IS, so each kind can look like it does in
// WhatsApp. Inbound messages are normalised by the gateway (§155) into
// `content_type` plus a plain-text `body`; this reads that and nothing more. It
// never invents data the server did not send (no coordinates, no map).

const IMAGE_EXT = /\.(jpe?g|png|webp|gif|bmp)(\?|#|$)/i;
const VIDEO_EXT = /\.(mp4|mov|webm|3gp|mkv)(\?|#|$)/i;
const AUDIO_EXT = /\.(ogg|opus|mp3|m4a|aac|wav|amr)(\?|#|$)/i;
const DOC_EXT = /\.(pdf|docx?|xlsx?|pptx?|txt|csv|zip|rar)(\?|#|$)/i;

/** @returns {"text"|"image"|"video"|"voice"|"document"|"sticker"|"location"|"contact"|"buttons"|"list"|"unsupported"} */
export function messageKind(m) {
  const type = m?.contentType;
  const media = m?.mediaType;
  const url = m?.mediaUrl || "";
  if (type === "location") return "location";
  if (type === "contact") return "contact";
  if (type === "buttons") return "buttons";
  if (type === "list") return "list";
  if (type === "unsupported") return "unsupported";
  if (media === "sticker") return "sticker";
  if (type === "voice" || media === "audio" || (url && AUDIO_EXT.test(url))) return "voice";
  if (type === "video" || media === "video" || (url && VIDEO_EXT.test(url))) return "video";
  if (type === "file" || media === "document" || (url && DOC_EXT.test(url))) return "document";
  if (type === "image" || media === "image" || (url && IMAGE_EXT.test(url))) return "image";
  return "text";
}

/** "📍 Cairo Tower, Gezira" -> { title, address }. The emoji is decoration the gateway adds. */
export function parseLocation(body) {
  const text = String(body || "").replace(/^\s*📍\s*/, "").trim();
  if (!text) return { title: "", address: "" };
  const [first, ...rest] = text.split(/\s{2,}|\n|,\s*/);
  return { title: first.trim(), address: rest.join(", ").trim() };
}

/** "Ali Hassan +201001234567" -> { name, phone }. A trailing phone-looking token is the number. */
export function parseContact(body) {
  const text = String(body || "").trim();
  if (!text || text === "[contacts]") return { name: "", phone: "" };
  const match = text.match(/^(.*?)\s*(\+?[\d][\d\s\-()]{5,})$/);
  if (!match) return { name: text, phone: "" };
  return { name: match[1].trim(), phone: match[2].trim() };
}

/** A document's file name from its URL, decoded, without the query string. */
export function fileNameOf(url, fallback = "") {
  if (!url) return fallback;
  try {
    const last = new URL(url, "http://x").pathname.split("/").filter(Boolean).pop() || "";
    const name = decodeURIComponent(last);
    return name || fallback;
  } catch {
    return fallback;
  }
}

/** "pdf", "docx"... uppercased for the badge, or "" when unknown. */
export function fileExtension(name) {
  const m = String(name || "").match(/\.([a-z0-9]{1,5})$/i);
  return m ? m[1].toUpperCase() : "";
}

/**
 * The text of a message that must not show raw. The gateway stores the raw JSON
 * of a provider type it does not know as `body` (for forensics): showing it in a
 * chat bubble would dump technical data on the agent. Text kinds pass through.
 */
export function displayBody(m) {
  const kind = messageKind(m);
  if (kind === "unsupported") return "";
  return String(m?.text ?? "");
}

/** True when `text` is just a file name ("Invoice.pdf"): one token ending in an extension. */
export function looksLikeFileName(text) {
  const t = String(text || "").trim();
  return t.length > 0 && !/\s/.test(t) && /\.[a-z0-9]{1,5}$/i.test(t);
}
