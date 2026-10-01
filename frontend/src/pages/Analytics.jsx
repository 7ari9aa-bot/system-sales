import React from "react";
import {
  AreaChart, Area, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, PieChart, Pie, Cell, Legend,
} from "recharts";
import { Link } from "react-router-dom";
import { TrendingUp, TrendingDown, ArrowRight, Package, Clock, Sparkles, ShoppingBag } from "lucide-react";
import { PageHeader, SectionCard, Delta, Badge } from "@/components/dashboard/ui";
import { useDashboard } from "@/lib/dashboardContext";
import { formatCurrency } from "@/lib/dashboardData";
import useSalesStats from "@/hooks/useSalesStats";
import { useT } from "@/lib/i18n";

const SOURCE_COLORS = ["hsl(var(--chart-1))", "hsl(var(--chart-2))", "hsl(var(--chart-4))", "hsl(var(--chart-3))"];

function ChartTooltip({ active, payload, label, t }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-xl border border-border bg-popover shadow-lg px-3 py-2.5">
      <div className="text-[11px] text-muted-foreground mb-1">{label}</div>
      {payload.map((p) => (
        <div key={p.dataKey || p.name} className="flex items-center gap-2 text-[12px]">
          <span className="h-2 w-2 rounded-full" style={{ background: p.color }} />
          <span className="text-muted-foreground">{p.name || p.dataKey}</span>
          <span className="font-semibold tabular-nums ml-auto">{typeof p.value === "number" ? formatCurrency(p.value) : p.value}</span>
        </div>
      ))}
    </div>
  );
}

