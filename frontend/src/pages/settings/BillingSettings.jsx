import React from "react";
import { useT } from "@/lib/i18n";
import { useRealUsage } from "@/hooks/useRealData";
import { formatCurrency } from "@/lib/regional";
import SettingsShell, { SettingCard, SettingRow } from "@/components/settings/SettingsShell";
import { ProgressBar, Badge } from "@/components/dashboard/ui";
import { Button } from "@/components/ui/button";
import { Sparkles, MessageSquare, Users, AlertTriangle } from "lucide-react";

// Token model: a hard cap plus a reserve cap. When the cap is exceeded the
// service keeps running on the reserve; once the reserve is exhausted the
// service locks until tokens are renewed.
const TOKEN_PLAN = {
  cap: 10000000,
  consumed: 10200000, // 200k over the cap → drawing from reserve
  reserveCap: 2000000,
  reserveConsumed: 200000,
  renewDate: "Oct 14, 2026",
  endDate: "Nov 14, 2026",
};

const INVOICES = [
  { id: "INV-0926", date: "Sep 14, 2026", amount: 42.18, status: "Paid" },
  { id: "INV-0826", date: "Aug 14, 2026", amount: 38.4, status: "Paid" },
  { id: "INV-0726", date: "Jul 14, 2026", amount: 31.2, status: "Paid" },
];

