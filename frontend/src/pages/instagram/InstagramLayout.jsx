import React from "react";
import { NavLink, Outlet } from "react-router-dom";
import { Bookmark, Inbox as InboxIcon, MessageCircle, Send, Image as ImageIcon } from "lucide-react";
import { InboxProvider, useInbox } from "@/pages/inbox/InboxProvider";
import { cn } from "@/lib/utils";

/** Every Instagram section is its own route; this rail links between them. */
export const INSTAGRAM_SECTIONS = [
  { to: "/instagram/direct", ar: "الرسائل", en: "Messages", icon: Send },
  { to: "/instagram/requests", ar: "الطلبات", en: "Requests", icon: Bookmark },
  { to: "/instagram/comments", ar: "التعليقات", en: "Comments", icon: MessageCircle },
  { to: "/instagram/posts", ar: "المنشورات", en: "Posts", icon: ImageIcon },
];

function InstagramShell() {
  const { lang, error, demoAccount } = useInbox();
  const isArabic = lang === "ar";
  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      {error && (
        <div role="alert" className="mb-3 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">{error}</div>
      )}
      <div dir="ltr" className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_52px] overflow-hidden">
        <main className="flex h-full min-h-0 min-w-0 flex-col">
          <header className="flex h-[54px] shrink-0 items-center justify-between border-b border-[#dbdbdb] bg-white px-4 sm:px-6">
            <nav aria-label={isArabic ? "أقسام إنستغرام" : "Instagram sections"} className="flex h-full items-center gap-5">
              {INSTAGRAM_SECTIONS.map(({ to, ar, en, icon: Icon }) => (
                <NavLink
                  key={to}
                  to={to}
                  className={({ isActive }) => cn(
                    "inline-flex h-full items-center gap-2 border-b-2 px-1 text-[13px] font-semibold transition-colors",
                    isActive ? "border-[#d62976] text-[#262626]" : "border-transparent text-[#8e8e8e] hover:text-[#262626]"
                  )}
                >
                  <Icon className="h-4 w-4" />{isArabic ? ar : en}
                </NavLink>
              ))}
            </nav>
            <div className="hidden items-center gap-2 text-[12px] text-[#737373] sm:flex">
              <span className={cn("h-2 w-2 rounded-full", demoAccount ? "bg-[#d97706]" : "bg-[#32c78a]")} />
              {demoAccount ? (isArabic ? "بيانات تجريبية" : "Demo data") : "Instagram"}
            </div>
          </header>
          <div className="min-h-0 flex-1"><Outlet /></div>
        </main>
        <aside className="z-10 flex min-h-0 min-w-0 flex-col items-center border-l border-border/80 bg-card" aria-label="Instagram">
          <RailLinks />
        </aside>
      </div>
    </div>
  );
}

function RailLinks() {
  const { lang } = useInbox();
  return (
    <NavLink to="/inbox" className="mt-3 grid h-10 w-10 place-items-center rounded-xl text-muted-foreground hover:bg-surface" aria-label={lang === "ar" ? "كل القنوات" : "All channels"}>
      <InboxIcon className="h-5 w-5" />
    </NavLink>
  );
}

export default function InstagramLayout() {
  return (
    <InboxProvider>
      <InstagramShell />
    </InboxProvider>
  );
}