export default function Analytics() {
  const t = useT();
  const { range } = useDashboard();
  const live = useSalesStats(range);
  const data = live?.trend || [];
  const s = {
    netSales: { value: live?.netSales ?? 0 },
    orders: { value: live?.orders ?? 0 },
    customers: { value: live?.customers ?? 0 },
    aiConversations: { value: live?.openConversations ?? 0 },
    aiSpend: { value: 0 },
  };
  const sources = live?.sources || [];

  // "What changed" — أرقام حقيقية بدون دلتا وهمية: الـbackend مش بينشر مقارنات فترات
  const changes = [
    { label: t("analytics.kpi.netSales"), value: formatCurrency(s.netSales.value, true), icon: ShoppingBag },
    { label: t("analytics.kpi.orders"), value: s.orders.value.toLocaleString(), icon: TrendingUp },
    { label: t("home.customers"), value: s.customers.value.toLocaleString(), icon: Package },
  ];

  // "What to do next" — إجراءات مشتقة من أرقام حقيقية فقط، وبتظهر لما يكون سببها موجود
  const next = [];
  if ((live?.lowStock ?? 0) + (live?.outOfStock ?? 0) > 0) {
    next.push({ icon: Package, tone: "warning", title: t("insight.stock.title", { n: live.lowStock }), action: t("common.review"), to: "/inventory" });
  }
  if ((live?.unread ?? 0) > 0) {
    next.push({ icon: Clock, tone: "primary", title: t("home.attention.inbox.title", { n: live.unread }), action: t("home.attention.inbox.action"), to: "/inbox" });
  }
  if (sources.length) {
    next.push({ icon: TrendingUp, tone: "success", title: t("insight.source.title", { name: sources[0].source }), action: t("home.viewAnalytics"), to: "/marketing" });
  }
  const NEXT_TONE = {
    warning: "bg-warning/15 text-warning",
    primary: "bg-primary/10 text-primary",
    success: "bg-success/15 text-success",
  };

  return (
    <div>
      <PageHeader title={t("analytics.title")} subtitle={t("analytics.subtitle")} />

      {/* What changed / What to do next — the cockpit summary */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5 mb-5">
        <SectionCard title={t("analytics.whatChanged")} bodyClassName="pt-1">
          <div className="space-y-3">
            {changes.map((c) => {
              const Icon = c.icon;
              const up = c.delta >= 0;
              return (
                <div key={c.label} className="flex items-center gap-3 p-3 rounded-xl border border-border">
                  <span className="h-9 w-9 rounded-lg bg-surface grid place-items-center text-muted-foreground"><Icon className="h-[18px] w-[18px]" /></span>
                  <div className="flex-1">
                    <div className="text-[12px] text-muted-foreground">{c.label}</div>
                    <div className="font-display text-[18px] font-semibold tabular-nums">{c.value}</div>
                  </div>
                </div>
              );
            })}
          </div>
        </SectionCard>

        <SectionCard title={t("analytics.whatNext")} bodyClassName="pt-1">
          <div className="space-y-2.5">
            {next.map((n, i) => {
              const Icon = n.icon;
              return (
                <Link key={i} to={n.to} className="flex items-center gap-3 p-3 rounded-xl border border-border hover:border-primary/40 hover:bg-surface/50 transition-colors group">
                  <span className={`h-9 w-9 rounded-lg grid place-items-center ${NEXT_TONE[n.tone]}`}><Icon className="h-[18px] w-[18px]" /></span>
                  <span className="flex-1 text-[13px] font-medium">{n.title}</span>
                  <span className="text-[12px] text-primary flex items-center gap-1">{n.action}<ArrowRight className="h-3.5 w-3.5 group-hover:translate-x-0.5 transition-transform" /></span>
                </Link>
              );
            })}
          </div>
        </SectionCard>
      </div>

      <SectionCard title={t("analytics.revenueOverTime")} className="mb-5" bodyClassName="pt-2">
        <div className="h-[260px]">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data} margin={{ top: 8, right: 8, left: 8, bottom: 0 }}>
              <defs>
                <linearGradient id="aGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="hsl(var(--primary))" stopOpacity={0.3} />
                  <stop offset="100%" stopColor="hsl(var(--primary))" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="hsl(var(--border))" strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="label" tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }} axisLine={false} tickLine={false} minTickGap={24} />
              <YAxis tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }} axisLine={false} tickLine={false} width={44} tickFormatter={(v) => `${(v / 1000).toFixed(0)}k`} />
              <Tooltip content={<ChartTooltip t={t} />} cursor={{ stroke: "hsl(var(--border))" }} />
              <Area type="monotone" dataKey="revenue" name={t("chart.revenue")} stroke="hsl(var(--primary))" strokeWidth={2.5} fill="url(#aGrad)" dot={false} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </SectionCard>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <SectionCard title={t("analytics.ordersByPeriod")} bodyClassName="pt-2">
          <div className="h-[220px]">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data} margin={{ top: 8, right: 8, left: 8, bottom: 0 }}>
                <CartesianGrid stroke="hsl(var(--border))" strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="label" tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }} axisLine={false} tickLine={false} minTickGap={24} />
                <YAxis tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }} axisLine={false} tickLine={false} width={32} />
                <Tooltip content={<ChartTooltip t={t} />} cursor={{ fill: "hsl(var(--surface))" }} />
                <Bar dataKey="orders" name={t("chart.orders")} fill="hsl(var(--accent))" radius={[4, 4, 0, 0]} barSize={18} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </SectionCard>

        <SectionCard title={t("analytics.attributedTitle")} bodyClassName="pt-2">
          <div className="h-[220px]">
            {sources.length === 0 ? (
              <div className="grid h-full place-items-center text-[13px] text-muted-foreground">{t("insight.empty")}</div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={sources.map((src, i) => ({ name: src.source, value: Number(src.revenue) || 0, color: SOURCE_COLORS[i % SOURCE_COLORS.length] }))} dataKey="value" nameKey="name" innerRadius={50} outerRadius={78} paddingAngle={2}>
                    {sources.map((src, i) => (
                      <Cell key={src.source} fill={SOURCE_COLORS[i % SOURCE_COLORS.length]} stroke="hsl(var(--card))" strokeWidth={2} />
                    ))}
                  </Pie>
                  <Tooltip content={<ChartTooltip t={t} />} />
                  <Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} />
                </PieChart>
              </ResponsiveContainer>
            )}
          </div>
        </SectionCard>
      </div>

      <SectionCard title={t("analytics.topProducts")} className="mt-5">
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-border text-[11.5px] uppercase tracking-wide text-muted-foreground">
              <th className="font-medium py-2.5">#</th>
              <th className="font-medium py-2.5">{t("analytics.col.product")}</th>
              <th className="font-medium py-2.5 text-right">{t("analytics.col.units")}</th>
              <th className="font-medium py-2.5 text-right">{t("analytics.col.revenue")}</th>
              <th className="font-medium py-2.5 text-right">{t("analytics.col.trend")}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {sources.map((src, i) => (
              <li key={src.source} className="flex items-center gap-3">
                <span className="text-[12px] font-semibold text-muted-foreground w-4 tabular-nums">{i + 1}</span>
                <span className="text-[13px] font-medium flex-1 truncate">{src.source}</span>
                <span className="text-[11px] text-muted-foreground tabular-nums">{src.conversions}</span>
                <span className="text-[13px] font-semibold tabular-nums w-20 text-right">{formatCurrency(Number(src.revenue), true)}</span>
              </li>
            ))}
          </tbody>
        </table>
      </SectionCard>
    </div>
  );
}