import React, { useState, useRef, useEffect, useLayoutEffect, useCallback } from "react";
import {
  ArrowLeft,
  ArrowRight,
  ArrowUpRight,
  Search,
  Sparkles,
  X,
  Check,
  CheckCheck,
  Paperclip,
  Smile,
  Mic,
  MoreVertical,
  Send,
  Palette,
  Play,
  Pause,
  FileText,
} from "lucide-react";
import { cn } from "@/lib/utils";
import ConversationAvatar from "@/components/inbox/ConversationAvatar";
import { MESSENGER_CHAT_THEMES } from "@/lib/channels";
import ChannelContactDrawer from "@/components/inbox/ChannelContactDrawer";
import ChannelEmojiStickerPicker from "@/components/inbox/ChannelEmojiStickerPicker";
import ChannelAttachmentMenu from "@/components/inbox/ChannelAttachmentMenu";
import ChannelVoiceRecorder from "@/components/inbox/ChannelVoiceRecorder";
import CustomerDrawer from "@/components/customers/CustomerDrawer";

export default function ChannelChat({
  channel,
  className = "",
  onBack,
  messengerThemeId,
  onMessengerThemeChange,
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
  const [themePickerOpen, setThemePickerOpen] = useState(false);
  const [telegramMessagesScrolling, setTelegramMessagesScrolling] = useState(false);

  // Authentic Channel states
  const [contactDrawerOpen, setContactDrawerOpen] = useState(false);
  const [emojiPickerOpen, setEmojiPickerOpen] = useState(false);
  const [attachmentMenuOpen, setAttachmentMenuOpen] = useState(false);
  const [isRecordingVoice, setIsRecordingVoice] = useState(false);
  const [customer360Record, setCustomer360Record] = useState(null);

  const scrollRef = useRef(null);
  const telegramScrollTimerRef = useRef(null);
  const preserveScrollRef = useRef(null);
  const messageViewportRef = useRef({ conversationId: null, latestMessageId: null });

  const isApp = channel.theme === "app";
  const isWhatsApp = channel.id === "whatsapp";
  const isInstagram = channel.id === "instagram";
  const isMessenger = channel.id === "messenger";
  const isTelegram = channel.id === "telegram";
  const messengerTheme = MESSENGER_CHAT_THEMES.find((theme) => theme.id === messengerThemeId) || MESSENGER_CHAT_THEMES[0];
  const th = isApp ? null : isMessenger ? { ...channel.theme, out: messengerTheme.accent } : channel.theme;
  const allMessages = conversation?.messages || [];

  const messageBackgroundStyle = isWhatsApp ? {
    backgroundColor: "#efeae2",
    backgroundImage: "linear-gradient(rgba(245,240,232,0.88), rgba(245,240,232,0.88)), url('https://static.whatsapp.net/rsrc.php/yp/r/OA5z0a81CZk.webp')",
    backgroundRepeat: "no-repeat, repeat",
    backgroundSize: "100% 100%, 320px 570px",
  } : isTelegram ? {
    backgroundColor: "#a9cf9a",
    backgroundImage: "url('/telegram-chat-wallpaper.png')",
    backgroundPosition: "center",
    backgroundRepeat: "no-repeat",
    backgroundSize: "cover",
  } : undefined;

  const visibleMessages = (isWhatsApp || isInstagram || isMessenger || isTelegram) && searchQuery.trim()
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
    setThemePickerOpen(false);
    setContactDrawerOpen(false);
    setEmojiPickerOpen(false);
    setAttachmentMenuOpen(false);
    setIsRecordingVoice(false);
  }, [conversation?.id]);

  useEffect(() => () => clearTimeout(telegramScrollTimerRef.current), []);

  async function submitMessage() {
    const body = text.trim();
    if (!body || sending || !conversation) return;
    const sent = await onSend?.(conversation.id, body);
    if (sent !== false) {
      setText("");
      setEmojiPickerOpen(false);
      setAttachmentMenuOpen(false);
    }
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
    if (isTelegram) {
      setTelegramMessagesScrolling(true);
      clearTimeout(telegramScrollTimerRef.current);
      telegramScrollTimerRef.current = setTimeout(() => setTelegramMessagesScrolling(false), 800);
    }
    void loadOlderAtTop(event.currentTarget);
  }, [isTelegram, loadOlderAtTop]);

  if (!conversation) {
    return (
      <div className={cn("flex-1 grid place-items-center border bg-card text-center p-8", isWhatsApp ? "rounded-xl border-[#d1d7db] lg:rounded-none lg:border-y lg:border-r lg:border-l-0" : isInstagram ? "rounded-none border-0 bg-white" : "rounded-2xl border-border", className, "lg:items-center lg:justify-center")}>
        <div>
          <div className="h-12 w-12 rounded-full bg-surface grid place-items-center mx-auto mb-3">
            <Sparkles className="h-5 w-5 text-muted-foreground" />
          </div>
          <p className="text-[13.5px] text-muted-foreground">{t("inbox.selectConversation")}</p>
        </div>
      </div>
    );
  }

  return (
    <div
      className={cn("relative flex-1 flex flex-col min-h-0 overflow-hidden border", isWhatsApp ? "rounded-xl border-[#d1d7db] lg:rounded-none lg:border-y lg:border-r lg:border-l-0" : isInstagram ? "rounded-none border-0 border-s border-[#dbdbdb] bg-white" : isMessenger ? "rounded-none border-0 border-s border-[#e4e6eb] bg-white" : "rounded-2xl border-border", className)}
      style={isApp ? undefined : { background: th.chatBg }}
    >
      {/* Header — Click opens authentic channel profile drawer */}
      <div
        dir={isWhatsApp || isTelegram ? "ltr" : isInstagram || isMessenger ? (lang === "ar" ? "rtl" : "ltr") : undefined}
        className={cn("relative flex items-center gap-3 px-4 shrink-0", isWhatsApp ? "h-[60px] px-4" : isTelegram ? "h-[66px] px-5" : isInstagram ? "h-[64px] px-4" : isMessenger ? "h-16 px-5" : "h-14")}
        style={isApp ? { background: "hsl(var(--card))", borderBottom: "1px solid hsl(var(--border))" } : { background: th.headerBg, color: th.headerText, borderBottom: (isWhatsApp || isTelegram || isInstagram || isMessenger) ? "1px solid " + th.divider : undefined }}
      >
        {(isWhatsApp || isMessenger) && onBack && (
          <button
            type="button"
            onClick={onBack}
            aria-label={t("inbox.backToChats", "Back to chats")}
            title={t("inbox.backToChats", "Back to chats")}
            className={cn("-mx-1 grid h-9 w-9 shrink-0 place-items-center rounded-full transition-colors hover:bg-black/5 focus-visible:outline-none focus-visible:ring-2 lg:hidden", isWhatsApp ? "text-[#54656f] focus-visible:ring-[#00a884]" : "text-[#65676b] focus-visible:ring-[#0084ff]")}
          >
            {lang === "ar" ? <ArrowRight className="h-5 w-5" /> : <ArrowLeft className="h-5 w-5" />}
          </button>
        )}

        {/* Customer Header clickable section */}
        <div
          role="button"
          tabIndex={0}
          onClick={() => setContactDrawerOpen(true)}
          className="flex items-center gap-3 flex-1 min-w-0 cursor-pointer select-none hover:opacity-90 transition-opacity"
          title={lang === "ar" ? "عرض تفاصيل جهة الاتصال" : "View contact details"}
        >
          {isTelegram || isInstagram || isMessenger ? (
            <ConversationAvatar conversation={conversation} className={cn("h-10 w-10 text-[14px]", isInstagram && "h-11 w-11")} />
          ) : (
            <div
              className={cn("rounded-full grid place-items-center font-semibold shrink-0 shadow-xs", isWhatsApp ? "h-10 w-10 text-[12px]" : "h-9 w-9 text-[13px]")}
              style={{ background: conversation.color, color: isWhatsApp ? "#54656f" : "#fff" }}
            >
              {conversation.initials}
            </div>
          )}
          <div className="flex-1 min-w-0 text-start">
            <div dir={isWhatsApp || isTelegram || isInstagram || isMessenger ? "auto" : undefined} className={cn("truncate", isWhatsApp ? "text-left text-[15px] font-semibold text-[#111b21]" : isTelegram ? "text-left text-[15px] font-medium text-[#222]" : isInstagram ? "text-[14px] font-semibold text-[#262626]" : isMessenger ? "text-[15px] font-semibold text-[#050505]" : "text-[14px] font-semibold", isApp && "text-foreground")}>
              {conversation.customer}
            </div>
            {!isMessenger && (
              <div className={cn("truncate text-[11.5px]", isWhatsApp ? "text-left text-[#667781]" : isTelegram ? "text-[#7f9db8]" : isInstagram ? "text-[#8e8e8e]" : "text-muted-foreground")}>
                {isTelegram ? "bot" : channel.name}
              </div>
            )}
          </div>
        </div>

        {/* Action icons in header */}
        {isMessenger && (
          <button
            type="button"
            aria-label={lang === "ar" ? "تغيير ثيم المحادثة" : "Change chat theme"}
            aria-expanded={themePickerOpen}
            aria-haspopup="dialog"
            onClick={() => setThemePickerOpen((open) => !open)}
            className="grid h-9 w-9 shrink-0 place-items-center rounded-full text-[#65676b] transition-colors hover:bg-[#f0f2f5] focus-visible:outline-none focus-visible:ring-2"
            style={{ color: messengerTheme.accent, "--tw-ring-color": messengerTheme.accent }}
          >
            <Palette className="h-[18px] w-[18px]" />
          </button>
        )}

        {(isWhatsApp || isInstagram || isMessenger || isTelegram) && (
          <button
            type="button"
            aria-label={t("inbox.searchMessages", "Search messages")}
            aria-expanded={searchOpen}
            onClick={() => { setSearchOpen((open) => !open); setSearchQuery(""); }}
            className={cn("grid h-9 w-9 shrink-0 place-items-center rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2", isWhatsApp ? "text-[#54656f] hover:bg-[#f5f6f6] focus-visible:ring-[#00a884]" : isInstagram ? "text-[#262626] hover:bg-[#f5f5f5] focus-visible:ring-[#3797f0]" : isMessenger ? "hover:bg-[#f0f2f5] focus-visible:ring-[#0084ff]" : "text-[#707e8b] hover:bg-[#f2f5f7] focus-visible:ring-[#3390ec]")}
            style={isMessenger ? { color: messengerTheme.accent } : undefined}
          >
            <Search className="h-[18px] w-[18px]" />
          </button>
        )}

        <button
          type="button"
          onClick={() => setContactDrawerOpen(true)}
          title={lang === "ar" ? "خيارات المحادثة والملف الشخصي" : "Chat options & Profile"}
          className="grid h-9 w-9 shrink-0 place-items-center rounded-full hover:bg-black/5 text-muted-foreground transition-colors"
        >
          <MoreVertical className="h-[18px] w-[18px]" />
        </button>
      </div>

      {/* Messenger Theme Dialog */}
      {isMessenger && themePickerOpen && (
        <div role="dialog" aria-label={lang === "ar" ? "ثيم المحادثة" : "Chat theme"} className="absolute left-3 top-[60px] z-30 w-[280px] rounded-xl border border-[#e4e6eb] bg-white p-3 shadow-[0_8px_28px_rgba(0,0,0,0.16)]">
          <div className="mb-1 text-[13px] font-semibold text-[#050505]">{lang === "ar" ? "لون المحادثة" : "Chat color"}</div>
          <p className="mb-2.5 text-[11px] text-[#65676b]">{lang === "ar" ? "يتغير الشكل في واجهة الانبوكس." : "Changes the appearance in this inbox."}</p>
          <div className="grid grid-cols-2 gap-1">
            {MESSENGER_CHAT_THEMES.map((theme) => (
              <button
                key={theme.id}
                type="button"
                aria-label={theme.name[lang === "ar" ? "ar" : "en"]}
                aria-pressed={messengerTheme.id === theme.id}
                title={theme.name[lang === "ar" ? "ar" : "en"]}
                onClick={() => { onMessengerThemeChange?.(theme.id); setThemePickerOpen(false); }}
                className={cn("flex min-w-0 items-center gap-2 rounded-lg px-2 py-1.5 text-[11px] text-[#65676b] hover:bg-[#f0f2f5] focus-visible:outline-none focus-visible:ring-2", messengerTheme.id === theme.id && "bg-[#f0f2f5]")}
                style={{ "--tw-ring-color": theme.accent }}
              >
                <span className={cn("grid h-8 w-8 shrink-0 place-items-center rounded-full border-2 border-white shadow-[0_0_0_1px_rgba(0,0,0,0.08)]", messengerTheme.id === theme.id && "ring-2 ring-offset-1")} style={{ background: theme.accent, "--tw-ring-color": theme.accent }}>
                  {messengerTheme.id === theme.id && <Check className="h-4 w-4 text-white" />}
                </span>
                <span className="truncate">{theme.name[lang === "ar" ? "ar" : "en"]}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Search Messages in Chat */}
      {(isWhatsApp || isInstagram || isMessenger || isTelegram) && searchOpen && (
        <div className={cn("flex h-12 shrink-0 items-center gap-2 border-b bg-white px-3", isWhatsApp ? "border-[#d1d7db]" : isInstagram ? "border-[#dbdbdb]" : isMessenger ? "border-[#e4e6eb]" : "border-[#e4e9ec]")}>
          <Search className={cn("h-4 w-4 shrink-0", isWhatsApp ? "text-[#667781]" : isInstagram ? "text-[#8e8e8e]" : isMessenger ? "text-[#65676b]" : "text-[#82919e]")} />
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

      {/* Messages Scroll Area */}
      <div
        ref={scrollRef}
        onScroll={handleMessagesScroll}
        className={cn(
          "flex-1 min-h-0 overflow-y-auto scrollbar-thin px-4 py-3 space-y-2",
          isWhatsApp && "px-5 py-4 space-y-2",
          isTelegram && "px-4 py-3 space-y-1.5 sm:px-6 sm:py-4 telegram-transient-scrollbar",
          isTelegram && telegramMessagesScrolling && "is-scrolling"
        )}
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
          const dayKey = isWhatsApp || isInstagram || isMessenger || isTelegram ? getMessageDayKey(m.createdAt) : "";
          const previousDayKey = (isWhatsApp || isInstagram || isMessenger || isTelegram) && index > 0 ? getMessageDayKey(visibleMessages[index - 1].createdAt) : "";
          return (
            <React.Fragment key={m.id}>
              {dayKey && dayKey !== previousDayKey && (
                <div className="flex justify-center py-1.5" aria-label={formatWhatsAppDay(m.createdAt, lang, t)}>
                  <span className={cn("rounded-md bg-white/90 px-2.5 py-1 text-[11px] font-medium shadow-[0_1px_0.5px_rgba(11,20,26,0.13)]", isTelegram ? "text-[#527da3]" : isMessenger ? "text-[#65676b]" : "text-[#54656f]")}>
                    {formatWhatsAppDay(m.createdAt, lang, t)}
                  </span>
                </div>
              )}
              <Bubble
                m={m}
                isApp={isApp}
                isWhatsApp={isWhatsApp}
                isInstagram={isInstagram}
                isMessenger={isMessenger}
                isTelegram={isTelegram}
                lang={lang}
                th={th}
                conversation={conversation}
                showIncomingAvatar={isMessenger && m.side !== "out" && (index === visibleMessages.length - 1 || visibleMessages[index + 1]?.side === "out")}
              />
            </React.Fragment>
          );
        })}

        {approval && (
          <div
            className="mt-2 rounded-xl px-3.5 py-3 text-[12.5px]"
            style={isApp ?
              { background: "hsl(var(--warning-soft))", border: "1px solid hsl(var(--warning) / 0.3)", color: "hsl(var(--warning))" } :
              { background: "#FFF8E1", border: "1px solid #FFE082", color: "#8a6d00" }}
          >
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
                style={{ background: "#16a34a" }}
              >
                {t("inbox.approve")}
              </button>
              <button
                type="button"
                disabled={pendingDecision}
                onClick={() => onDecline?.(conversation.id)}
                className="h-8 px-3 rounded-lg text-[12px] font-medium"
                style={{ background: isApp ? "hsl(var(--surface))" : "#fff", border: "1px solid #e5e7eb" }}
              >
                {t("inbox.decline")}
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Attachment & Emoji Popovers above input */}
      <ChannelEmojiStickerPicker
        isOpen={emojiPickerOpen}
        onClose={() => setEmojiPickerOpen(false)}
        onSelectEmoji={(emoji) => setText((prev) => prev + emoji)}
        onSelectSticker={(sticker) => {
          void onSend?.(conversation.id, `🖼️ ${sticker.label}`, { mediaType: "image", mediaUrl: sticker.url });
        }}
        lang={lang}
        isWhatsApp={isWhatsApp}
      />

      <ChannelAttachmentMenu
        isOpen={attachmentMenuOpen}
        onClose={() => setAttachmentMenuOpen(false)}
        channelId={channel.id}
        lang={lang}
        onFileSelected={(file, type) => {
          const previewUrl = URL.createObjectURL(file);
          void onSend?.(conversation.id, file.name, { mediaType: type, mediaUrl: previewUrl });
        }}
        onSendAction={(content) => {
          void onSend?.(conversation.id, content);
        }}
      />

      {/* Input Bar */}
      <div
        className={cn("shrink-0 p-2 relative z-20", isWhatsApp && "px-3 py-1 sm:px-4", isInstagram && "px-3 py-2", isMessenger && "px-4 py-3", isTelegram && "px-2 py-1 sm:px-3 sm:py-1.5")}
        style={isApp ? { background: "hsl(var(--card))", borderTop: "1px solid hsl(var(--border))" } : { background: isWhatsApp ? "#f0f2f5" : isTelegram ? "#f5f6f7" : isInstagram ? "#fff" : isMessenger ? "#fff" : th.inputBg, borderTop: "1px solid " + th.inputBorder }}
      >
        {isRecordingVoice ? (
          <ChannelVoiceRecorder
            isRecording={isRecordingVoice}
            onCancel={() => setIsRecordingVoice(false)}
            onSendVoice={(durationStr) => {
              void onSend?.(conversation.id, `🎤 رسالة صوتية (${durationStr})`, { mediaType: "audio", duration: durationStr });
            }}
            channelId={channel.id}
            lang={lang}
          />
        ) : isWhatsApp ? (
          <div dir="ltr" className="flex h-11 items-center gap-1.5 overflow-hidden rounded-full bg-white px-2 shadow-[0_1px_2px_rgba(0,0,0,0.12)] sm:h-14 sm:gap-2 sm:px-3" style={{ borderRadius: 9999 }}>
            <button
              type="button"
              onClick={() => { setAttachmentMenuOpen((v) => !v); setEmojiPickerOpen(false); }}
              aria-label={lang === "ar" ? "المرفقات" : "Attachments"}
              title={lang === "ar" ? "المرفقات" : "Attachments"}
              className="grid h-9 w-9 shrink-0 place-items-center rounded-full text-[#54656f] hover:bg-[#f5f6f6] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#00a884] transition-colors"
              style={{ color: "#54656f" }}
            >
              <Paperclip className="h-5 w-5" />
            </button>
            <button
              type="button"
              onClick={() => { setEmojiPickerOpen((v) => !v); setAttachmentMenuOpen(false); }}
              aria-label={lang === "ar" ? "الرموز التعبيرية والاستيكرز" : "Emoji & Stickers"}
              title={lang === "ar" ? "الرموز التعبيرية والاستيكرز" : "Emoji & Stickers"}
              className="grid h-9 w-9 shrink-0 place-items-center rounded-full text-[#54656f] hover:bg-[#f5f6f6] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#00a884] transition-colors"
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
                className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-[#00a884] text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#00a884] focus-visible:ring-offset-2 transition-transform hover:scale-105"
                title={t("inbox.send")}
                style={{ backgroundColor: "#00a884", color: "#fff" }}
              >
                <ArrowUpRight className="h-[18px] w-[18px]" />
              </button>
            ) : (
              <button
                type="button"
                onClick={() => setIsRecordingVoice(true)}
                aria-label={lang === "ar" ? "تسجيل رسالة صوتية" : "Record voice message"}
                title={lang === "ar" ? "تسجيل رسالة صوتية" : "Record voice message"}
                className="grid h-10 w-10 shrink-0 place-items-center rounded-full text-[#54656f] hover:bg-[#f5f6f6] hover:text-[#00a884] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#00a884] transition-colors"
                style={{ color: "#54656f" }}
              >
                <Mic className="h-[21px] w-[21px]" />
              </button>
            )}
          </div>
        ) : isTelegram ? (
          <div dir="ltr" className="flex h-10 items-center gap-1 rounded-md bg-white px-2 sm:h-11 sm:gap-2 sm:px-3" style={{ boxShadow: "0 1px 2px rgba(0,0,0,.08)" }}>
            <button
              type="button"
              onClick={() => setAttachmentMenuOpen((v) => !v)}
              aria-label={lang === "ar" ? "المرفقات" : "Attachments"}
              title={lang === "ar" ? "المرفقات" : "Attachments"}
              className="grid h-9 w-9 shrink-0 place-items-center rounded-full text-[#8a9aa8] hover:bg-[#eff8fd] hover:text-[#2aabee] transition-colors"
            >
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
            <button
              type="button"
              onClick={() => setEmojiPickerOpen((v) => !v)}
              aria-label={lang === "ar" ? "الرموز والاستيكرز" : "Emoji picker"}
              title={lang === "ar" ? "الرموز والاستيكرز" : "Emoji picker"}
              className="grid h-9 w-9 shrink-0 place-items-center rounded-full text-[#8a9aa8] hover:bg-[#eff8fd] hover:text-[#2aabee] transition-colors"
            >
              <Smile className="h-[21px] w-[21px]" />
            </button>
            {text.trim() ? (
              <button
                type="button"
                onClick={() => { void submitMessage(); }}
                disabled={sending}
                aria-label={t("inbox.send")}
                title={t("inbox.send")}
                className="grid h-9 w-9 shrink-0 place-items-center rounded-full text-[#2aabee] hover:bg-[#eff8fd] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#2aabee]"
              >
                <ArrowUpRight className="h-[19px] w-[19px]" />
              </button>
            ) : (
              <button
                type="button"
                onClick={() => setIsRecordingVoice(true)}
                aria-label={lang === "ar" ? "رسالة صوتية" : "Voice message"}
                title={lang === "ar" ? "رسالة صوتية" : "Voice message"}
                className="grid h-9 w-9 shrink-0 place-items-center rounded-full text-[#8a9aa8] hover:bg-[#eff8fd] hover:text-[#2aabee] transition-colors"
              >
                <Mic className="h-[21px] w-[21px]" />
              </button>
            )}
          </div>
        ) : isInstagram ? (
          <div dir="ltr" className="flex h-11 items-center gap-1 rounded-full border border-[#dbdbdb] bg-white px-2 sm:h-12 sm:px-3">
            <button
              type="button"
              onClick={() => setEmojiPickerOpen((v) => !v)}
              aria-label={lang === "ar" ? "الرموز التعبيرية" : "Emoji picker"}
              title={lang === "ar" ? "الرموز التعبيرية" : "Emoji picker"}
              className="grid h-9 w-9 shrink-0 place-items-center rounded-full text-[#262626] hover:bg-[#f5f5f5] transition-colors"
            >
              <Smile className="h-[21px] w-[21px]" />
            </button>
            <input
              value={text}
              onChange={(event) => setText(event.target.value)}
              dir={lang === "ar" ? "rtl" : "ltr"}
              onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void submitMessage(); } }}
              placeholder={t("inbox.typeMessage")}
              aria-label={t("inbox.typeMessage")}
              disabled={sending}
              className={cn("h-full min-w-0 flex-1 bg-transparent px-2 text-[13px] text-[#262626] outline-none placeholder:text-[#8e8e8e]", lang === "ar" ? "text-right" : "text-left")}
            />
            {!text.trim() ? (
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={() => setAttachmentMenuOpen((v) => !v)}
                  aria-label={lang === "ar" ? "إرسال صور أو ملفات" : "Media attachment"}
                  title={lang === "ar" ? "إرسال صور أو ملفات" : "Media attachment"}
                  className="grid h-9 w-9 shrink-0 place-items-center rounded-full text-[#262626] hover:bg-[#f5f5f5] transition-colors"
                >
                  <Paperclip className="h-[19px] w-[19px]" />
                </button>
                <button
                  type="button"
                  onClick={() => setIsRecordingVoice(true)}
                  aria-label={lang === "ar" ? "تسجيل رسالة صوتية" : "Voice note"}
                  title={lang === "ar" ? "تسجيل رسالة صوتية" : "Voice note"}
                  className="grid h-9 w-9 shrink-0 place-items-center rounded-full text-[#262626] hover:bg-[#f5f5f5] transition-colors"
                >
                  <Mic className="h-[19px] w-[19px]" />
                </button>
              </div>
            ) : (
              <button
                type="button"
                onClick={() => { void submitMessage(); }}
                disabled={sending}
                aria-label={t("inbox.send")}
                title={t("inbox.send")}
                className="shrink-0 px-2 text-[13px] font-semibold text-[#0095f6] hover:opacity-80 disabled:opacity-50"
              >
                {lang === "ar" ? "إرسال" : "Send"}
              </button>
            )}
          </div>
        ) : isMessenger ? (
          <div dir="ltr" className="flex h-11 items-center gap-2 rounded-full border border-[#e4e6eb] bg-white px-3">
            <button
              type="button"
              onClick={() => setAttachmentMenuOpen((v) => !v)}
              className="grid h-8 w-8 shrink-0 place-items-center rounded-full text-[#0084ff] hover:bg-[#f0f2f5]"
              title={lang === "ar" ? "إرفاق ملف أو صورة" : "Attach media"}
            >
              <Paperclip className="h-4 w-4" />
            </button>
            <button
              type="button"
              onClick={() => setEmojiPickerOpen((v) => !v)}
              className="grid h-8 w-8 shrink-0 place-items-center rounded-full text-[#0084ff] hover:bg-[#f0f2f5]"
              title={lang === "ar" ? "الرموز التعبيرية" : "Emoji picker"}
            >
              <Smile className="h-4 w-4" />
            </button>
            <input
              value={text}
              onChange={(event) => setText(event.target.value)}
              dir="auto"
              onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void submitMessage(); } }}
              placeholder={t("inbox.typeMessage")}
              aria-label={t("inbox.typeMessage")}
              disabled={sending}
              className={cn("h-full min-w-0 flex-1 bg-transparent px-2 text-[14px] text-[#050505] outline-none placeholder:text-[#65676b]", lang === "ar" ? "text-right" : "text-left")}
            />
            {text.trim() ? (
              <button
                type="button"
                onClick={() => { void submitMessage(); }}
                disabled={!text.trim() || sending}
                aria-label={t("inbox.send")}
                title={t("inbox.send")}
                className="grid h-8 w-8 shrink-0 place-items-center rounded-full text-white transition-opacity disabled:cursor-not-allowed disabled:opacity-40"
                style={{ background: th.out }}
              >
                <Send className="h-4 w-4" />
              </button>
            ) : (
              <button
                type="button"
                onClick={() => setIsRecordingVoice(true)}
                className="grid h-8 w-8 shrink-0 place-items-center rounded-full text-[#0084ff] hover:bg-[#f0f2f5]"
                title={lang === "ar" ? "رسالة صوتية" : "Voice note"}
              >
                <Mic className="h-4 w-4" />
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

      {/* Authentic Contact Details Drawer */}
      <ChannelContactDrawer
        isOpen={contactDrawerOpen}
        onClose={() => setContactDrawerOpen(false)}
        channel={channel}
        conversation={conversation}
        lang={lang}
        onOpenCustomerProfile={() => {
          setCustomer360Record({
            id: conversation.customer_id || conversation.id,
            name: conversation.customer,
            phone: conversation.customer_phone,
            lifetime_value: conversation.lifetime_value,
          });
        }}
      />

      {/* Customer 360 Drawer when requested from Contact Info */}
      {customer360Record && (
        <CustomerDrawer
          customer={customer360Record}
          onClose={() => setCustomer360Record(null)}
        />
      )}
    </div>
  );
}

