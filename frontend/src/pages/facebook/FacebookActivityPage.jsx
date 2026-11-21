import React, { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import FbAvatar from "@/components/facebook/FbAvatar";
import { FB } from "@/components/facebook/fbTheme";
import { cn } from "@/lib/utils";
import { needsAnswer, useFacebookData } from "./useFacebookData";
import { groupNotifications, headerMenuItems, loadReadMark, saveReadMark } from "./notificationGroups";

/** The small round badge Facebook puts on a notification's avatar: here, a comment bubble. */
function CommentBadge() {
  return (
    <span className="absolute -bottom-1 -end-1 flex h-6 w-6 items-center justify-center rounded-full border-2 border-white" style={{ background: FB.blue }} aria-hidden="true">
      <svg width="12" height="12" viewBox="0 0 24 24" fill="#fff"><path d="M12 3C6.5 3 2 6.6 2 11c0 2.3 1.2 4.4 3.2 5.8L4.500 21l4.300-2c1 .2 2.100.3 3.200.3 5.500 0 10-3.600 10-8S17.500 3 12 3z" /></svg>
    </span>
  );
}

/** /facebook/activity — Notifications, built from what the API gives: comments on the Page's posts. */
export default function FacebookActivityPage() {
  const { lang, posts, postsLoading, postsError } = useFacebookData();
  const ar = lang === "ar";
  const [onlyUnread, setOnlyUnread] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const navigate = useNavigate();
  const store = typeof window === "undefined" ? null : window.localStorage;
  const [readUpTo, setReadUpTo] = useState(() => loadReadMark(store, "page"));
  const items = useMemo(() => {
    const out = [];
    for (const post of posts) {
      const walk = (list) => list.forEach((c) => { if (!c.isPage) out.push({ comment: c, post, waiting: needsAnswer(c) }); walk(c.replies || []); });
      walk(post.comments || []);
    }
    return out;
  }, [posts]);
  const { fresh, earlier, hiddenCount } = useMemo(() => groupNotifications(items, { onlyUnread, showAll, readUpTo }), [items, onlyUnread, showAll, readUpTo]);
  const empty = fresh.length === 0 && earlier.length === 0;

  const row = ({ comment, post, waiting }) => (
    <li key={comment.id}>
      <Link to={`/facebook/posts/${encodeURIComponent(post.id)}`} className="flex items-center gap-3 rounded-lg p-2 hover:bg-[#f2f2f2]">
        <span className="relative shrink-0"><FbAvatar src="" name={comment.author} size="h-14 w-14" /><CommentBadge /></span>
        <span className="min-w-0 flex-1 text-[15px] leading-5" style={{ color: waiting ? FB.text : FB.text2 }}>
          <span dir="auto"><b>{comment.author}</b> {ar ? "علّق:" : "commented:"} <span dir="auto">{comment.text}</span></span>
          <span className="mt-0.5 block text-[13px]" style={{ color: waiting ? FB.blue : FB.text2 }}>{comment.timeLabel}</span>
        </span>
        {waiting && <span className="h-3 w-3 shrink-0 rounded-full" style={{ background: FB.blue }} role="img" aria-label={ar ? "بانتظار ردك" : "Waiting for your reply"} />}
      </Link>
    </li>
  );
  const tab = (active) => cn("rounded-full px-3 py-1.5 text-[15px] font-semibold", active ? "bg-[#e7f3ff] text-[#0866ff]" : "text-[#050505] hover:bg-[#f2f2f2]");

  return (
    <div className="h-full overflow-y-auto" data-testid="facebook-activity">
      <div className="mx-auto my-4 w-full max-w-[680px] rounded-lg bg-white p-3 shadow-[0_1px_2px_rgba(0,0,0,0.2)]">
        <div className="relative flex items-center justify-between">
          <h1 className="px-1 text-[24px] font-bold">{ar ? "الإشعارات" : "Notifications"}</h1>
          <button type="button" aria-label={ar ? "خيارات" : "Options"} aria-haspopup="menu" aria-expanded={menuOpen} data-testid="fb-notif-menu" onClick={() => setMenuOpen((v) => !v)} className="grid h-9 w-9 place-items-center rounded-full text-[20px] font-bold leading-none hover:bg-[#f2f2f2]" style={{ color: FB.text }}>⋯</button>
          {menuOpen && (
            <ul role="menu" className="absolute end-0 top-10 z-10 min-w-[220px] rounded-lg bg-white p-2 shadow-[0_2px_12px_rgba(0,0,0,0.2)]">
              {headerMenuItems(lang).map((m) => (
                <li key={m.id} role="none">
                  <button type="button" role="menuitem" className="w-full rounded-md px-3 py-2 text-start text-[15px] font-semibold hover:bg-[#f2f2f2]" onClick={() => {
                    setMenuOpen(false);
                    if (m.id === "markAllRead") { const at = Date.now(); saveReadMark(store, "page", at); setReadUpTo(at); } else navigate(m.to);
                  }}>{m.label}</button>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="mb-2 mt-1 flex gap-1" role="tablist">
          <button type="button" role="tab" aria-selected={!onlyUnread} className={tab(!onlyUnread)} onClick={() => setOnlyUnread(false)}>{ar ? "الكل" : "All"}</button>
          <button type="button" role="tab" aria-selected={onlyUnread} className={tab(onlyUnread)} onClick={() => setOnlyUnread(true)}>{ar ? "غير مقروءة" : "Unread"}</button>
        </div>
        {postsError && <p role="alert" className="mb-2 text-[14px]" style={{ color: FB.red }}>{postsError}</p>}
        {postsLoading && empty && <p role="status" style={{ color: FB.text2 }}>{ar ? "جارٍ التحميل..." : "Loading..."}</p>}
        {!postsLoading && !postsError && empty && (
          <p className="p-8 text-center text-[15px]" style={{ color: FB.text2 }}>
            {onlyUnread ? (ar ? "لا توجد إشعارات غير مقروءة." : "No unread notifications.") : (ar ? "عندما يعلّق أحد على منشورات الصفحة ستراه هنا." : "When someone comments on the Page's posts, you'll see it here.")}
          </p>
        )}
        {fresh.length > 0 && (<><h2 className="px-1 pb-1 pt-2 text-[17px] font-semibold">{ar ? "جديدة" : "New"}</h2><ul>{fresh.map(row)}</ul></>)}
        {earlier.length > 0 && (<><h2 className="px-1 pb-1 pt-2 text-[17px] font-semibold">{ar ? "الأقدم" : "Earlier"}</h2><ul>{earlier.map(row)}</ul></>)}
        {hiddenCount > 0 && (
          <button type="button" onClick={() => setShowAll(true)} className="mt-2 w-full rounded-md bg-[#e4e6eb] py-2 text-[15px] font-semibold hover:bg-[#d8dadf]">
            {ar ? "عرض الإشعارات السابقة" : "See previous notifications"}
          </button>
        )}
      </div>
    </div>
  );
}
