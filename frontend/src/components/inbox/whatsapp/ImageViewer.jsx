import React, { useCallback, useEffect, useRef, useState } from "react";
import { BackIcon, CloseIcon, DownloadIcon } from "./icons";
import { indexOfMessage, step } from "./mediaGallery";
import { WHATSAPP_FONT } from "./WhatsAppBubble";

const WORDS = {
  ar: { close: "إغلاق", download: "تنزيل", prev: "الصورة السابقة", next: "الصورة التالية", viewer: "عارض الصور", of: "من", sent: "أنت", received: "العميل", image: "صورة" },
  en: { close: "Close", download: "Download", prev: "Previous photo", next: "Next photo", viewer: "Photo viewer", of: "of", sent: "You", received: "Customer", image: "Photo" },
};

/**
 * Full-screen photo viewer. `gallery` is the conversation's images (see
 * mediaGallery.js); `startId` is the one that was opened. Closing returns focus
 * to whatever opened it, and the page behind does not scroll while it is open.
 */
export default function ImageViewer({ gallery, startId, lang = "ar", onClose }) {
  const w = WORDS[lang] || WORDS.en;
  const [index, setIndex] = useState(() => Math.max(0, indexOfMessage(gallery, startId)));
  const [failed, setFailed] = useState(false);
  const rootRef = useRef(null);
  const opener = useRef(typeof document !== "undefined" ? document.activeElement : null);
  const slide = gallery[index];
  // Arrow keys follow the reading direction: in Arabic "next" is to the left.
  const rtl = lang === "ar";

  const go = useCallback((delta) => { setFailed(false); setIndex((i) => step(i, delta, gallery.length)); }, [gallery.length]);

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    rootRef.current?.focus();
    const back = opener.current;
    return () => { document.body.style.overflow = previousOverflow; back?.focus?.(); };
  }, []);

  useEffect(() => {
    function onKey(e) {
      if (e.key === "Escape") { e.stopPropagation(); onClose?.(); }
      else if (e.key === "ArrowRight") go(rtl ? -1 : 1);
      else if (e.key === "ArrowLeft") go(rtl ? 1 : -1);
      else if (e.key === "Tab") {
        // Keep focus inside the viewer.
        const items = [...(rootRef.current?.querySelectorAll("button:not([disabled]), a[href]") || [])];
        if (!items.length) return;
        const first = items[0];
        const last = items[items.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [go, onClose, rtl]);

  if (!slide) return null;
  const atStart = index === 0;
  const atEnd = index === gallery.length - 1;
  const who = slide.side === "out" ? w.sent : w.received;

  return (
    <div
      ref={rootRef}
      role="dialog"
      aria-modal="true"
      aria-label={w.viewer}
      tabIndex={-1}
      data-testid="image-viewer"
      dir={rtl ? "rtl" : "ltr"}
      className="fixed inset-0 z-[100] flex flex-col bg-[#0b141a]/95 text-white outline-none"
      style={{ fontFamily: WHATSAPP_FONT }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose?.(); }}
    >
      <div className="flex items-center gap-3 px-4 py-3">
        <button type="button" onClick={onClose} aria-label={w.close} title={w.close} data-testid="viewer-close" className="grid h-10 w-10 place-items-center rounded-full hover:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white">
          <CloseIcon size={22} />
        </button>
        <div className="min-w-0 flex-1">
          <div className="truncate text-[15px] font-medium">{who}</div>
          <div className="text-[12.5px] text-white/70">
            {slide.time}{gallery.length > 1 && ` · ${index + 1} ${w.of} ${gallery.length}`}
          </div>
        </div>
        <a
          href={slide.url}
          download
          target="_blank"
          rel="noopener noreferrer"
          aria-label={w.download}
          title={w.download}
          data-testid="viewer-download"
          className="grid h-10 w-10 place-items-center rounded-full hover:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white"
        >
          <DownloadIcon size={22} />
        </a>
      </div>

      <div className="relative flex min-h-0 flex-1 items-center justify-center px-14" onClick={(e) => { if (e.target === e.currentTarget) onClose?.(); }}>
        {gallery.length > 1 && (
          <>
            <button type="button" onClick={() => go(-1)} disabled={atStart} aria-label={w.prev} data-testid="viewer-prev" className={"absolute start-3 top-1/2 grid h-11 w-11 -translate-y-1/2 place-items-center rounded-full bg-white/10 hover:bg-white/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white disabled:opacity-30"}>
              <BackIcon size={22} className={rtl ? "rotate-180" : ""} />
            </button>
            <button type="button" onClick={() => go(1)} disabled={atEnd} aria-label={w.next} data-testid="viewer-next" className="absolute end-3 top-1/2 grid h-11 w-11 -translate-y-1/2 place-items-center rounded-full bg-white/10 hover:bg-white/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white disabled:opacity-30">
              <BackIcon size={22} className={rtl ? "" : "rotate-180"} />
            </button>
          </>
        )}
        {failed ? (
          <p role="alert" className="text-[15px] text-white/80">{lang === "ar" ? "تعذّر تحميل الصورة" : "The photo could not be loaded"}</p>
        ) : (
          <img key={slide.id} src={slide.url} alt={slide.caption || w.image} onError={() => setFailed(true)} className="max-h-full max-w-full rounded-md object-contain" data-testid="viewer-image" />
        )}
      </div>

      {slide.caption && (
        <p dir="auto" data-testid="viewer-caption" className="mx-auto max-w-[min(90vw,720px)] px-4 pb-5 pt-2 text-center text-[15px]">{slide.caption}</p>
      )}
    </div>
  );
}
