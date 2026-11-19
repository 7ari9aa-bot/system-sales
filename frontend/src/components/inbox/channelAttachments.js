// What an agent may attach to a Messenger or a Telegram chat, decided in the browser BEFORE the
// upload so a wrong file is refused at once. Messenger's and Telegram's own formats and sizes, not
// WhatsApp's; they mirror backend/app/modules/conversations/gateway/messenger_media.py and
// telegram_media.py, which re-check the real bytes: this is a courtesy, the server is the authority.

const MB = 1024 * 1024;

// Messenger: an image is at most 8 MB, everything else 25 MB, and any file type is carried as a
// plain file. Telegram (a file sent by link): a photo is at most 5 MB, everything else 20 MB, and a
// document must be a PDF or a ZIP.
export const MAX_BYTES = {
  messenger: { image: 8 * MB, audio: 25 * MB, video: 25 * MB, document: 25 * MB },
  telegram: { image: 5 * MB, audio: 20 * MB, video: 20 * MB, document: 20 * MB },
};

const KIND_BY_MIME = {
  "image/jpeg": "image", "image/png": "image", "image/gif": "image", "image/webp": "image",
  "audio/mpeg": "audio", "audio/mp4": "audio", "audio/aac": "audio", "audio/wav": "audio", "audio/x-wav": "audio",
  "video/mp4": "video", "video/quicktime": "video", "video/webm": "video",
  "application/pdf": "document", "application/zip": "document",
};

// Only these are delivered by Telegram from a link.
const TELEGRAM_MIMES = new Set([
  "image/jpeg", "image/png", "image/gif", "image/webp", "video/mp4", "audio/mpeg", "audio/mp4", "application/pdf", "application/zip",
]);

// A page or a program is not a file to hand a customer.
const NEVER = new Set(["text/html", "image/svg+xml", "application/x-msdownload", "application/x-sh", "application/javascript", "text/javascript"]);

const MIME_BY_EXT = {
  jpg: "image/jpeg", jpeg: "image/jpeg", png: "image/png", gif: "image/gif", webp: "image/webp",
  mp3: "audio/mpeg", m4a: "audio/mp4", aac: "audio/aac", wav: "audio/wav",
  mp4: "video/mp4", mov: "video/quicktime", webm: "video/webm",
  pdf: "application/pdf", zip: "application/zip",
};

/** The `accept` list for the file picker. Messenger takes any file; Telegram only what it delivers. */
export const ACCEPT = {
  messenger: "",
  telegram: ".jpg,.jpeg,.png,.gif,.webp,.mp4,.mp3,.m4a,.pdf,.zip",
};

export function mimeOf(file) {
  const declared = String(file?.type || "").split(";")[0].trim().toLowerCase();
  const normal = declared === "image/jpg" ? "image/jpeg" : declared;
  if (normal && normal !== "application/octet-stream") return normal;
  const ext = String(file?.name || "").split(".").pop().toLowerCase();
  return MIME_BY_EXT[ext] || normal;
}

const LABEL = {
  ar: { image: "الصورة", audio: "الصوت", video: "الفيديو", document: "الملف" },
  en: { image: "image", audio: "audio file", video: "video", document: "file" },
};
const NAME = { messenger: { ar: "ماسنجر", en: "Messenger" }, telegram: { ar: "تيليجرام", en: "Telegram" } };

/** @returns {{ok: true, kind: string, mime: string} | {ok: false, error: string}} */
export function checkFile(file, { channel, lang = "en" } = {}) {
  const ar = lang === "ar";
  const limits = MAX_BYTES[channel];
  if (!limits) return { ok: false, error: ar ? "هذه القناة لا تدعم إرسال الملفات." : "This channel cannot send files." };
  const mime = mimeOf(file);
  if (!mime || NEVER.has(mime)) {
    return { ok: false, error: ar ? "لا يمكن إرسال هذا النوع من الملفات." : "This type of file cannot be sent." };
  }
  if (channel === "telegram" && !TELEGRAM_MIMES.has(mime)) {
    return { ok: false, error: ar
      ? "تيليجرام يستلم فقط صور JPG وPNG وGIF وWebP وفيديو MP4 وصوت MP3 وM4A وملفات PDF وZIP."
      : "Telegram accepts only JPG, PNG, GIF and WebP images, MP4 video, MP3 and M4A audio, and PDF and ZIP files." };
  }
  // On Messenger any other type travels as a plain file.
  const kind = KIND_BY_MIME[mime] || "document";
  if (!file.size) return { ok: false, error: ar ? "الملف فارغ." : "The file is empty." };
  if (file.size > limits[kind]) {
    const mb = limits[kind] / MB;
    return { ok: false, error: ar
      ? `الحد الأقصى لحجم ${LABEL.ar[kind]} على ${NAME[channel].ar} ${mb} ميجابايت.`
      : `A ${LABEL.en[kind]} can be at most ${mb} MB on ${NAME[channel].en}.` };
  }
  return { ok: true, kind, mime };
}
