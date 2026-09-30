import React from "react";
import { Plus, Users, Crown, Sparkles, ShoppingBag } from "lucide-react";
import { Badge } from "@/components/dashboard/ui";
import { formatCurrency } from "@/lib/dashboardData";
import useCustomers from "@/hooks/useCustomers";
import { useT } from "@/lib/i18n";

const SEGMENTS = [
  { id: "s1", icon: Crown, tone: "warning", count: 42 },
  { id: "s2", icon: ShoppingBag, tone: "success", count: 318 },
  { id: "s3", icon: Sparkles, tone: "accent", count: 74 },
  { id: "s4", icon: Users, tone: "destructive", count: 126 },
];

export default function Audience() {
  const t = useT();
  const customers = useCustomers();
  const TONE = { warning: "warning", success: "success", accent: "accent", destructive: "destructive" };
  const ICON_TONE = {
    warning: "bg-warning/10 text-warning",
    success: "bg-success/15 text-success",
    accent: "bg-accent/10 text-accent",
    destructive: "bg-destructive/10 text-destructive",
  };
  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="font-display text-[15px] font-semibold">{t("marketing.audience.segments")}</h2>
        <button className="h-9 px-3.5 rounded-lg bg-primary text-primary-foreground text-[13px] font-medium flex items-center gap-1.5">
          <Plus className="h-4 w-4" /> {t("marketing.audience.newSegment")}
        </button>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3.5 mb-6">
        {SEGMENTS.map((s) => {
          const Icon = s.icon;
          return (
            <div key={s.id} className="rounded-2xl bg-card border border-border p-4 hover:border-primary/40 transition-colors cursor-pointer">
              <div className="flex items-center justify-between">
                <span className={`h-9 w-9 rounded-lg grid place-items-center ${ICON_TONE[s.tone]}`}>
                  <Icon className="h-[18px] w-[18px]" />
                </span>
                <Badge tone={TONE[s.tone]}>{s.count.toLocaleString()}</Badge>
              </div>
              <div className="mt-3 text-[13.5px] font-semibold truncate">{t(`segment.${s.id}.name`)}</div>
              <div className="text-[11.5px] text-muted-foreground mt-0.5 truncate">{t(`segment.${s.id}.rule`)}</div>
            </div>
          );
        })}
      </div>

      <h2 className="font-display text-[15px] font-semibold mb-3">{t("marketing.audience.contacts")}</h2>
      <div className="rounded-2xl bg-card border border-border overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] table-fixed text-left">
            <colgroup>
              <col style={{ width: "40%" }} /><col style={{ width: "18%" }} /><col style={{ width: "24%" }} /><col style={{ width: "18%" }} />
            </colgroup>
            <thead>
              <tr className="border-b border-border text-[11.5px] uppercase tracking-wide text-muted-foreground">
                <th className="font-medium px-5 py-3">{t("customers.col.customer")}</th>
                <th className="font-medium px-5 py-3 text-right">{t("customers.col.orders")}</th>
                <th className="font-medium px-5 py-3 text-right">{t("customers.col.ltv")}</th>
                <th className="font-medium px-5 py-3">{t("customers.col.status")}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {(customers || []).map((c) => (
                <tr key={c.id} className="hover:bg-surface/50 transition-colors">
                  <td className="px-5 py-3 text-[13.5px] font-medium">{c.name}</td>
                  <td className="px-5 py-3 text-right text-[13.5px] tabular-nums">{c.orders}</td>
                  <td className="px-5 py-3 text-right text-[13.5px] font-semibold tabular-nums">{formatCurrency(c.spent)}</td>
                  <td className="px-5 py-3"><Badge tone={{ active: "primary", lead: "accent", vip: "warning" }[c.status]}>{t(`customers.status.${c.status}`)}</Badge></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}