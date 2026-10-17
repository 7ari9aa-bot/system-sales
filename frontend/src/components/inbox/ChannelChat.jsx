import React, { useState, useRef, useEffect, useLayoutEffect, useCallback } from "react";
import { ArrowLeft, ArrowRight, ArrowUpRight, Search, Sparkles, X, Check, CheckCheck, Paperclip, Smile, Mic, PanelRight, MoreVertical } from "lucide-react";
import { cn } from "@/lib/utils";

const TELEGRAM_DOODLE_PATTERN = "data:image/svg+xml," + encodeURIComponent(`
  <svg xmlns="http://www.w3.org/2000/svg" width="360" height="320" viewBox="0 0 360 320" fill="none" stroke="#547a65" stroke-opacity=".24" stroke-width="1.35" stroke-linecap="round" stroke-linejoin="round">
    <!-- Telegram-style scattered line-art icons; the background color remains dominant. -->
    <g>
      <path d="M31 29l4-11 4 11 11 4-11 4-4 11-4-11-11-4 11-4Zm220 39 3-8 3 8 8 3-8 3-3 8-3-8-8-3 8-3Z"/>
      <path d="M76 43c-7-10-22-5-20 7 1 8 13 17 20 22 7-5 19-14 20-22 2-12-13-17-20-7Z"/>
      <path d="M139 37c8-10 23-10 31 0v15c0 10-6 17-15 24-9-7-16-14-16-24V37Zm7 1v14c0 6 3 11 9 16 6-5 9-10 9-16V38"/>
      <circle cx="291" cy="35" r="16"/><ellipse cx="291" cy="35" rx="25" ry="8" transform="rotate(-24 291 35)"/><circle cx="291" cy="35" r="5"/>
      <path d="M34 111c8-10 22-11 31-2l-4 17-17 5-13-9 3-11Zm4-1 14 15m-10-22 19 18M84 111c7-7 18-7 25 0v16H84v-16Zm-4 0h33m-27 6h21m-21 5h13"/>
      <path d="m151 105 32-16-10 34-7-12-15-6Zm15 6 17-22M208 105l12-11 12 11-3 16-9 8-9-8-3-16Zm9-11v-6h6v6"/>
      <path d="M274 107c8-8 18-8 26 0-8 8-18 8-26 0Zm0 0-9-7m35 7 9-7m-27 7c-3-6-2-11 2-15m8 15c4-6 3-11-1-15"/>
      <circle cx="66" cy="190" r="24"/><path d="M42 190h48M66 166c-8 8-8 40 0 48m0-48c8 8 8 40 0 48m-19-34c12 7 26 7 38 0m-38 20c12-7 26-7 38 0"/>
      <path d="M128 171c0-8 6-14 14-14s14 6 14 14c0 6-4 10-8 13-4 3-6 6-6 10m0 9v1m0-47v-6m-19 11-4-4m42 0 4-4m-30-5h6"/>
      <path d="M199 172c7-10 22-10 29 0 7 9 4 19-4 26l-11 10-11-10c-8-7-11-17-3-26Zm0 1 14 14 15-14m-30 0 15 15 14-15"/>
      <path d="m270 170 5-12 5 12 12 5-12 5-5 12-5-12-12-5 12-5Zm40 36c0-9 7-16 16-16s16 7 16 16-7 16-16 16-16-7-16-16Zm5 0 6-6 11 12m-17 0 6 6 11-12"/>
      <path d="M31 258c9-9 23-9 32 0v18H31v-18Zm-5 0h42m-33 7h25m-25 6h17m61-18 18-13 18 13-5 20-13 11-13-11-5-20Zm18-13v-8h9v8m-18 17h27"/>
      <path d="M203 253c-9 0-15 7-15 15 0 12 15 22 15 22s15-10 15-22c0-8-6-15-15-15Zm-5 15 4 4 8-9m34-8 14-8 14 8-5 17-9 8-9-8-5-17Z"/>
      <circle cx="322" cy="268" r="19"/><path d="m309 268 8-8 7 7 11-11m-32 25h38"/>
      <path d="M106 78c8-7 18-7 25 0l-7 10h-13l-5-10Zm4 10-6 9m20-9 7 9m-18-9v12m-52 112 9-7 9 7-3 11-6 6-6-6-3-11Z"/>
    </g>
  </svg>
`);

