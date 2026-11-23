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
  ImageIcon,
  Mic,
  Smile,
  Heart,
  MoreVertical,
  Send,
  Palette,
  Play,
  Pause,
  ThumbsUp,
  Reply,
  Copy,
} from "lucide-react";
import { cn } from "@/lib/utils";
import ConversationAvatar from "@/components/inbox/ConversationAvatar";
import { MESSENGER_CHAT_THEMES } from "@/lib/channels";
import { messengerBubbleBackground, messengerBubbleCorners, messengerGroup, messengerLinkHost, messengerLinkParts, messengerMessageShape, messengerQuoteText, messengerReactionSummary, messengerSeenMessageId, messengerStatusLine, messengerTimeDivider } from "./messengerChat";
import ChannelContactDrawer from "@/components/inbox/ChannelContactDrawer";
import ChannelEmojiStickerPicker from "@/components/inbox/ChannelEmojiStickerPicker";
import ChannelAttachmentMenu from "@/components/inbox/ChannelAttachmentMenu";
import IgQuickReplies, { quickReplyProblem } from "@/components/inbox/instagram/IgQuickReplies";
import CustomerDrawer from "@/components/customers/CustomerDrawer";
import ImageViewer from "./whatsapp/ImageViewer";
import { galleryOf } from "./whatsapp/mediaGallery";
import WhatsAppBubble, { WHATSAPP_FONT } from "./whatsapp/WhatsAppBubble";
import ContactInfoPanel from "./whatsapp/ContactInfoPanel";
import ChatHeader from "./whatsapp/ChatHeader";
import Composer from "./whatsapp/Composer";
import TemplatePicker from "./whatsapp/TemplatePicker";
import InteractiveComposer from "./whatsapp/InteractiveComposer";
import { composerAvailability } from "./whatsapp/composerState";
import AttachPreview from "./whatsapp/AttachPreview";
import VoiceRecorder from "./whatsapp/VoiceRecorder";
import MessengerVoiceRecorder from "./MessengerVoiceRecorder";
import { checkFile } from "./whatsapp/attachments";
import { ACCEPT as IG_ACCEPT, checkFile as checkInstagramFile } from "./instagram/igAttachments";
import IgAttachPreview from "./instagram/IgAttachPreview";
import ChannelAttachPreview from "./ChannelAttachPreview";
import { checkFile as checkChannelFile, mimeOf as mimeOfChannelFile } from "./channelAttachments";
import { uploadMedia } from "@/lib/inboxSend";
import { ChoiceBody, ContactBody, DocumentBody, InteractiveBody, LocationBody, OrderBody, PhotoBody, StickerBody, UnsupportedBody, VideoBody } from "./whatsapp/MessageBodies";
import { InstagramBubble } from "./instagram/InstagramBubble";
import IgAvatar from "@/components/instagram/IgAvatar";
import { IgBack, IgInfo, IgVerified } from "@/components/instagram/igIcons";
import { displayBody, looksLikeFileName, messageKind } from "./whatsapp/messageKind";
import { api } from "@/lib/api";
import { readSignalBody, shouldSignalTyping, supportsReadSignal } from "./whatsapp/readSignal";
import { formatCurrency } from "@/lib/regional";
import { isAwayFromBottom, unreadSince } from "./whatsapp/scrollState";
import { ChevronDownIcon } from "./whatsapp/icons";
import MessageStatus from "./whatsapp/MessageStatus";

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
  sendError = "",
  pendingDecision = false,
  t,
  onSend,
  onReact,
  onListStateChange,
  pinnedCount = 0,
  onApprove,
  onDecline,
  onViewProfile,
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
  const messengerImageInput = useRef(null);
  const messengerGifInput = useRef(null);
  const igFileInput = useRef(null);
  const [quickOpen, setQuickOpen] = useState(false);
  const [quickReplies, setQuickReplies] = useState([]);
  const [isRecordingVoice, setIsRecordingVoice] = useState(false);
  const [templatesOpen, setTemplatesOpen] = useState(false);
  const [interactiveOpen, setInteractiveOpen] = useState(false);
  // WhatsApp only: the file the agent picked (or the voice note just recorded),
  // shown in a preview until Send uploads it and sends the message.
  const [attachment, setAttachment] = useState(null); // { file, kind, asSticker, audioUrl? }
  const [uploading, setUploading] = useState(false);
  const [attachError, setAttachError] = useState("");
  const [customer360Record, setCustomer360Record] = useState(null);
  const [waCustomer, setWaCustomer] = useState(null);

  // The real customer record (email, spend, purchase block) is read only while
  // the WhatsApp contact panel is open, and never trusted past this chat.
  const waCustomerId = conversation?.customerId || null;
  useEffect(() => {
    setWaCustomer(null);
    if (!contactDrawerOpen || channel.id !== "whatsapp" || !waCustomerId) return undefined;
    let alive = true;
    api(`/customers/${waCustomerId}`).then((row) => { if (alive) setWaCustomer(row); }).catch(() => { if (alive) setWaCustomer(null); });
    return () => { alive = false; };
  }, [contactDrawerOpen, channel.id, waCustomerId]);

  async function toggleBuyBlock(block) {
    if (!waCustomerId) return;
    try {
      const saved = await api(`/customers/${waCustomerId}/${block ? "block" : "unblock"}`, { method: "POST" });
      setWaCustomer((previous) => (previous ? { ...previous, is_blocked: Boolean(saved?.is_blocked) } : previous));
    } catch { /* the panel keeps showing the real state */ }
  }

  const scrollRef = useRef(null);
  const [awayFromBottom, setAwayFromBottom] = useState(false);
  const [replyingTo, setReplyingTo] = useState(null);
  const [viewerId, setViewerId] = useState(null);
  const [lastSeenId, setLastSeenId] = useState(null);
  const telegramScrollTimerRef = useRef(null);
  const preserveScrollRef = useRef(null);
  const messageViewportRef = useRef({ conversationId: null, latestMessageId: null });

  const isApp = channel.theme === "app";
  const isWhatsApp = channel.id === "whatsapp";
  const isInstagram = channel.id === "instagram";

  // "typing…" on the customer's phone while an agent writes a WhatsApp, Instagram or Messenger reply. One
  // signal per 20s (Meta clears it after 25s), only inside the 24h window, and only
  // while there is text: it is a courtesy, so a failure is silent.
  const typingSentAtRef = useRef(null);
  useEffect(() => {
    if (!(isWhatsApp || isInstagram || isMessenger) || !supportsReadSignal(conversation)) return;
    if (!shouldSignalTyping({ text, lastSentAt: typingSentAtRef.current, lastCustomerMessageAt: conversation.lastCustomerMessageAt })) return;
    typingSentAtRef.current = Date.now();
    api(`/conversations/${conversation.id}/read-signal`, { method: "POST", body: readSignalBody(true) }).catch(() => {});
  }, [text, isWhatsApp, isInstagram, conversation?.id, conversation?.lastCustomerMessageAt]);
  // A different chat starts its own 20s clock.
  useEffect(() => { typingSentAtRef.current = null; }, [conversation?.id]);
  const isMessenger = channel.id === "messenger";
  const isTelegram = channel.id === "telegram";
  const messengerTheme = MESSENGER_CHAT_THEMES.find((theme) => theme.id === messengerThemeId) || MESSENGER_CHAT_THEMES[0];
  const th = isApp ? null : isMessenger ? { ...channel.theme, out: messengerTheme.accent } : channel.theme;
  const allMessages = conversation?.messages || [];

  const messageBackgroundStyle = isWhatsApp ? {
    // Our own doodle tile (light or dark by theme) on WhatsApp's wallpaper
    // colour: nothing is fetched from Meta.
    backgroundColor: "var(--wa-bg-chat)",
    backgroundImage: "var(--wa-wallpaper)",
    backgroundRepeat: "repeat",
    backgroundSize: "160px 176px",
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
  // Instagram marks only the newest message WE sent as "Seen"; a search never changes which one it is.
  const lastSentId = (() => {
    for (let i = allMessages.length - 1; i >= 0; i -= 1) {
      if (allMessages[i].side === "out" && allMessages[i].senderType !== "system") return allMessages[i].id;
    }
    return null;
  })();

  // Messenger's only receipt is the reader's avatar under the last bubble they opened, and its
  // header says "Active now" while the customer is writing. Both are derived, never guessed.
  const messengerSeenId = isMessenger ? messengerSeenMessageId(allMessages) : null;
  const messengerStatus = isMessenger ? messengerStatusLine(allMessages, lang) : null;

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
    } else if (previous.conversationId !== conversation.id) {
      element.scrollTop = element.scrollHeight;
      setLastSeenId(null);
    } else if (previous.latestMessageId !== latestMessageId) {
      const newest = messages.at(-1);
      // WhatsApp never yanks you away from history you are reading: a customer
      // message that arrives while you are scrolled up waits behind the button.
      if (isWhatsApp && newest?.side === "in" && isAwayFromBottom(element)) {
        setLastSeenId((seen) => seen ?? previous.latestMessageId);
      } else {
        element.scrollTop = element.scrollHeight;
      }
    }
    messageViewportRef.current = { conversationId: conversation.id, latestMessageId };
  }, [conversation?.id, conversation?.messages]);

  useEffect(() => {
    setText("");
    setReplyingTo(null);
    setViewerId(null);
    setSearchQuery("");
    setSearchOpen(false);
    setThemePickerOpen(false);
    setContactDrawerOpen(false);
    setEmojiPickerOpen(false);
    setAttachmentMenuOpen(false);
    setIsRecordingVoice(false);
    setAttachment(null);
    setUploading(false);
    setAttachError("");
  }, [conversation?.id]);

  useEffect(() => () => clearTimeout(telegramScrollTimerRef.current), []);

  async function submitMessage(overrideBody) {
    const body = String(overrideBody ?? text).trim();
    if (!body || sending || !conversation) return;
    const buttons = isInstagram ? quickReplies.map((t) => t.trim()).filter(Boolean) : [];
    if (isInstagram && quickReplies.length && quickReplyProblem(quickReplies, lang)) return;
    const opts = { ...(replyingTo ? { replyTo: replyingTo } : {}), ...(buttons.length ? { quickReplies: buttons } : {}) };
    const sent = await onSend?.(conversation.id, body, Object.keys(opts).length ? opts : undefined);
    if (sent !== false) {
      setQuickReplies([]);
      setQuickOpen(false);
      setText("");
      setReplyingTo(null);
      setEmojiPickerOpen(false);
      setAttachmentMenuOpen(false);
    }
  }

  // A file was picked: check it here so a wrong one is refused before any upload.
  function pickFile(file, { asSticker = false } = {}) {
    const checked = isInstagram ? checkInstagramFile(file, { lang })
      : isMessenger || isTelegram ? checkChannelFile(file, { channel: channel.id, lang })
      : checkFile(file, { lang, asSticker });
    if (!checked.ok) { setAttachError(checked.error); return; }
    setAttachError("");
    setAttachment({ file, kind: checked.kind, asSticker });
  }

  async function sendAttachment(caption) {
    if (!attachment || uploading || !conversation) return;
    setUploading(true);
    setAttachError("");
    const up = await uploadMedia(conversation.id, attachment.file, { asSticker: attachment.asSticker, mimeOf: isMessenger || isTelegram ? mimeOfChannelFile : null });
    if (!up.ok) { setUploading(false); setAttachError(up.error); return; }
    const sent = await onSend?.(conversation.id, caption, {
      mediaId: up.media.media_id,
      mediaKind: up.media.kind,
      filename: up.media.filename,
      previewFile: attachment.file,
      replyTo: replyingTo || undefined,
    });
    setUploading(false);
    if (sent === false) { setAttachError(lang === "ar" ? "تم رفع الملف لكن تعذّر إرساله. حاول مرة أخرى." : "The file was uploaded but could not be sent. Try again."); return; }
    setAttachment(null);
    setReplyingTo(null);
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
    const away = isAwayFromBottom(event.currentTarget);
    setAwayFromBottom(away);
    if (!away) setLastSeenId(null);
  }, [isTelegram, loadOlderAtTop]);

  if (!conversation) {
    return (
      <div className={cn("flex-1 grid place-items-center border bg-card text-center p-8", isWhatsApp ? "rounded-xl border-[color:var(--wa-divider)] lg:rounded-none lg:border-y-0 lg:border-r-0 lg:border-l-0" : isInstagram ? "rounded-none border-0 bg-white" : "rounded-2xl border-border", className, "lg:items-center lg:justify-center")}>
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
      className={cn("relative flex-1 flex flex-col min-h-0 overflow-hidden border", isWhatsApp ? cn("wa-scope rounded-xl border-[color:var(--wa-divider)] lg:rounded-none lg:border-y-0 lg:border-r-0 lg:border-l-0", contactDrawerOpen && "lg:pe-[308px]") : isInstagram ? "rounded-none border-0 border-s border-[#dbdbdb] bg-white" : isMessenger ? "rounded-none border-0 border-s border-[#e4e6eb] bg-white" : "rounded-2xl border-border", className)}
      style={isApp ? undefined : { background: th.chatBg }}
    >
      {isWhatsApp ? (
        <ChatHeader
          conversation={conversation}
          lang={lang}
          pinnedCount={pinnedCount}
          searchOpen={searchOpen}
          AvatarComponent={ConversationAvatar}
          onBack={onBack}
          onOpenInfo={() => setContactDrawerOpen(true)}
          onToggleSearch={() => { setSearchOpen((open) => !open); setSearchQuery(""); }}
          onChange={(body) => onListStateChange?.(conversation, body)}
        />
      ) : (
      <>
      <div
        dir={isWhatsApp || isTelegram ? "ltr" : isInstagram || isMessenger ? (lang === "ar" ? "rtl" : "ltr") : undefined}
        className={cn("relative flex items-center gap-3 px-4 shrink-0", isWhatsApp ? "h-[60px] px-4" : isTelegram ? "h-[66px] px-5" : isInstagram ? "h-[64px] px-4" : isMessenger ? "h-16 px-5" : "h-14")}
        style={isApp ? { background: "hsl(var(--card))", borderBottom: "1px solid hsl(var(--border))" } : { background: th.headerBg, color: th.headerText, borderBottom: (isWhatsApp || isTelegram || isInstagram || isMessenger) ? "1px solid " + th.divider : undefined }}
      >
        {isInstagram && onBack && (
          <button type="button" onClick={onBack} aria-label={lang === "ar" ? "رجوع" : "Back"} className="grid h-9 w-9 shrink-0 place-items-center rounded-full md:hidden"><IgBack className="rtl:-scale-x-100" /></button>
        )}
        {(isWhatsApp || isMessenger) && onBack && (
          <button
            type="button"
            onClick={onBack}
            aria-label={t("inbox.backToChats", "Back to chats")}
            title={t("inbox.backToChats", "Back to chats")}
            className={cn("-mx-1 grid h-9 w-9 shrink-0 place-items-center rounded-full transition-colors hover:bg-black/5 focus-visible:outline-none focus-visible:ring-2 lg:hidden", isWhatsApp ? "text-[color:var(--wa-text-icon)] focus-visible:ring-[color:var(--wa-green)]" : "text-[#65676b] focus-visible:ring-[#0084ff]")}
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
              style={{ background: conversation.color, color: isWhatsApp ? "var(--wa-text-icon)" : "#fff" }}
            >
              {conversation.initials}
            </div>
          )}
          <div className="flex-1 min-w-0 text-start">
            <div dir={isWhatsApp || isTelegram || isInstagram || isMessenger ? "auto" : undefined} className={cn("truncate", isWhatsApp ? "text-left text-[15px] font-semibold text-[color:var(--wa-text)]" : isTelegram ? "text-left text-[15px] font-medium text-[#222]" : isInstagram ? "text-[14px] font-semibold text-[#262626]" : isMessenger ? "text-[15px] font-semibold text-[#050505]" : "text-[14px] font-semibold", isApp && "text-foreground")}>
              {conversation.customer}
            </div>
            {isMessenger ? (
              // Messenger prints "Active now" while the customer is writing, otherwise the page name.
              <div data-testid="messenger-presence" className="truncate text-[13px] text-[#65676B]">
                {channel.name}
              </div>
            ) : (
              <div className={cn("truncate text-[11.5px]", isWhatsApp ? "text-left text-[color:var(--wa-text-secondary)]" : isTelegram ? "text-[#7f9db8]" : isInstagram ? "text-[#8e8e8e]" : "text-muted-foreground")}>
                {isTelegram ? "bot" : isInstagram ? (String(conversation.handle || "").replace(/^@/, "") || channel.name) : channel.name}
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
            className={cn("grid h-9 w-9 shrink-0 place-items-center rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2", isWhatsApp ? "text-[color:var(--wa-text-icon)] hover:bg-[var(--wa-bg-hover)] focus-visible:ring-[color:var(--wa-green)]" : isInstagram ? "text-[#262626] hover:bg-[#f5f5f5] focus-visible:ring-[#3797f0]" : isMessenger ? "hover:bg-[#f0f2f5] focus-visible:ring-[#0084ff]" : "text-[#707e8b] hover:bg-[#f2f5f7] focus-visible:ring-[#3390ec]")}
            style={isMessenger ? { color: messengerTheme.accent } : undefined}
          >
            <Search className="h-[18px] w-[18px]" />
          </button>
        )}

        <button
          type="button"
          onClick={() => setContactDrawerOpen(true)}
          title={isInstagram ? (lang === "ar" ? "معلومات المحادثة" : "Conversation information") : lang === "ar" ? "خيارات المحادثة والملف الشخصي" : "Chat options & Profile"}
          aria-label={isInstagram ? (lang === "ar" ? "معلومات المحادثة" : "Conversation information") : lang === "ar" ? "خيارات المحادثة والملف الشخصي" : "Chat options & Profile"}
          className={cn("grid h-9 w-9 shrink-0 place-items-center rounded-full transition-colors", isInstagram ? "text-[#0c1014] hover:opacity-60" : "hover:bg-black/5 text-muted-foreground")}
        >
          {isInstagram ? <IgInfo /> : <MoreVertical className="h-[18px] w-[18px]" />}
        </button>
      </div>

      </>
      )}

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
        <div className={cn("flex h-12 shrink-0 items-center gap-2 border-b bg-[var(--wa-bg-panel)] px-3", isWhatsApp ? "border-[color:var(--wa-divider)]" : isInstagram ? "border-[#dbdfe4]" : isMessenger ? "border-[#e4e6eb]" : "border-[#e4e9ec]")}>
          <Search className={cn("h-4 w-4 shrink-0", isWhatsApp ? "text-[color:var(--wa-text-secondary)]" : isInstagram ? "text-[#8e8e8e]" : isMessenger ? "text-[#65676b]" : "text-[#82919e]")} />
          <input
            type="search"
            autoFocus
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            dir={lang === "ar" ? "rtl" : "ltr"}
            aria-label={t("inbox.searchMessages", "Search messages")}
            placeholder={t("inbox.searchMessages", "Search messages")}
            className={cn("min-w-0 flex-1 bg-transparent text-[13px] outline-none placeholder:text-[#8696a0]", isWhatsApp ? "text-[color:var(--wa-text)]" : "text-[#222]", lang === "ar" ? "text-right" : "text-left")}
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
          "flex-1 min-h-0 overflow-y-auto scrollbar-thin px-4 py-3",
          // Messenger spaces its own bubbles (2px inside a run, 8px between runs), so it takes no blanket gap.
          !isMessenger && "space-y-2",
          isWhatsApp && "px-5 py-4 space-y-2",
          isTelegram && "px-4 py-3 space-y-1.5 sm:px-6 sm:py-4 telegram-transient-scrollbar",
          isTelegram && telegramMessagesScrolling && "is-scrolling"
        )}
        style={messageBackgroundStyle}
      >
        {loadingOlderMessages && <div role="status" className="py-2 text-center text-[11.5px] text-muted-foreground">{t("common.loading")}</div>}
        {isInstagram && !hasOlderMessages && !loadingMessages && !searchQuery.trim() && (
          <div data-testid="ig-thread-intro" className="flex flex-col items-center px-4 pb-6 pt-8 text-center">
            <IgAvatar src={conversation.avatarUrl} size={96} />
            <p dir="auto" className="mt-3 flex items-center gap-1 text-[20px] font-semibold text-[#0c1014]">{conversation.customer}{conversation.verified && <IgVerified size={14} />}</p>
            <p className="text-[14px] text-[#6a717a]"><span dir="ltr">{String(conversation.handle || "").replace(/^@/, "") || "Instagram"}</span> · Instagram</p>
            {onViewProfile && <button type="button" onClick={onViewProfile} className="ig-fill mt-4 inline-flex h-8 items-center rounded-[8px] px-4 text-[14px] font-semibold leading-[18px] text-[#0c1014] [--ig-fill:#f0f2f5] [--ig-fill-hover:#dbdfe4]">{lang === "ar" ? "عرض الملف الشخصي" : "View profile"}</button>}
          </div>
        )}
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
        {isMessenger && !loadingMessages && !messagesError && (conversation.messages || []).length === 0 && (
          <div data-testid="messenger-empty" role="status" className="flex flex-col items-center gap-2 py-12">
            <ConversationAvatar conversation={conversation} className="h-[60px] w-[60px] text-[20px]" />
            <div dir="auto" className="text-[17px] font-bold text-[#050505]">{conversation.customer || conversation.name}</div>
          </div>
        )}
        {!isMessenger && !loadingMessages && !messagesError && (conversation.messages || []).length === 0 && (
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
          // A run of bubbles from one person is one visual group in Messenger.
          const messengerRow = isMessenger ? messengerGroup(visibleMessages, index) : null;
          return (
            <React.Fragment key={m.id}>
              {isMessenger ? (
                messengerTimeDivider(visibleMessages, index) && (
                  <div data-testid="messenger-time-divider" className="flex justify-center py-3">
                    <span dir="auto" className="text-[12px] font-medium text-[#65676b]">
                      {dayKey !== previousDayKey ? `${formatWhatsAppDay(m.createdAt, lang, t)} ${m.time}` : m.time}
                    </span>
                  </div>
                )
              ) : dayKey && dayKey !== previousDayKey && (
                <div className={cn("flex justify-center", isInstagram ? "py-3" : "py-1.5")} aria-label={formatWhatsAppDay(m.createdAt, lang, t)}>
                  {/* Instagram prints the day as plain grey text, no pill and no shadow. */}
                  <span className={cn(isInstagram ? "text-[12px] text-[#6a717a]" : "rounded-lg px-3 py-1.5 text-[12.5px] shadow-[0_1px_0.5px_rgba(11,20,26,0.13)]", !isInstagram && (!isTelegram && !isMessenger && isWhatsApp ? "bg-[var(--wa-bg-panel)] text-[color:var(--wa-text-secondary)]" : "bg-white/90 font-medium"), !isInstagram && (isTelegram ? "text-[#527da3]" : isMessenger ? "text-[#65676b]" : !isWhatsApp && "text-[#54656f]"))}>
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
                onReply={setReplyingTo}
                onReact={onReact}
                onOpenImage={setViewerId}
                showSeen={isInstagram && m.status === "read" && m.id === lastSentId}
                messengerRow={messengerRow}
                messengerTheme={messengerTheme}
                showSeenAvatar={isMessenger && m.id === messengerSeenId}
                showIncomingAvatar={isMessenger && m.side !== "out" && (index === visibleMessages.length - 1 || visibleMessages[index + 1]?.side === "out")}
              />
            </React.Fragment>
          );
        })}

        {messengerStatus && (
          <div data-testid="messenger-status-line" className="mt-1 px-1 text-end text-[11px] text-[#65676b]" dir="auto">{messengerStatus}</div>
        )}

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
      {isWhatsApp && awayFromBottom && (
        <div className="pointer-events-none relative z-20 h-0">
          <button
            type="button"
            data-testid="jump-to-latest"
            onClick={() => {
              const el = scrollRef.current;
              if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
              setLastSeenId(null);
            }}
            aria-label={lang === "ar" ? "الانتقال لآخر الرسائل" : "Jump to latest messages"}
            title={lang === "ar" ? "الانتقال لآخر الرسائل" : "Jump to latest messages"}
            className="pointer-events-auto absolute -top-14 end-4 grid h-10 w-10 place-items-center rounded-full bg-white text-[#54656f] shadow-[0_1px_4px_rgba(11,20,26,0.3)] transition-colors hover:bg-[#f5f6f6] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#00a884]"
          >
            <ChevronDownIcon size={24} />
            {unreadSince(conversation.messages, lastSeenId) > 0 && (
              <span data-testid="jump-unread" className="absolute -top-2 start-1/2 grid h-5 min-w-5 -translate-x-1/2 place-items-center rounded-full bg-[#25d366] px-1 text-[11px] font-semibold leading-none text-white" dir="ltr">
                {unreadSince(conversation.messages, lastSeenId)}
              </span>
            )}
          </button>
        </div>
      )}

      {/* Attachment & Emoji Popovers above input */}
      <ChannelEmojiStickerPicker
        isOpen={emojiPickerOpen}
        onClose={() => setEmojiPickerOpen(false)}
        onSelectEmoji={(emoji) => setText((prev) => prev + emoji)}
        lang={lang}
        isWhatsApp={isWhatsApp}
      />

      <ChannelAttachmentMenu
        isOpen={attachmentMenuOpen && !isWhatsApp && !isInstagram}
        onClose={() => setAttachmentMenuOpen(false)}
        channelId={channel.id}
        lang={lang}
        onFileSelected={(file) => pickFile(file)}
      />

      {isWhatsApp && (
        <TemplatePicker
          open={templatesOpen}
          lang={lang}
          fontFamily={WHATSAPP_FONT}
          onClose={() => setTemplatesOpen(false)}
          loadTemplates={async () => (await api("/message-templates?status=approved&provider=whatsapp"))?.items || []}
          onSend={async (template) => (await onSend?.(conversation.id, "", { template })) !== false}
        />
      )}

      {isWhatsApp && (
        <InteractiveComposer
          open={interactiveOpen}
          lang={lang}
          fontFamily={WHATSAPP_FONT}
          windowOpen={composerAvailability({ lastCustomerMessageAt: conversation.lastCustomerMessageAt, now: new Date() }).canType}
          sendError={sendError}
          onClose={() => setInteractiveOpen(false)}
          onSend={async (interactive) => (await onSend?.(conversation.id, "", { interactive })) !== false}
        />
      )}

      {isWhatsApp && attachment && (
        <AttachPreview
          file={attachment.file}
          kind={attachment.kind}
          audioUrl={attachment.audioUrl}
          busy={uploading}
          error={attachError}
          lang={lang}
          onSend={(caption) => { void sendAttachment(caption); }}
          onCancel={() => { if (attachment.audioUrl) URL.revokeObjectURL(attachment.audioUrl); setAttachment(null); setAttachError(""); }}
        />
      )}
      {isInstagram && attachment && (
        <IgAttachPreview
          file={attachment.file}
          kind={attachment.kind}
          busy={uploading}
          error={attachError}
          lang={lang}
          onSend={() => { void sendAttachment(""); }}
          onCancel={() => { setAttachment(null); setAttachError(""); }}
        />
      )}
      {(isMessenger || isTelegram) && attachment && (
        <ChannelAttachPreview
          channel={channel.id}
          file={attachment.file}
          kind={attachment.kind}
          busy={uploading}
          error={attachError}
          lang={lang}
          onSend={(caption) => { void sendAttachment(caption); }}
          onCancel={() => { setAttachment(null); setAttachError(""); }}
        />
      )}
      {(isMessenger || isTelegram) && !attachment && attachError && (
        <div role="alert" data-testid="channel-attach-pick-error" dir={lang === "ar" ? "rtl" : "ltr"} className="mx-3 mb-1 flex items-start gap-2 rounded-lg bg-[#fde8ec] px-3 py-2 text-[13px] text-[#7a1230]">
          <span className="flex-1">{attachError}</span>
          <button type="button" onClick={() => setAttachError("")} aria-label={lang === "ar" ? "إغلاق" : "Dismiss"} className="shrink-0">×</button>
        </div>
      )}
      {isInstagram && !attachment && attachError && (
        <div role="alert" data-testid="ig-attach-pick-error" dir={lang === "ar" ? "rtl" : "ltr"} className="mx-3 mb-1 flex items-start gap-2 rounded-lg bg-[#f3f5f7] px-3 py-2 text-[13px] text-[#ed4956]">
          <span className="flex-1">{attachError}</span>
          <button type="button" onClick={() => setAttachError("")} aria-label={lang === "ar" ? "إغلاق" : "Dismiss"} className="shrink-0">×</button>
        </div>
      )}
      {isWhatsApp && !attachment && attachError && (
        <div role="alert" data-testid="attach-pick-error" dir={lang === "ar" ? "rtl" : "ltr"} className="mx-3 mb-1 flex items-start gap-2 rounded-lg bg-[#fde8ec] px-3 py-2 text-[13px] text-[#7a1230]">
          <span className="flex-1">{attachError}</span>
          <button type="button" onClick={() => setAttachError("")} aria-label={lang === "ar" ? "إغلاق" : "Dismiss"} className="shrink-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#00a884]">×</button>
        </div>
      )}

      {/* Input Bar */}
      <div
        className={cn("shrink-0 p-2 relative z-20", isWhatsApp && "px-0 py-0", isInstagram && "px-3 py-2", isMessenger && "px-4 py-3", isTelegram && "px-2 py-1 sm:px-3 sm:py-1.5")}
        style={isApp ? { background: "hsl(var(--card))", borderTop: "1px solid hsl(var(--border))" } : { background: isWhatsApp ? "transparent" : isTelegram ? "#f5f6f7" : isInstagram ? "#fff" : isMessenger ? "#fff" : th.inputBg, borderTop: isWhatsApp ? "none" : "1px solid " + th.inputBorder }}
      >
        {isWhatsApp && isRecordingVoice ? (
          <VoiceRecorder
            lang={lang}
            onCancel={() => setIsRecordingVoice(false)}
            onError={(message) => setAttachError(message)}
            onDone={(file) => { setIsRecordingVoice(false); setAttachError(""); setAttachment({ file, kind: "audio", asSticker: false, audioUrl: URL.createObjectURL(file) }); }}
          />
        ) : isWhatsApp ? (
          <Composer
            value={text}
            onChange={setText}
            onSend={() => { void submitMessage(); }}
            onToggleEmoji={() => { setEmojiPickerOpen((v) => !v); setAttachmentMenuOpen(false); }}
            onCancelReply={() => setReplyingTo(null)}
            replyingTo={replyingTo}
            customerName={conversation.customer}
            lastCustomerMessageAt={conversation.lastCustomerMessageAt}
            sending={sending || uploading}
            lang={lang}
            fontFamily={WHATSAPP_FONT}
            onPickFile={pickFile}
            onStartVoice={() => { setAttachError(""); setIsRecordingVoice(true); }}
            onOpenTemplates={() => setTemplatesOpen(true)}
            onOpenInteractive={() => setInteractiveOpen(true)}
          />
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
            {text.trim() && (
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
            )}
          </div>
        ) : isInstagram ? (
          <>
          {quickOpen && <IgQuickReplies items={quickReplies} onChange={setQuickReplies} onClose={() => setQuickOpen(false)} lang={lang} />}
          <div dir="ltr" className="flex h-[46px] items-center gap-1 rounded-full border border-[#dbdfe4] bg-white px-3">
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
                <input ref={igFileInput} type="file" accept={IG_ACCEPT} hidden data-testid="ig-chat-file-input"
                  onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) pickFile(f); }} />
                <button
                  type="button"
                  onClick={() => igFileInput.current?.click()}
                  disabled={sending || uploading}
                  aria-label={lang === "ar" ? "إرسال صور أو ملفات" : "Media attachment"}
                  title={lang === "ar" ? "إرسال صور أو ملفات" : "Media attachment"}
                  className="grid h-9 w-9 shrink-0 place-items-center rounded-full text-[#262626] hover:bg-[#f5f5f5] transition-colors disabled:opacity-50"
                >
                  <ImageIcon className="h-[19px] w-[19px]" />
                </button>
                <button
                  type="button"
                  data-testid="ig-send-heart"
                  onClick={() => { void onSend?.(conversation.id, "", { heart: true }); }}
                  disabled={sending}
                  aria-label={lang === "ar" ? "إرسال قلب" : "Send a heart"}
                  title={lang === "ar" ? "إرسال قلب" : "Send a heart"}
                  className="grid h-9 w-9 shrink-0 place-items-center rounded-full text-[#262626] hover:bg-[#f5f5f5] transition-colors disabled:opacity-50"
                >
                  <Heart className="h-[19px] w-[19px]" />
                </button>
              </div>
            ) : (
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  data-testid="ig-quick-toggle"
                  aria-pressed={quickOpen}
                  onClick={() => { if (!quickOpen && !quickReplies.length) setQuickReplies([""]); setQuickOpen((v) => !v); }}
                  className={cn("shrink-0 rounded-full px-2.5 py-1 text-[12px] font-semibold hover:bg-[#f3f5f7]", quickReplies.some((q) => q.trim()) ? "text-[#0095f6]" : "text-[#6a717a]")}
                >
                  {lang === "ar" ? "أزرار" : "Buttons"}{quickReplies.filter((q) => q.trim()).length ? ` (${quickReplies.filter((q) => q.trim()).length})` : ""}
                </button>
                <button
                  type="button"
                  onClick={() => { void submitMessage(); }}
                  disabled={sending || Boolean(quickReplyProblem(quickReplies, lang))}
                  aria-label={t("inbox.send")}
                  title={quickReplyProblem(quickReplies, lang) || t("inbox.send")}
                  className="shrink-0 px-2 text-[13px] font-semibold text-[#0095f6] hover:opacity-80 disabled:opacity-50"
                >
                  {lang === "ar" ? "إرسال" : "Send"}
                </button>
              </div>
            )}
          </div>
          </>
        ) : isMessenger ? (
          <>
          {replyingTo && (
            <div data-testid="messenger-reply-bar" dir={lang === "ar" ? "rtl" : "ltr"} className="mb-1 flex items-center gap-2 rounded-xl bg-[#f0f2f5] px-3 py-1.5">
              <div className="min-w-0 flex-1">
                <div className="text-[12px] font-semibold text-[#050505]">{lang === "ar" ? `الرد على ${replyingTo.side === "out" ? "نفسك" : conversation.customer}` : `Replying to ${replyingTo.side === "out" ? "yourself" : conversation.customer}`}</div>
                <div className="truncate text-[12px] text-[#65676b]" dir="auto">{messengerQuoteText({ body: replyingTo.text, content_type: replyingTo.contentType }, lang)}</div>
              </div>
              <button type="button" data-testid="messenger-reply-cancel" onClick={() => setReplyingTo(null)} aria-label={lang === "ar" ? "إلغاء الرد" : "Cancel reply"} className="grid h-6 w-6 shrink-0 place-items-center rounded-full text-[#65676b] hover:bg-[#e4e6eb]"><X className="h-4 w-4" /></button>
            </div>
          )}
          {isRecordingVoice ? (
            <MessengerVoiceRecorder
              lang={lang}
              accent={messengerTheme.accent}
              onCancel={() => setIsRecordingVoice(false)}
              onError={(message) => setAttachError(message)}
              onDone={(file) => { setIsRecordingVoice(false); setAttachError(""); setAttachment({ file, kind: "audio", asSticker: false }); }}
            />
          ) : (
          <div dir={lang === "ar" ? "rtl" : "ltr"} data-testid="messenger-composer" className="flex min-h-9 items-center gap-0.5">
            {/* Messenger order, start to end: attach, photo, GIF, mic, then the box with its emoji button inside. */}
            <button
              type="button"
              onClick={() => setAttachmentMenuOpen((v) => !v)}
              className="grid h-9 w-9 shrink-0 place-items-center rounded-full hover:bg-[#f0f2f5]"
              style={{ color: messengerTheme.accent }}
              title={lang === "ar" ? "إرفاق ملف" : "Attach a file"}
              aria-label={lang === "ar" ? "إرفاق ملف" : "Attach a file"}
              aria-haspopup="menu"
              aria-expanded={attachmentMenuOpen}
            >
              <Paperclip className="h-5 w-5" />
            </button>
            <button
              type="button"
              data-testid="messenger-image-button"
              onClick={() => messengerImageInput.current?.click()}
              className="grid h-9 w-9 shrink-0 place-items-center rounded-full hover:bg-[#f0f2f5]"
              style={{ color: messengerTheme.accent }}
              title={lang === "ar" ? "إرسال صورة" : "Send a photo"}
              aria-label={lang === "ar" ? "إرسال صورة" : "Send a photo"}
            >
              <ImageIcon className="h-5 w-5" />
            </button>
            <input
              ref={messengerImageInput}
              type="file"
              accept="image/jpeg,image/png,image/gif,image/webp"
              hidden
              data-testid="messenger-image-input"
              onChange={(event) => { const file = event.target.files?.[0]; event.target.value = ""; if (file) pickFile(file); }}
            />
            <button
              type="button"
              data-testid="messenger-gif-button"
              onClick={() => messengerGifInput.current?.click()}
              className="grid h-9 w-9 shrink-0 place-items-center rounded-full text-[11px] font-extrabold leading-none hover:bg-[#f0f2f5]"
              style={{ color: messengerTheme.accent }}
              title={lang === "ar" ? "إرسال GIF" : "Send a GIF"}
              aria-label={lang === "ar" ? "إرسال GIF" : "Send a GIF"}
            >
              <span className="rounded-[4px] border-2 px-[3px] py-[1px]" style={{ borderColor: messengerTheme.accent }}>GIF</span>
            </button>
            <input
              ref={messengerGifInput}
              type="file"
              accept="image/gif"
              hidden
              data-testid="messenger-gif-input"
              onChange={(event) => { const file = event.target.files?.[0]; event.target.value = ""; if (file) pickFile(file); }}
            />
            <button
              type="button"
              data-testid="messenger-mic-button"
              onClick={() => { setAttachError(""); setIsRecordingVoice(true); }}
              className="grid h-9 w-9 shrink-0 place-items-center rounded-full hover:bg-[#f0f2f5]"
              style={{ color: messengerTheme.accent }}
              title={lang === "ar" ? "رسالة صوتية" : "Voice message"}
              aria-label={lang === "ar" ? "رسالة صوتية" : "Voice message"}
            >
              <Mic className="h-5 w-5" />
            </button>
            <div className="mx-1 flex h-9 min-w-0 flex-1 items-center rounded-full bg-[#f0f2f5] ps-3 pe-1">
              <input
                value={text}
                onChange={(event) => setText(event.target.value)}
                dir="auto"
                onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void submitMessage(); } }}
                placeholder="Aa"
                aria-label={t("inbox.typeMessage")}
                disabled={sending}
                className={cn("h-full min-w-0 flex-1 bg-transparent text-[15px] text-[#050505] outline-none placeholder:text-[#65676b]", lang === "ar" ? "text-right" : "text-left")}
              />
              <button
                type="button"
                data-testid="messenger-emoji-button"
                onClick={() => setEmojiPickerOpen((v) => !v)}
                className="grid h-7 w-7 shrink-0 place-items-center rounded-full hover:bg-[#e4e6eb]"
                style={{ color: messengerTheme.accent }}
                title={lang === "ar" ? "الرموز التعبيرية" : "Emoji picker"}
                aria-label={lang === "ar" ? "الرموز التعبيرية" : "Emoji picker"}
              >
                <Smile className="h-5 w-5" />
              </button>
            </div>
            {text.trim() ? (
              <button
                type="button"
                onClick={() => { void submitMessage(); }}
                disabled={sending}
                aria-label={t("inbox.send")}
                title={t("inbox.send")}
                className="grid h-9 w-9 shrink-0 place-items-center rounded-full transition-opacity hover:bg-[#f0f2f5] disabled:cursor-not-allowed disabled:opacity-40"
                style={{ color: messengerTheme.accent }}
              >
                <Send className="h-5 w-5" />
              </button>
            ) : (
              // Messenger keeps a thumbs-up in the send slot while the box is empty.
              <button
                type="button"
                onClick={() => { void submitMessage("👍"); }}
                disabled={sending}
                aria-label={lang === "ar" ? "إرسال إعجاب" : "Send a like"}
                title={lang === "ar" ? "إرسال إعجاب" : "Send a like"}
                className="grid h-9 w-9 shrink-0 place-items-center rounded-full transition-opacity hover:bg-[#f0f2f5] disabled:cursor-not-allowed disabled:opacity-40"
                style={{ color: messengerTheme.accent }}
              >
                <ThumbsUp className="h-5 w-5" fill="currentColor" />
              </button>
            )}
          </div>
          )}
          </>
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

      {/* Contact details: WhatsApp has its own panel built from real data only. */}
      {isWhatsApp ? (
        contactDrawerOpen && (
          <ContactInfoPanel
            conversation={conversation}
            customer={waCustomer}
            lang={lang}
            formatMoney={formatCurrency}
            onClose={() => setContactDrawerOpen(false)}
            onChange={(body) => onListStateChange?.(conversation, body)}
            onToggleBuyBlock={waCustomerId ? toggleBuyBlock : undefined}
            onOpenImage={(id) => { setContactDrawerOpen(false); setViewerId(id); }}
            onOpenCustomerProfile={() => {
              setContactDrawerOpen(false);
              setCustomer360Record({
                id: waCustomerId || undefined,
                name: conversation.customer,
                phone: waCustomer?.phone || conversation.phone,
                lifetime_value: waCustomer?.lifetime_value,
              });
            }}
          />
        )
      ) : (
      <ChannelContactDrawer
        isOpen={contactDrawerOpen}
        onClose={() => setContactDrawerOpen(false)}
        channel={channel}
        conversation={conversation}
        lang={lang}
        onSearch={() => { setContactDrawerOpen(false); setSearchOpen(true); setSearchQuery(""); }}
        onTheme={() => { setContactDrawerOpen(false); setThemePickerOpen(true); }}
        onListStateChange={isInstagram ? (row, body) => onListStateChange?.(row, body) : undefined}
        onOpenCustomerProfile={() => {
          setCustomer360Record({
            id: conversation.customer_id || conversation.id,
            name: conversation.customer,
            phone: conversation.customer_phone,
            lifetime_value: conversation.lifetime_value,
          });
        }}
      />

      )}

      {/* Customer 360 Drawer when requested from Contact Info */}
      {customer360Record && (
        <CustomerDrawer
          customer={customer360Record}
          onClose={() => setCustomer360Record(null)}
        />
      )}
      {viewerId && (isWhatsApp || isInstagram) && (
        <ImageViewer gallery={galleryOf(allMessages)} startId={viewerId} lang={lang} onClose={() => setViewerId(null)} />
      )}
    </div>
  );
}

