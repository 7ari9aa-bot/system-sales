import React, { useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { InboxProvider, useInbox } from "@/pages/inbox/InboxProvider";
import ChannelSwitcher from "@/components/inbox/ChannelSwitcher";
import FacebookNewPostDialog from "@/components/facebook/FacebookNewPostDialog";
import { FB } from "@/components/facebook/fbTheme";
import { FbBell, FbChannels, FbChart, FbHome, FbLogo, FbMessenger, FbPlus, FbReels } from "@/components/facebook/fbIcons";
import { cn } from "@/lib/utils";
import { useFacebookData } from "./useFacebookData";

function Badge({ count }) {
  if (!count) return null;
  return (
    <span className="absolute -end-2 -top-1.5 grid h-[18px] min-w-[18px] place-items-center rounded-full px-1 text-[11px] font-bold leading-none text-white" style={{ background: FB.red }}>
      {count > 99 ? "99+" : count}
    </span>
  );
}

/** Facebook's top bar, limited to what the Pages API lets a Page do. */
function TopBar({ onCreate }) {
  const { lang, unreadMessages, unanswered, pageName, pageAvatar, canAct } = useFacebookData();
  const { pathname } = useLocation();
  const { setActiveChannel } = useInbox();
  const ar = lang === "ar";
  const tab = (active) => cn(
    "relative grid h-12 min-w-0 flex-1 place-items-center sm:min-w-[56px] rounded-lg transition-colors hover:bg-[#f2f2f2] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0866ff] sm:max-w-[110px]",
    active ? "text-[#0866ff] hover:bg-transparent" : "text-[#65676b]",
  );
  const underline = (active) => active && <span className="absolute inset-x-1 bottom-[-4px] h-[3px] rounded-t-full" style={{ background: FB.blue }} />;
  const onPosts = pathname === "/facebook" || pathname.startsWith("/facebook/posts");
  const onActivity = pathname.startsWith("/facebook/activity");
  const onReels = pathname.startsWith("/facebook/reels");
  const onInsights = pathname.startsWith("/facebook/insights");
  return (
    <header className="z-20 flex shrink-0 flex-wrap items-center gap-x-2 border-b bg-white px-3 shadow-[0_1px_2px_rgba(0,0,0,0.1)] sm:h-14 sm:flex-nowrap" style={{ borderColor: FB.divider }}>
      <NavLink to="/facebook/posts" aria-label={ar ? "الصفحة الرئيسية" : "Home"} className="my-2 shrink-0 rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0866ff] sm:my-0"><FbLogo size={40} /></NavLink>
      <nav aria-label={ar ? "تنقل فيسبوك" : "Facebook navigation"} className="order-last flex h-12 w-full min-w-0 items-center justify-between gap-0 border-t sm:order-none sm:mx-auto sm:h-full sm:w-auto sm:flex-none sm:justify-center sm:gap-2 sm:border-t-0" style={{ borderColor: FB.divider }}>
        <NavLink to="/facebook/posts" className={() => tab(onPosts)} aria-label={ar ? "المنشورات" : "Posts"} title={ar ? "المنشورات" : "Posts"}>
          <FbHome filled={onPosts} size={26} />{underline(onPosts)}
        </NavLink>
        <NavLink to="/facebook/reels" className={() => tab(onReels)} aria-label={ar ? "الريلز والستوري" : "Reels and Stories"} title={ar ? "الريلز والستوري" : "Reels and Stories"}>
          <FbReels filled={onReels} size={26} />{underline(onReels)}
        </NavLink>
        <NavLink to="/facebook/activity" className={() => tab(onActivity)} aria-label={ar ? "الإشعارات" : "Notifications"} title={ar ? "الإشعارات" : "Notifications"}>
          <span className="relative"><FbBell filled={onActivity} size={26} /><Badge count={unanswered} /></span>{underline(onActivity)}
        </NavLink>
        <NavLink to="/facebook/insights" className={() => tab(onInsights)} aria-label={ar ? "الإحصاءات" : "Insights"} title={ar ? "الإحصاءات" : "Insights"}>
          <FbChart filled={onInsights} size={26} />{underline(onInsights)}
        </NavLink>
      </nav>
      <div className="ms-auto flex shrink-0 items-center gap-2">
        {onCreate && (
          <button type="button" onClick={onCreate} aria-label={ar ? "إنشاء منشور" : "Create post"} title={ar ? "إنشاء منشور" : "Create post"} className="grid h-10 w-10 place-items-center rounded-full bg-[#e4e6eb] text-[#050505] transition-colors hover:bg-[#d8dadf] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0866ff]">
            <FbPlus size={20} />
          </button>
        )}
        <NavLink to="/inbox" aria-label={ar ? "كل القنوات" : "All channels"} title={ar ? "كل القنوات" : "All channels"} className="grid h-10 w-10 place-items-center rounded-full bg-[#e4e6eb] text-[#050505] transition-colors hover:bg-[#d8dadf] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0866ff]">
          <FbChannels size={20} />
        </NavLink>
        <button type="button" data-testid="fb-messenger-link" onClick={() => setActiveChannel("messenger")} aria-label="Messenger" title={ar ? "افتح قناة ماسنجر" : "Open the Messenger channel"} className="relative grid h-10 w-10 place-items-center rounded-full bg-[#e4e6eb] text-[#050505] transition-colors hover:bg-[#d8dadf] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0866ff]">
          <FbMessenger size={20} /><Badge count={unreadMessages} />
        </button>
        <span className="grid h-10 w-10 shrink-0 place-items-center overflow-hidden rounded-full bg-[#e7f3ff] text-[15px] font-bold text-[#0866ff]" title={pageName} aria-label={pageName}>
          {pageAvatar ? <img src={pageAvatar} alt="" className="h-full w-full object-cover" /> : (pageName || "F").slice(0, 1)}
        </span>
      </div>
      {!canAct && <span className="sr-only">demo</span>}
    </header>
  );
}

function FacebookShell() {
  const { lang, canAct, live, pageError } = useFacebookData();
  const { channels, unreadByChannel, setActiveChannel, activeChannel, t } = useInbox();
  const [creating, setCreating] = useState(false);
  const ar = lang === "ar";
  return (
    <div dir="ltr" className="grid h-full min-h-0 grid-cols-[minmax(0,1fr)_52px] overflow-hidden">
      <div dir={ar ? "rtl" : "ltr"} data-testid="facebook-app" className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden" style={{ background: FB.bg, color: FB.text, fontFamily: FB.font }}>
        <TopBar onCreate={canAct ? () => setCreating(true) : null} />
        {(pageError || live.error) && <div role="alert" className="border-b bg-white px-4 py-2 text-[13px]" style={{ borderColor: FB.divider, color: FB.red }}>{pageError || live.error}</div>}
        <main className="min-h-0 min-w-0 flex-1 overflow-hidden"><Outlet /></main>
      </div>
      {/* Same channel strip as the inbox, pinned to the physical right edge whatever the language direction. */}
      <aside className="z-10 flex min-h-0 min-w-0 flex-col items-center border-l border-border/80 bg-card" aria-label={t("inbox.title")}>
        <ChannelSwitcher channels={channels} active={activeChannel} unreadByChannel={unreadByChannel} onSelect={setActiveChannel} />
      </aside>
      {creating && canAct && <FacebookNewPostDialog lang={lang} onPublish={live.publish} onClose={() => setCreating(false)} />}
    </div>
  );
}

export default function FacebookLayout() {
  return (
    <InboxProvider>
      <FacebookShell />
    </InboxProvider>
  );
}
