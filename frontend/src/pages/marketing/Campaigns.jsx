import React from "react";
import { Plus, TrendingUp } from "lucide-react";
import { Badge } from "@/components/dashboard/ui";
import ChannelIcon from "@/components/dashboard/ChannelIcon";
import { CAMPAIGNS, MARKETING_SNAPSHOT, formatCurrency } from "@/lib/dashboardData";
import { useT } from "@/lib/i18n";

export default function Campaigns() {
  const t = useT();
  const m = MARKETING_SNAPSHOT;
  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3.5 flex-1">
          <Stat label={t("marketing.stat.active")} value={m.activeCampaigns} />
          <Stat label={t("marketing.stat.revenue")} value={formatCurrency(m.attributedRevenue, true)} icon={<TrendingUp className="h-4 w-4" />} />
          <Stat label={t("marketing.stat.leads")} value={m.leads} />
          <Stat label={t("marketing.stat.conversion")} value={`${m.conversion}%`} />
        </div>
        <button className="h-9 px-3.5 rounded-lg bg-primary text-primary-foreground text-[13px] font-medium flex items-center gap-1.5 ml-4 shrink-0">
          <Plus className="h-4 w-4" /> {t("marketing.new")}
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {CAMPAIGNS.map((c) => (
          <div key={c.id} className="rounded-2xl bg-card border border-border p-5">
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-3">
                <ChannelIcon channel={c.channel} />
                <div>
                  <div className="text-[14px] font-semibold">{c.name}</div>
                  <div className="text-[12px] text-muted-foreground">{t(`channel.${c.channel}`)}</div>
                </div>
              </div>
              <Badge tone={c.status === "active" ? "success" : "muted"}>{t(`marketing.status.${c.status}`)}</Badge>
            </div>
            <div className="mt-4 grid grid-cols-4 gap-3 pt-4 border-t border-border">
              <Metric label={t("marketing.metric.revenue")} value={formatCurrency(c.revenue, true)} />
              <Metric label={t("marketing.metric.leads")} value={c.leads} />
              <Metric label={t("marketing.metric.conversion")} value={`${c.conversion}%`} />
              <Metric label={t("marketing.campaign.roas")} value={`${(c.revenue / Math.max(1, c.leads * 8)).toFixed(1)}×`} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function Stat({ label, value, icon }) {
  return (
    <div className="rounded-2xl bg-card border border-border p-4">
      <div className="flex items-center gap-2 text-muted-foreground">{icon}<span className="text-[12.5px] font-medium">{label}</span></div>
      <div className="mt-2 font-display text-[22px] font-semibold tabular-nums">{value}</div>
    </div>
  );
}
function Metric({ label, value }) {
  return (
    <div>
      <div className="text-[11.5px] text-muted-foreground">{label}</div>
      <div className="text-[15px] font-semibold tabular-nums mt-0.5">{value}</div>
    </div>
  );
}