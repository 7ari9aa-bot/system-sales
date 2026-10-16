import React, { useState, useRef, useEffect, useLayoutEffect, useCallback } from "react";
import { ArrowLeft, ArrowRight, ArrowUpRight, Sparkles, Check, CheckCheck } from "lucide-react";
import { cn } from "@/lib/utils";

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
  const scrollRef = useRef(null);
  const preserveScrollRef = useRef(null);
  const messageViewportRef = useRef({ conversationId: null, latestMessageId: null });
  const isApp = channel.theme === "app";
  const isWhatsApp = channel.id === "whatsapp";
  const th = isApp ? null : channel.theme;

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
      <div className={cn("flex-1 grid place-items-center border bg-card text-center p-8", isWhatsApp ? "rounded-xl border-[#d1d7db]" : "rounded-2xl border-border", className)}>
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
      className={cn("flex-1 flex flex-col min-h-0 overflow-hidden border", isWhatsApp ? "rounded-xl border-[#d1d7db]" : "rounded-2xl border-border", className)}
      style={isApp ? undefined : { background: th.chatBg }}>
      
      {/* Header */}
      <div
        dir={isWhatsApp ? (lang === "ar" ? "rtl" : "ltr") : undefined}
        className={cn("flex items-center gap-3 px-4 shrink-0", isWhatsApp ? "h-[60px]" : "h-14")}
        style={isApp ? { background: "hsl(var(--card))", borderBottom: "1px solid hsl(var(--border))" } : { background: th.headerBg, color: th.headerText, borderBottom: isWhatsApp ? `1px solid ${th.divider}` : undefined }}>

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
          className={cn("rounded-full grid place-items-center text-[13px] font-semibold shrink-0", isWhatsApp ? "h-10 w-10" : "h-9 w-9")}
          style={{ background: conversation.color, color: "#fff" }}>
          
          {conversation.initials}
        </div>
        <div className="flex-1 min-w-0">
          <div dir={isWhatsApp ? "auto" : undefined} className={cn("truncate", isWhatsApp ? "text-[15px] font-medium text-[#111b21]" : "text-[14px] font-semibold", isApp && "text-foreground")}>{conversation.customer}</div>
          <div className={cn("truncate", isWhatsApp ? "text-[12px] text-[#667781]" : "text-[11.5px]", isApp && "text-muted-foreground", !isApp && !isWhatsApp && "opacity-80")}>{channel.name}</div>
        </div>
      </div>

      {/* Messages */}
      <div
        ref={scrollRef}
        onScroll={handleMessagesScroll}
        className={cn("flex-1 min-h-0 overflow-y-auto scrollbar-thin px-4 py-3 space-y-2", isWhatsApp && "px-4 py-4")}
        style={isWhatsApp ? {
          backgroundColor: th.chatBg,
          backgroundImage: [
            "radial-gradient(ellipse 13px 9px at 28px 29px, transparent 91%, rgba(84, 101, 111, 0.035) 94%, transparent 100%)",
            "radial-gradient(ellipse 7px 13px at 112px 82px, transparent 90%, rgba(84, 101, 111, 0.03) 94%, transparent 100%)",
            "linear-gradient(34deg, transparent 49.6%, rgba(84, 101, 111, 0.022) 50%, transparent 50.5%)",
            "linear-gradient(145deg, transparent 49.6%, rgba(84, 101, 111, 0.02) 50%, transparent 50.5%)",
          ].join(", "),
          backgroundSize: "197px 173px, 263px 221px, 179px 157px, 241px 203px",
          backgroundPosition: "0 0, 51px 37px, 17px 26px, 83px 11px",
        } : undefined}
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
        {(conversation.messages || []).map((m) =>
        <Bubble key={m.id} m={m} isApp={isApp} isWhatsApp={isWhatsApp} th={th} />
        )}
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
      <div className={cn("shrink-0 p-2", isWhatsApp && "px-3 py-2.5")} style={isApp ? { background: "hsl(var(--card))", borderTop: "1px solid hsl(var(--border))" } : { background: th.inputBg, borderTop: `1px solid ${th.inputBorder}` }}>
        <div
          dir={isWhatsApp ? (lang === "ar" ? "rtl" : "ltr") : undefined}
          className={cn("flex items-center gap-2 rounded-full px-3 py-1.5", isWhatsApp && "min-h-11")}
          style={isApp ?
          { background: "hsl(var(--surface))", border: "1px solid hsl(var(--border))" } :
          { background: "#fff", border: `1px solid ${th.inputBorder}` }}>
          
          <input
            value={text}
            onChange={(e) => setText(e.target.value)}
            dir={isWhatsApp ? (lang === "ar" ? "rtl" : "ltr") : undefined}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void submitMessage(); } }}
            placeholder={t("inbox.typeMessage")}
            aria-label={t("inbox.typeMessage")}
            disabled={sending}
            className={cn("flex-1 bg-transparent text-[13px] focus:outline-hidden", isWhatsApp && (lang === "ar" ? "text-right" : "text-left"))}
            style={isApp ? undefined : { color: "#111" }} />
          <button
            type="button"
            onClick={() => { void submitMessage(); }}
            disabled={!text.trim() || sending}
            aria-label={t("inbox.send")}
            className="h-8 w-8 grid place-items-center rounded-full text-white shrink-0"
            style={{ background: channel.accent, opacity: !text.trim() || sending ? 0.55 : 1 }}
            title={t("inbox.send")}>

            <ArrowUpRight className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>);

}

function Bubble({ m, isApp, isWhatsApp, th }) {
  const out = m.side === "out";
  const showTail = !isApp && th?.tail;

  if (isWhatsApp) {
    return (
      <div className={cn("flex", out ? "justify-end" : "justify-start")}>
        <div
          className={cn(
            "relative max-w-[82%] rounded-lg px-2.5 py-1.5 text-[13px] leading-[1.45] shadow-[0_1px_0.5px_rgba(11,20,26,0.13)] sm:max-w-[72%]",
            showTail && (out ? "rounded-br-sm" : "rounded-bl-sm")
          )}
          style={{ background: out ? th.out : th.in, color: out ? th.outText : th.inText }}
        >
          <div className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]" dir="auto">
            {m.text}{" "}
            <span className="inline-flex items-center gap-0.5 whitespace-nowrap align-baseline text-[10px] leading-none text-[#667781]" dir="ltr">
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

function Foot({ m, isApp, th }) {
  return (
    <span className="inline-flex items-center gap-1 ml-2 align-bottom text-[10px] opacity-60">
      {m.time}
      {m.side === "out" && !isApp && th?.checkmarks && (m.status === "read" ? <CheckCheck className="h-3 w-3" style={{ color: "#34B7F1" }} /> : m.status === "delivered" ? <CheckCheck className="h-3 w-3" /> : <Check className="h-3 w-3" />)}
      {m.ai && <Sparkles className="h-2.5 w-2.5" />}
    </span>);

}
