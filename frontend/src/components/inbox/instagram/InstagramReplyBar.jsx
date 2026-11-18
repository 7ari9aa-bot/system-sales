import React from "react";

const W = {
  en: { replyingTo: "Replying to", you: "yourself", cancel: "Cancel reply", attachment: "Attachment" },
  ar: { replyingTo: "الرد على", you: "نفسك", cancel: "إلغاء الرد", attachment: "مرفق" },
};

// The line Instagram draws above the message box while you answer one particular message.
export function InstagramReplyBar({ replyingTo, customerName = "", lang = "ar", onCancel }) {
  if (!replyingTo) return null;
  const w = W[lang === "ar" ? "ar" : "en"];
  const who = replyingTo.side === "out" ? w.you : customerName || "";
  const text = String(replyingTo.text || "").trim() || w.attachment;
  return (
    <div data-testid="ig-replying-to" dir="auto" className="flex items-start gap-2 px-4 pb-1 pt-2">
      <div className="min-w-0 flex-1 text-[12px] leading-snug text-[#737373]">
        <div>
          {w.replyingTo} <span className="font-semibold text-[#262626]">{who}</span>
        </div>
        <div className="truncate">{text}</div>
      </div>
      <button type="button" data-testid="ig-cancel-reply" onClick={onCancel} aria-label={w.cancel} title={w.cancel} className="grid h-6 w-6 shrink-0 place-items-center rounded-full text-[#737373] hover:bg-[#efefef]">
        <svg aria-hidden viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M6 6l12 12M18 6 6 18" /></svg>
      </button>
    </div>
  );
}
