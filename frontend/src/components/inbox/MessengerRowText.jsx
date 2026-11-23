import React from "react";
import { cn } from "@/lib/utils";
import { messengerRowPreview } from "./messengerChat";

// The text column of one Messenger conversation row: a bold name when there is something unread,
// "You:" before our own last message, the time after the preview, and a blue dot at the end.
// Messenger shows no status chip and no unread count, so neither is drawn.
export default function MessengerRowText({ conversation, lang = "ar" }) {
  const unread = Number(conversation?.unread) > 0;
  return (
    <div data-testid="messenger-row" className="min-w-0 flex-1">
      <div dir="auto" className={cn("truncate text-[15px] text-[#050505]", unread ? "font-semibold" : "font-medium")}>{conversation.customer}</div>
      <div className="mt-0.5 flex min-w-0 items-center gap-1 text-[13px]">
        <span dir="auto" className={cn("min-w-0 truncate", unread ? "font-semibold text-[#050505]" : "text-[#65676b]")}>{messengerRowPreview(conversation, lang)}</span>
        {conversation.time && <span dir="ltr" className="shrink-0 text-[#65676b]">· {conversation.time}</span>}
        {unread && <span data-testid="messenger-unread-dot" aria-label={lang === "ar" ? "غير مقروءة" : "Unread"} className="ms-auto h-3 w-3 shrink-0 rounded-full bg-[#0084ff]" />}
      </div>
    </div>
  );
}
