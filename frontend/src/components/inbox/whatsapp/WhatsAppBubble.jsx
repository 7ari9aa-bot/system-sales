import React, { useState } from "react";
import { Sparkles } from "lucide-react";
import MessageMenu from "./MessageMenu";
import MessageStatus from "./MessageStatus";
import MessageSource from "./MessageSource";
import { BlockedIcon, CameraIcon, FileIcon, MicIcon, ChevronDownIcon, PinIcon, UserIcon } from "./icons";
import { cn } from "@/lib/utils";

// WhatsApp's own text stack. These are the fonts the operating system already
// ships; nothing is downloaded, so no font file is redistributed.
export const WHATSAPP_FONT =
  '"Segoe UI", "Helvetica Neue", Helvetica, "Lucida Grande", Arial, Ubuntu, Cantarell, "Fira Sans", sans-serif';

const WORDS = {
  ar: { deleted: "تم حذف هذه الرسالة", reply: "رد", options: "خيارات الرسالة", edited: "معدّلة", photo: "صورة", voice: "رسالة صوتية", video: "فيديو", file: "مستند", location: "الموقع", contact: "جهة اتصال", you: "أنت", unavailable: "الرسالة غير متاحة", unsupported: "رسالة غير مدعومة" },
  en: { deleted: "This message was deleted", reply: "Reply", options: "Message options", edited: "Edited", photo: "Photo", voice: "Voice message", video: "Video", file: "Document", location: "Location", contact: "Contact", you: "You", unavailable: "Message unavailable", unsupported: "Unsupported message" },
};

// What a quoted message shows when it has no text of its own.
export function quotePreview(quote, lang = "ar") {
  const w = WORDS[lang] || WORDS.en;
  if (!quote || quote.available === false) return { icon: null, text: w.unavailable };
  const kinds = { image: [CameraIcon, w.photo], voice: [MicIcon, w.voice], video: [CameraIcon, w.video], file: [FileIcon, w.file], location: [PinIcon, w.location], contact: [UserIcon, w.contact] };
  const kind = kinds[quote.content_type];
  if (quote.body) return { icon: kind ? kind[0] : null, text: quote.body };
  return { icon: kind ? kind[0] : null, text: kind ? kind[1] : w.unsupported };
}

function QuotedReply({ quote, lang, out }) {
  const { icon: Icon, text } = quotePreview(quote, lang);
  const author = quote?.direction === "outbound" ? (WORDS[lang] || WORDS.en).you : null;
  return (
    <div
      data-testid="quoted-reply"
      dir="auto"
      className={cn("mb-1 flex overflow-hidden rounded-md border-s-4 border-[#06cf9c] px-2 py-1 text-[12.5px] leading-tight", out ? "bg-[var(--wa-bubble-out-inner)]" : "bg-[var(--wa-bg-hover)]")}
    >
      <div className="min-w-0">
        {author && <div className="mb-0.5 text-[12.5px] font-medium text-[#06cf9c]">{author}</div>}
        <div className="flex items-center gap-1 text-[color:var(--wa-text-secondary)]">
          {Icon && <Icon size={14} />}
          <span className="line-clamp-2 break-words">{text}</span>
        </div>
      </div>
    </div>
  );
}

function Reactions({ reactions }) {
  if (!reactions?.length) return null;
  return (
    <span
      data-testid="reactions"
      className="absolute -bottom-3 end-2 z-10 flex items-center gap-0.5 rounded-full bg-[var(--wa-bg-panel)] px-1.5 py-px text-[14px] leading-5 shadow-[0_1px_2px_rgba(11,20,26,0.25)]"
    >
      {reactions.join("")}
    </span>
  );
}

