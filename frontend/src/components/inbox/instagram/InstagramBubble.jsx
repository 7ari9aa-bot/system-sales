import React from "react";
import { cn } from "@/lib/utils";
import { IgHeart, IgReply } from "@/components/instagram/igIcons";
import { instagramKind } from "./messageKind";
import { AudioBody, CardBody, DeletedBody, FileBody, HeartBody, ImageBody, StickerBody, UnsupportedBody, VideoBody } from "./InstagramBodies";

const SEEN = { en: "Seen", ar: "تمت المشاهدة" };
// Instagram's Send API lets a business react with the heart only.
const HEART = "\u2764\ufe0f";

// Instagram draws an outgoing "Seen" once, under the newest message we sent, never a tick on each.
export function InstagramBubble({ m, th, lang = "ar", showSeen = false, onOpenImage, onReact, onReply }) {
  const out = m.side === "out";
  const kind = instagramKind(m);
  const bare = kind === "heart" || kind === "sticker"; // these float with no bubble around them
  const radius = th?.bubbleRadius ?? 18;
  const text = String(m.text || "").trim();
  const caption = kind === "text" || kind === "deleted" || kind === "unsupported" || kind === "heart" || kind === "sticker" ? "" : text;

  let body;
  if (kind === "deleted") body = <DeletedBody lang={lang} />;
  else if (kind === "unsupported") body = <UnsupportedBody lang={lang} />;
  else if (kind === "heart") body = <HeartBody />;
  else if (kind === "sticker") body = <StickerBody src={m.mediaUrl} />;
  else if (kind === "image") body = <ImageBody src={m.mediaUrl} lang={lang} onOpen={onOpenImage && (() => onOpenImage(m.id))} />;
  else if (kind === "video") body = <VideoBody src={m.mediaUrl} lang={lang} />;
  else if (kind === "voice") body = <AudioBody src={m.mediaUrl} lang={lang} />;
  else if (kind === "file") body = <FileBody src={m.mediaUrl} label={m.fileName} lang={lang} />;
  else if (kind === "share" || kind === "story_reply" || kind === "story_mention") {
    const preview = m.mediaUrl && /\.(jpe?g|png|webp|gif)(\?|$)/i.test(m.mediaUrl) ? <img src={m.mediaUrl} alt="" loading="lazy" className="h-full w-full object-cover" /> : null;
    body = <CardBody card={m.card} kind={kind} lang={lang} preview={preview} />;
  } else body = <span dir="auto" className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]">{text}</span>;

  const reactions = Array.isArray(m.reactions) ? m.reactions.filter(Boolean) : [];
  const liked = m.myReaction === HEART;
  const canHeart = Boolean(onReact) && !out && !bare && kind !== "deleted" && kind !== "unsupported";
  // Instagram lets you quote any message, yours or theirs (Send API `reply_to`), so the
  // affordance sits on both sides and on every kind except the bare heart/sticker.
  const canReply = Boolean(onReply) && !bare && kind !== "deleted";
  return (
    <div className={cn("flex flex-col", out ? "items-end" : "items-start")}>
      {m.replyTo && (
        <div data-testid="ig-quote" className="mb-0.5 max-w-[76%] truncate rounded-xl bg-black/5 px-3 py-1 text-[12px] text-[#6a717a]" dir="auto">
          {m.replyTo.available === false ? "…" : m.replyTo.body || m.replyTo.text || "…"}
        </div>
      )}
      <div className={cn("group relative flex max-w-[82%] items-center gap-1 sm:max-w-[76%]", reactions.length && "mb-3")}>
        <div
          data-testid="ig-bubble"
          className={cn("text-[15px] leading-5", bare ? "" : "px-3 py-2", kind === "image" || kind === "video" ? "overflow-hidden !p-1" : "")}
          style={bare ? undefined : { background: out ? th?.out || "#4a5df9" : th?.in || "#f3f5f7", color: out ? th?.outText || "#fff" : th?.inText || "#0c1014", borderRadius: radius }}
        >
          {body}
          {caption && <div dir="auto" className="mt-1.5 whitespace-pre-wrap break-words [overflow-wrap:anywhere]">{caption}</div>}
        </div>
        {canReply && (
          <button type="button" data-testid="ig-reply" aria-label={lang === "ar" ? "الرد على الرسالة" : "Reply to message"}
            onClick={() => onReply(m)}
            className="shrink-0 rounded-full p-1 text-[#6a717a] opacity-0 hover:bg-[#f3f5f7] focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0095f6] group-hover:opacity-100">
            <IgReply size={16} />
          </button>
        )}
        {canHeart && (
          <button type="button" data-testid="ig-react-heart" aria-pressed={liked} aria-label={liked ? (lang === "ar" ? "إزالة القلب" : "Remove heart") : (lang === "ar" ? "أرسل قلبًا" : "React with a heart")}
            onClick={() => onReact(liked ? "" : HEART)}
            className={cn("shrink-0 rounded-full p-1 text-[#6a717a] hover:bg-[#f3f5f7] focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0095f6] group-hover:opacity-100", liked ? "opacity-100 text-[#ff3040]" : "opacity-0")}>
            <IgHeart size={16} filled={liked} />
          </button>
        )}
        {reactions.length > 0 && (
          <span data-testid="ig-reactions" className={cn("absolute -bottom-3 flex items-center rounded-full border border-[#dbdfe4] bg-white px-1.5 text-[13px] leading-5 shadow-sm", out ? "end-2" : "start-2")}>
            {reactions.join("")}
          </span>
        )}
      </div>
      {Array.isArray(m.quickReplies) && m.quickReplies.length > 0 && (
        <div data-testid="ig-quick-sent" className={cn("mt-1 flex max-w-[82%] flex-wrap gap-1.5 sm:max-w-[76%]", out ? "justify-end" : "justify-start")}>
          {m.quickReplies.map((title) => <span key={title} dir="auto" className="rounded-full border border-[#dbdfe4] px-3 py-1 text-[13px] font-semibold text-[#4a5df9]">{title}</span>)}
        </div>
      )}
      {showSeen && out && <span data-testid="ig-seen" className="mt-0.5 px-1 text-[11px] text-[#6a717a]">{SEEN[lang === "ar" ? "ar" : "en"]}</span>}
    </div>
  );
}
