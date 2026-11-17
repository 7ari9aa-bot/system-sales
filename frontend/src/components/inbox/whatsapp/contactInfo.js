// What the "Contact info" panel can say about a chat, derived from the real
// messages and the real customer row. Nothing here is invented: when a fact is
// not known the panel leaves it out instead of filling in a placeholder.

const URL_RE = /\bhttps?:\/\/[^\s<>"')\]]+/gi;
// Trailing punctuation belongs to the sentence, not to the link.
const TRAILING = /[.,;:!?،؛]+$/;

export function linksIn(text) {
  const found = String(text ?? "").match(URL_RE) || [];
  return found.map((u) => u.replace(TRAILING, "")).filter(Boolean);
}

export function hostOf(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

const isDeleted = (m) => Boolean(m?.deleted);

// Photos and videos, newest first, as in the "Media" tab.
export function mediaOf(messages) {
  return (messages || [])
    .filter((m) => !isDeleted(m) && m.mediaUrl && (m.contentType === "image" || m.contentType === "video" || m.mediaType === "image" || m.mediaType === "video"))
    .map((m) => ({ id: m.id, url: m.mediaUrl, kind: m.contentType === "video" || m.mediaType === "video" ? "video" : "image", at: m.createdAt }))
    .sort((a, b) => new Date(b.at) - new Date(a.at));
}

export function docsOf(messages) {
  return (messages || [])
    .filter((m) => !isDeleted(m) && m.contentType === "file" && m.mediaUrl)
    .map((m) => ({ id: m.id, url: m.mediaUrl, name: (m.text && !/^(document|file)$/i.test(m.text) ? m.text : "") || "", at: m.createdAt }))
    .sort((a, b) => new Date(b.at) - new Date(a.at));
}

export function sharedLinksOf(messages) {
  const out = [];
  const seen = new Set();
  for (const m of [...(messages || [])].sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt))) {
    if (isDeleted(m) || m.contentType === "reaction") continue;
    for (const url of linksIn(m.text)) {
      if (seen.has(url)) continue;
      seen.add(url);
      out.push({ id: `${m.id}:${url}`, url, host: hostOf(url), at: m.createdAt });
    }
  }
  return out;
}

export function countsOf(messages) {
  return { media: mediaOf(messages).length, docs: docsOf(messages).length, links: sharedLinksOf(messages).length };
}

// A phone number as people read it: "+20 100 123 4567" for an Egyptian mobile,
// the bare "+digits" otherwise. Never fabricates a number.
export function displayPhone(raw) {
  const digits = String(raw ?? "").replace(/[^\d+]/g, "");
  if (!digits) return "";
  const plus = digits.startsWith("+") ? digits : `+${digits}`;
  // Egyptian mobile: +20 1XX XXX XXXX
  const m = plus.match(/^\+20(1\d{2})(\d{3})(\d{4})$/);
  return m ? `+20 ${m[1]} ${m[2]} ${m[3]}` : plus;
}