function Meta({ m, out, lang }) {
  const w = WORDS[lang] || WORDS.en;
  return (
    <span className="float-end ms-3 mt-1.5 inline-flex translate-y-1 items-center gap-1 whitespace-nowrap align-bottom text-[11px] leading-none text-[color:var(--wa-text-secondary)]" dir="ltr">
      {m.edited && !m.deleted && <span dir="auto">{w.edited}</span>}
      <span>{m.time}</span>
      {m.ai && <Sparkles className="h-3 w-3 text-amber-500" aria-hidden="true" />}
      {/* Business App / AI / FIHRIST: who wrote this outbound message. */}
      <MessageSource m={m} lang={lang} className="text-[10.5px] font-medium" />
      {out && <MessageStatus status={m.status} lang={lang} />}
    </span>
  );
}

// One WhatsApp bubble. `children` carries media rendered by the caller (voice
// player, image) so existing players are reused rather than duplicated.
export default function WhatsAppBubble({ m, th, lang = "ar", children, onReply, onCopy, onReact, mine = "" }) {
  const out = m.side === "out";
  const [menuOpen, setMenuOpen] = useState(false);
  const hasMenu = Boolean(onReply || onCopy || onReact) && !m.deleted;
  const w = WORDS[lang] || WORDS.en;
  const hasReactions = !m.deleted && m.reactions?.length > 0;

  return (
    <div className={cn("group/bubble flex items-center gap-1", out ? "flex-row-reverse justify-start" : "justify-start", hasReactions && "mb-3")}>
      <div
        data-testid="whatsapp-bubble"
        data-direction={out ? "out" : "in"}
        onContextMenu={hasMenu ? (e) => { e.preventDefault(); setMenuOpen(true); } : undefined}
        className="relative max-w-[82%] rounded-lg px-[9px] py-[6px] text-[14.2px] leading-[19px] shadow-[0_1px_0.5px_rgba(11,20,26,0.13)] sm:max-w-[72%] lg:max-w-[65%]"
        style={{ background: out ? th.out : th.in, color: out ? th.outText : th.inText, fontFamily: WHATSAPP_FONT }}
      >
        {th.tail && (
          <span
            aria-hidden="true"
            className={cn("absolute top-0 h-[13px] w-2", out ? "-end-2" : "-start-2")}
            style={{ background: out ? th.out : th.in, clipPath: out ? "polygon(0 0, 100% 0, 0 100%)" : "polygon(0 0, 100% 0, 100% 100%)" }}
          />
        )}
        {m.deleted ? (
          <div dir="auto" className="flex items-center gap-1.5 italic text-[color:var(--wa-text-secondary)]">
            <BlockedIcon size={16} />
            <span>{w.deleted}</span>
            <Meta m={m} out={out} lang={lang} />
          </div>
        ) : (
          <>
            {m.replyTo && <QuotedReply quote={m.replyTo} lang={lang} out={out} />}
            {children ?? (
              <div dir="auto" className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]">
                {m.text}
                <Meta m={m} out={out} lang={lang} />
              </div>
            )}
          </>
        )}
        <Reactions reactions={hasReactions ? m.reactions : null} />
      </div>
      {hasMenu && (
        <div className="relative shrink-0">
          <button
            type="button"
            data-testid="bubble-options"
            onClick={() => setMenuOpen((v) => !v)}
            aria-label={w.options}
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            title={w.options}
            className={cn(
              "grid h-7 w-7 place-items-center rounded-full bg-white/90 text-[color:var(--wa-text-icon)] shadow-sm transition-opacity hover:bg-[var(--wa-bg-panel)] focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--wa-green)] group-hover/bubble:opacity-100",
              menuOpen ? "opacity-100" : "opacity-0",
            )}
          >
            <ChevronDownIcon size={16} />
          </button>
          {menuOpen && (
            <div className={cn("absolute top-8 z-30", out ? "end-0" : "start-0")}>
              <MessageMenu m={m} lang={lang} mine={mine} canReact={Boolean(onReact)} onReply={onReply} onCopy={onCopy} onReact={onReact} onClose={() => setMenuOpen(false)} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
