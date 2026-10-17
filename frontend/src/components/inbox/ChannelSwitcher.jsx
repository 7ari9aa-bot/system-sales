import React from "react";
import { MessageCircle, Instagram, MessagesSquare, MessageSquare, Send, Facebook, Lock } from "lucide-react";
import { CHANNELS } from "@/lib/channels";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";

const ICONS = { MessageCircle, Instagram, MessagesSquare, MessageSquare, Send, Facebook };

export default function ChannelSwitcher({ active, onSelect, channels = CHANNELS, unreadByChannel = {} }) {
  const t = useT();
  return (
    <nav aria-label={t("inbox.title")} className="flex w-full flex-col items-center gap-1.5 overflow-y-auto overflow-x-hidden py-2">
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
            aria-label={locked ? t("inbox.lockedChannel", { name: ch.name }) : ch.name}
            title={locked ? t("inbox.lockedChannel", { name: ch.name }) : ch.name}
            className={cn(
              "group relative grid h-10 w-10 shrink-0 place-items-center rounded-xl transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
              locked
                ? "text-muted-foreground/60 cursor-not-allowed"
                : isActive
                  ? "text-white shadow-sm"
                  : "text-muted-foreground hover:bg-surface hover:text-foreground"
            )}
            style={isActive && !locked ? { background: ch.accent } : undefined}
          >
            <Icon className={cn("h-[18px] w-[18px]", locked && "opacity-50")} />
            {locked && <Lock aria-hidden="true" className="absolute bottom-1 right-1 h-2.5 w-2.5 rounded-full bg-background p-px opacity-75" />}
            {unread > 0 && (
              <span aria-label={`${unread} unread`} className="absolute -right-0.5 -top-0.5 min-w-[17px] rounded-full bg-[#2aabee] px-1 text-center text-[9px] font-semibold leading-[17px] tabular-nums text-white shadow-sm">
                {unread}
              </span>
            )}
          </button>
        );
      })}
    </nav>
  );
}