// A themed chat pane that renders in the selected channel's real look.
// Brand channels (WhatsApp/Instagram/Messenger/Telegram/Facebook) keep their
// authentic light theme; the "app" theme channel follows the dashboard.
export default function ChannelChat({
  channel,
  className = "",
  onBack,
  lang = "en",
  conversation,
  approval,
  loadingMessages = false,
  loadingOlderMessages = false,
  hasOlderMessages = false,
  onLoadOlderMessages,
  messagesError = "",
  onRetryMessages,
  sending = false,
  pendingDecision = false,
  t,
  onSend,
  onApprove,
  onDecline,
}) {
  const [text, setText] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const scrollRef = useRef(null);
  const preserveScrollRef = useRef(null);
  const messageViewportRef = useRef({ conversationId: null, latestMessageId: null });
  const isApp = channel.theme === "app";
  const isWhatsApp = channel.id === "whatsapp";
  const isTelegram = channel.id === "telegram";
  const th = isApp ? null : channel.theme;
  const allMessages = conversation?.messages || [];
  const messageBackgroundStyle = isWhatsApp ? {
    backgroundColor: "#efeae2",
    backgroundImage: "linear-gradient(rgba(245,240,232,0.88), rgba(245,240,232,0.88)), url('https://static.whatsapp.net/rsrc.php/yp/r/OA5z0a81CZk.webp')",
    backgroundRepeat: "no-repeat, repeat",
    backgroundSize: "100% 100%, 320px 570px",
  } : isTelegram ? {
    backgroundColor: "#a9cf9a",
    backgroundImage: "url(\"" + TELEGRAM_DOODLE_PATTERN + "\"), linear-gradient(118deg, #e6e28d 0%, #80b78f 50%, #e2df8a 100%)",
    backgroundRepeat: "repeat, no-repeat",
    backgroundSize: "260px 230px, 100% 100%",
  } : undefined;
  const visibleMessages = (isWhatsApp || isTelegram) && searchQuery.trim()
    ? allMessages.filter((message) => String(message.text || "").toLocaleLowerCase().includes(searchQuery.trim().toLocaleLowerCase()))
    : allMessages;

  useLayoutEffect(() => {
    const element = scrollRef.current;
    if (!element || !conversation) return;
    const messages = conversation.messages || [];
    const latestMessageId = messages.at(-1)?.id ?? null;
    const previous = messageViewportRef.current;
    const preserve = preserveScrollRef.current;

    if (preserve?.conversationId === conversation.id) {
      element.scrollTop = preserve.scrollTop + element.scrollHeight - preserve.scrollHeight;
      preserveScrollRef.current = null;
    } else if (previous.conversationId !== conversation.id || previous.latestMessageId !== latestMessageId) {
      element.scrollTop = element.scrollHeight;
    }
    messageViewportRef.current = { conversationId: conversation.id, latestMessageId };
  }, [conversation?.id, conversation?.messages]);

  useEffect(() => {
    setText("");
    setSearchQuery("");
    setSearchOpen(false);
  }, [conversation?.id]);

  async function submitMessage() {
    const body = text.trim();
    if (!body || sending || !conversation) return;
    const sent = await onSend?.(conversation.id, body);
    if (sent !== false) setText("");
  }

  const loadOlderAtTop = useCallback(async (element) => {
    if (!element || element.scrollTop > 48 || !hasOlderMessages || loadingMessages || loadingOlderMessages) return;
    preserveScrollRef.current = {
      conversationId: conversation.id,
      scrollHeight: element.scrollHeight,
      scrollTop: element.scrollTop,
    };
    const loaded = await onLoadOlderMessages?.();
    if (!loaded) preserveScrollRef.current = null;
  }, [conversation?.id, hasOlderMessages, loadingMessages, loadingOlderMessages, onLoadOlderMessages]);

  const handleMessagesScroll = useCallback((event) => {
    void loadOlderAtTop(event.currentTarget);
  }, [loadOlderAtTop]);

  useEffect(() => {
    const element = scrollRef.current;
    if (!element || !conversation || loadingMessages || loadingOlderMessages || !hasOlderMessages) return undefined;
    if (element.scrollHeight > element.clientHeight + 1) return undefined;
    const frame = requestAnimationFrame(() => void loadOlderAtTop(element));
    return () => cancelAnimationFrame(frame);
  }, [conversation?.id, conversation?.messages?.length, hasOlderMessages, loadingMessages, loadingOlderMessages, loadOlderAtTop]);

  if (!conversation) {
    return (
      <div className={cn("flex-1 grid place-items-center border bg-card text-center p-8", isWhatsApp ? "rounded-xl border-[#d1d7db] lg:rounded-none lg:border-y lg:border-r lg:border-l-0" : "rounded-2xl border-border", className, "lg:items-center lg:justify-center")}>
        <div>
          <div className="h-12 w-12 rounded-full bg-surface grid place-items-center mx-auto mb-3">
            <Sparkles className="h-5 w-5 text-muted-foreground" />
          </div>
          <p className="text-[13.5px] text-muted-foreground">{t("inbox.selectConversation")}</p>
        </div>
      </div>);

  }

  return (
    <div
      className={cn("flex-1 flex flex-col min-h-0 overflow-hidden border", isWhatsApp ? "rounded-xl border-[#d1d7db] lg:rounded-none lg:border-y lg:border-r lg:border-l-0" : "rounded-2xl border-border", className)}
      style={isApp ? undefined : { background: th.chatBg }}>
      
      {/* Header */}
      <div
        dir={isWhatsApp || isTelegram ? "ltr" : undefined}
        className={cn("flex items-center gap-3 px-4 shrink-0", isWhatsApp ? "h-[60px] px-4" : isTelegram ? "h-[66px] px-5" : "h-14")}
        style={isApp ? { background: "hsl(var(--card))", borderBottom: "1px solid hsl(var(--border))" } : { background: th.headerBg, color: th.headerText, borderBottom: (isWhatsApp || isTelegram) ? "1px solid " + th.divider : undefined }}>

        {isWhatsApp && onBack && (
          <button
            type="button"
            onClick={onBack}
            aria-label={t("inbox.backToChats", "Back to chats")}
            title={t("inbox.backToChats", "Back to chats")}
            className="-mx-1 grid h-9 w-9 shrink-0 place-items-center rounded-full text-[#54656f] transition-colors hover:bg-black/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#00a884] lg:hidden"
          >
            {lang === "ar" ? <ArrowRight className="h-5 w-5" /> : <ArrowLeft className="h-5 w-5" />}
          </button>
        )}
        
        <div
          className={cn("rounded-full grid place-items-center font-semibold shrink-0", isWhatsApp ? "h-10 w-10 text-[12px]" : isTelegram ? "h-10 w-10 text-[14px]" : "h-9 w-9 text-[13px]")}
          style={{ background: conversation.color, color: isWhatsApp ? "#54656f" : "#fff" }}>
          
          {conversation.initials}
        </div>
        <div className="flex-1 min-w-0">
          <div dir={isWhatsApp || isTelegram ? "auto" : undefined} className={cn("truncate", isWhatsApp ? "text-left text-[15px] font-medium text-[#111b21]" : isTelegram ? "text-left text-[15px] font-medium text-[#222]" : "text-[14px] font-semibold", isApp && "text-foreground")}>{conversation.customer}</div>
          <div className={cn("truncate", isWhatsApp ? "text-left text-[12px] text-[#667781]" : isTelegram ? "text-[12px] text-[#7f9db8]" : "text-[11.5px]", isApp && "text-muted-foreground", !isApp && !isWhatsApp && !isTelegram && "opacity-80")}>{isTelegram ? "bot" : channel.name}</div>
        </div>
        {(isWhatsApp || isTelegram) && (
          <button
            type="button"
            aria-label={t("inbox.searchMessages", "Search messages")}
            aria-expanded={searchOpen}
            onClick={() => { setSearchOpen((open) => !open); setSearchQuery(""); }}
            className={cn("grid h-9 w-9 shrink-0 place-items-center rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2", isWhatsApp ? "text-[#54656f] hover:bg-[#f5f6f6] focus-visible:ring-[#00a884]" : "text-[#707e8b] hover:bg-[#f2f5f7] focus-visible:ring-[#3390ec]")}
          >
            <Search className="h-[18px] w-[18px]" />
          </button>
        )}
        {isTelegram && (
          <>
            <button type="button" disabled aria-label={lang === "ar" ? "عرض المحادثة غير متاح" : "Conversation view unavailable"} className="grid h-9 w-9 shrink-0 place-items-center rounded-full text-[#707e8b] disabled:cursor-default">
              <PanelRight className="h-[18px] w-[18px]" />
            </button>
            <button type="button" disabled aria-label={lang === "ar" ? "المزيد غير متاح" : "More options unavailable"} className="grid h-9 w-9 shrink-0 place-items-center rounded-full text-[#707e8b] disabled:cursor-default">
              <MoreVertical className="h-[18px] w-[18px]" />
            </button>
          </>
        )}
      </div>

      {(isWhatsApp || isTelegram) && searchOpen && (
        <div className={cn("flex h-12 shrink-0 items-center gap-2 border-b bg-white px-3", isWhatsApp ? "border-[#d1d7db]" : "border-[#e4e9ec]")}>
          <Search className={cn("h-4 w-4 shrink-0", isWhatsApp ? "text-[#667781]" : "text-[#82919e]")} />
          <input
            type="search"
            autoFocus
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            dir={lang === "ar" ? "rtl" : "ltr"}
            aria-label={t("inbox.searchMessages", "Search messages")}
            placeholder={t("inbox.searchMessages", "Search messages")}
            className={cn("min-w-0 flex-1 bg-transparent text-[13px] outline-none placeholder:text-[#8696a0]", isWhatsApp ? "text-[#111b21]" : "text-[#222]", lang === "ar" ? "text-right" : "text-left")}
          />
          {searchQuery && (
            <button type="button" onClick={() => setSearchQuery("")} aria-label={t("common.clear", "Clear search")} className="grid h-7 w-7 shrink-0 place-items-center rounded-full text-[#667781] hover:bg-[#f0f2f5]">
              <X className="h-4 w-4" />
            </button>
          )}
        </div>
      )}

      {/* Messages */}
      <div
        ref={scrollRef}
        onScroll={handleMessagesScroll}
        className={cn("flex-1 min-h-0 overflow-y-auto scrollbar-thin px-4 py-3 space-y-2", isWhatsApp && "px-5 py-4 space-y-2", isTelegram && "px-4 py-3 space-y-1.5 sm:px-6 sm:py-4")}
        style={messageBackgroundStyle}
      >
        {loadingOlderMessages && <div role="status" className="py-2 text-center text-[11.5px] text-muted-foreground">{t("common.loading")}</div>}
        {loadingMessages && (conversation.messages || []).length === 0 && (
          <div className="py-10 text-center text-[12.5px] text-muted-foreground">{t("common.loading")}</div>
        )}
        {messagesError && (
          <div role="alert" className="mx-auto mb-3 max-w-lg rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-center text-[12.5px] text-destructive">
            <span>{messagesError}</span>
            <button type="button" onClick={onRetryMessages} className="ml-2 font-medium underline">
              {t("common.retry", "Retry")}
            </button>
          </div>
        )}
        {!loadingMessages && !messagesError && (conversation.messages || []).length === 0 && (
          <div className="py-10 text-center text-[12.5px] text-muted-foreground">
            {t("inbox.noMessages", "No messages are available for this conversation yet.")}
          </div>
        )}
        {searchQuery.trim() && visibleMessages.length === 0 && (
          <div className="py-8 text-center text-[12.5px] text-[#667781]">{t("inbox.noMessageMatches", "No matching messages")}</div>
        )}
        {visibleMessages.map((m, index) => {
          const dayKey = isWhatsApp || isTelegram ? getMessageDayKey(m.createdAt) : "";
          const previousDayKey = (isWhatsApp || isTelegram) && index > 0 ? getMessageDayKey(visibleMessages[index - 1].createdAt) : "";
          return (
            <React.Fragment key={m.id}>
              {dayKey && dayKey !== previousDayKey && (
                <div className="flex justify-center py-1.5" aria-label={formatWhatsAppDay(m.createdAt, lang, t)}>
                  <span className={cn("rounded-md bg-white/90 px-2.5 py-1 text-[11px] font-medium shadow-[0_1px_0.5px_rgba(11,20,26,0.13)]", isTelegram ? "text-[#527da3]" : "text-[#54656f]")}>
                    {formatWhatsAppDay(m.createdAt, lang, t)}
                  </span>
                </div>
              )}
              <Bubble m={m} isApp={isApp} isWhatsApp={isWhatsApp} isTelegram={isTelegram} th={th} />
            </React.Fragment>
          );
        })}
        {approval &&
        <div
          className="mt-2 rounded-xl px-3.5 py-3 text-[12.5px]"
          style={isApp ?
          { background: "hsl(var(--warning-soft))", border: "1px solid hsl(var(--warning) / 0.3)", color: "hsl(var(--warning))" } :
          { background: "#FFF8E1", border: "1px solid #FFE082", color: "#8a6d00" }}>
          
            <div className="font-medium mb-1">{t("inbox.approval.title")}</div>
            <p className="opacity-90">{approval.action}</p>
            {approval.payload?.arguments && (
              <pre className="mt-2 max-h-32 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-black/5 p-2 text-[11px]">
                {JSON.stringify(approval.payload.arguments, null, 2)}
              </pre>
            )}
            <div className="flex gap-2 mt-2.5">
              <button
                type="button"
                disabled={pendingDecision}
                onClick={() => onApprove?.(conversation.id)}
                className="h-8 px-3 rounded-lg text-[12px] font-medium text-white"
                style={{ background: "#16a34a" }}>
                {t("inbox.approve")}
              </button>
              <button
                type="button"
                disabled={pendingDecision}
                onClick={() => onDecline?.(conversation.id)}
                className="h-8 px-3 rounded-lg text-[12px] font-medium"
                style={{ background: isApp ? "hsl(var(--surface))" : "#fff", border: "1px solid #e5e7eb" }}>
                {t("inbox.decline")}
              </button>
            </div>
          </div>
        }
      </div>

      {/* Input */}
      <div className={cn("shrink-0 p-2", isWhatsApp && "px-3 py-1 sm:px-4", isTelegram && "px-3 py-2 sm:px-4 sm:py-2.5")} style={isApp ? { background: "hsl(var(--card))", borderTop: "1px solid hsl(var(--border))" } : { background: isWhatsApp ? "#f0f2f5" : isTelegram ? "#f5f6f7" : th.inputBg, borderTop: "1px solid " + th.inputBorder }}>
        {isWhatsApp ? (
          <div dir="ltr" className="flex h-11 items-center gap-1.5 overflow-hidden rounded-full bg-white px-2 shadow-[0_1px_2px_rgba(0,0,0,0.12)] sm:h-14 sm:gap-2 sm:px-3" style={{ borderRadius: 9999 }}>
            <button
              type="button"
              disabled
              aria-label={lang === "ar" ? "المرفقات غير متاحة" : "Attachments unavailable"}
              title={lang === "ar" ? "المرفقات غير متاحة" : "Attachments unavailable"}
              className="grid h-9 w-9 shrink-0 place-items-center rounded-full text-[#54656f] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#00a884]"
              style={{ color: "#54656f" }}
            >
              <Paperclip className="h-5 w-5" />
            </button>
            <button
              type="button"
              disabled
              aria-label={lang === "ar" ? "اختيار الرموز غير متاح" : "Emoji picker unavailable"}
              title={lang === "ar" ? "اختيار الرموز غير متاح" : "Emoji picker unavailable"}
              className="grid h-9 w-9 shrink-0 place-items-center rounded-full text-[#54656f] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#00a884]"
              style={{ color: "#54656f" }}
            >
              <Smile className="h-[21px] w-[21px]" />
            </button>
            <input
              value={text}
              onChange={(e) => setText(e.target.value)}
              dir={lang === "ar" ? "rtl" : "ltr"}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void submitMessage(); } }}
              placeholder={t("inbox.typeMessage")}
              aria-label={t("inbox.typeMessage")}
              disabled={sending}
              className={cn("h-full min-w-0 flex-1 bg-transparent px-2 text-[14px] text-[#111b21] focus:outline-none placeholder:text-[#8696a0]", lang === "ar" ? "text-right" : "text-left")}
            />
            {text.trim() ? (
              <button
                type="button"
                onClick={() => { void submitMessage(); }}
                disabled={sending}
                aria-label={t("inbox.send")}
                className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-[#00a884] text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#00a884] focus-visible:ring-offset-2"
                title={t("inbox.send")}
                style={{ backgroundColor: "#00a884", color: "#fff" }}
              >
                <ArrowUpRight className="h-[18px] w-[18px]" />
              </button>
            ) : (
              <button
                type="button"
                aria-disabled="true"
                aria-label={lang === "ar" ? "الرسائل الصوتية غير متاحة" : "Voice messages unavailable"}
                title={lang === "ar" ? "الرسائل الصوتية غير متاحة" : "Voice messages unavailable"}
                className="grid h-10 w-10 shrink-0 place-items-center rounded-full text-[#54656f] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#00a884]"
                style={{ color: "#54656f" }}
              disabled
              >
                <Mic className="h-[21px] w-[21px]" />
              </button>
            )}
          </div>
        ) : isTelegram ? (
          <div dir="ltr" className="flex h-11 items-center gap-1 rounded-md bg-white px-2 sm:h-12 sm:gap-2 sm:px-3" style={{ boxShadow: "0 1px 2px rgba(0,0,0,.08)" }}>
            <button type="button" disabled aria-label={lang === "ar" ? "المرفقات غير متاحة" : "Attachments unavailable"} title={lang === "ar" ? "المرفقات غير متاحة" : "Attachments unavailable"} className="grid h-9 w-9 shrink-0 place-items-center rounded-full text-[#8a9aa8] disabled:cursor-default">
              <Paperclip className="h-[21px] w-[21px]" />
            </button>
            <input
              value={text}
              onChange={(e) => setText(e.target.value)}
              dir={lang === "ar" ? "rtl" : "ltr"}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void submitMessage(); } }}
              placeholder={t("inbox.typeMessage")}
              aria-label={t("inbox.typeMessage")}
              disabled={sending}
              className={cn("h-full min-w-0 flex-1 bg-transparent px-2 text-[14px] text-[#222] focus:outline-none placeholder:text-[#8b98a3]", lang === "ar" ? "text-right" : "text-left")}
            />
            <button type="button" disabled aria-label={lang === "ar" ? "اختيار الرموز غير متاح" : "Emoji picker unavailable"} title={lang === "ar" ? "اختيار الرموز غير متاح" : "Emoji picker unavailable"} className="grid h-9 w-9 shrink-0 place-items-center rounded-full text-[#8a9aa8] disabled:cursor-default">
              <Smile className="h-[21px] w-[21px]" />
            </button>
            {text.trim() ? (
              <button type="button" onClick={() => { void submitMessage(); }} disabled={sending} aria-label={t("inbox.send")} title={t("inbox.send")} className="grid h-9 w-9 shrink-0 place-items-center rounded-full text-[#2aabee] hover:bg-[#eff8fd] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#2aabee]">
                <ArrowUpRight className="h-[19px] w-[19px]" />
              </button>
            ) : (
              <button type="button" disabled aria-label={lang === "ar" ? "الرسائل الصوتية غير متاحة" : "Voice messages unavailable"} title={lang === "ar" ? "الرسائل الصوتية غير متاحة" : "Voice messages unavailable"} className="grid h-9 w-9 shrink-0 place-items-center rounded-full text-[#8a9aa8] disabled:cursor-default">
                <Mic className="h-[21px] w-[21px]" />
              </button>
            )}
          </div>
        ) : (
          <div
            className="flex items-center gap-2 rounded-full px-3 py-1.5"
            style={isApp ? { background: "hsl(var(--surface))", border: "1px solid hsl(var(--border))" } : { background: "#fff", border: "1px solid " + th.inputBorder }}
          >
            <input
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void submitMessage(); } }}
              placeholder={t("inbox.typeMessage")}
              aria-label={t("inbox.typeMessage")}
              disabled={sending}
              className="flex-1 bg-transparent text-[13px] focus:outline-hidden"
              style={isApp ? undefined : { color: "#111" }}
            />
            <button
              type="button"
              onClick={() => { void submitMessage(); }}
              disabled={!text.trim() || sending}
              aria-label={t("inbox.send")}
              className="grid h-8 w-8 shrink-0 place-items-center rounded-full text-white"
              style={{ background: channel.accent, opacity: !text.trim() || sending ? 0.55 : 1 }}
              title={t("inbox.send")}
            >
              <ArrowUpRight className="h-4 w-4" />
            </button>
          </div>
        )}
      </div>
    </div>);

}