// Subcomponent: Message Bubble
// One Messenger message. Its look follows messengerMessageShape: a photo, video or sticker stands
// on the page with no bubble, a file is a card, a removed message is a grey line, a system line is
// centred grey text, and text and audio sit in the blue or grey bubble.
function MessengerBubble({ m, messengerRow, showSeenAvatar, showIncomingAvatar, messengerTheme, th, lang, conversation, onReply, onOpenImage }) {
  const out = m.side === "out";
  const group = messengerRow || { first: true, last: true, alone: true, size: 1 };
  const shape = messengerMessageShape(m);
  const ar = lang === "ar";

  if (shape === "system") {
    return (
      <div data-testid="messenger-system" dir="auto" className="my-2 px-6 text-center text-[12px] leading-snug text-[#65676b]">{m.text}</div>
    );
  }

  const quote = m.replyTo ? messengerQuoteText(m.replyTo, lang) : "";
  const reactions = messengerReactionSummary(m.reactions);
  const canAct = !m.unsaved && !m.deleted;
  const hoverButton = "grid h-7 w-7 place-items-center rounded-full text-[#65676b] hover:bg-[#f0f2f5] focus-visible:bg-[#f0f2f5] focus-visible:outline-none";
  const bare = shape === "photo" || shape === "video" || shape === "sticker" || shape === "bigEmoji";
  const caption = m.mediaUrl && m.text && !String(m.text).startsWith("blob:") && shape !== "file" ? String(m.text) : "";
  // A message that is only a web address gets Messenger's preview card under the bubble. The card
  // shows the site and the address the sender wrote; no title or picture is invented for it.
  const linkParts = shape === "text" ? messengerLinkParts(m.text) : [];
  const linkOnly = linkParts.length === 1 && linkParts[0].type === "link" ? linkParts[0].value : "";

  let body;
  if (shape === "deleted") {
    body = (
      <div data-testid="messenger-deleted" dir="auto" className="rounded-[18px] border border-[#ced0d4] px-3 py-2 text-[14px] italic text-[#65676b]">
        {ar ? "تم حذف هذه الرسالة" : "This message was removed"}
      </div>
    );
  } else if (shape === "bigEmoji") {
    body = <div data-testid="messenger-big-emoji" title={m.time} className="text-[44px] leading-[1.1]" dir="auto">{String(m.text).trim()}</div>;
  } else if (shape === "photo" || shape === "sticker") {
    const open = onOpenImage && shape === "photo" ? () => onOpenImage(m.id) : undefined;
    body = (
      <button type="button" data-testid={shape === "photo" ? "messenger-photo" : "messenger-sticker"} onClick={open} disabled={!open} aria-label={ar ? "فتح الصورة" : "Open photo"} className="block max-w-[260px] overflow-hidden rounded-[18px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0084ff]">
        <img src={m.mediaUrl} alt="" loading="lazy" className={cn("block h-auto max-h-[320px] w-auto max-w-full object-cover", shape === "sticker" && "max-h-[150px] object-contain")} />
      </button>
    );
  } else if (shape === "video") {
    body = (
      <video data-testid="messenger-video" src={m.mediaUrl} controls preload="metadata" className="block max-h-[320px] max-w-[260px] rounded-[18px] bg-black" />
    );
  } else if (shape === "file") {
    body = (
      <a data-testid="messenger-file" href={m.mediaUrl} target="_blank" rel="noreferrer" className="flex max-w-[260px] items-center gap-2 rounded-[18px] bg-[#f0f0f0] px-3 py-2 text-[#050505] hover:bg-[#e4e6eb]">
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-[#e4e6eb]"><Paperclip className="h-4 w-4 text-[#65676b]" /></span>
        <span dir="auto" className="min-w-0 truncate text-[14px] font-medium">{m.fileName || (ar ? "ملف" : "File")}</span>
      </a>
    );
  } else {
    body = (
      <div
        title={m.time}
        className={cn(
          "relative max-w-full px-3 py-2 text-[15px] leading-[1.35] rounded-[18px]",
          messengerBubbleCorners({ out, first: group.first, last: group.last }),
          reactions && "mb-3"
        )}
        style={{ background: messengerBubbleBackground(messengerTheme, out), color: out ? "#FFFFFF" : th?.inText || "#050505" }}
      >
        {shape === "audio" ? (
          <VoiceBubble m={m} out={out} time={m.time} status={m.status} checkmarks={false} />
        ) : (
          <div className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]" dir="auto">
            {messengerLinkParts(m.text).map((part, i) =>
              part.type === "link" ? (
                <a key={i} data-testid="messenger-link" href={part.value} target="_blank" rel="noreferrer" onClick={(event) => event.stopPropagation()} className="underline underline-offset-2">{part.value}</a>
              ) : (
                <React.Fragment key={i}>{part.value}</React.Fragment>
              )
            )}
            {m.ai && <Sparkles className="ms-1 inline h-3 w-3 align-baseline text-amber-300" />}
          </div>
        )}
      </div>
    );
  }

  const badge = reactions && (
    <span data-testid="messenger-reactions" className={cn("absolute -bottom-3 flex items-center gap-0.5 rounded-full border-2 border-white bg-[#f0f2f5] px-1.5 text-[12px] leading-[18px] text-[#050505]", out ? "end-2" : "start-2")}>
      {reactions.emojis.join("")}
      {reactions.count > 1 && <span className="text-[11px] text-[#65676b]">{reactions.count}</span>}
    </span>
  );

  return (
    <div className={cn("flex flex-col", out ? "items-end" : "items-start", group.alone ? "mt-2" : "mt-0.5")}>
      {quote && (
        <div data-testid="messenger-quote" dir="auto" className="mb-0.5 max-w-[76%] truncate rounded-[18px] bg-[#f0f0f0] px-3 py-1.5 text-[13px] text-[#65676b]">{quote}</div>
      )}
      <div className={cn("group/msg flex max-w-[82%] items-end gap-1 sm:max-w-[76%]", out ? "flex-row-reverse" : "flex-row")}>
        {!out && (
          <span className="w-6 shrink-0 self-end">
            {showIncomingAvatar && <span data-testid="messenger-incoming-avatar" className="inline-flex"><ConversationAvatar conversation={conversation} className="h-6 w-6 text-[9px]" /></span>}
          </span>
        )}
        <div className={cn("relative flex min-w-0 flex-col gap-0.5", out ? "items-end" : "items-start")}>
          {body}
          {caption && (shape === "photo" || shape === "video") && (
            <div dir="auto" className="rounded-[18px] bg-[#f0f0f0] px-3 py-2 text-[15px] text-[#050505]">{caption}</div>
          )}
          {linkOnly && messengerLinkHost(linkOnly) && (
            <a data-testid="messenger-link-preview" href={linkOnly} target="_blank" rel="noreferrer" onClick={(event) => event.stopPropagation()} className="block w-[240px] max-w-full overflow-hidden rounded-[18px] border border-[#e4e6eb] bg-white hover:bg-[#f7f8fa]">
              <div className="px-3 py-2">
                <div className="text-[11px] uppercase tracking-wide text-[#65676b]" dir="ltr">{messengerLinkHost(linkOnly)}</div>
                <div className="truncate text-[13.5px] text-[#050505]" dir="ltr">{linkOnly}</div>
              </div>
            </a>
          )}
          {badge && bare && <span className="mb-3" />}
          {badge}
        </div>
        {out && m.status === "failed" && (
          <span data-testid="messenger-failed" title={ar ? "لم يتم الإرسال" : "Not sent"} className="grid h-5 w-5 shrink-0 place-items-center self-center rounded-full bg-[#e41e3f] text-[12px] font-bold leading-none text-white" role="img" aria-label={ar ? "لم يتم الإرسال" : "Not sent"}>!</span>
        )}
        {canAct && (
          <div className="flex shrink-0 items-center self-center opacity-0 transition-opacity focus-within:opacity-100 group-hover/msg:opacity-100">
            {onReply && (
              <button type="button" data-testid="messenger-hover-reply" className={hoverButton} onClick={() => onReply(m)} title={ar ? "رد" : "Reply"} aria-label={ar ? "رد" : "Reply"}>
                <Reply className="h-4 w-4" />
              </button>
            )}
            {m.text && shape !== "audio" && (
              <button type="button" data-testid="messenger-hover-copy" className={hoverButton} onClick={() => { void navigator.clipboard?.writeText(String(m.text)); }} title={ar ? "نسخ" : "Copy"} aria-label={ar ? "نسخ" : "Copy"}>
                <Copy className="h-4 w-4" />
              </button>
            )}
          </div>
        )}
      </div>
      {out && m.status === "failed" && (
        <div className="mt-1 px-1 text-[11px] text-[#e41e3f]" dir="auto">{ar ? "لم يتم الإرسال" : "Not sent"}</div>
      )}
      {showSeenAvatar && (
        <span data-testid="messenger-seen-avatar" className="mt-1 inline-flex">
          <ConversationAvatar conversation={conversation} className="h-4 w-4 text-[8px]" />
        </span>
      )}
    </div>
  );
}

