// What an agent may attach to a WhatsApp chat, decided in the browser BEFORE the
// upload so a wrong file is refused at once instead of after a long upload. The
// numbers are WhatsApp Cloud API's own and mirror
// backend/app/modules/conversations/outbound_media.py, which re-checks the real
// bytes: this is a courtesy, the server is the authority.

const MB = 1024 * 1024;

export const MAX_BYTES = { image: 5 * MB, sticker: 100 * 1024, audio: 16 * MB, video: 16 * MB, document: 25 * MB };
export const CAPTION_MAX = 1024;
export const ABSOLUTE_MAX_BYTES = 25 * MB;

const KIND_BY_MIME = {
  "image/jpeg": "image", "image/png": "image", "image/webp": "image",
  "audio/aac": "audio", "audio/mp4": "audio", "audio/mpeg": "audio", "audio/amr": "audio", "audio/ogg": "audio",
  "video/mp4": "video", "video/3gpp": "video",
  "application/pdf": "document", "text/plain": "document", "application/msword": "document",
  "application/vnd.ms-excel": "document", "application/vnd.ms-powerpoint": "document",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "document",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "document",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation": "document",
};

// A browser sometimes leaves a file's type empty (Windows with .docx). The
// extension is the fallback, never the first choice.
const MIME_BY_EXT = {
  jpg: "image/jpeg", jpeg: "image/jpeg", png: "image/png", webp: "image/webp",
  mp4: "video/mp4", "3gp": "video/3gpp", aac: "audio/aac", m4a: "audio/mp4", mp3: "audio/mpeg",
  amr: "audio/amr", ogg: "audio/ogg", opus: "audio/ogg", pdf: "application/pdf", txt: "text/plain",
  doc: "application/msword", xls: "application/vnd.ms-excel", ppt: "application/vnd.ms-powerpoint",
  docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  pptx: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
};

export function mimeOf(file) {
  const declared = String(file?.type || "").split(";")[0].trim().toLowerCase();
  const normal = declared === "image/jpg" ? "image/jpeg" : declared;
  if (KIND_BY_MIME[normal]) return normal;
  const ext = String(file?.name || "").split(".").pop().toLowerCase();
  return MIME_BY_EXT[ext] || normal;
}

export function kindOf(file, { asSticker = false } = {}) {
  const mime = mimeOf(file);
  if (asSticker && mime === "image/webp") return "sticker";
  return KIND_BY_MIME[mime] || null;
}

const WORDS = {
  ar: {
    type: "هذا النوع من الملفات لا يمكن إرساله على واتساب.",
    empty: "الملف فارغ.",
    big: (kind, limit) => `الحد الأقصى لـ${{ image: "الصورة", sticker: "الملصق", audio: "الصوت", video: "الفيديو", document: "المستند" }[kind]} على واتساب ${limit}.`,
    sticker: "الملصق يجب أن يكون صورة WebP.",
  },
  en: {
    type: "This type of file cannot be sent on WhatsApp.",
    empty: "The file is empty.",
    big: (kind, limit) => `A ${kind} can be at most ${limit} on WhatsApp.`,
    sticker: "A sticker must be a WebP image.",
  },
};

export function limitLabel(bytes, lang = "en") {
  const kb = bytes / 1024;
  if (bytes < MB) return lang === "ar" ? `${Math.round(kb)} كيلوبايت` : `${Math.round(kb)} KB`;
  return lang === "ar" ? `${Math.round(bytes / MB)} ميجابايت` : `${Math.round(bytes / MB)} MB`;
}

/** @returns {{ok: true, kind: string, mime: string} | {ok: false, error: string}} */
export function checkFile(file, { lang = "en", asSticker = false } = {}) {
  const w = WORDS[lang] || WORDS.en;
  const mime = mimeOf(file);
  const kind = kindOf(file, { asSticker });
  if (asSticker && mime !== "image/webp") return { ok: false, error: w.sticker };
  if (!kind) return { ok: false, error: w.type };
  if (!file.size) return { ok: false, error: w.empty };
  if (file.size > MAX_BYTES[kind]) return { ok: false, error: w.big(kind, limitLabel(MAX_BYTES[kind], lang)) };
  return { ok: true, kind, mime };
}

/** Audio and stickers cannot carry a caption on WhatsApp. */
export function canCaption(kind) {
  return kind === "image" || kind === "video" || kind === "document";
}

export function fileSizeLabel(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < MB) return `${Math.round(bytes / 1024)} KB`;
  const mb = bytes / MB;
  return `${mb < 10 ? mb.toFixed(1) : Math.round(mb)} MB`;
}

/** The kind of recording a browser can make, in the order WhatsApp accepts them. */
export function pickRecordingType(isTypeSupported) {
  // WhatsApp plays ogg/opus voice notes and mp4/aac; webm is not accepted.
  for (const t of ["audio/ogg;codecs=opus", "audio/mp4", "audio/ogg"]) {
    if (isTypeSupported?.(t)) return t;
  }
  return null;
}

export function formatDuration(totalSeconds) {
  const s = Math.max(0, Math.floor(totalSeconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
