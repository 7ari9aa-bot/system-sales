/** The line under a contact's name in the inbox list.
 *
 * A media, reaction, button or deleted message carries no text body, and the
 * server's preview is then NULL — which used to render as an empty row that
 * reads like a broken list. Naming the kind of the last message is both honest
 * and what every messaging list does. */

const DELETED_KEY = "inbox.preview.deleted";
const FALLBACK_KEY = "inbox.preview.empty";

export function previewLine(row, t) {
  const text = typeof row?.last_message_preview === "string" ? row.last_message_preview.trim() : "";
  if (text) return text;
  if (row?.last_message_deleted) return t(DELETED_KEY);
  const type = row?.last_message_content_type;
  if (type && type !== "text") {
    const key = `inbox.preview.${type}`;
    const label = t(key);
    if (label && label !== key) return label;
  }
  return t(FALLBACK_KEY);
}
