import React, { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Search } from "lucide-react";
import ChannelSwitcher from "@/components/inbox/ChannelSwitcher";
import ChannelChat from "@/components/inbox/ChannelChat";
import ConversationAvatar from "@/components/inbox/ConversationAvatar";
import ChatList from "@/components/inbox/whatsapp/ChatList";
import { cn } from "@/lib/utils";
import { CHAT_LIST_MIN_WIDTH, CHAT_LIST_MAX_WIDTH, useInbox } from "./InboxProvider";

/** The classic inbox screen (list + chat + channel rail). Unchanged look. */
export default function InboxWorkspace({ embedded = false }) {
  const {
    FILTERS,
    activeChannel,
    approvalLoadError,
    changeListState,
    channel,
    channelStatus,
    channels,
    chatListWidth,
    connectedCount,
    conversations,
    current,
    decideApproval,
    error,
    filter,
    finishChatListResize,
    handleReact,
    handleResizeKeyDown,
    handleResizePointerDown,
    handleResizePointerMove,
    handleSend,
    inboxCursor,
    inboxLoadError,
    inboxMoreError,
    inboxSplitRef,
    instagramAccountIdentity,
    instagramFolder,
    instagramFolders,
    isFacebook,
    isInstagram,
    isMessenger,
    isResizingChatList,
    isTelegram,
    isWhatsApp,
    lang,
    loadMoreConversations,
    loadOlderMessages,
    loadingInbox,
    loadingMessages,
    loadingMoreInbox,
    loadingOlderMessages,
    messageCursor,
    messagesError,
    messengerThemes,
    mobileChatOpen,
    pendingApproval,
    pendingDecision,
    query,
    reloadApprovals,
    selectConversation,
    sending,
    setActiveChannel,
    setActiveId,
    setApprovalLoadError,
    setFilter,
    setInboxRetryAttempt,
    setInstagramFolder,
    setMessageRetryAttempt,
    setMessengerThemes,
    setMobileChatOpen,
    setQuery,
    setTelegramListScrolling,
    t,
    telegramListScrollTimerRef,
    telegramListScrolling,
    unreadByChannel,
    visibleConversations,
  } = useInbox();
  const navigate = useNavigate();
  // Facebook has its own pages (/facebook/...), built on the Page's real posts and comments. The
  // inbox never draws a second, local-only copy of them: landing here on Facebook goes there.
  useEffect(() => {
    if (isFacebook) navigate("/facebook/posts", { replace: true });
  }, [isFacebook, navigate]);
  if (isFacebook) return null;

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      {!embedded && error && (
        <div role="alert" className="mb-3 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </div>
      )}
      {!embedded && approvalLoadError && (
        <div role="alert" className="mb-3 flex items-center justify-between gap-3 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          <span>{approvalLoadError}</span>
          <button type="button" onClick={() => void reloadApprovals().catch((e) => setApprovalLoadError(e?.message || "Could not load pending approvals."))} className="shrink-0 underline">{t("common.retry", "Retry")}</button>
        </div>
      )}

      <div dir="ltr" className={embedded ? "flex min-h-0 flex-1 flex-col overflow-hidden" : "grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_52px] overflow-hidden"}>
      <div className="flex h-full min-h-0 min-w-0 flex-col">
      <div
        ref={inboxSplitRef}
        dir="ltr"
        style={{ "--inbox-chat-list-width": `${chatListWidth}px` }}
        className={cn(
          "grid min-h-0 flex-1 grid-cols-1",
          isWhatsApp
            ? "grid-rows-[minmax(0,1fr)] lg:grid-cols-[var(--inbox-chat-list-width)_1px_minmax(0,1fr)] lg:gap-0"
            : isTelegram
              ? "gap-0 lg:grid-cols-[var(--inbox-chat-list-width)_5px_minmax(0,1fr)] lg:grid-rows-1 grid-rows-[minmax(180px,30dvh)_minmax(0,1fr)] sm:grid-rows-[minmax(240px,32dvh)_minmax(0,1fr)]"
              : isInstagram
                ? "gap-0 lg:grid-cols-[var(--inbox-chat-list-width)_5px_minmax(0,1fr)] lg:grid-rows-1 grid-rows-[minmax(180px,30dvh)_minmax(0,1fr)] sm:grid-rows-[minmax(240px,32dvh)_minmax(0,1fr)]"
                : isMessenger
                  ? "gap-0 grid-rows-[minmax(0,1fr)] lg:grid-cols-[var(--inbox-chat-list-width)_5px_minmax(0,1fr)] lg:grid-rows-1"
                  : "gap-0 lg:grid-cols-[var(--inbox-chat-list-width)_5px_minmax(0,1fr)] lg:grid-rows-1 grid-rows-[minmax(180px,30dvh)_minmax(0,1fr)] sm:grid-rows-[minmax(240px,32dvh)_minmax(0,1fr)]"
        )}
      >
        <div className={cn(
          "bg-card border flex-col min-h-0 overflow-hidden",
          isWhatsApp ? "rounded-none border-0 bg-[var(--wa-bg-panel)]" : isTelegram ? "rounded-none border-0 border-r border-[#e4e9ec] bg-white" : isInstagram ? "rounded-none border-0 border-r border-[#dbdbdb] bg-white" : isMessenger ? "rounded-none border-0 border-r border-[#e4e6eb] bg-white" : "rounded-2xl border-border",
          (isWhatsApp || isMessenger) && mobileChatOpen ? "hidden lg:flex" : "flex"
        )}>
          {isWhatsApp ? (
            loadingInbox ? (
              <div className="py-10 text-center px-4 text-[13px] text-muted-foreground">{t("common.loading")}</div>
            ) : inboxLoadError ? (
              <div role="alert" className="m-3 rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-center text-[12.5px] text-destructive">
                <p>{inboxLoadError}</p>
                <button type="button" onClick={() => setInboxRetryAttempt((attempt) => attempt + 1)} className="mt-2 font-medium underline">
                  {t("common.retry", "Retry")}
                </button>
              </div>
            ) : (
              <ChatList
                rows={conversations}
                activeId={current?.id}
                lang={lang}
                ConversationAvatar={ConversationAvatar}
                onOpen={(conversation) => { selectConversation(conversation); setMobileChatOpen(true); }}
                onChange={changeListState}
                footer={(loadingMoreInbox || inboxMoreError || inboxCursor) ? (
                  <div className="px-3 py-2 text-center text-[11.5px] text-muted-foreground">
                    {inboxMoreError ? (
                      <button type="button" onClick={() => void loadMoreConversations()} className="text-primary hover:underline">{t("common.retry", "Retry")}</button>
                    ) : loadingMoreInbox ? t("common.loading") : (
                      <button type="button" onClick={() => void loadMoreConversations()} className="text-primary hover:underline">{t("inbox.loadMore", "Load more conversations")}</button>
                    )}
                  </div>
                ) : null}
              />
            )
          ) : (
          <>
          <div className={cn(isTelegram ? "space-y-0 p-2" : isInstagram ? "space-y-3 px-4 pb-3 pt-4" : isMessenger ? "space-y-3 p-4" : "space-y-2.5 p-3", isWhatsApp ? "border-b border-[#d1d7db]" : isTelegram ? "border-b border-[#e4e9ec]" : isInstagram ? "border-b border-[#dbdbdb]" : isMessenger ? "border-b border-[#e4e6eb]" : "border-b border-border")}>
            {isInstagram && <div className="flex items-center justify-between"><h2 className="text-[19px] font-semibold tracking-tight text-[#262626]">{lang === "ar" ? "الرسائل" : "Messages"}</h2>{instagramAccountIdentity && <span dir="ltr" className="text-[12px] font-semibold text-[#8e8e8e]">{instagramAccountIdentity.startsWith("@") ? instagramAccountIdentity : `@${instagramAccountIdentity}`}</span>}</div>}
            {isMessenger && <h2 className="text-[20px] font-bold tracking-[-0.02em] text-[#050505]">{lang === "ar" ? "المحادثات" : "Chats"}</h2>}
            <div className="relative">
              <Search className={cn("absolute top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground", (isWhatsApp || isInstagram || isMessenger) && lang === "ar" ? "right-3" : "left-3")} />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                dir={isWhatsApp || isInstagram || isMessenger ? (lang === "ar" ? "rtl" : "ltr") : undefined}
                aria-label={t("inbox.search")}
                placeholder={t("inbox.search")}
                className={cn(
                  "w-full h-9 text-[13px] placeholder:text-muted-foreground focus:outline-hidden focus:ring-2 focus:ring-ring/30",
                  isTelegram ? "h-9 rounded-full border border-transparent bg-[#f1f1f1]" : "rounded-lg",
                  (isWhatsApp || isInstagram || isMessenger) && lang === "ar" ? "pr-9 pl-3 text-right" : "pl-9 pr-3",
                  isWhatsApp ? "bg-[#f0f2f5] border border-[#f0f2f5]" : isInstagram ? "bg-[#efefef] border border-[#efefef] rounded-lg" : isMessenger ? "bg-[#f0f2f5] border border-[#f0f2f5] rounded-full" : !isTelegram && "bg-surface border border-border"
                )}
              />
            </div>
            {isInstagram ? (
              <div role="tablist" aria-label={lang === "ar" ? "مجلدات الرسائل" : "Message folders"} className="flex items-center justify-between gap-1">
                {instagramFolders.map((folder) => <button key={folder.id} type="button" role="tab" aria-selected={instagramFolder === folder.id} onClick={() => { setInstagramFolder(folder.id); setActiveId(null); }} className={cn("whitespace-nowrap px-2 py-1.5 text-[12px] font-semibold", instagramFolder === folder.id ? "border-b-2 border-[#262626] text-[#262626]" : "border-b-2 border-transparent text-[#8e8e8e] hover:text-[#262626]")}>{folder.label}</button>)}
              </div>
            ) : !isTelegram && <div className={cn("flex gap-1", isWhatsApp && "-mb-3 border-b border-[#d1d7db]")}>
              {FILTERS.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  aria-pressed={filter === item.id}
                  onClick={() => setFilter(item.id)}
                  className={cn(
                    "whitespace-nowrap transition-colors",
                    isWhatsApp
                      ? cn("px-2.5 py-2 text-[12px]", filter === item.id ? "border-b-2 border-[#00a884] font-semibold text-[#008f72]" : "border-b-2 border-transparent text-[#667781] hover:text-[#111b21]")
                      : isMessenger
                        ? cn("rounded-full px-3 py-1.5 text-[12px] font-medium", filter === item.id ? "bg-[#e7f3ff] font-semibold text-[#0866ff]" : "text-[#65676b] hover:bg-[#f0f2f5]")
                      : cn("px-2.5 py-1 rounded-md text-[12px] font-medium", filter === item.id ? "bg-primary text-primary-foreground" : "bg-surface text-muted-foreground hover:text-foreground")
                  )}
                >
                  {item.label}
                </button>
              ))}
            </div>}
          </div>
          <div
            className={cn(
              "flex-1 overflow-y-auto scrollbar-thin",
              (isWhatsApp || isInstagram) && "bg-white",
              isTelegram && "telegram-transient-scrollbar",
              isTelegram && telegramListScrolling && "is-scrolling"
            )}
            onScroll={(event) => {
              const node = event.currentTarget;
              if (isTelegram) {
                setTelegramListScrolling(true);
                clearTimeout(telegramListScrollTimerRef.current);
                telegramListScrollTimerRef.current = setTimeout(() => setTelegramListScrolling(false), 800);
              }
              if (node.scrollHeight - node.scrollTop - node.clientHeight < 120) void loadMoreConversations();
            }}
          >
            {loadingInbox ? (
              <div className="py-10 text-center px-4 text-[13px] text-muted-foreground">{t("common.loading")}</div>
            ) : inboxLoadError ? (
              <div role="alert" className="m-3 rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-center text-[12.5px] text-destructive">
                <p>{inboxLoadError}</p>
                <button type="button" onClick={() => setInboxRetryAttempt((attempt) => attempt + 1)} className="mt-2 font-medium underline">
                  {t("common.retry", "Retry")}
                </button>
              </div>
            ) : visibleConversations.length === 0 ? (
              <div className="py-8 text-center px-4">
                <p className="text-[13px] text-muted-foreground">{t("inbox.noConversations")}</p>
              </div>
            ) : visibleConversations.map((conversation) => (
              <button
                key={conversation.id}
                type="button"
                aria-pressed={current?.id === conversation.id}
                onClick={() => { selectConversation(conversation); if (isWhatsApp || isMessenger) setMobileChatOpen(true); }}
                className={cn(
                  "w-full flex border-b transition-colors",
                  isTelegram ? "min-h-[58px] gap-2 px-2 py-1.5" : isInstagram ? "min-h-[68px] gap-3 px-4 py-2" : "gap-3 px-3 py-2.5",
                  isWhatsApp ? "border-[#e9edef] hover:bg-[#f5f6f6]" : isTelegram ? "border-[#edf0f2] hover:bg-[#f4f7f9]" : isInstagram ? "border-transparent hover:bg-[#fafafa]" : isMessenger ? "border-[#e4e6eb] hover:bg-[#f2f2f2]" : "border-border/60 hover:bg-surface/60",
                  isWhatsApp || isTelegram || isInstagram || isMessenger ? (lang === "ar" ? "text-right" : "text-left") : "text-left",
                  current?.id === conversation.id && (isWhatsApp ? "bg-[#f0f2f5]" : isTelegram ? "bg-[#419fd9] text-white hover:bg-[#419fd9]" : isInstagram ? "bg-[#efefef]" : isMessenger ? "bg-[#e7f3ff]" : "bg-primary/5")
                )}
              >
                <div className="relative shrink-0">
                  {isInstagram ? (
                    <div className={cn("rounded-full p-[2px]", (conversation.hasStory || conversation.story?.available || conversation.story_available) ? "bg-[conic-gradient(from_45deg,#feda75,#fa7e1e,#d62976,#962fbf,#4f5bd5,#feda75)]" : "border border-[#dbdbdb]")}><ConversationAvatar conversation={conversation} className={cn("h-11 w-11 text-[13px]", (conversation.hasStory || conversation.story?.available || conversation.story_available) && "border-2 border-white")} /></div>
                  ) : isTelegram ? (
                    <ConversationAvatar conversation={conversation} className="h-10 w-10 text-[12px]" />
                  ) : isMessenger ? (
                    <ConversationAvatar conversation={conversation} className="h-11 w-11 text-[12px]" />
                  ) : (
                    <div className={cn("rounded-full grid place-items-center text-[12px] font-semibold text-white", isWhatsApp ? "h-12 w-12 text-[#54656f]" : "h-11 w-11")} style={{ background: conversation.color, color: isWhatsApp ? "#54656f" : "#fff" }}>
                      {conversation.initials}
                    </div>
                  )}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <span dir={isWhatsApp || isTelegram || isMessenger ? "auto" : undefined} className={cn("truncate", isWhatsApp ? "text-[14px] font-medium text-[#111b21]" : isTelegram ? "text-[14px] font-medium" : "text-[13px] font-medium")}>{conversation.customer}</span>
                    <span dir={isWhatsApp || isTelegram || isInstagram ? "ltr" : undefined} className={cn("shrink-0", isWhatsApp ? "text-[11px] text-[#667781]" : isTelegram ? current?.id === conversation.id ? "text-[11px] text-white/85" : "text-[11px] text-[#7f9db8]" : isInstagram ? "text-[10.5px] text-[#8e8e8e]" : "text-[11px] text-muted-foreground")}>{conversation.time}</span>
                  </div>
                  {isInstagram ? (
                    <div className="mt-0.5 flex min-w-0 items-center gap-2"><p dir="auto" className="min-w-0 flex-1 truncate text-[11.5px] text-[#8e8e8e]">{conversation.preview}</p>{conversation.unread > 0 && <span aria-label={lang === "ar" ? "رسائل غير مقروءة" : "Unread message"} className="h-1.5 w-1.5 shrink-0 rounded-full bg-[#0095f6]" />}</div>
                  ) : isTelegram ? (
                    <div className="mt-0.5 flex min-w-0 items-center gap-1.5">
                      <p dir="auto" className={cn("min-w-0 flex-1 truncate text-[11.5px]", current?.id === conversation.id ? "text-white/90" : "text-[#7b8d9b]")}>{conversation.preview}</p>
                      {conversation.unread > 0 && <span className="min-w-5 rounded-full bg-[#2aabee] px-1.5 py-0.5 text-center text-[10px] font-semibold tabular-nums text-white">{conversation.unread}</span>}
                    </div>
                  ) : <p dir={isWhatsApp || isMessenger ? "auto" : undefined} className={cn("truncate mt-0.5", isWhatsApp ? "text-[12px] text-[#667781]" : "text-[12px] text-muted-foreground")}>{conversation.preview}</p>}
                  {!isTelegram && !isInstagram && <div className="mt-1 flex items-center gap-1.5">
                    <span className={cn("px-1.5 py-0.5 text-[10px]", isWhatsApp ? "rounded-full bg-[#f0f2f5] text-[#667781]" : "rounded-md bg-surface text-muted-foreground")}>
                      {t(`inbox.status.${conversation.status}`)}
                    </span>
                    {conversation.unread > 0 && (
                      <span className={cn("ml-auto text-[10px] font-semibold px-1.5 py-0.5 tabular-nums", isWhatsApp ? "min-w-5 rounded-full bg-[#25d366] text-center text-white" : isTelegram ? "min-w-5 rounded-full bg-[#2aabee] text-center text-white" : "rounded-md bg-primary text-primary-foreground")}>
                        {conversation.unread}
                      </span>
                    )}
                  </div>}
                </div>
              </button>
            ))}
            {(loadingMoreInbox || inboxMoreError || inboxCursor) && (
              <div className="px-3 py-2 text-center text-[11.5px] text-muted-foreground">
                {inboxMoreError ? (
                  <button type="button" onClick={() => void loadMoreConversations()} className="text-primary hover:underline">{t("common.retry", "Retry")}</button>
                ) : loadingMoreInbox ? t("common.loading") : (
                  <button type="button" onClick={() => void loadMoreConversations()} className="text-primary hover:underline">{t("inbox.loadMore", "Load more conversations")}</button>
                )}
              </div>
            )}
          </div>
          </>
          )}
          {channelStatus && connectedCount === 0 && (
            <p className="shrink-0 border-t border-border px-3 py-2 text-[11px] leading-relaxed text-muted-foreground">
              {t("inbox.noConnectedChannels", "Connect a channel in Settings → Channels to start receiving messages.")}
            </p>
          )}
        </div>

        {!isFacebook && (
          <div
            role="separator"
            aria-label={lang === "ar" ? "تغيير عرض قائمة المحادثات" : "Resize conversation list"}
            aria-orientation="vertical"
            aria-valuemin={CHAT_LIST_MIN_WIDTH}
            aria-valuemax={CHAT_LIST_MAX_WIDTH}
            aria-valuenow={chatListWidth}
            tabIndex={0}
            className={cn(
              "group relative hidden cursor-col-resize touch-none select-none border-x outline-none transition-colors lg:block",
              isMessenger ? "border-[#e4e6eb] bg-white hover:bg-[#e7f3ff] focus-visible:bg-[#e7f3ff]" : isInstagram ? "border-[#dbdbdb] bg-white hover:bg-[#fff2f6] focus-visible:bg-[#fff2f6]" : isTelegram ? "border-[#e4e9ec] bg-white hover:bg-[#eff8fd] focus-visible:bg-[#eff8fd]" : "border-x-0 bg-[var(--wa-divider)] before:absolute before:inset-y-0 before:-inset-x-1.5 before:content-[''] hover:bg-[#00a884] focus-visible:bg-[#00a884]",
              isResizingChatList && (isMessenger ? "bg-[#e7f3ff]" : isInstagram ? "bg-[#fff2f6]" : isTelegram ? "bg-[#eff8fd]" : "bg-[var(--wa-bg-hover)]")
            )}
            onPointerDown={handleResizePointerDown}
            onPointerMove={handleResizePointerMove}
            onPointerUp={finishChatListResize}
            onPointerCancel={finishChatListResize}
            onLostPointerCapture={() => finishChatListResize()}
            onKeyDown={handleResizeKeyDown}
          >
            <span className={cn("absolute inset-y-0 left-1/2 w-px -translate-x-1/2 transition-colors", isMessenger ? "bg-[#e4e6eb] group-hover:bg-[#0084ff] group-focus-visible:bg-[#0084ff]" : isInstagram ? "bg-[#dbdbdb] group-hover:bg-[#d62976] group-focus-visible:bg-[#d62976]" : isTelegram ? "bg-[#e4e9ec] group-hover:bg-[#2aabee] group-focus-visible:bg-[#2aabee]" : "bg-[var(--wa-divider)] group-hover:bg-[#00a884] group-focus-visible:bg-[#00a884]")} />
            <span className={cn("absolute left-1/2 top-1/2 h-9 w-1 -translate-x-1/2 -translate-y-1/2 rounded-full transition-colors", isMessenger ? "bg-[#c4c8ce] group-hover:bg-[#0084ff] group-focus-visible:bg-[#0084ff]" : isInstagram ? "bg-[#c4c8ce] group-hover:bg-[#d62976] group-focus-visible:bg-[#d62976]" : isTelegram ? "bg-[#c4c8ce] group-hover:bg-[#2aabee] group-focus-visible:bg-[#2aabee]" : "bg-[var(--wa-divider)] group-hover:bg-[#00a884] group-focus-visible:bg-[#00a884]")} />
          </div>
        )}

        <ChannelChat
          channel={channel}
          lang={lang}
          className={(isWhatsApp || isMessenger) && !mobileChatOpen ? "hidden lg:flex" : ""}
          onBack={isWhatsApp || isMessenger ? () => setMobileChatOpen(false) : undefined}
          messengerThemeId={current ? messengerThemes[current.id] : undefined}
          onMessengerThemeChange={(themeId) => {
            if (!current) return;
            setMessengerThemes((previous) => ({ ...previous, [current.id]: themeId }));
          }}
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
          pinnedCount={isWhatsApp ? conversations.filter((row) => row.pinnedAt && !row.archivedAt).length : 0}
          onApprove={() => decideApproval(pendingApproval, "APPROVED")}
          onDecline={() => decideApproval(pendingApproval, "REJECTED")}
        />
      </div>
      </div>
      {!embedded && <aside className="z-10 flex min-h-0 min-w-0 flex-col items-center border-l border-border/80 bg-card" aria-label={t("inbox.title")}>
        <ChannelSwitcher
          channels={channels}
          active={activeChannel}
          unreadByChannel={unreadByChannel}
          onSelect={(id) => { setActiveChannel(id); setActiveId(null); setMobileChatOpen(false); setFilter("all"); }}
        />
      </aside>}
      </div>
    </div>
  );
}
