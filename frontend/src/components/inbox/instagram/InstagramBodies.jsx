import React, { useState } from "react";
import { cn } from "@/lib/utils";
import { safeHttps } from "./messageKind";

const COPY = {
  en: { photoFailed: "Photo unavailable", videoFailed: "Video unavailable", post: "Shared a post", reel: "Shared a reel", storyReply: "Replied to your story", storyMention: "Mentioned you in their story", storyGone: "Story no longer available", open: "Open on Instagram", unsent: "Message unsent", unsupported: "This message type isn't supported yet", file: "File", voice: "Voice message" },
  ar: { photoFailed: "الصورة غير متاحة", videoFailed: "الفيديو غير متاح", post: "شارك منشورًا", reel: "شارك ريل", storyReply: "رد على قصتك", storyMention: "أشار إليك في قصته", storyGone: "القصة لم تعد متاحة", open: "فتح على إنستغرام", unsent: "تم إلغاء إرسال الرسالة", unsupported: "نوع الرسالة هذا غير مدعوم بعد", file: "ملف", voice: "رسالة صوتية" },
};
export const igCopy = (lang) => COPY[lang === "ar" ? "ar" : "en"];

function Broken({ children, className }) {
  return <div data-testid="media-failed" role="img" aria-label={String(children)} className={cn("flex h-28 w-52 max-w-full items-center justify-center rounded-xl bg-black/5 px-3 text-center text-[13px] opacity-70", className)}>{children}</div>;
}

export function ImageBody({ src, lang, onOpen }) {
  const [failed, setFailed] = useState(false);
  if (failed) return <Broken>{igCopy(lang).photoFailed}</Broken>;
  return (
    <button type="button" onClick={onOpen} className="block overflow-hidden rounded-xl">
      <img data-testid="ig-image" src={src} alt="" loading="lazy" onError={() => setFailed(true)} className="max-h-[320px] w-full min-w-[160px] max-w-[260px] object-cover" />
    </button>
  );
}

export function VideoBody({ src, lang }) {
  const [failed, setFailed] = useState(false);
  if (failed) return <Broken>{igCopy(lang).videoFailed}</Broken>;
  return <video data-testid="ig-video" src={src} controls preload="metadata" onError={() => setFailed(true)} className="max-h-[320px] w-full max-w-[260px] rounded-xl bg-black" />;
}

export function AudioBody({ src, lang }) {
  return <audio data-testid="ig-voice" src={src} controls preload="none" aria-label={igCopy(lang).voice} className="h-10 w-56 max-w-full" />;
}

export function FileBody({ src, label, lang }) {
  const href = safeHttps(src);
  const text = label || igCopy(lang).file;
  return href
    ? <a data-testid="ig-file" href={href} target="_blank" rel="noopener noreferrer" className="inline-flex max-w-[240px] items-center gap-2 rounded-xl bg-black/5 px-3 py-2 underline-offset-2 hover:underline"><span aria-hidden="true">📄</span><span className="truncate">{text}</span></a>
    : <span data-testid="ig-file" className="inline-flex items-center gap-2 rounded-xl bg-black/5 px-3 py-2"><span aria-hidden="true">📄</span>{text}</span>;
}

export function StickerBody({ src }) {
  const [failed, setFailed] = useState(false);
  if (failed) return null;
  return <img data-testid="ig-sticker" src={src} alt="" loading="lazy" onError={() => setFailed(true)} className="h-32 w-32 object-contain" />;
}

// The "like" heart is just a large heart with no bubble around it.
export function HeartBody() {
  return <span data-testid="ig-heart" role="img" aria-label="❤️" className="block select-none text-[44px] leading-none">❤️</span>;
}

export function DeletedBody({ lang }) {
  return <span data-testid="ig-deleted" className="italic opacity-70">{igCopy(lang).unsent}</span>;
}

export function UnsupportedBody({ lang }) {
  return <span data-testid="ig-unsupported" className="italic opacity-70">{igCopy(lang).unsupported}</span>;
}

// A shared post / reel, or a story: a small framed card with what we know, and a link out.
export function CardBody({ card, kind, lang, preview }) {
  const w = igCopy(lang);
  const href = safeHttps(card?.url);
  const reel = card?.kind === "ig_reel" || card?.kind === "reel";
  const heading = kind === "story_reply" ? w.storyReply : kind === "story_mention" ? w.storyMention : reel ? w.reel : w.post;
  const isStory = kind === "story_reply" || kind === "story_mention";
  return (
    <div data-testid={`ig-card-${kind}`} className="w-60 max-w-full overflow-hidden rounded-xl border border-[#0c1014]/10 bg-white text-[#262626]">
      {preview && <div className="aspect-square w-full bg-[#f3f5f7]">{preview}</div>}
      <div className="space-y-1 px-3 py-2">
        <div className="text-[12px] font-semibold text-[#6a717a]">{heading}</div>
        {card?.title && <div dir="auto" className="line-clamp-3 break-words text-[13px]">{card.title}</div>}
        {!card?.url && isStory && <div className="text-[12px] text-[#6a717a]">{w.storyGone}</div>}
        {href && <a href={href} target="_blank" rel="noopener noreferrer" className="inline-block text-[13px] font-semibold text-[#0095f6] hover:underline">{w.open}</a>}
      </div>
    </div>
  );
}
