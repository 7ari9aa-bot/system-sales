import React from "react";
import { MessageCircle, Instagram, MessagesSquare, MessageSquare, Send, Facebook, Lock } from "lucide-react";
import { CHANNELS, conversationsFor } from "@/lib/channels";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";

const ICONS = { MessageCircle, Instagram, MessagesSquare, MessageSquare, Send, Facebook };

export default function ChannelSwitcher({ active, onSelect }) {
  const t = useT();
  return (
    <div className="flex items-center gap-1 overflow-x-auto scrollbar-thin">
      {CHANNELS.map((ch) => {
        const Icon = ICONS[ch.icon] || MessageCircle;
        const isActive = active === ch.id;
        const locked = !ch.connected;
        return (
          <button
            key={ch.id}
            onClick={() => !locked && onSelect(ch.id)}
            disabled={locked}
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
            {isActive && !locked && (
              <span className="ml-0.5 text-[10px] font-semibold px-1 py-0 rounded bg-white/25 tabular-nums text-white leading-4">
                {countFor(ch.id)}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

function countFor(id) {
  const list = conversationsFor(id);
  return list.reduce((n, c) => n + (c.unread || 0), 0) || list.length;
}