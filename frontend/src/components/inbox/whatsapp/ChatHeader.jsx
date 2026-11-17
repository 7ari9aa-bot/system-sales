import React, { useEffect, useRef, useState } from "react";
import { BackIcon, ClockIcon, MoreIcon, SearchIcon, UserIcon } from "./icons";
import ChatListMenu from "./ChatListMenu";
import { displayPhone } from "./contactInfo";
import { headerSubtitle, replyWindow } from "./replyWindow";
import { isMuted } from "./chatListState";
import { cn } from "@/lib/utils";

const WORDS = {
  ar: { back: "رجوع إلى المحادثات", search: "بحث في الرسائل", info: "معلومات جهة الاتصال", more: "المزيد", contact: "معلومات جهة الاتصال", muted: "الإشعارات مكتومة", pinned: "محادثة مثبتة", windowClosed: "انتهت نافذة الرد. يمكنك الرد بقالب معتمد فقط." },
  en: { back: "Back to chats", search: "Search messages", info: "Contact info", more: "More", contact: "Contact info", muted: "Notifications muted", pinned: "Pinned chat", windowClosed: "The reply window has closed. You can only reply with an approved template." },
};

/**
 * The header of an open WhatsApp chat. The line under the name carries facts the
 * agent can act on (the customer's number and how long the free reply window has
 * left), never a made-up "online" or "last seen": the Cloud API does not tell us
 * either.
 */
export default function ChatHeader({
  conversation, lang = "ar", pinnedCount = 0, searchOpen = false, now,
  onBack, onOpenInfo, onToggleSearch, onChange, AvatarComponent,
}) {
  const w = WORDS[lang] || WORDS.en;
  const [menuOpen, setMenuOpen] = useState(false);
  const moreRef = useRef(null);
  const [tick, setTick] = useState(() => now || new Date());

  // Keep "ends in 1h 30m" honest while the chat stays open.
  useEffect(() => {
    if (now) return undefined;
    const id = setInterval(() => setTick(new Date()), 30_000);
    return () => clearInterval(id);
  }, [now]);

  if (!conversation) return null;
  const windowInfo = replyWindow(conversation.lastCustomerMessageAt, now || tick);
  const phone = displayPhone(conversation.phone);
  const subtitle = headerSubtitle({ phone, windowInfo, lang });
  const warn = windowInfo.state === "closed" || windowInfo.state === "closing";
  const iconBtn = "grid h-10 w-10 shrink-0 place-items-center rounded-full text-[#54656f] transition-colors hover:bg-black/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#00a884]";
  const closeMenu = () => { setMenuOpen(false); moreRef.current?.focus(); };

  return (
    <header dir="ltr" data-testid="chat-header" className="relative z-20 flex h-[60px] shrink-0 items-center gap-2 border-b border-[#d1d7db] bg-[#f0f2f5] px-4">
      {onBack && (
        <button type="button" onClick={onBack} aria-label={w.back} data-testid="header-back" className={cn(iconBtn, "-ms-2 lg:hidden")}>
          <BackIcon size={22} className={lang === "ar" ? "rotate-180" : undefined} />
        </button>
      )}

      <button type="button" onClick={onOpenInfo} aria-label={`${w.contact}: ${conversation.customer}`} data-testid="header-identity" className="flex min-w-0 flex-1 items-center gap-3 rounded-lg py-1 text-start focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#00a884]">
        {AvatarComponent ? (
          <AvatarComponent conversation={conversation} className="h-10 w-10 text-[13px]" />
        ) : (
          <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full text-[13px] font-semibold text-[#54656f]" style={{ background: conversation.color || "#dfe5e7" }} aria-hidden="true">{conversation.initials}</span>
        )}
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-1.5">
            <span dir="auto" data-testid="header-name" className="truncate text-[16px] font-medium text-[#111b21]">{conversation.customer}</span>
            {conversation.pinnedAt && <span title={w.pinned} role="img" aria-label={w.pinned} className="text-[#8696a0]">📌</span>}
            {isMuted(conversation) && <span title={w.muted} role="img" aria-label={w.muted} className="text-[#8696a0]">🔇</span>}
          </span>
          {subtitle && (
            <span data-testid="header-subtitle" data-window={windowInfo.state} dir="auto" className={cn("flex items-center gap-1 truncate text-[13px]", warn ? "text-[#b45309]" : "text-[#667781]")}>
              {warn && <ClockIcon size={13} aria-hidden="true" />}
              <span className="truncate">{subtitle}</span>
            </span>
          )}
        </span>
      </button>

      <button type="button" onClick={onToggleSearch} aria-label={w.search} aria-pressed={searchOpen} data-testid="header-search" className={cn(iconBtn, searchOpen && "bg-black/5")}>
        <SearchIcon size={20} />
      </button>
      <button type="button" onClick={onOpenInfo} aria-label={w.info} data-testid="header-info" className={cn(iconBtn, "hidden sm:grid")}>
        <UserIcon size={20} />
      </button>
      <div className="relative">
        <button ref={moreRef} type="button" onClick={() => setMenuOpen((open) => !open)} aria-label={w.more} aria-haspopup="menu" aria-expanded={menuOpen} data-testid="header-more" className={iconBtn}>
          <MoreIcon size={20} />
        </button>
        {menuOpen && (
          <div className="absolute end-0 top-11 z-30" dir={lang === "ar" ? "rtl" : "ltr"}>
            <ChatListMenu row={conversation} lang={lang} pinnedCount={pinnedCount} onChange={onChange} onClose={closeMenu} />
          </div>
        )}
      </div>
    </header>
  );
}
