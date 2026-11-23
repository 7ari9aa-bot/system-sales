import React, { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import ChannelChat from "@/components/inbox/ChannelChat";
import IgAvatar from "@/components/instagram/IgAvatar";
import { IG, igShortTime } from "@/components/instagram/igTheme";
import { IgArchive, IgBack, IgMessenger, IgMore, IgMuted, IgPin, IgSearch } from "@/components/instagram/igIcons";
import { cn } from "@/lib/utils";
import { useInstagramData } from "./useInstagramData";

const folderOf = (row) => {
  const folder = row.folder || "primary";
  return folder === "requests" || folder === "general" ? folder : "primary";
};

function ThreadRow({ row, active, lang, onOpen, onChange }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const isArabic = lang === "ar";
  const unread = row.unread > 0 || row.markedUnread;
  const when = igShortTime(row.lastAt, lang);
  const mutedNow = Boolean(row.mutedUntil) && new Date(row.mutedUntil) > new Date();
  const act = (body) => { setMenuOpen(false); onChange(row, body); };
  const item = "block w-full px-4 py-3 text-start text-[14px] hover:bg-[#f3f5f7]";
  return (
    <div className={cn("group relative mx-2 flex items-center rounded-[12px]", active ? "bg-[#f3f5f7]" : "hover:bg-[#f3f5f7]")}>
      <button type="button" onClick={onOpen} aria-pressed={active} aria-label={row.customer}
        className="flex min-w-0 flex-1 items-center gap-3 rounded-[12px] px-4 py-2 text-start focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[#0095f6]">
        <IgAvatar src={row.avatarUrl} size={56} ring={row.hasStory} />
        <span className="min-w-0 flex-1">
          <span dir="auto" className={cn("block truncate text-[14px] leading-[18px]", unread ? "font-semibold" : "font-normal")}>{row.customer}</span>
          <span className={cn("mt-0.5 flex min-w-0 items-center gap-1 text-[12px] leading-4", unread ? "font-semibold text-[#0c1014]" : "text-[#6a717a]")}>
            <span dir="auto" className="truncate">{row.preview}</span>
            {when && <><span aria-hidden="true">·</span><span className="shrink-0">{when}</span></>}
          </span>
        </span>
        {row.pinnedAt && <span aria-label={isArabic ? "مثبّتة" : "Pinned"} style={{ color: IG.secondary }}><IgPin size={16} /></span>}
        {mutedNow && <span aria-label={isArabic ? "مكتومة" : "Muted"} style={{ color: IG.secondary }}><IgMuted size={16} /></span>}
        {unread && <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: IG.blue }} aria-label={isArabic ? "غير مقروءة" : "Unread"} />}
      </button>
      <button type="button" aria-label={isArabic ? "المزيد" : "More"} aria-expanded={menuOpen} data-testid="ig-row-more" onClick={() => setMenuOpen((v) => !v)}
        className={cn("me-3 shrink-0 rounded-full p-1.5 hover:bg-[#dbdfe4] focus-visible:opacity-100 group-hover:opacity-100", menuOpen ? "opacity-100" : "opacity-0")}><IgMore size={20} /></button>
      {menuOpen && (
        <>
          <button type="button" aria-label={isArabic ? "إغلاق" : "Close"} className="fixed inset-0 z-10 cursor-default" onClick={() => setMenuOpen(false)} />
          <div role="menu" data-testid="ig-row-menu" className="absolute end-3 top-12 z-20 w-56 overflow-hidden rounded-xl bg-white py-1 shadow-[0_4px_12px_rgba(0,0,0,.15)]">
            <button role="menuitem" type="button" className={item} data-testid="ig-row-pin" onClick={() => act({ pinned: !row.pinnedAt })}>{row.pinnedAt ? (isArabic ? "إلغاء التثبيت" : "Unpin") : (isArabic ? "تثبيت" : "Pin")}</button>
            <button role="menuitem" type="button" className={item} data-testid="ig-row-mute" onClick={() => act({ mute: mutedNow ? "off" : "always" })}>{mutedNow ? (isArabic ? "إلغاء الكتم" : "Unmute") : (isArabic ? "كتم" : "Mute")}</button>
            <button role="menuitem" type="button" className={item} data-testid="ig-row-unread" onClick={() => act({ marked_unread: !row.markedUnread })}>{row.markedUnread ? (isArabic ? "تعليم كمقروءة" : "Mark as read") : (isArabic ? "تعليم كغير مقروءة" : "Mark as unread")}</button>
            <button role="menuitem" type="button" className={item} data-testid="ig-row-archive" onClick={() => act({ archived: !row.archivedAt })}>{row.archivedAt ? (isArabic ? "إلغاء الأرشفة" : "Unarchive") : (isArabic ? "أرشفة" : "Archive")}</button>
          </div>
        </>
      )}
    </div>
  );
}

