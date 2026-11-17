import React, { useEffect, useRef } from "react";
import { CameraIcon, FileIcon } from "./icons";

const WORDS = {
  ar: { menu: "إرفاق", document: "مستند", media: "صور وفيديو", sticker: "ملصق", camera: "كاميرا" },
  en: { menu: "Attach", document: "Document", media: "Photos & videos", sticker: "Sticker", camera: "Camera" },
};

const DOCUMENT_ACCEPT = ".pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,application/pdf,text/plain";
const MEDIA_ACCEPT = "image/jpeg,image/png,image/webp,video/mp4,video/3gpp";

/**
 * The "+" menu: the kinds of file WhatsApp lets an agent send. Each entry opens
 * the browser's own file picker; the picked file goes to the preview, never
 * straight to the customer.
 */
export default function AttachMenu({ open, onClose, onPick, lang = "ar" }) {
  const w = WORDS[lang] || WORDS.en;
  const ref = useRef(null);
  const docRef = useRef(null);
  const mediaRef = useRef(null);
  const stickerRef = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => { if (e.key === "Escape") onClose?.(); };
    const onDown = (e) => { if (ref.current && !ref.current.contains(e.target)) onClose?.(); };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onDown);
    return () => { document.removeEventListener("keydown", onKey); document.removeEventListener("mousedown", onDown); };
  }, [open, onClose]);

  const choose = (asSticker) => (e) => {
    const file = e.target.files?.[0];
    e.target.value = ""; // picking the same file twice must still fire
    if (file) onPick?.(file, { asSticker });
    onClose?.();
  };

  const item = "flex w-full items-center gap-3 px-4 py-2.5 text-[15px] text-[color:var(--wa-text)] hover:bg-[var(--wa-bg-hover)] focus-visible:bg-[var(--wa-bg-hover)] focus-visible:outline-none";
  return (
    <>
      <input ref={docRef} type="file" accept={DOCUMENT_ACCEPT} className="hidden" data-testid="attach-input-document" onChange={choose(false)} />
      <input ref={mediaRef} type="file" accept={MEDIA_ACCEPT} className="hidden" data-testid="attach-input-media" onChange={choose(false)} />
      <input ref={stickerRef} type="file" accept="image/webp" className="hidden" data-testid="attach-input-sticker" onChange={choose(true)} />
      {open && (
        <div ref={ref} role="menu" aria-label={w.menu} data-testid="attach-menu" dir={lang === "ar" ? "rtl" : "ltr"}
          className="absolute bottom-full start-2 z-30 mb-2 w-60 overflow-hidden rounded-xl bg-[var(--wa-bg-panel)] py-2 shadow-[0_2px_12px_rgba(11,20,26,0.25)]">
          <button type="button" role="menuitem" className={item} data-testid="attach-document" onClick={() => docRef.current?.click()}>
            <span className="grid h-9 w-9 place-items-center rounded-full bg-[#7f66ff] text-white"><FileIcon size={20} /></span>{w.document}
          </button>
          <button type="button" role="menuitem" className={item} data-testid="attach-media" onClick={() => mediaRef.current?.click()}>
            <span className="grid h-9 w-9 place-items-center rounded-full bg-[#007bfc] text-white"><CameraIcon size={20} /></span>{w.media}
          </button>
          <button type="button" role="menuitem" className={item} data-testid="attach-sticker" onClick={() => stickerRef.current?.click()}>
            <span className="grid h-9 w-9 place-items-center rounded-full bg-[#02a698] text-lg text-white" aria-hidden="true">☺</span>{w.sticker}
          </button>
        </div>
      )}
    </>
  );
}
