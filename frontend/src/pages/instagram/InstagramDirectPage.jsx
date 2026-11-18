import React, { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import ChannelChat from "@/components/inbox/ChannelChat";
import IgAvatar from "@/components/instagram/IgAvatar";
import { IG, igShortTime } from "@/components/instagram/igTheme";
import { IgBack, IgMessenger, IgSearch } from "@/components/instagram/igIcons";
import { cn } from "@/lib/utils";
import { useInstagramData } from "./useInstagramData";

const folderOf = (row) => {
  const folder = row.folder || "primary";
  return folder === "requests" || folder === "general" ? folder : "primary";
};

function ThreadRow({ row, active, lang, onOpen }) {
  const unread = row.unread > 0 || row.markedUnread;
  const when = igShortTime(row.lastAt, lang);
  return (
    <button type="button" onClick={onOpen} aria-pressed={active} aria-label={row.customer}
      className={cn("flex w-full items-center gap-3 px-6 py-2 text-start transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[#0095f6]", active ? "bg-[#efefef]" : "hover:bg-[#f2f2f2]")}>
      <IgAvatar src={row.avatarUrl} size={56} ring={row.hasStory} />
      <span className="min-w-0 flex-1">
        <span dir="auto" className={cn("block truncate text-[14px] leading-[18px]", unread ? "font-semibold" : "font-normal")}>{row.customer}</span>
        <span className={cn("mt-0.5 flex min-w-0 items-center gap-1 text-[12px] leading-4", unread ? "font-semibold text-black" : "text-[#737373]")}>
          <span dir="auto" className="truncate">{row.preview}</span>
          {when && <><span aria-hidden="true">·</span><span className="shrink-0">{when}</span></>}
        </span>
      </span>
      {unread && <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: IG.blue }} aria-label={lang === "ar" ? "غير مقروءة" : "Unread"} />}
    </button>
  );
}

function EmptyThread({ lang }) {
  const isArabic = lang === "ar";
  return (
    <div className="grid h-full place-items-center p-8 text-center">
      <div>
        <span className="mx-auto grid h-24 w-24 place-items-center rounded-full border-2 border-black"><IgMessenger size={48} /></span>
        <h2 className="mt-4 text-[20px] font-normal">{isArabic ? "رسائلك" : "Your messages"}</h2>
        <p className="mt-1 text-[14px]" style={{ color: IG.secondary }}>{isArabic ? "اختر محادثة للرد على عملائك." : "Choose a chat to reply to your customers."}</p>
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
  const showingRequests = folder === "requests";
  const requestCount = threads.filter((row) => folderOf(row) === "requests" && !row.archivedAt).length;

  const rows = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    return threads
      .filter((row) => !row.archivedAt && folderOf(row) === folder)
      .filter((row) => !needle || `${row.customer} ${row.handle}`.toLocaleLowerCase().includes(needle))
      .sort((a, b) => new Date(b.lastAt || 0) - new Date(a.lastAt || 0));
  }, [threads, query, folder]);

  const openThread = (row) => selectConversation(row);

  return (
    <div className="flex h-full min-h-0">
      <section aria-label={isArabic ? "المحادثات" : "Chats"} className={cn("flex min-h-0 w-full shrink-0 flex-col border-e md:w-[397px]", threadId && "hidden md:flex")} style={{ borderColor: IG.border }}>
        {showingRequests ? (
          <header className="flex h-[75px] shrink-0 items-center gap-4 px-6">
            <Link to="/instagram/direct/inbox" aria-label={isArabic ? "رجوع" : "Back"} className="rounded-full p-1 hover:bg-[#f2f2f2]"><IgBack className={isArabic ? "-scale-x-100" : undefined} /></Link>
            <h1 className="text-[16px] font-bold">{isArabic ? "طلبات المراسلة" : "Message requests"}</h1>
          </header>
        ) : (
          <header className="shrink-0 px-6 pb-3 pt-9">
            <h1 className="text-[20px] font-bold"><span dir="ltr" className="block truncate">{username || "Instagram"}</span></h1>
          </header>
        )}
        <div className="shrink-0 px-6 pb-3">
          <label className="flex h-9 items-center gap-2 rounded-lg px-3" style={{ background: IG.button }}>
            <IgSearch size={16} className="text-[#737373]" />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={isArabic ? "بحث" : "Search"} aria-label={isArabic ? "بحث في المحادثات" : "Search chats"} className="h-full min-w-0 flex-1 bg-transparent text-[14px] outline-none placeholder:text-[#737373]" />
          </label>
        </div>
        {showingRequests ? (
          <p className="shrink-0 px-6 pb-3 text-[12px] leading-4" style={{ color: IG.secondary }}>
            {isArabic ? "افتح المحادثة لتعرف من يراسلك. ردّك يقبل الطلب وينقله إلى رسائلك." : "Open a chat to see who's messaging you. Replying accepts the request and moves it to your messages."}
          </p>
        ) : (
          <nav aria-label={isArabic ? "مجلدات الرسائل" : "Message folders"} className="flex shrink-0 border-b px-6" style={{ borderColor: IG.border }}>
            {[["primary", "/instagram/direct/inbox", isArabic ? "الأساسية" : "Primary"], ["general", "/instagram/direct/general", isArabic ? "العامة" : "General"], ["requests", "/instagram/direct/requests", isArabic ? "الطلبات" : "Requests"]].map(([id, to, name]) => (
              <Link key={id} to={to} aria-current={folder === id ? "page" : undefined}
                className={cn("-mb-px flex h-11 flex-1 items-center justify-center border-b text-[14px] font-semibold", folder === id ? "border-black text-black" : "border-transparent text-[#737373] hover:text-black")}>
                {name}{id === "requests" && requestCount ? ` (${requestCount})` : ""}
              </Link>
            ))}
          </nav>
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
              {query ? (isArabic ? "لا توجد نتائج." : "No results.") : showingRequests ? (isArabic ? "لا توجد طلبات مراسلة." : "No message requests.") : folder === "general" ? (isArabic ? "لا توجد رسائل في العامة." : "No messages in General.") : (isArabic ? "لا توجد رسائل بعد." : "No messages yet.")}
            </p>
          )}
          {rows.map((row) => <ThreadRow key={row.id} row={row} lang={lang} active={row.id === threadId} onOpen={() => openThread(row)} />)}
          {inboxCursor && (
            <button type="button" onClick={() => loadMoreConversations()} disabled={loadingMoreInbox} className="mx-6 my-3 text-[14px] font-semibold disabled:opacity-50" style={{ color: IG.blue }}>
              {loadingMoreInbox ? t("common.loading") : (isArabic ? "عرض المزيد" : "Show more")}
            </button>
          )}
        </div>
      </section>
      <div className={cn("min-h-0 min-w-0 flex-1 flex-col", threadId ? "flex" : "hidden md:flex")}>
        {threadId && open && current?.id === open.id
          ? <InstagramThread data={data} onBack={() => navigate(folder === "requests" ? "/instagram/direct/requests" : folder === "general" ? "/instagram/direct/general" : "/instagram/direct/inbox")} />
          : threadId && !loadingInbox && !open
            ? <p role="alert" className="m-auto p-8 text-center text-[14px]" style={{ color: IG.secondary }}>{isArabic ? "هذه المحادثة غير موجودة." : "This chat isn't available."} <Link className="font-semibold" style={{ color: IG.blue }} to="/instagram/direct/inbox">{isArabic ? "رجوع للرسائل" : "Back to messages"}</Link></p>
            : <EmptyThread lang={lang} />}
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