function Bubble({ m, showSeen = false, messengerRow = null, showSeenAvatar = false, messengerTheme = null, isApp: _isApp, isWhatsApp, isInstagram: _isInstagram, isMessenger, isTelegram, lang: _lang, th, conversation: _conversation, showIncomingAvatar: _showIncomingAvatar, onReply, onReact, onOpenImage }) {
  const out = m.side === "out";
  const isAudio = m.mediaType === "audio" || String(m.text || "").startsWith("🎤");
  const mediaUrl = m.mediaUrl;

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

    // Each kind of message looks like it does in WhatsApp. The bubble frame,
    // quote, deleted state, reactions and the delivery mark come from
    // WhatsAppBubble; the voice player is the existing one.
    const kind = messageKind(m);
    const caption = displayBody(m);
    const time = (
      <div className="mt-1 flex items-center justify-end gap-1 text-[11px] text-[#667781]" dir="ltr">
        <span>{m.time}</span>
        {out && <MessageStatus status={m.status} lang={_lang} />}
      </div>
    );
    const withCaption = (body, text = caption) => (
      <div className="space-y-1.5">
        {body}
        {text && !text.startsWith("blob:") && <div dir="auto" className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]">{text}</div>}
        {time}
      </div>
    );
    let media = null;
    if (kind === "voice") {
      media = <VoiceBubble m={m} out={out} time={m.time} status={m.status} checkmarks={th.checkmarks} isWhatsApp />;
    } else if (kind === "image" && mediaUrl) {
      media = withCaption(<PhotoBody src={mediaUrl} caption={caption} lang={_lang} onOpen={onOpenImage && !m.deleted ? () => onOpenImage(m.id) : undefined} />);
    } else if (kind === "sticker" && mediaUrl) {
      media = <div>{<StickerBody src={mediaUrl} lang={_lang} />}{time}</div>;
    } else if (kind === "video" && mediaUrl) {
      media = withCaption(<VideoBody src={mediaUrl} caption={caption} lang={_lang} />);
    } else if (kind === "document") {
      // The server's file name wins; for older messages a bare file name in the
      // text is the label and any other text is the caption.
      const isName = !m.fileName && looksLikeFileName(caption);
      media = withCaption(<DocumentBody src={mediaUrl} label={m.fileName || (isName ? caption : "")} lang={_lang} out={out} />, isName ? "" : caption);
    } else if (kind === "location") {
      media = withCaption(<LocationBody body={m.text} lang={_lang} />, "");
    } else if (kind === "contact") {
      media = withCaption(<ContactBody body={m.text} lang={_lang} />, "");
    } else if (kind === "interactive") {
      media = withCaption(<InteractiveBody message={m.interactive} lang={_lang} />, "");
    } else if (kind === "order") {
      media = withCaption(<OrderBody order={m.order} lang={_lang} />, "");
    } else if (kind === "buttons" || kind === "list") {
      media = withCaption(<ChoiceBody body={m.text} kind={kind} lang={_lang} />, "");
    } else if (kind === "unsupported") {
      media = withCaption(<UnsupportedBody lang={_lang} />, "");
    }
    return <WhatsAppBubble
        m={m}
        th={th}
        lang={_lang}
        mine={m.myReaction || ""}
        onReply={onReply}
        onCopy={(msg) => { void navigator.clipboard?.writeText(msg.text || ""); }}
        onReact={onReact && !m.unsaved ? (emoji) => { void onReact(_conversation.id, m.id, emoji, m.myReaction || ""); } : undefined}
      >{media}</WhatsAppBubble>;
  }

  if (_isInstagram) {
    return <InstagramBubble m={m} th={th} lang={_lang} showSeen={showSeen} onOpenImage={onOpenImage} onReact={onReact && !m.unsaved ? (emoji) => { void onReact(_conversation.id, m.id, emoji, m.myReaction || ""); } : undefined} />;
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

  // Messenger: a gradient bubble, 18px corners that square to 4px where two bubbles of the same
  // group meet, the time alone (no ticks), and the reader's avatar under the last bubble they read.
  if (isMessenger) {
    return <MessengerBubble m={m} messengerRow={messengerRow} showSeenAvatar={showSeenAvatar} showIncomingAvatar={_showIncomingAvatar} messengerTheme={messengerTheme} th={th} lang={_lang} conversation={_conversation} onReply={onReply} onOpenImage={onOpenImage} />;
  }


  // Instagram
  return (
    <div className={cn("flex", out ? "justify-end" : "justify-start")}>
      <div
        className={cn("max-w-[82%] px-3.5 py-2 text-[14px] leading-[1.45] sm:max-w-[76%]", _isInstagram ? "rounded-[12px]" : cn("rounded-[18px]", out ? "rounded-br-sm" : "rounded-bl-sm"))}
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
                  ? isWhatsApp ? "bg-[var(--wa-green)]" : "bg-primary"
                  : isWhatsApp ? "bg-[var(--wa-text-faint)]" : out ? "bg-white/60" : "bg-black/30"
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

export function formatWhatsAppDay(iso, lang, _t) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const target = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const diff = (today.getTime() - target.getTime()) / 86400000;
  if (diff === 0) return lang === "ar" ? "اليوم" : "Today";
  if (diff === 1) return lang === "ar" ? "أمس" : "Yesterday";
  // WhatsApp Web: a weekday name for the last week, then a plain dd/mm/yyyy.
  if (diff > 1 && diff < 7) return date.toLocaleDateString(lang === "ar" ? "ar-EG" : "en-US", { weekday: "long" });
  const dd = String(date.getDate()).padStart(2, "0");
  const mm = String(date.getMonth() + 1).padStart(2, "0");
  return `${dd}/${mm}/${date.getFullYear()}`;
}