function Bubble({ m, isApp, isWhatsApp, isTelegram, th }) {
  const out = m.side === "out";
  const showTail = !isApp && th?.tail;

  if (isWhatsApp) {
    if (m.senderType === "system") {
      return (
        <div className="flex justify-center py-1">
          <div className="max-w-[85%] rounded-lg bg-white/95 px-3 py-2 text-center text-[12px] leading-snug text-[#54656f] shadow-[0_1px_0.5px_rgba(11,20,26,0.13)]">
            <span>{m.text}</span>
            {m.time && <span className="ms-1.5 whitespace-nowrap text-[10px] text-[#8696a0]" dir="ltr">{m.time}</span>}
          </div>
        </div>
      );
    }

    return (
      <div className={cn("flex", out ? "justify-end" : "justify-start")}>
        <div
          className={cn(
            "relative max-w-[82%] rounded-lg px-3 py-2 text-[14px] leading-[1.4] shadow-[0_1px_0.5px_rgba(11,20,26,0.13)] sm:max-w-[72%] lg:max-w-[65%]",
            showTail && (out ? "rounded-br-sm" : "rounded-bl-sm")
          )}
          style={{ background: out ? th.out : th.in, color: out ? th.outText : th.inText }}
        >
          {showTail && (
            <span
              aria-hidden="true"
              className={cn("absolute bottom-0 h-2.5 w-2", out ? "-right-[5px]" : "-left-[5px]")}
              style={{
                background: out ? th.out : th.in,
                clipPath: out ? "polygon(0 0, 100% 100%, 0 100%)" : "polygon(100% 0, 100% 100%, 0 100%)",
              }}
            />
          )}
          <div className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]" dir="auto">
            {m.text}{" "}
            <span className="inline-flex items-center gap-0.5 whitespace-nowrap align-baseline text-[11px] leading-none text-[#667781]" dir="ltr">
              <span>{m.time}</span>
            {out && th.checkmarks && (m.status === "read"
              ? <CheckCheck className="h-3.5 w-3.5 text-[#53bdeb]" />
              : m.status === "delivered"
                ? <CheckCheck className="h-3.5 w-3.5" />
                : <Check className="h-3.5 w-3.5" />)}
            {m.ai && <Sparkles className="h-3 w-3" />}
            </span>
          </div>
        </div>
      </div>
    );
  }

  if (isTelegram) {
    if (m.senderType === "system") {
      return (
        <div className="flex justify-center py-1.5">
          <div className="max-w-[88%] rounded-full bg-white/80 px-3 py-1.5 text-center text-[12px] leading-snug text-[#527da3] shadow-[0_1px_2px_rgba(0,0,0,.08)]">
            <span>{m.text}</span>
            {m.time && <span className="ms-1.5 whitespace-nowrap text-[10px] text-[#91a1ae]" dir="ltr">{m.time}</span>}
          </div>
        </div>
      );
    }

    return (
      <div className={cn("flex", out ? "justify-end" : "justify-start")}>
        <div className={cn("relative max-w-[82%] rounded-xl px-3 py-2 text-[14px] leading-[1.38] shadow-[0_1px_2px_rgba(45,70,48,.14)] sm:max-w-[72%]", out ? "rounded-br-[4px]" : "rounded-bl-[4px]")} style={{ background: out ? th.out : th.in, color: out ? th.outText : th.inText }}>
          <div className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]" dir="auto">
            {m.text}{" "}
            <span className="inline-flex items-center gap-0.5 whitespace-nowrap align-baseline text-[10px] leading-none text-[#90a0ab]" dir="ltr">
              <span>{m.time}</span>
              {out && th.checkmarks && (m.status === "read"
                ? <CheckCheck className="h-3 w-3" style={{ color: th.checkColor || "#3390ec" }} />
                : m.status === "delivered"
                  ? <CheckCheck className="h-3 w-3" style={{ color: th.checkColor || "#3390ec" }} />
                  : <Check className="h-3 w-3" style={{ color: th.checkColor || "#3390ec" }} />)}
              {m.ai && <Sparkles className="h-3 w-3" />}
            </span>
          </div>
        </div>
      </div>
    );
  }

  if (isApp) {
    return (
      <div className={cn("flex", out ? "justify-end" : "justify-start")}>
        <div
          className={cn(
            "max-w-[75%] rounded-2xl px-3.5 py-2 text-[13px] leading-relaxed",
            out ? "bg-primary text-primary-foreground rounded-br-md" : "bg-surface text-foreground rounded-bl-md"
          )}>
          
          {m.text}
          <Foot m={m} isApp={isApp} />
        </div>
      </div>);

  }

  return (
    <div className={cn("flex", out ? "justify-end" : "justify-start")}>
      <div
        className={cn("max-w-[72%] rounded-lg px-3 py-2 text-[13px] leading-relaxed shadow-sm relative", showTail && (out ? "rounded-br-none" : "rounded-bl-none"))}
        style={{ background: out ? th.out : th.in, color: out ? th.outText : th.inText }}>
        
        {m.text}
        <Foot m={m} isApp={isApp} th={th} />
      </div>
    </div>);

}

function getMessageDayKey(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
}

function formatWhatsAppDay(value, lang, t) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  if (getMessageDayKey(date) === getMessageDayKey(today)) return t("inbox.date.today", "Today");
  if (getMessageDayKey(date) === getMessageDayKey(yesterday)) return t("inbox.date.yesterday", "Yesterday");
  return new Intl.DateTimeFormat(lang === "ar" ? "ar-EG" : "en-GB", {
    day: "numeric",
    month: "long",
    year: date.getFullYear() === today.getFullYear() ? undefined : "numeric",
  }).format(date);
}

function Foot({ m, isApp, th }) {
  return (
    <span className="inline-flex items-center gap-1 ml-2 align-bottom text-[10px] opacity-60">
      {m.time}
      {m.side === "out" && !isApp && th?.checkmarks && (m.status === "read" ? <CheckCheck className="h-3 w-3" style={{ color: "#34B7F1" }} /> : m.status === "delivered" ? <CheckCheck className="h-3 w-3" /> : <Check className="h-3 w-3" />)}
      {m.ai && <Sparkles className="h-2.5 w-2.5" />}
    </span>);

}
