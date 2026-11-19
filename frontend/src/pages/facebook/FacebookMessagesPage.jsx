import React, { useEffect } from "react";
import { useNavigate, useParams } from "react-router-dom";
import ChannelChat from "@/components/inbox/ChannelChat";
import FbAvatar from "@/components/facebook/FbAvatar";
import { FB } from "@/components/facebook/fbTheme";
import { fbAge } from "@/lib/facebookApi";
import { cn } from "@/lib/utils";
import { useFacebookData } from "./useFacebookData";

/** /facebook/messages and /facebook/messages/:threadId — the Page's Messenger inbox, with the same chat the inbox uses. */
export default function FacebookMessagesPage() {
  const data = useFacebookData();
  const { threadId } = useParams();
  const navigate = useNavigate();
  const { lang, t, threads, current, loadingInbox, inboxLoadError, inboxCursor, loadingMoreInbox, loadMoreConversations, selectConversation, setInboxRetryAttempt } = data;
  const { channel, pendingApproval, loadingMessages, loadingOlderMessages, messageCursor, loadOlderMessages, messagesError, activeChannel, setMessageRetryAttempt, sending, pendingDecision, handleSend, handleReact, changeListState, decideApproval } = data;
  const ar = lang === "ar";
  const open = threadId ? threads.find((row) => row.id === threadId) || null : null;

  // The address decides which chat is open, so back, refresh and a shared link all land in the same place.
  useEffect(() => {
    if (open && current?.id !== open.id) selectConversation(open);
  }, [open, current?.id, selectConversation]);

  return (
    <div className="flex h-full min-h-0 bg-white" data-testid="facebook-messages">
      <section aria-label={ar ? "المحادثات" : "Chats"} className={cn("flex min-h-0 w-full shrink-0 flex-col border-e md:w-[360px]", threadId && "hidden md:flex")} style={{ borderColor: FB.divider }}>
        <h1 className="px-4 pb-2 pt-4 text-[24px] font-bold">{ar ? "المحادثات" : "Chats"}</h1>
        <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
          {inboxLoadError && (
            <div role="alert" className="p-4 text-[14px]" style={{ color: FB.red }}>
              {inboxLoadError}
              <button type="button" onClick={() => setInboxRetryAttempt((n) => n + 1)} className="ms-2 font-semibold text-[#0866ff] hover:underline">{ar ? "إعادة المحاولة" : "Retry"}</button>
            </div>
          )}
          {loadingInbox && threads.length === 0 && <p role="status" className="p-4 text-[14px]" style={{ color: FB.text2 }}>{ar ? "جارٍ التحميل..." : "Loading..."}</p>}
          {!loadingInbox && !inboxLoadError && threads.length === 0 && <p className="p-8 text-center text-[15px]" style={{ color: FB.text2 }}>{ar ? "لا توجد محادثات بعد." : "No chats yet."}</p>}
          {threads.map((row) => {
            const unread = row.unread > 0 || row.markedUnread;
            const active = row.id === threadId;
            return (
              <button key={row.id} type="button" aria-pressed={active} onClick={() => navigate(`/facebook/messages/${encodeURIComponent(row.id)}`)} className={cn("flex w-full items-center gap-3 rounded-lg p-2 text-start focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0866ff]", active ? "bg-[#e7f3ff]" : "hover:bg-[#f2f2f2]")}>
                <FbAvatar src={row.avatarUrl} name={row.customer} size="h-14 w-14" />
                <span className="min-w-0 flex-1">
                  <span dir="auto" className={cn("block truncate text-[15px]", unread ? "font-bold" : "font-medium")}>{row.customer}</span>
                  <span className={cn("flex min-w-0 items-center gap-1 text-[13px]", unread ? "font-semibold text-[#050505]" : "text-[#65676b]")}>
                    <span dir="auto" className="truncate">{row.preview}</span>
                    {row.lastAt && <><span aria-hidden="true">·</span><span className="shrink-0">{fbAge(row.lastAt, lang)}</span></>}
                  </span>
                </span>
                {unread && <span className="h-3 w-3 shrink-0 rounded-full" style={{ background: FB.blue }} aria-label={ar ? "غير مقروءة" : "Unread"} />}
              </button>
            );
          })}
          {inboxCursor && (
            <button type="button" disabled={loadingMoreInbox} onClick={loadMoreConversations} className="mt-1 w-full rounded-lg py-2 text-[14px] font-semibold text-[#0866ff] hover:bg-[#f2f2f2] disabled:opacity-60">{loadingMoreInbox ? (ar ? "جارٍ التحميل..." : "Loading...") : (ar ? "عرض المزيد" : "Show more")}</button>
          )}
        </div>
      </section>
      <section className={cn("min-h-0 min-w-0 flex-1", !threadId && "hidden md:block")}>
        {open && current?.id === open.id ? (
          <ChannelChat
            channel={channel}
            lang={lang}
            className="h-full"
            onBack={() => navigate("/facebook/messages")}
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
          />
        ) : (
          <div className="grid h-full place-items-center p-8 text-center text-[15px]" style={{ color: FB.text2 }}>{threadId && loadingInbox ? (ar ? "جارٍ التحميل..." : "Loading...") : (ar ? "اختر محادثة لعرضها" : "Select a chat")}</div>
        )}
      </section>
    </div>
  );
}
