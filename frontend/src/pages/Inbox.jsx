import React, { useEffect, useState } from "react";
import { Search, Sparkles } from "lucide-react";
import { PageHeader, Badge } from "@/components/dashboard/ui";
import ChannelSwitcher from "@/components/inbox/ChannelSwitcher";
import ChannelChat from "@/components/inbox/ChannelChat";
import { CHANNELS, getChannel } from "@/lib/channels";
import { api } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";

// Deep-clone the static seed once so the inbox has mutable state per channel.
const clone = (obj) => JSON.parse(JSON.stringify(obj));

// صندوق فارغ لكل قناة — بيمتلئ من /conversations الحقيقية بعد التحميل
const EMPTY_CONV_MAP = Object.fromEntries(CHANNELS.map((ch) => [ch.id, []]));

function nowTime() {
  const d = new Date();
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

export default function Inbox() {
  const t = useT();
  const [activeChannel, setActiveChannel] = useState("whatsapp");
  const [activeId, setActiveId] = useState(null);
  const [filter, setFilter] = useState("all");
  const [convMap, setConvMap] = useState(() => clone(EMPTY_CONV_MAP));

  // المحادثات الحقيقية من الـbackend — بتتوزع على القنوات بعد التحميل
  useEffect(() => {
    let alive = true;
    api("/conversations?limit=200")
      .then((d) => {
        if (!alive) return;
        const rows = d?.items ?? (Array.isArray(d) ? d : []);
        const map = clone(EMPTY_CONV_MAP);
        for (const c of rows) {
          const ch = c.channel || "webchat";
          if (!map[ch]) map[ch] = [];
          map[ch].push({
            id: c.id,
            customer: c.customer_name || c.customer_id || "—",
            preview: c.last_message_preview || "",
            status: (c.status || "").replace("waiting_", ""),
            ai: (c.status || "") === "waiting_ai",
            time: c.last_message_at ? new Date(c.last_message_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "",
            unread: c.unread_count ?? 0,
          });
        }
        setConvMap(map);
      })
      .catch(() => {});
    return () => { alive = false; };
  }, []);

  const channel = getChannel(activeChannel);
  const conversations = convMap[activeChannel] || [];
  const current = conversations.find((c) => c.id === activeId) || conversations[0] || null;

  const STATUS = {
    waiting: { label: t("inbox.status.waiting"), tone: "warning" },
    approval: { label: t("inbox.status.approval"), tone: "destructive" },
    ai: { label: t("inbox.status.ai"), tone: "accent" },
    resolved: { label: t("inbox.status.resolved"), tone: "success" },
  };

  const FILTERS = [
    { id: "all", label: t("inbox.filter.all") },
    { id: "ai", label: t("inbox.filter.agent") },
    { id: "human", label: t("inbox.filter.human") },
  ];

  const filtered = conversations.filter((c) => (filter === "all" ? true : c.handledBy === filter));
  const connectedCount = CHANNELS.filter((c) => c.connected).length;

  function patchConversation(channelId, convId, updater) {
    setConvMap((prev) => ({
      ...prev,
      [channelId]: (prev[channelId] || []).map((c) => (c.id === convId ? updater(c) : c)),
    }));
  }

  function handleSend(convId, text) {
    patchConversation(activeChannel, convId, (c) => ({
      ...c,
      preview: text,
      time: nowTime(),
      unread: 0,
      messages: [...c.messages, { side: "out", text, time: nowTime(), status: "delivered" }],
    }));
  }

  function handleApprove(convId) {
    patchConversation(activeChannel, convId, (c) => ({
      ...c,
      status: "resolved",
      handledBy: "ai",
      messages: [...c.messages, { side: "out", text: t("inbox.approval.sent"), time: nowTime(), ai: true, status: "read" }],
    }));
  }

  function handleDecline(convId) {
    patchConversation(activeChannel, convId, (c) => ({
      ...c,
      status: "waiting",
      handledBy: "human",
    }));
  }

  return (
    <div className="flex flex-col h-[calc(100vh-112px)]">
      <PageHeader
        title={t("inbox.title")}
        subtitle={t("inbox.channelsConnected", { n: connectedCount })}
      />

      {/* Channel switcher — compact inline row */}
      <div className="flex items-center gap-1 mb-3 -mt-2">
        <ChannelSwitcher active={activeChannel} onSelect={(id) => { setActiveChannel(id); setActiveId(null); setFilter("all"); }} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[340px_1fr] grid-rows-[260px_1fr] lg:grid-rows-1 gap-4 flex-1 min-h-0">
        {/* Conversation list */}
        <div className="rounded-2xl bg-card border border-border flex flex-col min-h-0 overflow-hidden">
          <div className="p-3 border-b border-border space-y-2.5">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <input
                placeholder={t("inbox.search")}
                className="w-full h-9 pl-9 pr-3 rounded-lg bg-surface border border-border text-[13px] placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring/30"
              />
            </div>
            <div className="flex gap-1">
              {FILTERS.map((f) => (
                <button
                  key={f.id}
                  onClick={() => setFilter(f.id)}
                  className={cn(
                    "px-2.5 py-1 rounded-md text-[12px] font-medium whitespace-nowrap transition-colors",
                    filter === f.id ? "bg-primary text-primary-foreground" : "bg-surface text-muted-foreground hover:text-foreground"
                  )}
                >
                  {f.label}
                </button>
              ))}
            </div>
          </div>
          <div className="flex-1 overflow-y-auto scrollbar-thin">
            {filtered.length === 0 ? (
              <div className="py-10 text-center px-4">
                <p className="text-[13px] text-muted-foreground">{t("inbox.noConversations")}</p>
              </div>
            ) : (
              filtered.map((c) => (
                <button
                  key={c.id}
                  onClick={() => setActiveId(c.id)}
                  className={cn(
                    "w-full flex gap-3 px-3.5 py-3 text-left border-b border-border/60 hover:bg-surface/60 transition-colors",
                    current?.id === c.id && "bg-primary/5"
                  )}
                >
                  <div className="relative shrink-0">
                    <div className="h-9 w-9 rounded-full grid place-items-center text-[12px] font-semibold text-white" style={{ background: c.color }}>
                      {c.initials}
                    </div>
                    {c.status === "ai" && (
                      <span className="absolute -bottom-0.5 -right-0.5 h-4 w-4 rounded-full bg-card border border-border grid place-items-center">
                        <Sparkles className="h-2.5 w-2.5 text-accent" />
                      </span>
                    )}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-[13px] font-medium truncate">{c.customer}</span>
                      <span className="text-[11px] text-muted-foreground shrink-0">{c.time}</span>
                    </div>
                    <p className="text-[12px] text-muted-foreground truncate mt-0.5">{c.preview}</p>
                    <div className="flex items-center gap-1.5 mt-1.5">
                      {(() => {
                        const st = STATUS[c.status] || { tone: "muted", label: c.status };
                        return <Badge tone={st.tone}>{st.label}</Badge>;
                      })()}
                      {c.unread > 0 && (
                        <span className="ml-auto text-[10px] font-semibold px-1.5 py-0.5 rounded-md bg-primary text-primary-foreground tabular-nums">
                          {c.unread}
                        </span>
                      )}
                    </div>
                  </div>
                </button>
              ))
            )}
          </div>
        </div>

        {/* Themed chat pane */}
        <ChannelChat
          channel={channel}
          conversation={current}
          t={t}
          onSend={handleSend}
          onApprove={handleApprove}
          onDecline={handleDecline}
        />
      </div>
    </div>
  );
}