function EmptyThread({ lang, requests }) {
  const isArabic = lang === "ar";
  return (
    <div className="grid h-full place-items-center p-8 text-center">
      <div>
        <span className="mx-auto grid h-24 w-24 place-items-center rounded-full border-2 border-[#0c1014]"><IgMessenger size={48} /></span>
        <h2 className="mt-4 text-[20px] font-normal">{requests ? (isArabic ? "طلبات المراسلة" : "Message requests") : (isArabic ? "رسائلك" : "Your messages")}</h2>
        <p className="mt-1 text-[14px]" style={{ color: IG.secondary }}>{requests ? (isArabic ? "افتح طلبًا لترى من يراسلك. ردّك يقبل الطلب وينقله إلى رسائلك." : "Open a request to see who is messaging you. Replying accepts it and moves it to your messages.") : (isArabic ? "أرسل رسالة لبدء محادثة." : "Send a message to start a chat.")}</p>
      </div>
    </div>
  );
}

/** /instagram/direct/inbox, /instagram/direct/requests and /instagram/direct/t/:threadId */
export default function InstagramDirectPage({ folder: routeFolder = "primary" }) {
  const data = useInstagramData();
  const { lang, t, username, threads, current, loadingInbox, inboxLoadError, inboxCursor, loadingMoreInbox, loadMoreConversations, selectConversation, setInboxRetryAttempt } = data;
  const { threadId } = useParams();
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const isArabic = lang === "ar";
  const open = threadId ? threads.find((row) => row.id === threadId) || null : null;
  const folder = open ? folderOf(open) : routeFolder;
  const archivedOpen = Boolean(open?.archivedAt);
  const showingRequests = folder === "requests";
  const requestCount = threads.filter((row) => folderOf(row) === "requests" && !row.archivedAt).length;

  const archivedCount = threads.filter((row) => row.archivedAt).length;
  const showingArchive = routeFolder === "archived" || archivedOpen;
  const rows = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    return threads
      .filter((row) => (showingArchive ? Boolean(row.archivedAt) : !row.archivedAt && folderOf(row) === folder))
      .filter((row) => !needle || `${row.customer} ${row.handle}`.toLocaleLowerCase().includes(needle))
      .sort((a, b) => (Boolean(b.pinnedAt) - Boolean(a.pinnedAt)) || (new Date(b.lastAt || 0) - new Date(a.lastAt || 0)));
  }, [threads, query, folder, showingArchive]);

  const openThread = (row) => selectConversation(row);

  return (
    <div className="flex h-full min-h-0">
      <section aria-label={isArabic ? "المحادثات" : "Chats"} className={cn("flex min-h-0 w-full shrink-0 flex-col border-e md:w-[393px]", threadId && "hidden md:flex")} style={{ borderColor: IG.border }}>
        {showingRequests || showingArchive ? (
          <header className="flex h-[75px] shrink-0 items-center gap-4 px-6">
            <Link to="/instagram/direct/inbox" aria-label={isArabic ? "رجوع" : "Back"} className="rounded-full p-1 hover:bg-[#f3f5f7]"><IgBack className={isArabic ? "-scale-x-100" : undefined} /></Link>
            <h1 className="text-[20px] font-bold">{showingArchive ? (isArabic ? "المحادثات المؤرشفة" : "Archived chats") : (isArabic ? "طلبات المراسلة" : "Message requests")}</h1>
          </header>
        ) : (
          <header className="shrink-0 px-6 pb-3 pt-9">
            <h1 className="text-[20px] font-bold"><span dir="ltr" className="block truncate">{username || "Instagram"}</span></h1>
          </header>
        )}
        {showingArchive ? null : showingRequests ? (
          <p className="shrink-0 px-6 pb-3 text-[12px] leading-4" style={{ color: IG.secondary }}>
            {isArabic ? "هذه الرسائل من أشخاص قمت بتقييدهم أو لا تتابعهم. لن يعرفوا أنك شاهدت طلبهم حتى تسمح لهم بمراسلتك." : "These messages are from people you've restricted or don't follow. They won't know you viewed their request until you allow them to message you."}
          </p>
        ) : (
          <nav aria-label={isArabic ? "مجلدات الرسائل" : "Message folders"} className="flex shrink-0 border-b px-6" style={{ borderColor: IG.border }}>
            {[["primary", "/instagram/direct/inbox", isArabic ? "الأساسية" : "Primary"], ["general", "/instagram/direct/general", isArabic ? "العامة" : "General"], ["requests", "/instagram/direct/requests", isArabic ? "الطلبات" : "Requests"]].map(([id, to, name]) => (
              <Link key={id} to={to} aria-current={folder === id ? "page" : undefined}
                className={cn("-mb-px flex h-11 flex-1 items-center justify-center border-b text-[14px] font-semibold", folder === id ? "border-[#0c1014] text-[#0c1014]" : "border-transparent text-[#6a717a] hover:text-[#0c1014]")}>
                {name}{id === "requests" && requestCount ? ` (${requestCount})` : ""}
              </Link>
            ))}
          </nav>
        )}
        <div className="shrink-0 px-6 pb-3">
          <label className="flex h-10 items-center gap-2 rounded-full px-4" style={{ background: IG.hover }}>
            <IgSearch size={16} className="text-[#6a717a]" />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={isArabic ? "بحث" : "Search"} aria-label={isArabic ? "بحث في المحادثات" : "Search chats"} className="h-full min-w-0 flex-1 bg-transparent text-[14px] outline-none placeholder:text-[#6a717a]" />
          </label>
        </div>
        {!showingArchive && !showingRequests && archivedCount > 0 && (
          <Link to="/instagram/direct/archived" data-testid="ig-archive-link" className="flex shrink-0 items-center gap-3 px-6 py-3 text-[14px] font-semibold hover:bg-[#f3f5f7]">
            <IgArchive size={20} /><span className="flex-1">{isArabic ? "المحادثات المؤرشفة" : "Archived chats"}</span><span style={{ color: IG.secondary }}>{archivedCount}</span>
          </Link>
        )}
        <div className="min-h-0 flex-1 overflow-y-auto pb-4">
          {loadingInbox && rows.length === 0 && <p role="status" className="px-6 py-4 text-[14px]" style={{ color: IG.secondary }}>{t("common.loading")}</p>}
          {inboxLoadError && (
            <div role="alert" className="mx-6 my-2 text-[13px]" style={{ color: IG.error }}>
              {inboxLoadError} <button type="button" className="font-semibold underline" onClick={() => setInboxRetryAttempt((n) => n + 1)}>{t("common.retry", "Retry")}</button>
            </div>
          )}
          {!loadingInbox && !inboxLoadError && rows.length === 0 && (
            <p className="px-6 py-10 text-center text-[14px]" style={{ color: IG.secondary }}>
              {query ? (isArabic ? "لا توجد نتائج." : "No results.") : showingArchive ? (isArabic ? "لا توجد محادثات مؤرشفة." : "No archived chats.") : showingRequests ? (isArabic ? "لا توجد طلبات مراسلة." : "No message requests.") : folder === "general" ? (isArabic ? "لا توجد رسائل في العامة." : "No messages in General.") : (isArabic ? "لا توجد رسائل بعد." : "No messages yet.")}
            </p>
          )}
          {rows.map((row) => <ThreadRow key={row.id} row={row} lang={lang} active={row.id === threadId} onOpen={() => openThread(row)} onChange={data.changeListState} />)}
          {inboxCursor && (
            <button type="button" onClick={() => loadMoreConversations()} disabled={loadingMoreInbox} className="mx-6 my-3 text-[14px] font-semibold disabled:opacity-50" style={{ color: IG.blue }}>
              {loadingMoreInbox ? t("common.loading") : (isArabic ? "عرض المزيد" : "Show more")}
            </button>
          )}
        </div>
      </section>
      <div className={cn("min-h-0 min-w-0 flex-1 flex-col", threadId ? "flex" : "hidden md:flex")}>
        {threadId && open && current?.id === open.id
          ? <InstagramThread data={data} onBack={() => navigate(showingArchive ? "/instagram/direct/archived" : folder === "requests" ? "/instagram/direct/requests" : folder === "general" ? "/instagram/direct/general" : "/instagram/direct/inbox")} />
          : threadId && !loadingInbox && !open
            ? <p role="alert" className="m-auto p-8 text-center text-[14px]" style={{ color: IG.secondary }}>{isArabic ? "هذه المحادثة غير موجودة." : "This chat isn't available."} <Link className="font-semibold" style={{ color: IG.blue }} to="/instagram/direct/inbox">{isArabic ? "رجوع للرسائل" : "Back to messages"}</Link></p>
            : <EmptyThread lang={lang} requests={showingRequests} />}
      </div>
    </div>
  );
}

