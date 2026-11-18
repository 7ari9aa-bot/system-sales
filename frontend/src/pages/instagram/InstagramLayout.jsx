import React, { useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { InboxProvider, useInbox } from "@/pages/inbox/InboxProvider";
import ChannelSwitcher from "@/components/inbox/ChannelSwitcher";
import InstagramNewPostDialog from "@/components/inbox/InstagramNewPostDialog";
import IgAvatar from "@/components/instagram/IgAvatar";
import { IG } from "@/components/instagram/igTheme";
import { IgChannels, IgCreate, IgGlyph, IgHeart, IgMessenger } from "@/components/instagram/igIcons";
import { cn } from "@/lib/utils";
import { useInstagramData } from "./useInstagramData";

function Badge({ count, dot = false }) {
  if (!count) return null;
  if (dot) return <span className="absolute -end-0.5 top-0 h-2 w-2 rounded-full border border-white" style={{ background: IG.red }} />;
  return (
    <span className="absolute -end-1.5 -top-1.5 grid h-[18px] min-w-[18px] place-items-center rounded-full border-2 border-white px-1 text-[11px] font-semibold leading-none text-white" style={{ background: IG.red }}>
      {count > 99 ? "99+" : count}
    </span>
  );
}

/** Instagram's left navigation, limited to what the Instagram API lets a shop do. */
function Rail({ compact, onCreate }) {
  const { lang, unreadMessages, unanswered, account } = useInstagramData();
  const { pathname } = useLocation();
  const isArabic = lang === "ar";
  const item = (isActive) => cn(
    "group relative flex h-12 items-center gap-4 rounded-lg px-3 text-[16px] transition-colors hover:bg-[#f3f5f7] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0095f6]",
    compact ? "w-12 justify-center px-0" : "w-12 justify-center px-0 xl:w-full xl:justify-start xl:px-3",
    isActive ? "font-bold" : "font-normal"
  );
  const label = (text) => <span className={cn("truncate", compact ? "sr-only" : "sr-only xl:not-sr-only")}>{text}</span>;
  return (
    <nav aria-label={isArabic ? "تنقل إنستغرام" : "Instagram navigation"} className={cn("order-last flex h-12 w-full shrink-0 flex-row items-center border-t px-2 md:order-none md:h-full md:flex-col md:border-e md:border-t-0 md:px-3 md:pb-5 md:pt-2", compact ? "md:w-[72px] md:items-center" : "md:w-[72px] md:items-center xl:w-[244px] xl:items-stretch")} style={{ borderColor: IG.border }}>
      <NavLink to="/instagram/direct/inbox" className={cn("mb-4 hidden h-[72px] items-center px-3 md:flex", compact && "justify-center px-0")} aria-label="Instagram">
        <IgGlyph size={24} />
        {!compact && <span className="ms-4 hidden text-[22px] font-semibold tracking-[-0.01em] xl:inline" style={{ fontFamily: "'Billabong', 'Grand Hotel', cursive, " + IG.font }}>Instagram</span>}
      </NavLink>
      <div className="flex flex-1 flex-row items-center justify-around gap-1 md:flex-col md:items-stretch md:justify-start">
        <NavLink to="/instagram/direct/inbox" className={({ isActive }) => item(isActive || pathname.startsWith("/instagram/direct"))}>
          {({ isActive }) => <>
            <span className="relative transition-transform group-hover:scale-105"><IgMessenger filled={isActive || pathname.startsWith("/instagram/direct")} /><Badge count={unreadMessages} /></span>
            {label(isArabic ? "الرسائل" : "Messages")}
          </>}
        </NavLink>
        <NavLink to="/instagram/activity" className={({ isActive }) => item(isActive)}>
          {({ isActive }) => <>
            <span className="relative transition-transform group-hover:scale-105"><IgHeart filled={isActive} /><Badge count={unanswered} dot /></span>
            {label(isArabic ? "الإشعارات" : "Notifications")}
          </>}
        </NavLink>
        {onCreate && (
          <button type="button" onClick={onCreate} className={item(false)}>
            <span className="transition-transform group-hover:scale-105"><IgCreate /></span>
            {label(isArabic ? "إنشاء" : "Create")}
          </button>
        )}
        <NavLink to="/instagram/profile" end={false} className={({ isActive }) => item(isActive || pathname.startsWith("/instagram/p/"))}>
          {({ isActive }) => <>
            <span className={cn("rounded-full transition-transform group-hover:scale-105", (isActive || pathname.startsWith("/instagram/p/")) && "ring-2 ring-black ring-offset-1")}><IgAvatar src={account?.profile_picture_url} size={24} /></span>
            {label(isArabic ? "الملف الشخصي" : "Profile")}
          </>}
        </NavLink>
      </div>
      <NavLink to="/inbox" className={cn(item(false), "hidden md:flex")}>
        <span className="transition-transform group-hover:scale-105"><IgChannels /></span>
        {label(isArabic ? "كل القنوات" : "All channels")}
      </NavLink>
    </nav>
  );
}

function InstagramShell() {
  const { lang, error, actions, demoAccount } = useInstagramData();
  const { channels, unreadByChannel, setActiveChannel, activeChannel, t } = useInbox();
  const { pathname } = useLocation();
  const [creating, setCreating] = useState(false);
  const isArabic = lang === "ar";
  // Like instagram.com, the rail folds to icons while a chat is open.
  const compact = pathname.startsWith("/instagram/direct");
  return (
    <div dir="ltr" className="grid h-full min-h-0 grid-cols-[minmax(0,1fr)_52px] overflow-hidden">
      <div dir={isArabic ? "rtl" : "ltr"} data-testid="instagram-app" data-instagram-app="" className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden bg-white text-[#0c1014] md:flex-row" style={{ fontFamily: IG.font }}>
        <Rail compact={compact} onCreate={!demoAccount && actions.publish ? () => setCreating(true) : null} />
        <main className="flex min-h-0 min-w-0 flex-1 flex-col">
          {error && <div role="alert" className="border-b px-4 py-2 text-[13px]" style={{ borderColor: IG.border, color: IG.error }}>{error}</div>}
          <div className="min-h-0 flex-1"><Outlet /></div>
        </main>
      </div>
      {/* Same channel strip as the inbox, pinned to the physical right edge whatever the language direction. */}
      <aside className="z-10 flex min-h-0 min-w-0 flex-col items-center border-l border-border/80 bg-card" aria-label={t("inbox.title")}>
        <ChannelSwitcher channels={channels} active={activeChannel} unreadByChannel={unreadByChannel} onSelect={setActiveChannel} />
      </aside>
      {creating && actions.publish && <InstagramNewPostDialog lang={lang} onPublish={actions.publish} onClose={() => setCreating(false)} />}
    </div>
  );
}

export default function InstagramLayout() {
  return (
    <InboxProvider>
      <InstagramShell />
    </InboxProvider>
  );
}
