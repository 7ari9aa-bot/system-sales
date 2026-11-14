/** Attaching a small text file to a question.
 *
 *  The assistant reads the shop's own data and takes plain text only (the send limit is 4000
 *  characters), so a "file" here is read INSIDE the browser and its text joins the question box.
 *  Nothing is uploaded; the owner sees exactly what will be sent and can edit it first.
 *  Only small plain-text kinds are taken: anything else would be a button that pretends. */

export const ATTACH_EXTENSIONS = ["txt", "csv", "md", "json"];
export const ATTACH_MAX_BYTES = 12_000;
export const ATTACH_MAX_CHARS = 3_000;
const SEND_LIMIT = 4_000;

const INVISIBLE = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]/g;

export function checkAttachment(file) {
  if (!file || typeof file.name !== "string") return { ok: false, reason: "type" };
  const ext = file.name.includes(".") ? file.name.split(".").pop().toLowerCase() : "";
  if (!ATTACH_EXTENSIONS.includes(ext)) return { ok: false, reason: "type" };
  if (!file.size) return { ok: false, reason: "empty" };
  if (file.size > ATTACH_MAX_BYTES) return { ok: false, reason: "size" };
  return { ok: true };
}

/** The box text with the file joined under it, or why it can't be. */
export function mergeAttachment(current, name, raw) {
  const body = String(raw ?? "").replace(/\r\n?/g, "\n").replace(INVISIBLE, "").trim();
  if (!body) return { ok: false, reason: "empty" };
  if (body.length > ATTACH_MAX_CHARS) return { ok: false, reason: "long" };
  const label = String(name ?? "").replace(/[\r\n\u2028\u2029]+/g, " ").replace(INVISIBLE, "").slice(0, 60).trim() || "file";
  const head = (current ?? "").trimEnd();
  const text = `${head ? `${head}\n\n` : ""}[${label}]\n${body}`;
  if (text.length > SEND_LIMIT) return { ok: false, reason: "long" };
  return { ok: true, text };
}