// Subcomponent: Message Bubble
function Bubble({ m, isApp, isWhatsApp, isInstagram: _isInstagram, isMessenger: _isMessenger, isTelegram, lang: _lang, th, conversation: _conversation, showIncomingAvatar: _showIncomingAvatar }) {
  const out = m.side === "out";
  const showTail = !isApp && th?.tail;
  const isAudio = m.mediaType === "audio" || String(m.text || "").startsWith("🎤");
  const mediaUrl = m.mediaUrl;
  const isImage = m.mediaType === "image" || (mediaUrl && /\.(jpg|jpeg|png|webp|gif)$/i.test(mediaUrl));
  const isDocument = m.mediaType === "document" || (mediaUrl && /\.(pdf|doc|docx|xlsx|txt)$/i.test(mediaUrl));

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

          {/* Voice Note Bubble */}
          {isAudio ? (
            <VoiceBubble m={m} out={out} time={m.time} status={m.status} checkmarks={th.checkmarks} isWhatsApp />
          ) : isImage && mediaUrl ? (
            <div className="space-y-1.5">
              <div className="rounded-lg overflow-hidden max-w-[280px]">
                <img src={mediaUrl} alt="attachment" className="w-full max-h-64 object-cover rounded-lg" />
              </div>
              {m.text && !m.text.startsWith("blob:") && (
                <div className="text-[13px]">{m.text}</div>
              )}
              <div className="flex justify-end items-center gap-1 text-[11px] text-[#667781]" dir="ltr">
                <span>{m.time}</span>
                {out && th.checkmarks && (
                  m.status === "read" ? <CheckCheck className="h-3.5 w-3.5 text-[#53bdeb]" /> : <Check className="h-3.5 w-3.5" />
                )}
              </div>
            </div>
          ) : isDocument && mediaUrl ? (
            <div className="flex items-center gap-3 p-1">
              <div className="h-10 w-10 rounded-lg bg-[#7f66ff]/20 text-[#7f66ff] grid place-items-center">
                <FileText className="h-5 w-5" />
              </div>
              <div className="min-w-0 flex-1">
                <div className="text-[13px] font-medium truncate">{m.text || "Document"}</div>
                <div className="text-[11px] text-[#667781]">{m.time}</div>
              </div>
            </div>
          ) : (
            <div className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]" dir="auto">
              {m.text}{" "}
              <span className="inline-flex items-center gap-0.5 whitespace-nowrap align-baseline text-[11px] leading-none text-[#667781]" dir="ltr">
                <span>{m.time}</span>
                {out && th.checkmarks && (
                  m.status === "read"
                    ? <CheckCheck className="h-3.5 w-3.5 text-[#53bdeb]" />
                    : m.status === "delivered"
                      ? <CheckCheck className="h-3.5 w-3.5" />
                      : <Check className="h-3.5 w-3.5" />
                )}
                {m.ai && <Sparkles className="h-3 w-3 text-amber-500" />}
              </span>
            </div>
          )}
        </div>
      </div>
    );
  }

  if (isTelegram) {
    return (
      <div className={cn("flex", out ? "justify-end" : "justify-start")}>
        <div className={cn("relative max-w-[82%] rounded-xl px-3 py-2 text-[14px] leading-[1.38] shadow-[0_1px_2px_rgba(45,70,48,.14)] sm:max-w-[72%]", out ? "rounded-br-[4px]" : "rounded-bl-[4px]")} style={{ background: out ? th.out : th.in, color: out ? th.outText : th.inText }}>
          {isAudio ? (
            <VoiceBubble m={m} out={out} time={m.time} status={m.status} checkmarks={th.checkmarks} checkColor={th.checkColor} />
          ) : (
            <div className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]" dir="auto">
              {m.text}{" "}
              <span className="inline-flex items-center gap-0.5 whitespace-nowrap align-baseline text-[10px] leading-none text-[#90a0ab]" dir="ltr">
                <span>{m.time}</span>
                {out && th.checkmarks && (
                  m.status === "read"
                    ? <CheckCheck className="h-3 w-3" style={{ color: th.checkColor || "#3390ec" }} />
                    : <Check className="h-3 w-3" style={{ color: th.checkColor || "#3390ec" }} />
                )}
                {m.ai && <Sparkles className="h-3 w-3" />}
              </span>
            </div>
          )}
        </div>
      </div>
    );
  }

  // Messenger & Instagram
  return (
    <div className={cn("flex", out ? "justify-end" : "justify-start")}>
      <div
        className={cn("max-w-[82%] rounded-[18px] px-3.5 py-2 text-[14px] leading-[1.45] sm:max-w-[76%]", out ? "rounded-br-sm" : "rounded-bl-sm")}
        style={{ background: out ? th?.out || "#0084ff" : th?.in || "#f0f0f0", color: out ? th?.outText || "#fff" : th?.inText || "#111" }}
      >
        {isAudio ? (
          <VoiceBubble m={m} out={out} time={m.time} status={m.status} checkmarks={th?.checkmarks} />
        ) : (
          <div className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]" dir="auto">
            {m.text}{" "}
            <span dir="ltr" className={cn("inline-flex items-center gap-1 align-baseline text-[10px]", out ? "opacity-80" : "text-muted-foreground")}>
              {m.time}
              {out && th?.checkmarks && <CheckCheck className="h-3 w-3" />}
              {m.ai && <Sparkles className="h-3 w-3 text-amber-400" />}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

// Voice Note Player inside message bubble
function VoiceBubble({ m, out, time, status, checkmarks, isWhatsApp = false, checkColor: _checkColor }) {
  const [playing, setPlaying] = useState(false);

  return (
    <div className="flex items-center gap-3 py-1 min-w-[210px] sm:min-w-[250px]">
      <button
        type="button"
        onClick={() => setPlaying(!playing)}
        className={cn(
          "h-9 w-9 rounded-full flex items-center justify-center shrink-0 shadow-xs transition-transform hover:scale-105",
          isWhatsApp
            ? "bg-[#00a884] text-white"
            : out
            ? "bg-white text-primary"
            : "bg-primary text-white"
        )}
      >
        {playing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4 fill-current ml-0.5" />}
      </button>

      <div className="flex-1 space-y-1">
        {/* Animated / styled sound wave */}
        <div className="flex items-center gap-0.5 h-5">
          {[8, 14, 18, 12, 22, 16, 20, 10, 14, 18, 12, 16, 20, 14, 10, 18, 14, 12, 8].map((h, i) => (
            <span
              key={i}
              className={cn(
                "w-1 rounded-full transition-colors",
                playing && i < 11
                  ? isWhatsApp ? "bg-[#00a884]" : "bg-primary"
                  : isWhatsApp ? "bg-[#8696a0]" : out ? "bg-white/60" : "bg-black/30"
              )}
              style={{ height: `${h}px` }}
            />
          ))}
        </div>
        <div className="flex items-center justify-between text-[10.5px] opacity-80 tabular-nums">
          <span>{m.duration || "0:14"}</span>
          <span dir="ltr" className="flex items-center gap-1">
            <span>{time}</span>
            {out && checkmarks && (
              status === "read"
                ? <CheckCheck className="h-3 w-3 text-[#53bdeb]" />
                : <Check className="h-3 w-3" />
            )}
          </span>
        </div>
      </div>
    </div>
  );
}

function getMessageDayKey(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`;
}

function formatWhatsAppDay(iso, lang, _t) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const target = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const diff = (today.getTime() - target.getTime()) / 86400000;
  if (diff === 0) return lang === "ar" ? "اليوم" : "Today";
  if (diff === 1) return lang === "ar" ? "أمس" : "Yesterday";
  return date.toLocaleDateString(lang === "ar" ? "ar-EG" : "en-US", { weekday: "short", month: "short", day: "numeric" });
}
