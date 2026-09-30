import React, { useMemo } from "react";
import { X, Phone, AtSign, Mail, MessageCircle, ShoppingBag, Sparkles, UserPlus, Crown } from "lucide-react";
import ChannelIcon from "@/components/dashboard/ChannelIcon";
import { Badge } from "@/components/dashboard/ui";
import { formatCurrency } from "@/lib/regional";
import { useT } from "@/lib/i18n";

// Auto-identification: a customer is identified by their channel handle,
// not by a form. We derive a handle + contact line from the channel type.
function identify(customer, t) {
  const ch = customer.channel;
  const seed = customer.name.replace(/\s/g, "").toLowerCase();
  const label = t(`customers.identify.${ch}`);
  if (ch === "whatsapp") return { icon: Phone, handle: `+20 1${seed.slice(0, 8)}`, label };
  if (ch === "instagram") return { icon: AtSign, handle: `@${seed}`, label };
  if (ch === "messenger") return { icon: MessageCircle, handle: `m.me/${seed}`, label };
  if (ch === "telegram") return { icon: AtSign, handle: `@${seed}`, label };
  if (ch === "webchat") return { icon: Mail, handle: `${seed}@guest`, label };
  return { icon: Mail, handle: seed, label: t("customers.identify.other") };
}

function timeline(customer, t) {
  const id = identify(customer, t);
  const days = (n) => t("time.daysShort", { n });
  const events = [
    { icon: UserPlus, tone: "muted", title: t("customers.timeline.joined"), detail: id.label, time: days(30) },
    { icon: MessageCircle, tone: "primary", title: t("customers.timeline.message", { channel: t(`channel.${customer.channel}`) }), detail: id.handle, time: customer.lastSeen },
  ];
  for (let i = 0; i < Math.min(customer.orders, 3); i++) {
    events.push({ icon: ShoppingBag, tone: "accent", title: t("customers.timeline.order", { id: 2040 - i * 2 }), detail: formatCurrency(customer.spent / customer.orders), time: days((i + 1) * 4) });
  }
  if (customer.status === "vip") events.push({ icon: Crown, tone: "warning", title: t("customers.status.vip"), detail: t("customers.detail.vipNote"), time: "—" });
  events.push({ icon: Sparkles, tone: "accent", title: t("customers.timeline.ai"), detail: t("customers.detail.aiNote"), time: days(2) });
  return events;
}

const TONE = {
  muted: "bg-surface text-muted-foreground",
  primary: "bg-primary/10 text-primary",
  accent: "bg-accent/10 text-accent",
  warning: "bg-warning/15 text-warning",
};

export default function CustomerDrawer({ customer, onClose }) {
  const t = useT();
  const id = useMemo(() => customer && identify(customer, t), [customer, t]);
  const events = useMemo(() => customer && timeline(customer, t), [customer, t]);

  if (!customer) return null;
  const STATUS = { active: "primary", lead: "accent", vip: "warning" };

  return (
    <div className="fixed inset-0 z-50 flex justify-end animate-fade-in" onClick={onClose}>
      <div className="absolute inset-0 bg-black/40" />
      <div className="relative w-full max-w-md h-full bg-card border-l border-border shadow-xl overflow-y-auto scrollbar-thin" onClick={(e) => e.stopPropagation()}>
        <div className="sticky top-0 bg-card/90 backdrop-blur px-5 py-4 border-b border-border flex items-center justify-between">
          <h3 className="font-display text-[16px] font-semibold">{t("customers.detail.title")}</h3>
          <button onClick={onClose} className="h-8 w-8 grid place-items-center rounded-lg hover:bg-surface text-muted-foreground"><X className="h-4 w-4" /></button>
        </div>

        <div className="p-5">
          {/* Identity */}
          <div className="flex items-center gap-3">
            <div className="h-14 w-14 rounded-full bg-accent/15 text-accent grid place-items-center text-[16px] font-semibold">
              {customer.name.split(" ").map((n) => n[0]).join("").slice(0, 2)}
            </div>
            <div className="min-w-0">
              <div className="text-[15px] font-semibold truncate">{customer.name}</div>
              <div className="flex items-center gap-1.5 mt-1">
                <ChannelIcon channel={customer.channel} className="h-5 w-5" />
                <Badge tone={STATUS[customer.status]}>{t(`customers.status.${customer.status}`)}</Badge>
              </div>
            </div>
          </div>

          {/* Auto-identified contact */}
          <div className="mt-5 rounded-xl border border-border bg-surface/50 p-3.5">
            <div className="text-[11.5px] text-muted-foreground mb-2">{t("customers.detail.identified")}</div>
            <div className="flex items-center gap-2.5">
              <span className="h-8 w-8 rounded-lg bg-card border border-border grid place-items-center">
                {React.createElement(id.icon, { className: "h-4 w-4 text-muted-foreground" })}
              </span>
              <div>
                <div className="text-[13.5px] font-medium tabular-nums">{id.handle}</div>
                <div className="text-[11.5px] text-muted-foreground">{id.label}</div>
              </div>
            </div>
          </div>

          {/* Stats */}
          <div className="grid grid-cols-2 gap-3 mt-4">
            <div className="rounded-xl border border-border p-3.5">
              <div className="text-[11.5px] text-muted-foreground">{t("customers.detail.orders")}</div>
              <div className="font-display text-[20px] font-semibold tabular-nums mt-1">{customer.orders}</div>
            </div>
            <div className="rounded-xl border border-border p-3.5">
              <div className="text-[11.5px] text-muted-foreground">{t("customers.detail.spent")}</div>
              <div className="font-display text-[20px] font-semibold tabular-nums mt-1">{formatCurrency(customer.spent)}</div>
            </div>
          </div>

          {/* Timeline */}
          <h4 className="text-[12.5px] font-semibold text-muted-foreground uppercase tracking-wide mt-6 mb-3">{t("customers.detail.timeline")}</h4>
          <div className="space-y-3">
            {events.map((e, i) => {
              const Icon = e.icon;
              return (
                <div key={i} className="flex gap-3">
                  <div className="flex flex-col items-center">
                    <span className={`h-8 w-8 rounded-lg grid place-items-center shrink-0 ${TONE[e.tone]}`}><Icon className="h-4 w-4" /></span>
                    {i < events.length - 1 && <span className="w-px flex-1 bg-border my-1" />}
                  </div>
                  <div className="pb-1">
                    <div className="text-[13px] font-medium">{e.title}</div>
                    <div className="text-[12px] text-muted-foreground">{e.detail}</div>
                    <div className="text-[11px] text-muted-foreground/70 mt-0.5">{e.time}</div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}