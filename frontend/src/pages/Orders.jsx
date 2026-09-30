import React, { useState } from "react";
import { Download, Search, DollarSign, ShoppingBag, TrendingUp, Clock, AlertCircle, Loader2 } from "lucide-react";
import { PageHeader, Badge, KpiCard } from "@/components/dashboard/ui";
import ChannelIcon from "@/components/dashboard/ChannelIcon";
import { formatCurrency } from "@/lib/dashboardData";
import useOrders from "@/hooks/useOrders";
import useSalesStats from "@/hooks/useSalesStats";
import { useDashboard } from "@/lib/dashboardContext";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";

export default function Orders() {
  const t = useT();
  const { range } = useDashboard();
  const live = useSalesStats(range);
  const s = {
    netSales: { value: live?.netSales ?? 0 },
    orders: { value: live?.orders ?? 0 },
    customers: { value: live?.customers ?? 0 },
  };
  const [filter, setFilter] = useState("all");
  const [q, setQ] = useState("");

  const STATUS = {
    fulfilled: { label: t("orders.status.fulfilled"), tone: "success" },
    processing: { label: t("orders.status.processing"), tone: "primary" },
    "follow-up": { label: t("orders.status.followup"), tone: "warning" },
  };

  const FILTERS = [
    { id: "all", label: t("orders.filter.all") },
    { id: "processing", label: t("orders.filter.processing") },
    { id: "follow-up", label: t("orders.filter.followup") },
    { id: "fulfilled", label: t("orders.filter.fulfilled") },
  ];

  const orders = useOrders();
  const ORDERS = orders || [];
  const filtered = ORDERS.filter((o) => {
    const matchF = filter === "all" || o.status === filter;
    const matchQ = !q || o.customer.toLowerCase().includes(q.toLowerCase()) || String(o.id).includes(q);
    return matchF && matchQ;
  });
  const followUpCount = ORDERS.filter((o) => o.status === "follow-up").length;

  return (
    <div>
      <PageHeader
        title={t("orders.title")}
        subtitle={t("orders.subtitle")}
        actions={
          <button className="h-9 px-3.5 rounded-lg bg-card border border-border text-[13px] font-medium flex items-center gap-1.5 hover:bg-surface">
            <Download className="h-4 w-4" /> {t("orders.export")}
          </button>
        }
      />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3.5 mb-5">
        <KpiCard label={t("orders.kpi.netSales")} value={formatCurrency(s.netSales.value, true)} to="/orders" accent={{ icon: <DollarSign />, bg: "bg-primary/10", color: "text-primary" }} />
        <KpiCard label={t("orders.kpi.orders")} value={s.orders.value.toLocaleString()} to="/orders" accent={{ icon: <ShoppingBag />, bg: "bg-accent/10", color: "text-accent" }} />
        <KpiCard label={t("orders.kpi.aov")} value={formatCurrency(Math.round(s.netSales.value / s.orders.value))} to="/orders" accent={{ icon: <TrendingUp />, bg: "bg-chart-4/10", color: "text-chart-4" }} />
        <KpiCard label={t("orders.kpi.followUp")} value={followUpCount} to="/orders" accent={{ icon: <Clock />, bg: "bg-warning/15", color: "text-warning" }} />
      </div>

      {followUpCount > 0 && (
        <div className="mb-4 rounded-xl border border-warning/30 bg-warning/10 px-4 py-3 flex items-center gap-2.5 text-warning">
          <AlertCircle className="h-4 w-4 shrink-0" />
          <span className="text-[13px] font-medium">{t("orders.attention", { n: followUpCount })}</span>
        </div>
      )}

      <div className="rounded-2xl bg-card border border-border overflow-hidden">
        <div className="px-5 py-3 border-b border-border flex flex-col sm:flex-row gap-3 sm:items-center">
          <div className="flex gap-1">
            {FILTERS.map((f) => (
              <button key={f.id} onClick={() => setFilter(f.id)} className={cn("px-2.5 py-1 rounded-md text-[12px] font-medium transition-colors", filter === f.id ? "bg-primary text-primary-foreground" : "bg-surface text-muted-foreground hover:text-foreground")}>{f.label}</button>
            ))}
          </div>
          <div className="relative sm:ml-auto sm:w-56">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("orders.search")} className="w-full h-9 pl-9 pr-3 rounded-lg bg-surface border border-border text-[13px] placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring/30" />
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[820px] table-fixed text-left">
            <colgroup>
              <col style={{ width: "10%" }} /><col style={{ width: "21%" }} /><col style={{ width: "16%" }} />
              <col style={{ width: "10%" }} /><col style={{ width: "15%" }} /><col style={{ width: "16%" }} /><col style={{ width: "12%" }} />
            </colgroup>
            <thead>
              <tr className="border-b border-border text-[11.5px] uppercase tracking-wide text-muted-foreground">
                <th className="font-medium px-5 py-3">{t("orders.col.order")}</th>
                <th className="font-medium px-5 py-3">{t("orders.col.customer")}</th>
                <th className="font-medium px-5 py-3">{t("orders.col.channel")}</th>
                <th className="font-medium px-5 py-3 text-right">{t("orders.col.items")}</th>
                <th className="font-medium px-5 py-3 text-right">{t("orders.col.total")}</th>
                <th className="font-medium px-5 py-3">{t("orders.col.status")}</th>
                <th className="font-medium px-5 py-3">{t("orders.col.date")}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {filtered.map((o) => (
                <tr key={o.id} className="hover:bg-surface/50 transition-colors">
                  <td className="px-5 py-3 text-[13.5px] font-semibold tabular-nums">#{o.id}</td>
                  <td className="px-5 py-3 text-[13.5px] font-medium">{o.customer}</td>
                  <td className="px-5 py-3">
                    <div className="flex items-center gap-2">
                      <ChannelIcon channel={o.channel} className="h-6 w-6" />
                      <span className="text-[12.5px] text-muted-foreground">{t(`channel.${o.channel}`)}</span>
                    </div>
                  </td>
                  <td className="px-5 py-3 text-right text-[13.5px] tabular-nums">{o.items}</td>
                  <td className="px-5 py-3 text-right text-[13.5px] font-semibold tabular-nums">{formatCurrency(o.total)}</td>
                  <td className="px-5 py-3"><Badge tone={STATUS[o.status].tone}>{STATUS[o.status].label}</Badge></td>
                  <td className="px-5 py-3 text-[12.5px] text-muted-foreground">{o.date}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {orders === null && <div className="py-12 grid place-items-center text-muted-foreground"><Loader2 className="h-6 w-6 animate-spin" /></div>}
        {orders !== null && filtered.length === 0 && <div className="py-12 text-center text-[13.5px] text-muted-foreground">{t("orders.empty")}</div>}
      </div>
    </div>
  );
}