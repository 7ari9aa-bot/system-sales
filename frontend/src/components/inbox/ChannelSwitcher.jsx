import React, { useState } from "react";
import { ChevronDown, MessageCircle, Instagram, MessagesSquare, MessageSquare, Send, Facebook, Lock } from "lucide-react";
import { CHANNELS } from "@/lib/channels";
import { useI18n, useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";

const ICONS = { MessageCircle, Instagram, MessagesSquare, MessageSquare, Send, Facebook };

export default function ChannelSwitcher({ active, onSelect, channels = CHANNELS, unreadByChannel = {}, variant = "default" }) {
  const t = useT();
  const { lang } = useI18n();
  const [open, setOpen] = useState(false);
  if (variant === "compact") {
    const selected = channels.find((channel) => channel.id === active) || channels[0];
    const SelectedIcon = ICONS[selected.icon] || MessageCircle;
    return (
      <div className="relative shrink-0" dir={lang === "ar" ? "rtl" : "ltr"} onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
      }}>
        <button
          type="button"
          aria-haspopup="menu"
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
          className="flex h-8 items-center gap-1.5 rounded-lg border border-[#d1d7db] bg-white px-2 text-[12px] font-medium text-[#54656f] hover:bg-[#f5f6f6] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#00a884]"
        >
          <SelectedIcon className="h-3.5 w-3.5" />
          <span>{selected.name}</span>
          <ChevronDown className="h-3.5 w-3.5" />
        </button>
        {open && (
          <div role="menu" className={cn("absolute top-full z-30 mt-1 min-w-44 overflow-hidden rounded-lg border border-[#d1d7db] bg-white py-1 shadow-lg", lang === "ar" ? "right-0" : "left-0")}>
            {channels.map((channel) => {
              const Icon = ICONS[channel.icon] || MessageCircle;
              const locked = !channel.connected;
              const unread = Number(unreadByChannel[channel.id]) || 0;
              return (
                <button
                  key={channel.id}
                  type="button"
                  role="menuitem"
                  disabled={locked}
                  onClick={() => { onSelect(channel.id); setOpen(false); }}
                  title={locked ? t("inbox.lockedChannel", { name: channel.name }) : channel.name}
                  className={cn("flex h-9 w-full items-center gap-2 px-3 text-start text-[12px]", locked ? "cursor-not-allowed text-[#aebac1]" : channel.id === active ? "bg-[#f0f2f5] text-[#111b21]" : "text-[#3b4a54] hover:bg-[#f5f6f6]")}
                >
                  <Icon className="h-4 w-4 shrink-0" />
                  <span className="min-w-0 flex-1 truncate">{channel.name}</span>
                  {locked ? <Lock className="h-3 w-3 shrink-0" /> : unread > 0 && <span className="rounded-full bg-[#25d366] px-1.5 text-[10px] leading-4 text-white">{unread}</span>}
                </button>
              );
            })}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="flex items-center gap-1 overflow-x-auto scrollbar-thin">
      {channels.map((ch) => {
        const Icon = ICONS[ch.icon] || MessageCircle;
        const isActive = active === ch.id;
        const locked = !ch.connected;
        const unread = Number(unreadByChannel[ch.id]) || 0;
        return (
          <button
            key={ch.id}
            type="button"
            onClick={() => !locked && onSelect(ch.id)}
            disabled={locked}
            aria-pressed={isActive}
            title={locked ? t("inbox.lockedChannel", { name: ch.name }) : ch.name}
            className={cn(
              "group relative shrink-0 flex items-center gap-1.5 h-7 px-2.5 rounded-lg text-[12px] font-medium transition-all",
              locked
                ? "text-muted-foreground/60 cursor-not-allowed"
                : isActive
                  ? "text-white shadow-sm"
                  : "text-muted-foreground hover:text-foreground hover:bg-surface"
            )}
            style={isActive && !locked ? { background: ch.accent } : undefined}
          >
            <Icon className={cn("h-3.5 w-3.5 shrink-0", locked && "opacity-50")} />
            <span className={cn(locked && "hidden sm:inline")}>{ch.name}</span>
            {locked && <Lock className="h-2.5 w-2.5 opacity-50" />}
            {isActive && !locked && unread > 0 && (
              <span className="ml-0.5 text-[10px] font-semibold px-1 py-0 rounded bg-white/25 tabular-nums text-white leading-4">
                {unread}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