export default function BillingSettings() {
  const t = useT();
  const u = useRealUsage();

  const overCap = TOKEN_PLAN.consumed > TOKEN_PLAN.cap;
  const reserveRemaining = Math.max(0, TOKEN_PLAN.reserveCap - TOKEN_PLAN.reserveConsumed);
  const reserveExhausted = overCap && reserveRemaining <= 0;
  const statusKey = reserveExhausted ? "locked" : overCap ? "reserve" : "healthy";
  const statusTone = reserveExhausted ? "destructive" : overCap ? "warning" : "success";

  const fmt = (n) => new Intl.NumberFormat("en-GB").format(n);

  return (
    <SettingsShell
      title={t("settings.nav.billing")}
      subtitle={t("settings.billing.desc")}
      actions={<Button className="h-9">{t("billing.upgrade")}</Button>}
    >
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        {/* Plan */}
        <SettingCard className="lg:col-span-1">
          <div className="flex items-center gap-2.5 pt-1">
            <span className="h-10 w-10 rounded-lg bg-primary text-primary-foreground grid place-items-center font-display font-semibold text-[15px]">G</span>
            <div>
              <div className="font-display text-[17px] font-semibold leading-none">{t("ls.plan", { plan: u.plan })}</div>
              <div className="text-[12px] text-muted-foreground mt-1">
                {formatCurrency(u.spend)} {t("billing.spent")}
              </div>
            </div>
          </div>
          <div className="mt-4 space-y-3">
            <Row label={t("billing.renewDate")} value={TOKEN_PLAN.renewDate} />
            <Row label={t("billing.endDate")} value={TOKEN_PLAN.endDate} />
          </div>
          <div className="mt-4 pt-3 border-t border-border space-y-4">
            <UsageBar icon={Sparkles} label={t("ls.aiUsage")} used={u.aiUsage.used} limit={u.aiUsage.limit} unit={t("ls.credits")} tone="accent" />
            <UsageBar icon={MessageSquare} label={t("ls.conversations")} used={u.conversations.used} limit={u.conversations.limit} unit="" tone="primary" />
            <UsageBar icon={Users} label={t("ls.team")} used={u.team.used} limit={u.team.limit} unit={t("ls.seats")} tone="primary" />
          </div>
        </SettingCard>

        {/* Token usage */}
        <SettingCard title={t("billing.tokenUsage")} className="lg:col-span-2">
          <div className="pt-2 space-y-4">
            <div className="flex items-center justify-between">
              <span className="text-[13px] font-medium">{t("billing.tokenCap")}</span>
              <Badge tone={statusTone}>{t(`billing.status.${statusKey}`)}</Badge>
            </div>
            <ProgressBar used={Math.min(TOKEN_PLAN.consumed, TOKEN_PLAN.cap)} limit={TOKEN_PLAN.cap} tone={overCap ? "warning" : "primary"} />
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
              <Stat label={t("billing.tokenCap")} value={fmt(TOKEN_PLAN.cap)} />
              <Stat label={t("billing.consumed")} value={fmt(TOKEN_PLAN.consumed)} />
              <Stat label={t("billing.remaining")} value={fmt(Math.max(0, TOKEN_PLAN.cap - TOKEN_PLAN.consumed))} />
              <Stat label={t("billing.reserveCap")} value={fmt(TOKEN_PLAN.reserveCap)} />
            </div>

            {overCap && (
              <div className="rounded-lg border border-warning/40 bg-warning/10 p-3.5 flex items-start gap-2.5">
                <AlertTriangle className="h-4 w-4 text-warning shrink-0 mt-0.5" />
                <div className="min-w-0">
                  <div className="text-[12.5px] font-medium text-warning">{t("billing.status.reserve")}</div>
                  <p className="text-[12px] text-muted-foreground mt-0.5 leading-relaxed">{t("billing.reserveWarn")}</p>
                </div>
              </div>
            )}

            <div className="pt-2 border-t border-border">
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-[12.5px] font-medium">{t("billing.reserveCap")}</span>
                <span className="text-[11.5px] tabular-nums text-muted-foreground">
                  {fmt(TOKEN_PLAN.reserveConsumed)} / {fmt(TOKEN_PLAN.reserveCap)}
                </span>
              </div>
              <ProgressBar used={TOKEN_PLAN.reserveConsumed} limit={TOKEN_PLAN.reserveCap} tone={reserveExhausted ? "destructive" : "warning"} />
              <div className="mt-1.5 text-[11.5px] text-muted-foreground">
                {t("billing.reserveRemaining")}: <span className="tabular-nums bdi">{fmt(reserveRemaining)}</span>
              </div>
            </div>

            <div className="flex items-center justify-end gap-2 pt-1">
              <Button variant="outline" className="h-8 text-[12.5px]">{t("ls.updateCard")}</Button>
              <Button className="h-8 text-[12.5px]">{t("billing.renewTokens")}</Button>
            </div>
          </div>
        </SettingCard>

        {/* Invoices */}
        <SettingCard title={t("billing.invoices")} className="lg:col-span-3">
          <div className="overflow-x-auto -mx-5 px-5">
            <table className="w-full text-left">
              <thead>
                <tr className="text-[11px] uppercase tracking-wide text-muted-foreground border-b border-border">
                  <th className="py-2.5 font-medium">{t("ls.invoice")}</th>
                  <th className="py-2.5 font-medium">{t("ls.date")}</th>
                  <th className="py-2.5 font-medium">{t("ls.amount")}</th>
                  <th className="py-2.5 font-medium">{t("ls.status")}</th>
                </tr>
              </thead>
              <tbody>
                {INVOICES.map((inv) => (
                  <tr key={inv.id} className="border-b border-border last:border-0">
                    <td className="py-3 text-[13px] font-medium tabular-nums">{inv.id}</td>
                    <td className="py-3 text-[12.5px] text-muted-foreground">{inv.date}</td>
                    <td className="py-3 text-[13px] tabular-nums bdi">{formatCurrency(inv.amount)}</td>
                    <td className="py-3"><Badge tone="success">{inv.status}</Badge></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </SettingCard>
      </div>
    </SettingsShell>
  );
}

function Row({ label, value }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-[12.5px] text-muted-foreground">{label}</span>
      <span className="text-[13px] font-medium tabular-nums">{value}</span>
    </div>
  );
}

function Stat({ label, value }) {
  return (
    <div className="rounded-lg bg-surface border border-border px-3 py-2.5">
      <div className="text-[11px] text-muted-foreground whitespace-nowrap truncate">{label}</div>
      <div className="text-[15px] font-semibold tabular-nums mt-0.5">{value}</div>
    </div>
  );
}

function UsageBar({ icon: Icon, label, used, limit, unit, tone }) {
  const pct = Math.round((used / limit) * 100);
  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <span className="flex items-center gap-2 text-[12.5px] font-medium">
          <Icon className="h-3.5 w-3.5 text-muted-foreground" />
          {label}
        </span>
        <span className="text-[11.5px] tabular-nums text-muted-foreground">
          {used.toLocaleString()} / {limit.toLocaleString()} {unit}
        </span>
      </div>
      <ProgressBar used={used} limit={limit} tone={pct > 85 ? "warning" : tone} />
    </div>
  );
}