import React from "react";
import { MessageCircle, Instagram, Send, MessagesSquare } from "lucide-react";
import { cn } from "@/lib/utils";

const MAP = {
  whatsapp: { icon: MessageCircle, color: "text-success", bg: "bg-success/10" },
  instagram: { icon: Instagram, color: "text-accent", bg: "bg-accent/10" },
  messenger: { icon: MessagesSquare, color: "text-chart-4", bg: "bg-chart-4/10" },
  telegram: { icon: Send, color: "text-chart-4", bg: "bg-chart-4/10" },
  webchat: { icon: MessageCircle, color: "text-muted-foreground", bg: "bg-surface" },
  email: { icon: MessageCircle, color: "text-warning", bg: "bg-warning/10" },
};

export default function ChannelIcon({ channel, className }) {
  const m = MAP[channel] || MAP.webchat;
  const Icon = m.icon;
  return (
    <span className={cn("inline-grid place-items-center h-7 w-7 rounded-lg", m.bg, className)}>
      <Icon className={cn("h-[15px] w-[15px]", m.color)} />
    </span>
  );
}

export function channelLabel(channel) {
  return channel.charAt(0).toUpperCase() + channel.slice(1);
}