import React from "react";
import { cn } from "@/lib/utils";

export const MAX_QUICK_REPLIES = 13;
export const QUICK_REPLY_CHARS = 20;

/** What is wrong with these quick replies, or "" when Instagram will accept them. */
export function quickReplyProblem(items, lang = "ar") {
  // A button left empty is simply not sent; only a repeated title is a mistake.
  const titles = items.map((t) => t.trim()).filter(Boolean);
  if (new Set(titles).size !== titles.length) return lang === "ar" ? "الأزرار لازم تكون مختلفة عن بعضها." : "Buttons must differ from each other.";
  return "";
}

/**
 * The reply buttons a customer can tap under our message. Instagram allows 13 of up to 20 characters, plain text only,
 * and tells us they are not shown on desktop, so the panel says so instead of promising more than Instagram does.
 */
export default function IgQuickReplies({ items, onChange, onClose, lang = "ar" }) {
  const ar = lang === "ar";
  const set = (i, value) => onChange(items.map((t, n) => (n === i ? value.slice(0, QUICK_REPLY_CHARS) : t)));
  return (
    <div data-testid="ig-quick-panel" dir={ar ? "rtl" : "ltr"} className="mb-2 rounded-2xl border border-[#dbdfe4] bg-white p-3">
      <div className="mb-2 flex items-center justify-between">
        <p className="text-[14px] font-semibold text-[#0c1014]">{ar ? "أزرار رد سريع" : "Quick replies"}</p>
        <button type="button" onClick={onClose} className="text-[12px] font-semibold text-[#6a717a] hover:text-[#0c1014]">{ar ? "إغلاق" : "Close"}</button>
      </div>
      <ul className="flex flex-col gap-2">
        {items.map((title, i) => (
          <li key={i} className="flex items-center gap-2">
            <input value={title} onChange={(e) => set(i, e.target.value)} dir="auto" aria-label={`${ar ? "زر" : "Button"} ${i + 1}`} data-testid="ig-quick-input"
              placeholder={ar ? "عنوان الزر" : "Button title"} className="h-9 min-w-0 flex-1 rounded-full bg-[#f3f5f7] px-4 text-[14px] outline-none placeholder:text-[#6a717a]" />
            <span className={cn("w-9 shrink-0 text-center text-[12px]", title.length >= QUICK_REPLY_CHARS ? "text-[#ed4956]" : "text-[#6a717a]")} dir="ltr">{title.length}/{QUICK_REPLY_CHARS}</span>
            <button type="button" onClick={() => onChange(items.filter((_, n) => n !== i))} aria-label={ar ? "حذف الزر" : "Remove button"} className="shrink-0 rounded-full px-2 text-[18px] leading-none text-[#6a717a] hover:bg-[#f3f5f7]">×</button>
          </li>
        ))}
      </ul>
      {items.length < MAX_QUICK_REPLIES && (
        <button type="button" data-testid="ig-quick-add" onClick={() => onChange([...items, ""])} className="mt-2 text-[14px] font-semibold text-[#0095f6] hover:text-[#00376b]">{ar ? "إضافة زر" : "Add a button"}</button>
      )}
      <p className="mt-2 text-[12px] leading-4 text-[#6a717a]">{ar ? "حتى 13 زرًا. تظهر في تطبيق إنستجرام على الموبايل فقط، وليس على الكمبيوتر." : "Up to 13 buttons. They show in Instagram's mobile app, not on desktop."}</p>
    </div>
  );
}
