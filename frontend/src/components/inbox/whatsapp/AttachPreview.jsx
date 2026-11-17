import React, { useEffect, useMemo, useRef, useState } from "react";
import { AlertIcon, CloseIcon, FileIcon, SendIcon } from "./icons";
import { CAPTION_MAX, canCaption, fileSizeLabel } from "./attachments";

const WORDS = {
  ar: { title: "معاينة", caption: "أضف تعليقًا", send: "إرسال", cancel: "إلغاء", uploading: "جارٍ الرفع", retry: "إعادة المحاولة", noCaption: "لا يمكن إضافة تعليق على هذا النوع", sticker: "ملصق", audio: "رسالة صوتية", over: "تجاوزت الحد" },
  en: { title: "Preview", caption: "Add a caption", send: "Send", cancel: "Cancel", uploading: "Uploading", retry: "Try again", noCaption: "This type cannot have a caption", sticker: "Sticker", audio: "Voice message", over: "Over the limit" },
};

/**
 * What the agent is about to send, shown before anything reaches the customer:
 * the picture or video itself, or the document's name and size, with a caption
 * where WhatsApp allows one. The file is uploaded only when Send is pressed, so
 * cancelling costs nothing and a file is never stored that was not sent.
 */
export default function AttachPreview({ file, kind, onSend, onCancel, busy = false, error = "", lang = "ar", audioUrl = null }) {
  const w = WORDS[lang] || WORDS.en;
  const [caption, setCaption] = useState("");
  const ref = useRef(null);
  const url = useMemo(() => audioUrl || (file && (kind === "image" || kind === "sticker" || kind === "video") ? URL.createObjectURL(file) : null), [file, kind, audioUrl]);
  useEffect(() => () => { if (url && !audioUrl) URL.revokeObjectURL(url); }, [url, audioUrl]);
  useEffect(() => { ref.current?.focus(); }, []);

  const allowed = canCaption(kind);
  const tooLong = caption.length > CAPTION_MAX;
  const submit = () => { if (!busy && !tooLong) onSend?.(allowed ? caption.trim() : ""); };

  return (
    <div role="dialog" aria-modal="true" aria-label={w.title} data-testid="attach-preview" dir={lang === "ar" ? "rtl" : "ltr"}
      className="absolute inset-0 z-40 flex flex-col bg-[#f0f2f5]"
      onKeyDown={(e) => { if (e.key === "Escape" && !busy) onCancel?.(); }}>
      <div className="flex items-center gap-3 bg-[#008069] px-3 py-3 text-white">
        <button type="button" onClick={onCancel} disabled={busy} aria-label={w.cancel} data-testid="attach-cancel"
          className="grid h-9 w-9 place-items-center rounded-full hover:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white disabled:opacity-50"><CloseIcon size={22} /></button>
        <div className="min-w-0 flex-1 truncate text-[16px]" dir="auto">{file?.name || w.audio}</div>
      </div>

      <div className="grid min-h-0 flex-1 place-items-center overflow-auto p-4">
        {kind === "image" && url && <img src={url} alt={file?.name || ""} data-testid="preview-image" className="max-h-full max-w-full rounded-lg object-contain shadow" />}
        {kind === "sticker" && url && <img src={url} alt={w.sticker} data-testid="preview-sticker" className="h-40 w-40 object-contain" />}
        {kind === "video" && url && <video src={url} controls data-testid="preview-video" className="max-h-full max-w-full rounded-lg shadow" />}
        {kind === "audio" && url && <audio src={url} controls data-testid="preview-audio" className="w-full max-w-sm" />}
        {kind === "document" && (
          <div data-testid="preview-document" className="flex w-72 flex-col items-center gap-3 rounded-xl bg-white p-8 text-center shadow">
            <FileIcon size={64} className="text-[#7f66ff]" />
            <div dir="auto" className="w-full break-words text-[15px] text-[#111b21]">{file?.name}</div>
            <div className="text-[13px] text-[#667781]">{fileSizeLabel(file?.size || 0)}</div>
          </div>
        )}
      </div>

      {error && (
        <div role="alert" data-testid="attach-error" className="mx-3 mb-2 flex items-start gap-2 rounded-lg bg-[#fde8ec] px-3 py-2 text-[13px] text-[#7a1230]">
          <AlertIcon size={16} className="mt-0.5 shrink-0" /><span className="flex-1">{error}</span>
        </div>
      )}

      <div dir="ltr" className="flex items-end gap-2 px-3 pb-3">
        <div className="min-w-0 flex-1">
          <input ref={ref} dir="auto" value={caption} onChange={(e) => setCaption(e.target.value)} disabled={!allowed || busy}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); submit(); } }}
            placeholder={allowed ? w.caption : w.noCaption} aria-label={w.caption} data-testid="attach-caption" aria-invalid={tooLong || undefined}
            className="block w-full rounded-lg border-0 bg-white px-3 py-[11px] text-[15px] text-[#111b21] placeholder:text-[#667781] focus:outline-none disabled:bg-[#e9edef]" />
          {tooLong && <div data-testid="attach-caption-over" className="px-1 pt-0.5 text-end text-[12px] text-[#ea0038]">{w.over} ({caption.length}/{CAPTION_MAX})</div>}
        </div>
        <button type="button" onClick={submit} disabled={busy || tooLong} aria-label={busy ? w.uploading : error ? w.retry : w.send} title={busy ? w.uploading : w.send} data-testid="attach-send"
          className="grid h-12 w-12 shrink-0 place-items-center rounded-full bg-[#00a884] text-white shadow focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#00a884] focus-visible:ring-offset-2 disabled:opacity-60">
          {busy ? <span className="h-5 w-5 animate-spin rounded-full border-2 border-white border-t-transparent" aria-hidden="true" /> : <SendIcon size={24} className={lang === "ar" ? "-scale-x-100" : undefined} />}
        </button>
      </div>
    </div>
  );
}
