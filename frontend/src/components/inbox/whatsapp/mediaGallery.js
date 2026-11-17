// Which messages a viewer can page through, and how it moves between them.
// Kept free of React so the rules can be tested without a DOM.

const IMAGE_URL = /\.(jpg|jpeg|png|webp|gif)(\?|$)/i;

/** A message the viewer can show: an image with a real, openable address. */
export function isViewableImage(m) {
  if (!m || m.deleted || !m.mediaUrl) return false;
  if (String(m.mediaUrl).startsWith("blob:")) return true; // a local preview still opens
  return m.mediaType === "image" || IMAGE_URL.test(m.mediaUrl);
}

/** The images of one conversation, oldest first, as the viewer's slides. */
export function galleryOf(messages) {
  return (messages || []).filter(isViewableImage).map((m) => ({
    id: m.id,
    url: m.mediaUrl,
    caption: m.text && !String(m.text).startsWith("blob:") && m.text !== m.mediaType ? m.text : "",
    time: m.time || "",
    side: m.side,
  }));
}

/** Position of a message in the gallery, or -1 when it is not one of its images. */
export function indexOfMessage(gallery, messageId) {
  return gallery.findIndex((g) => g.id === messageId);
}

/** Next position for an arrow key. Stops at the ends: it does not wrap round,
 *  so "next" on the last photo never silently jumps back to the first. */
export function step(index, delta, length) {
  if (!length) return -1;
  return Math.min(length - 1, Math.max(0, index + delta));
}
