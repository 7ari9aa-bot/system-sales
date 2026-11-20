import React, { useState } from "react";
import { BlockedIcon, FileIcon, LinkOutIcon, ListIcon, PinIcon, PlayIcon, UserIcon } from "./icons";
import { fileExtension, fileNameOf, parseContact, parseLocation } from "./messageKind";
import { cn } from "@/lib/utils";

const WORDS = {
  ar: { choices: "الخيارات", location: "الموقع", contact: "جهة اتصال", document: "مستند", download: "تنزيل", open: "فتح", saveAs: "حفظ باسم...", video: "فيديو", play: "تشغيل الفيديو", sticker: "ملصق", buttonReply: "ردّ بزر", listReply: "اختيار من قائمة", unsupported: "رسالة غير مدعومة. افتحها من تطبيق واتساب على الهاتف.", photoFailed: "تعذّر تحميل الصورة", mediaFailed: "تعذّر تحميل الملف", photo: "صورة", noNumber: "بدون رقم" },
  en: { choices: "Choices", location: "Location", contact: "Contact", document: "Document", download: "Download", open: "Open", saveAs: "Save as...", video: "Video", play: "Play video", sticker: "Sticker", buttonReply: "Button reply", listReply: "List choice", unsupported: "This message type is not supported. Open it in the WhatsApp app on your phone.", photoFailed: "Could not load the photo", mediaFailed: "Could not load the file", photo: "Photo", noNumber: "No number", },
};
const t = (lang) => WORDS[lang] || WORDS.en;

// A media URL from the customer expires. The browser reports that as an error
// on the element; a broken-image icon tells the agent nothing, so say it.
export function PhotoBody({ src, caption, lang, onOpen, className }) {
  const w = t(lang);
  const [failed, setFailed] = useState(false);
  if (failed) {
    return (
      <div data-testid="media-failed" role="img" aria-label={w.photoFailed} className="flex h-32 w-56 max-w-full items-center justify-center gap-2 rounded-lg bg-[var(--wa-bg-hover)] text-[13px] text-[color:var(--wa-text-secondary)]">
        <BlockedIcon size={18} />{w.photoFailed}
      </div>
    );
  }
  const img = <img src={src} alt={caption || w.photo} loading="lazy" onError={() => setFailed(true)} className={cn("max-h-64 w-full rounded-lg object-cover", className)} />;
  return (
    <div className="max-w-[280px] overflow-hidden rounded-lg">
      {onOpen ? (
        <button type="button" data-testid="open-image" onClick={onOpen} aria-label={w.photo} className="block w-full cursor-zoom-in rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--wa-green)]">{img}</button>
      ) : img}
    </div>
  );
}

export function StickerBody({ src, lang }) {
  const w = t(lang);
  const [failed, setFailed] = useState(false);
  if (failed) return <div data-testid="media-failed" className="text-[13px] text-[color:var(--wa-text-secondary)]">{w.sticker}</div>;
  // A sticker has no bubble chrome and no caption: just the image.
  return <img data-testid="sticker" src={src} alt={w.sticker} loading="lazy" onError={() => setFailed(true)} className="h-36 w-36 object-contain" />;
}

export function VideoBody({ src, caption, lang }) {
  const w = t(lang);
  const [failed, setFailed] = useState(false);
  const [playing, setPlaying] = useState(false);
  if (failed) {
    return (
      <div data-testid="media-failed" className="flex h-24 w-56 max-w-full items-center justify-center gap-2 rounded-lg bg-[var(--wa-bg-hover)] text-[13px] text-[color:var(--wa-text-secondary)]"><BlockedIcon size={18} />{w.mediaFailed}</div>
    );
  }
  return (
    <div className="max-w-[280px] overflow-hidden rounded-lg bg-black">
      {playing ? (
        <video data-testid="video" src={src} controls autoPlay preload="metadata" onError={() => setFailed(true)} className="max-h-64 w-full" aria-label={caption || w.video} />
      ) : (
        <button type="button" data-testid="play-video" onClick={() => setPlaying(true)} aria-label={w.play} className="grid h-40 w-64 max-w-full place-items-center text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--wa-green)]">
          <span className="grid h-12 w-12 place-items-center rounded-full bg-[var(--wa-bg-hover)]5"><PlayIcon size={26} /></span>
        </button>
      )}
    </div>
  );
}

