// What an agent may attach to an Instagram chat, decided in the browser BEFORE the upload so a
// wrong file is refused at once. These are Instagram's own formats and sizes and mirror
// backend/app/modules/conversations/gateway/instagram_limits.py (MEDIA_RULES / check_upload),
// which re-checks the real bytes: this is a courtesy, the server is the authority.
// They are NOT WhatsApp's: no WebP, no Ogg/MP3 audio, no Word/Excel, and an image is 8 MB.

const MB = 1024 * 1024;

export const MAX_BYTES = { image: 8 * MB, audio: 25 * MB, video: 25 * MB, document: 25 * MB };

const KIND_BY_MIME = {
  "image/jpeg": "image", "image/png": "image",
  "audio/aac": "audio", "audio/mp4": "audio", "audio/wav": "audio", "audio/x-wav": "audio",
  "video/mp4": "video", "video/ogg": "video", "video/x-msvideo": "video", "video/quicktime": "video", "video/webm": "video",
  "application/pdf": "document",
};

// A browser sometimes leaves a file's type empty. The extension is the fallback, never the first choice.
const MIME_BY_EXT = {
  jpg: "image/jpeg", jpeg: "image/jpeg", png: "image/png",
  aac: "audio/aac", m4a: "audio/mp4", wav: "audio/wav",
  mp4: "video/mp4", ogg: "video/ogg", avi: "video/x-msvideo", mov: "video/quicktime", webm: "video/webm",
  pdf: "application/pdf",
};

/** The `accept` list for the file picker: exactly what Instagram takes. */
export const ACCEPT = ".jpg,.jpeg,.png,.aac,.m4a,.wav,.mp4,.ogg,.avi,.mov,.webm,.pdf";

export function mimeOf(file) {
  const declared = String(file?.type || "").split(";")[0].trim().toLowerCase();
  const normal = declared === "image/jpg" ? "image/jpeg" : declared;
  if (KIND_BY_MIME[normal]) return normal;
  const ext = String(file?.name || "").split(".").pop().toLowerCase();
  return MIME_BY_EXT[ext] || normal;
}

const LABEL = {
  ar: { image: "الصورة", audio: "الصوت", video: "الفيديو", document: "الملف" },
  en: { image: "image", audio: "audio file", video: "video", document: "file" },
};

/** @returns {{ok: true, kind: string, mime: string} | {ok: false, error: string}} */
export function checkFile(file, { lang = "en" } = {}) {
  const ar = lang === "ar";
  const mime = mimeOf(file);
  const kind = KIND_BY_MIME[mime];
  if (!kind) {
    return { ok: false, error: ar
      ? "إنستغرام يقبل فقط صور JPG وPNG وفيديو MP4 وMOV وWebM وصوت AAC وM4A وWAV وملفات PDF."
      : "Instagram accepts only JPG and PNG images, MP4, MOV and WebM video, AAC, M4A and WAV audio, and PDF files." };
  }
  if (!file.size) return { ok: false, error: ar ? "الملف فارغ." : "The file is empty." };
  if (file.size > MAX_BYTES[kind]) {
    const mb = MAX_BYTES[kind] / MB;
    return { ok: false, error: ar
      ? `الحد الأقصى لحجم ${LABEL.ar[kind]} على إنستغرام ${mb} ميجابايت.`
      : `A ${LABEL.en[kind]} can be at most ${mb} MB on Instagram.` };
  }
  return { ok: true, kind, mime };
}
