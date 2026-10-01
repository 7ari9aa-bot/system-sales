import React, { useEffect, useState } from "react";
import { X, Phone, Mail, MessageCircle, ShoppingBag, Clock, CheckCircle2, UserRound } from "lucide-react";
import ChannelIcon from "@/components/dashboard/ChannelIcon";
import { Badge } from "@/components/dashboard/ui";
import { formatCurrency } from "@/lib/regional";
import { api } from "@/lib/api";
import { useT } from "@/lib/i18n";

const EVENT_ICONS = {
  order: ShoppingBag,
  conversation: MessageCircle,
  message: MessageCircle,
  task: CheckCircle2,
  note: UserRound,
};

function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString();
}

export default function CustomerDrawer({ customer, onClose }) {
  const t = useT();
  const [record, setRecord] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [retryAttempt, setRetryAttempt] = useState(0);

  useEffect(() => {
    if (!customer?.id) {
      setRecord(null);
      return undefined;
    }
    let alive = true;
    setRecord(null);
    setError(null);
    setLoading(true);
    api(`/customers/${customer.id}/360?limit=20&timeline_limit=60`)
      .then((data) => alive && setRecord(data))
      .catch((e) => alive && setError(e?.message || "Could not load the customer record."))
      .finally(() => alive && setLoading(false));
    return () => { alive = false; };
  }, [customer?.id, retryAttempt]);

  if (!customer) return null;
  const profile = record?.customer;
  const status = profile?.is_blocked ? "blocked" : "unknown";
  const statusLabel = status === "blocked"
    ? t("customers.status.blocked", "Blocked")
    : t("common.unavailable", "—");
  const timeline = record?.timeline || [];

  return (
    <div className="fixed inset-0 z-50 flex justify-end animate-fade-in" onClick={onClose}>
      <div className="absolute inset-0 bg-black/40" />
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="customer-profile-title"
        className="relative w-full max-w-md h-full bg-card border-l border-border shadow-xl overflow-y-auto scrollbar-thin"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="sticky top-0 bg-card/90 backdrop-blur px-5 py-4 border-b border-border flex items-center justify-between">
          <h3 id="customer-profile-title" className="font-display text-[16px] font-semibold">{t("customers.detail.title")}</h3>
          <button type="button" aria-label={t("common.close", "Close")} onClick={onClose} className="h-8 w-8 grid place-items-center rounded-lg hover:bg-surface text-muted-foreground">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="p-5">
          <div className="flex items-center gap-3">
            <div className="h-14 w-14 rounded-full bg-accent/15 text-accent grid place-items-center text-[16px] font-semibold">
              {String(profile?.name || customer.name).trim().split(/\s+/).map((part) => part[0]).join("").slice(0, 2).toUpperCase()}
            </div>
            <div className="min-w-0">
              <div className="text-[15px] font-semibold truncate">{profile?.name || customer.name}</div>
              {profile && <Badge tone={status === "blocked" ? "destructive" : "muted"}>{statusLabel}</Badge>}
            </div>
          </div>

          {loading && <p className="mt-6 text-sm text-muted-foreground">{t("common.loading")}</p>}
          {error && (
            <div role="alert" className="mt-6 flex items-center justify-between gap-3 rounded-lg bg-destructive/10 p-3 text-sm text-destructive">
              <span>{error}</span>
              <button type="button" onClick={() => setRetryAttempt((attempt) => attempt + 1)} className="shrink-0 font-medium underline">
                {t("common.retry", "Retry")}
              </button>
            </div>
          )}

          {profile && (
            <>
              <div className="mt-5 rounded-xl border border-border bg-surface/50 p-3.5 space-y-3">
                <div className="text-[11.5px] text-muted-foreground">{t("customers.detail.identified")}</div>
                {profile.phone && <ContactLine icon={Phone} value={profile.phone} />}
                {profile.email && <ContactLine icon={Mail} value={profile.email} />}
                {(record.identities || []).map((item) => (
                  <div key={item.id} className="flex items-center gap-2.5 text-[13px]">
                    <ChannelIcon channel={item.channel} className="h-5 w-5" />
                    <span className="text-muted-foreground">{item.channel}</span>
                    <span className="min-w-0 truncate font-medium" dir="auto">{item.external_id}</span>
                  </div>
                ))}
                {!profile.phone && !profile.email && !(record.identities || []).length && (
                  <p className="text-[13px] text-muted-foreground">—</p>
                )}
              </div>

              <div className="grid grid-cols-2 gap-3 mt-4">
                <Stat label={t("customers.detail.orders")} value={record.stats?.orders_shown ?? record.orders?.length ?? 0} />
                <Stat label={t("customers.detail.spent")} value={formatCurrency(Number(profile.lifetime_value || 0))} />
              </div>

              {!!record.tags?.length && (
                <div className="mt-4 flex flex-wrap gap-2">
                  {record.tags.map((tag) => <Badge key={tag.id} tone="muted">{tag.name}</Badge>)}
                </div>
              )}

              <h4 className="text-[12.5px] font-semibold text-muted-foreground uppercase tracking-wide mt-6 mb-3">{t("customers.detail.timeline")}</h4>
              {timeline.length === 0 ? (
                <p className="text-[13px] text-muted-foreground">{t("customers.detail.noActivity", "No recorded activity yet.")}</p>
              ) : (
                <div className="space-y-3">
                  {timeline.map((event, index) => {
                    const Icon = EVENT_ICONS[event.kind] || Clock;
                    return (
                      <div key={`${event.kind}-${event.ref_id || event.at}-${index}`} className="flex gap-3">
                        <span className="h-8 w-8 rounded-lg bg-primary/10 text-primary grid place-items-center shrink-0"><Icon className="h-4 w-4" /></span>
                        <div className="min-w-0 pb-1">
                          <div className="text-[13px] font-medium">{event.title || event.kind}</div>
                          {event.subtitle && <div className="text-[12px] text-muted-foreground">{event.subtitle}</div>}
                          <div className="text-[11px] text-muted-foreground/70 mt-0.5">{formatDate(event.at)}</div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}

              {!!record.orders?.length && (
                <div className="mt-6">
                  <h4 className="text-[12.5px] font-semibold text-muted-foreground uppercase tracking-wide mb-3">{t("customers.detail.orders")}</h4>
                  <div className="space-y-2">
                    {record.orders.slice(0, 5).map((order) => (
                      <div key={order.id} className="flex items-center justify-between gap-3 rounded-lg border border-border p-3">
                        <div className="min-w-0">
                          <div className="text-[13px] font-medium">#{order.number}</div>
                          <div className="text-[11.5px] text-muted-foreground">{order.status}</div>
                        </div>
                        <div className="text-[13px] font-semibold tabular-nums">{formatCurrency(Number(order.grand_total || 0))}</div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </section>
    </div>
  );
}

function ContactLine({ icon: Icon, value }) {
  return (
    <div className="flex items-center gap-2.5 text-[13px]">
      <Icon className="h-4 w-4 text-muted-foreground" />
      <span className="min-w-0 truncate" dir="auto">{value}</span>
    </div>
  );
}

function Stat({ label, value }) {
  return (
    <div className="rounded-xl border border-border p-3.5">
      <div className="text-[11.5px] text-muted-foreground">{label}</div>
      <div className="font-display text-[20px] font-semibold tabular-nums mt-1">{value}</div>
    </div>
  );
}
