import React from "react";
import { MessageCircle, Send } from "lucide-react";
import { cn } from "@/lib/utils";

export default function InstagramModeTabs({ active = "comments", lang = "ar", onChange, demoMode = false }) {
  const isArabic = lang === "ar";
  const tabs = [
    { id: "comments", label: isArabic ? "التعليقات" : "Comments", icon: MessageCircle },
    { id: "direct", label: isArabic ? "الرسائل الخاصة" : "Direct messages", icon: Send },
  ];
  return (
    <header className="flex h-[54px] shrink-0 items-center justify-between border-b border-[#dbdbdb] bg-white px-4 sm:px-6">
      <div className="flex h-full items-center gap-5" role="tablist" aria-label={isArabic ? "أقسام إنستغرام" : "Instagram sections"}>
        {tabs.map(({ id, label, icon: Icon }) => <button key={id} type="button" role="tab" aria-selected={active === id} onClick={() => onChange?.(id)} className={cn("inline-flex h-full items-center gap-2 border-b-2 px-1 text-[13px] font-semibold transition-colors", active === id ? "border-[#d62976] text-[#262626]" : "border-transparent text-[#8e8e8e] hover:text-[#262626]")}><Icon className="h-4 w-4" />{label}</button>)}
      </div>
      <div className="hidden items-center gap-2 text-[12px] text-[#737373] sm:flex"><span className={cn("h-2 w-2 rounded-full", demoMode ? "bg-[#d97706]" : "bg-[#32c78a]")} />{demoMode ? isArabic ? "بيانات تجريبية" : "Demo data" : active === "comments" ? isArabic ? "تعليقات المنشورات" : "Post comments" : isArabic ? "محادثات إنستغرام دايركت" : "Instagram Direct conversations"}</div>
    </header>
  );
}
