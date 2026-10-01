import React, { useState, useRef, useEffect } from "react";
import { ArrowUpRight, Sparkles, Check, CheckCheck, Phone, Video, MoreVertical } from "lucide-react";
import { cn } from "@/lib/utils";

// A themed chat pane that renders in the selected channel's real look.
// Brand channels (WhatsApp/Instagram/Messenger/Telegram/Facebook) keep their
// authentic light theme; the "app" theme channel follows the dashboard.
export default function ChannelChat({ channel, conversation, t, onSend, onApprove, onDecline }) {
  const [text, setText] = useState("");
  const scrollRef = useRef(null);
  const isApp = channel.theme === "app";
  const th = isApp ? null : channel.theme;

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [conversation?.id, conversation?.messages?.length]);

  if (!conversation) {
    return (
      <div className="flex-1 grid place-items-center rounded-2xl border border-border bg-card text-center p-8">
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
      className="flex-1 flex flex-col min-h-0 overflow-hidden rounded-2xl border border-border"
      style={isApp ? undefined : { background: th.chatBg }}>
      
      {/* Header */}
      <div
        className="flex items-center gap-3 px-4 h-16 shrink-0"
        style={isApp ? { background: "hsl(var(--card))", borderBottom: "1px solid hsl(var(--border))" } : { background: th.headerBg, color: th.headerText }}>
        
        <div
          className="h-9 w-9 rounded-full grid place-items-center text-[13px] font-semibold shrink-0"
          style={{ background: conversation.color, color: "#fff" }}>
          
          {conversation.initials}
        </div>
        <div className="flex-1 min-w-0">
          <div className={cn("text-[14px] font-semibold truncate", isApp ? "text-foreground" : "")}>{conversation.customer}</div>
          <div className={cn("text-[11.5px] truncate", isApp ? "text-muted-foreground" : "opacity-80")}>{channel.name}</div>
        </div>
        {!isApp &&
        <div className="flex items-center gap-1 opacity-90">
            <button className="h-8 w-8 grid place-items-center rounded-full hover:bg-white/10"><Video className="h-4 w-4" /></button>
            <button className="h-8 w-8 grid place-items-center rounded-full hover:bg-white/10"><Phone className="h-4 w-4" /></button>
            <button className="h-8 w-8 grid place-items-center rounded-full hover:bg-white/10"><MoreVertical className="h-4 w-4" /></button>
          </div>
        }
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto scrollbar-thin px-4 py-4 space-y-2">
        {/* المحادثات الحقيقية من القائمة ما بتوصلش برسايلها الكاملة —
            الرسايل بتتجيب عند فتح المحادثة؛ هنا معاينة آمنة فاضية */}
        {(conversation.messages || []).length === 0 && (
          <div className="py-10 text-center text-[12.5px] text-muted-foreground">
            {t("inbox.previewOnly")}
          </div>
        )}
        {(conversation.messages || []).map((m, i) =>
        <Bubble key={i} m={m} isApp={isApp} th={th} t={t} />
        )}
        {conversation.status === "approval" &&
        <div
          className="mt-2 rounded-xl px-3.5 py-3 text-[12.5px]"
          style={isApp ?
          { background: "hsl(var(--warning-soft))", border: "1px solid hsl(var(--warning) / 0.3)", color: "hsl(var(--warning))" } :
          { background: "#FFF8E1", border: "1px solid #FFE082", color: "#8a6d00" }}>
          
            <div className="font-medium mb-1">{t("inbox.approval.title")}</div>
            <p className="opacity-90">{t("inbox.approval.body")}</p>
            <div className="flex gap-2 mt-2.5">
              <button
                onClick={() => onApprove?.(conversation.id)}
                className="h-8 px-3 rounded-lg text-[12px] font-medium text-white"
                style={{ background: "#16a34a" }}>
                {t("inbox.approve")}
              </button>
              <button
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
      <div className="shrink-0 p-3" style={isApp ? { background: "hsl(var(--card))", borderTop: "1px solid hsl(var(--border))" } : { background: th.inputBg, borderTop: `1px solid ${th.inputBorder}` }}>
        <div
          className="flex items-center gap-2 rounded-full px-3 py-1.5"
          style={isApp ?
          { background: "hsl(var(--surface))", border: "1px solid hsl(var(--border))" } :
          { background: "#fff", border: `1px solid ${th.inputBorder}` }}>
          
          <input
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && text.trim()) { onSend?.(conversation.id, text.trim()); setText(""); } }}
            placeholder={t("inbox.typeMessage")}
            className="flex-1 bg-transparent text-[13px] focus:outline-none"
            style={isApp ? undefined : { color: "#111" }} />

          <button
            onClick={() => { if (text.trim()) { onSend?.(conversation.id, text.trim()); setText(""); } }}
            className="h-7 w-7 grid place-items-center rounded-full text-muted-foreground hover:text-foreground"
            title={t("inbox.ai")}>
            <Sparkles className="h-4 w-4" style={!isApp ? { color: channel.accent } : undefined} />
          </button>
          <button
            onClick={() => { if (text.trim()) { onSend?.(conversation.id, text.trim()); setText(""); } }}
            className="h-8 w-8 grid place-items-center rounded-full text-white shrink-0"
            style={{ background: channel.accent }}
            title={t("inbox.send")}>

            <ArrowUpRight className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>);

}

function Bubble({ m, isApp, th, t }) {
  const out = m.side === "out";
  const showTail = !isApp && th?.tail;

  if (isApp) {
    return (
      <div className={cn("flex", out ? "justify-end" : "justify-start")}>
        <div
          className={cn(
            "max-w-[75%] rounded-2xl px-3.5 py-2 text-[13px] leading-relaxed",
            out ? "bg-primary text-primary-foreground rounded-br-md" : "bg-surface text-foreground rounded-bl-md"
          )}>
          
          {m.text}
          <Foot m={m} isApp={isApp} t={t} />
        </div>
      </div>);

  }

  return (
    <div className={cn("flex", out ? "justify-end" : "justify-start")}>
      <div
        className={cn("max-w-[72%] rounded-lg px-3 py-2 text-[13px] leading-relaxed shadow-sm relative", showTail && (out ? "rounded-br-none" : "rounded-bl-none"))}
        style={{ background: out ? th.out : th.in, color: out ? th.outText : th.inText }}>
        
        {m.text}
        <Foot m={m} isApp={isApp} th={th} t={t} />
      </div>
    </div>);

}

function Foot({ m, isApp, th, t }) {
  return (
    <span className="inline-flex items-center gap-1 ml-2 align-bottom text-[10px] opacity-60">
      {m.time}
      {m.side === "out" && !isApp && th?.checkmarks && (m.status === "read" ? <CheckCheck className="h-3 w-3" style={{ color: "#34B7F1" }} /> : m.status === "delivered" ? <CheckCheck className="h-3 w-3" /> : <Check className="h-3 w-3" />)}
      {m.ai && <Sparkles className="h-2.5 w-2.5" />}
    </span>);

}