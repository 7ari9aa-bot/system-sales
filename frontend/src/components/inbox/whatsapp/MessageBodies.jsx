import React, { useState } from "react";
import { BlockedIcon, DownloadIcon, FileIcon, ListIcon, PinIcon, PlayIcon, UserIcon } from "./icons";
import { fileExtension, fileNameOf, parseContact, parseLocation } from "./messageKind";
import { cn } from "@/lib/utils";

const WORDS = {
  ar: { location: "الموقع", contact: "جهة اتصال", document: "مستند", download: "تنزيل", video: "فيديو", play: "تشغيل الفيديو", sticker: "ملصق", buttonReply: "ردّ بزر", listReply: "اختيار من قائمة", unsupported: "رسالة غير مدعومة. افتحها من تطبيق واتساب على الهاتف.", photoFailed: "تعذّر تحميل الصورة", mediaFailed: "تعذّر تحميل الملف", photo: "صورة", noNumber: "بدون رقم" },
  en: { location: "Location", contact: "Contact", document: "Document", download: "Download", video: "Video", play: "Play video", sticker: "Sticker", buttonReply: "Button reply", listReply: "List choice", unsupported: "This message type is not supported. Open it in the WhatsApp app on your phone.", photoFailed: "Could not load the photo", mediaFailed: "Could not load the file", photo: "Photo", noNumber: "No number", },
};
const t = (lang) => WORDS[lang] || WORDS.en;

// A media URL from the customer expires. The browser reports that as an error
// on the element; a broken-image icon tells the agent nothing, so say it.
export function PhotoBody({ src, caption, lang, onOpen, className }) {
  const w = t(lang);
  const [failed, setFailed] = useState(false);
  if (failed) {
    return (
      <div data-testid="media-failed" role="img" aria-label={w.photoFailed} className="flex h-32 w-56 max-w-full items-center justify-center gap-2 rounded-lg bg-black/5 text-[13px] text-[#667781]">
        <BlockedIcon size={18} />{w.photoFailed}
      </div>
    );
  }
  const img = <img src={src} alt={caption || w.photo} loading="lazy" onError={() => setFailed(true)} className={cn("max-h-64 w-full rounded-lg object-cover", className)} />;
  return (
    <div className="max-w-[280px] overflow-hidden rounded-lg">
      {onOpen ? (
        <button type="button" data-testid="open-image" onClick={onOpen} aria-label={w.photo} className="block w-full cursor-zoom-in rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#00a884]">{img}</button>
      ) : img}
    </div>
  );
}

export function StickerBody({ src, lang }) {
  const w = t(lang);
  const [failed, setFailed] = useState(false);
  if (failed) return <div data-testid="media-failed" className="text-[13px] text-[#667781]">{w.sticker}</div>;
  // A sticker has no bubble chrome and no caption: just the image.
  return <img data-testid="sticker" src={src} alt={w.sticker} loading="lazy" onError={() => setFailed(true)} className="h-36 w-36 object-contain" />;
}

export function VideoBody({ src, caption, lang }) {
  const w = t(lang);
  const [failed, setFailed] = useState(false);
  const [playing, setPlaying] = useState(false);
  if (failed) {
    return (
      <div data-testid="media-failed" className="flex h-24 w-56 max-w-full items-center justify-center gap-2 rounded-lg bg-black/5 text-[13px] text-[#667781]"><BlockedIcon size={18} />{w.mediaFailed}</div>
    );
  }
  return (
    <div className="max-w-[280px] overflow-hidden rounded-lg bg-black">
      {playing ? (
        <video data-testid="video" src={src} controls autoPlay preload="metadata" onError={() => setFailed(true)} className="max-h-64 w-full" aria-label={caption || w.video} />
      ) : (
        <button type="button" data-testid="play-video" onClick={() => setPlaying(true)} aria-label={w.play} className="grid h-40 w-64 max-w-full place-items-center text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#00a884]">
          <span className="grid h-12 w-12 place-items-center rounded-full bg-black/55"><PlayIcon size={26} /></span>
        </button>
      )}
    </div>
  );
}

export function DocumentBody({ src, label, lang, out }) {
  const w = t(lang);
  const name = label || fileNameOf(src, w.document);
  const ext = fileExtension(name);
  return (
    <div data-testid="document" className={cn("flex w-64 max-w-full items-center gap-3 rounded-lg p-2", out ? "bg-[#cfe9ca]" : "bg-[#f5f6f6]")}>
      <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-[#7f66ff]/15 text-[#7f66ff]"><FileIcon size={22} /></span>
      <span className="min-w-0 flex-1">
        <span dir="auto" className="block truncate text-[13.5px] font-medium">{name}</span>
        {ext && <span className="block text-[11.5px] text-[#667781]">{ext}</span>}
      </span>
      {src && (
        <a href={src} target="_blank" rel="noopener noreferrer" download data-testid="document-download" aria-label={`${w.download} ${name}`} title={w.download} className="grid h-9 w-9 shrink-0 place-items-center rounded-full text-[#54656f] hover:bg-black/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#00a884]">
          <DownloadIcon size={20} />
        </a>
      )}
    </div>
  );
}

// The gateway keeps only the place's name and address (no coordinates), so this
// shows exactly that. No map is drawn: there is nothing true to draw it from.
export function LocationBody({ body, lang }) {
  const w = t(lang);
  const { title, address } = parseLocation(body);
  return (
    <div data-testid="location" className="flex w-64 max-w-full items-center gap-3 rounded-lg bg-black/5 p-2">
      <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-[#ea4335]/15 text-[#ea4335]"><PinIcon size={22} /></span>
      <span className="min-w-0 flex-1" dir="auto">
        <span className="block text-[11.5px] text-[#667781]">{w.location}</span>
        <span className="block truncate text-[13.5px] font-medium">{title || w.location}</span>
        {address && <span className="block truncate text-[12.5px] text-[#667781]">{address}</span>}
      </span>
    </div>
  );
}

export function ContactBody({ body, lang }) {
  const w = t(lang);
  const { name, phone } = parseContact(body);
  return (
    <div data-testid="contact-card" className="flex w-64 max-w-full items-center gap-3 rounded-lg bg-black/5 p-2">
      <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-[#dfe5e7] text-[#54656f]"><UserIcon size={22} /></span>
      <span className="min-w-0 flex-1" dir="auto">
        <span className="block text-[11.5px] text-[#667781]">{w.contact}</span>
        <span className="block truncate text-[13.5px] font-medium">{name || phone || w.contact}</span>
        {name && <span className="block truncate text-[12.5px] text-[#667781]" dir="ltr">{phone || w.noNumber}</span>}
      </span>
    </div>
  );
}

// A tap on a quick-reply button or a list row: the customer's CHOICE, as text.
export function ChoiceBody({ body, kind, lang }) {
  const w = t(lang);
  const Icon = kind === "list" ? ListIcon : null;
  return (
    <div data-testid={kind === "list" ? "list-reply" : "button-reply"}>
      <div className="mb-0.5 flex items-center gap-1 text-[11.5px] text-[#667781]">
        {Icon && <Icon size={13} />}{kind === "list" ? w.listReply : w.buttonReply}
      </div>
      <div dir="auto" className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]">{body}</div>
    </div>
  );
}

export function UnsupportedBody({ lang }) {
  return (
    <div data-testid="unsupported" dir="auto" className="flex items-start gap-2 italic text-[#667781]">
      <BlockedIcon size={16} className="mt-0.5 shrink-0" />
      <span>{t(lang).unsupported}</span>
    </div>
  );
}
