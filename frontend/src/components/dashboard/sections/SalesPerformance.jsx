import React from "react";
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from "recharts";
import { SectionCard, Delta, Skeleton } from "@/components/dashboard/ui";
import { useDashboard } from "@/lib/dashboardContext";
import { formatCurrency } from "@/lib/dashboardData";
import useSalesStats from "@/hooks/useSalesStats";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";

function ChartTooltip({ active, payload, t }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-xl border border-border bg-popover shadow-lg px-3 py-2.5">
      <div className="text-[11px] text-muted-foreground mb-1">{payload[0]?.payload?.label}</div>
      <div className="space-y-1">
        {payload.map((p) => (
          <div key={p.dataKey} className="flex items-center gap-2 text-[12px]">
            <span className="h-2 w-2 rounded-full" style={{ background: p.color }} />
            <span className="text-muted-foreground">{t(p.dataKey === "revenue" ? "chart.revenue" : "chart.orders")}</span>
            <span className="font-semibold tabular-nums ml-auto">
              {p.dataKey === "revenue" ? formatCurrency(p.value) : p.value}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

/** أداء المبيعات — السلسلة اليومية الحقيقية (صافي كل يوم تجاري من
 *  GET /analytics/overview)، وبدل «أفضل المنتجات» الوهمية: أعلى
 *  المصادر المنسوبة لآخر لمسة من /analytics/dashboard بوسم صريح. */
export default function SalesPerformance() {
  const { range } = useDashboard();
  const t = useT();
  const live = useSalesStats(range);
  const data = live?.trend || [];
  const netSales = live?.netSales ?? 0;
  const orders = live?.orders ?? 0;
  const sources = (live?.sources ?? []).slice(0, 4);

  return (
    <SectionCard
      title={t("home.salesPerformance.title")}
      action={t("home.viewAnalytics")}
      actionTo="/analytics"
      bodyClassName="pt-2"
    >
      <div className="flex items-center justify-between gap-3 mb-3">
        <div className="inline-flex p-0.5 rounded-lg bg-surface border border-border">
          <span className="px-3 py-1 rounded-md text-[12.5px] font-medium bg-card text-foreground shadow-sm">
            {t("chart.revenue")}
          </span>
        </div>
        <div className="flex items-center gap-4 text-right">
          <div>
            <div className="text-[11px] text-muted-foreground">{t("chart.revenue")}</div>
            <div className="font-display text-[18px] font-semibold tabular-nums leading-none">
              {formatCurrency(netSales, true)}
            </div>
          </div>
          <div className="hidden sm:block">
            <div className="text-[11px] text-muted-foreground">{t("home.avgOrder")}</div>
            <div className="font-display text-[18px] font-semibold tabular-nums leading-none">
              {formatCurrency(orders ? Math.round(netSales / orders) : 0)}
            </div>
          </div>
        </div>
      </div>

      <div className="h-[200px] -mx-1">
        {data.length === 0 ? (
          <div className="h-full">
            <Skeleton className="h-[150px] w-full" />
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data} margin={{ top: 8, right: 8, left: 8, bottom: 0 }}>
              <defs>
                <linearGradient id="revGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="hsl(var(--primary))" stopOpacity={0.28} />
                  <stop offset="100%" stopColor="hsl(var(--primary))" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="hsl(var(--border))" strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="label" tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }} axisLine={false} tickLine={false} minTickGap={24} />
              <YAxis tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }} axisLine={false} tickLine={false} width={40} tickFormatter={(v) => `${(v / 1000).toFixed(0)}k`} />
              <Tooltip content={<ChartTooltip t={t} />} cursor={{ stroke: "hsl(var(--border))", strokeWidth: 1 }} />
              <Area type="monotone" dataKey="revenue" stroke="hsl(var(--primary))" strokeWidth={2.5} fill="url(#revGrad)" dot={false} activeDot={{ r: 4, strokeWidth: 0 }} />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>

      {sources.length > 0 && (
        <div className="mt-4 pt-4 border-t border-border" data-testid="attributed-by-source">
          <div className="flex items-center justify-between mb-2.5">
            <span className="text-[12.5px] font-medium text-muted-foreground">{t("analytics.topSources")}</span>
            <span className="text-[11px] text-muted-foreground">{t("analytics.attributedHint")}</span>
          </div>
          <ul className="space-y-2">
            {sources.map((s, i) => (
              <li key={s.source} className="flex items-center gap-3">
                <span className="text-[12px] font-semibold text-muted-foreground w-4 tabular-nums">{i + 1}</span>
                <span className="text-[13px] font-medium flex-1 truncate">{s.source}</span>
                <span className="text-[11px] text-muted-foreground tabular-nums">{s.conversions}</span>
                <span className="text-[13px] font-semibold tabular-nums w-20 text-right">{formatCurrency(Number(s.revenue), true)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </SectionCard>
  );
}