function InstagramThread({ data, onBack }) {
  const navigate = useNavigate();
  const { channel, lang, t, current, pendingApproval, loadingMessages, loadingOlderMessages, messageCursor, loadOlderMessages, messagesError, activeChannel, setMessageRetryAttempt, sending, pendingDecision, handleSend, handleReact, changeListState, decideApproval } = data;
  return (
    <ChannelChat
      channel={channel}
      lang={lang}
      className="h-full"
      onBack={onBack}
      conversation={current}
      approval={pendingApproval}
      loadingMessages={loadingMessages}
      loadingOlderMessages={loadingOlderMessages}
      hasOlderMessages={Boolean(messageCursor)}
      onLoadOlderMessages={loadOlderMessages}
      messagesError={messagesError?.conversationId === current?.id && messagesError?.channelId === activeChannel ? messagesError.message : ""}
      onRetryMessages={() => setMessageRetryAttempt((attempt) => attempt + 1)}
      sending={sending}
      pendingDecision={pendingDecision}
      error={null}
      t={t}
      onSend={handleSend}
      onReact={handleReact}
      onListStateChange={changeListState}
      onApprove={() => decideApproval(pendingApproval, "APPROVED")}
      onDecline={() => decideApproval(pendingApproval, "REJECTED")}
      onViewProfile={current?.customerId ? () => navigate(`/instagram/u/${encodeURIComponent(current.customerId)}`) : undefined}
    />
  );
}