export function DocumentBody({ src, label, lang, out }) {
  const w = t(lang);
  const name = label || fileNameOf(src, w.document);
  const ext = fileExtension(name);
  // The real app: a card, then two plain text actions under it, split by a hairline.
  return (
    <div data-testid="document" className="w-64 max-w-full">
      <div className={cn("flex items-center gap-3 rounded-lg p-2.5", out ? "bg-[var(--wa-bubble-out-inner)]" : "bg-[var(--wa-bg-hover)]")}>
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-[#7f66ff]/15 text-[#7f66ff]"><FileIcon size={22} /></span>
        <span className="min-w-0 flex-1">
          <span dir="auto" className="block truncate text-[13.5px] font-medium">{name}</span>
          {ext && <span className="block text-[11.5px] text-[color:var(--wa-text-secondary)]">{ext}</span>}
        </span>
      </div>
      {src && (
        <div className="mt-1 grid grid-cols-2 border-t border-[color:var(--wa-divider)] text-center text-[14px] font-medium text-[color:var(--wa-green-link)]">
          <a href={src} target="_blank" rel="noopener noreferrer" data-testid="document-open" className="py-2 hover:bg-black/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[color:var(--wa-green)]">{w.open}</a>
          <a href={src} download={name} target="_blank" rel="noopener noreferrer" data-testid="document-download" aria-label={`${w.download} ${name}`} className="py-2 hover:bg-black/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[color:var(--wa-green)]">{w.saveAs}</a>
        </div>
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
    <div data-testid="location" className="flex w-64 max-w-full items-center gap-3 rounded-lg bg-[var(--wa-bg-hover)] p-2">
      <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-[#ea4335]/15 text-[#ea4335]"><PinIcon size={22} /></span>
      <span className="min-w-0 flex-1" dir="auto">
        <span className="block text-[11.5px] text-[color:var(--wa-text-secondary)]">{w.location}</span>
        <span className="block truncate text-[13.5px] font-medium">{title || w.location}</span>
        {address && <span className="block truncate text-[12.5px] text-[color:var(--wa-text-secondary)]">{address}</span>}
      </span>
    </div>
  );
}

export function ContactBody({ body, lang }) {
  const w = t(lang);
  const { name, phone } = parseContact(body);
  return (
    <div data-testid="contact-card" className="flex w-64 max-w-full items-center gap-3 rounded-lg bg-[var(--wa-bg-hover)] p-2">
      <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-[var(--wa-divider)] text-[color:var(--wa-text-icon)]"><UserIcon size={22} /></span>
      <span className="min-w-0 flex-1" dir="auto">
        <span className="block text-[11.5px] text-[color:var(--wa-text-secondary)]">{w.contact}</span>
        <span className="block truncate text-[13.5px] font-medium">{name || phone || w.contact}</span>
        {name && <span className="block truncate text-[12.5px] text-[color:var(--wa-text-secondary)]" dir="ltr">{phone || w.noNumber}</span>}
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
      <div className="mb-0.5 flex items-center gap-1 text-[11.5px] text-[color:var(--wa-text-secondary)]">
        {Icon && <Icon size={13} />}{kind === "list" ? w.listReply : w.buttonReply}
      </div>
      <div dir="auto" className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]">{body}</div>
    </div>
  );
}

export function UnsupportedBody({ lang }) {
  return (
    <div data-testid="unsupported" dir="auto" className="flex items-start gap-2 italic text-[color:var(--wa-text-secondary)]">
      <BlockedIcon size={16} className="mt-0.5 shrink-0" />
      <span>{t(lang).unsupported}</span>
    </div>
  );
}

// A message WE sent with choices under it (buttons, a list, or a link button), drawn like the
// customer sees it. The agent is not the customer, so reply buttons and the list button only SHOW
// the choices; the link button is a real link. `message` is what the server checked and rebuilt.
export function InteractiveBody({ message, lang }) {
  const w = t(lang);
  const action = message?.action || {};
  const rows = [];
  if (message?.type === "button") {
    for (const b of action.buttons || []) rows.push({ key: b.reply.id, label: b.reply.title, icon: null });
  } else if (message?.type === "list") {
    rows.push({ key: "list", label: action.button, icon: <ListIcon size={16} /> });
  } else if (message?.type === "cta_url") {
    rows.push({ key: "cta", label: action.parameters?.display_text, href: action.parameters?.url, icon: <LinkOutIcon size={16} /> });
  }
  const header = message?.header?.type === "text" ? message.header.text : "";
  return (
    <div data-testid={`interactive-${message?.type || "unknown"}`} className="w-64 max-w-full">
      {header && <div dir="auto" className="mb-1 font-semibold">{header}</div>}
      <div dir="auto" className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]">{message?.body?.text}</div>
      {message?.footer?.text && (
        <div dir="auto" className="mt-1 text-[12.5px] text-[color:var(--wa-text-secondary)]">{message.footer.text}</div>
      )}
      {rows.length > 0 && (
        <div className="-mx-1 mt-2 border-t border-[color:var(--wa-divider)]" aria-label={w.choices}>
          {rows.map((r, i) => {
            const cls = cn(
              "flex items-center justify-center gap-1.5 px-2 py-2 text-center text-[14px] font-medium text-[color:var(--wa-green-link)]",
              i > 0 && "border-t border-[color:var(--wa-divider)]",
            );
            if (message?.type === "list") {
              return (
                <details key={r.key} data-testid="interactive-list" className="group">
                  <summary className={cn(cls, "cursor-pointer list-none [&::-webkit-details-marker]:hidden hover:bg-black/5")}>
                    {r.icon}<span dir="auto" className="truncate">{r.label}</span>
                  </summary>
                  <div className="space-y-2 pb-2 pt-1">
                    {(action.sections || []).map((sec) => (
                      <div key={sec.title}>
                        <div dir="auto" className="px-2 text-[12px] font-semibold text-[color:var(--wa-text-secondary)]">{sec.title}</div>
                        {sec.rows.map((row) => (
                          <div key={row.id} data-testid="interactive-row" className="px-2 py-1">
                            <div dir="auto" className="text-[13.5px]">{row.title}</div>
                            {row.description && <div dir="auto" className="text-[12px] text-[color:var(--wa-text-secondary)]">{row.description}</div>}
                          </div>
                        ))}
                      </div>
                    ))}
                  </div>
                </details>
              );
            }
            return r.href ? (
              <a key={r.key} href={r.href} target="_blank" rel="noopener noreferrer" data-testid="interactive-link" className={cn(cls, "hover:bg-black/5")}>
                {r.icon}<span dir="auto" className="truncate">{r.label}</span>
              </a>
            ) : (
              <div key={r.key} data-testid="interactive-choice" className={cls}>
                {r.icon}<span dir="auto" className="truncate">{r.label}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
