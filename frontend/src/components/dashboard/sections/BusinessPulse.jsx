import React from "react";
import { DollarSign, ShoppingBag, Sparkles, TrendingUp, Users } from "lucide-react";
import { KpiCard, KpiSkeleton } from "@/components/dashboard/ui";
import { useDashboard } from "@/lib/dashboardContext";
import { formatCurrency } from "@/lib/dashboardData";
import { useT } from "@/lib/i18n";
import useSalesStats from "@/hooks/useSalesStats";
import useUsageSummary from "@/hooks/useUsageSummary";

/** نبض الأعمال — أرقام حقيقية فقط: صافي المبيعات والطلبات من read model
 *  السيرفر (صافي بعد المرتجعات)، العملاء عدد حقيقي، طلبات الذكاء من
 *  /analytics/dashboard والمصروف من /ai/usage/summary. مفيش نسب تغيّر
 *  وهمية — الـbackend مش بينشر delta، فالشارة مش بتظهر. */
export default function BusinessPulse() {
  const { range } = useDashboard();
  const t = useT();
  const live = useSalesStats(range);
  const usage = useUsageSummary();

  const netSales = live?.netSales ?? null;
  const orders = live?.orders ?? null;
  const customers = live?.customers ?? null;
  const aiOrders = live?.aiOrders ?? null;
  const aiCost = usage?.totals?.cost ?? null;

  if (!live) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-3.5" data-testid="dash-pulse">
        {usage?.error && <div role="status" className="col-span-full flex items-center justify-between gap-3 text-[11.5px] text-muted-foreground">
          <span>{usage.error}</span>
          <button type="button" onClick={usage.retry} className="shrink-0 text-primary hover:underline">{t("common.retry", "Retry")}</button>
        </div>}
        {[0, 1, 2, 3, 4].map((i) => <KpiSkeleton key={i} />)}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-3.5" data-testid="dash-pulse">
      {live.dashboardError && <div role="alert" className="col-span-full flex items-center justify-between gap-3 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
        <span>{live.dashboardError}</span>
        <button type="button" onClick={live.retryDashboard} className="shrink-0 underline">{t("common.retry", "Retry")}</button>
      </div>}
      {usage?.error && <div role="status" className="col-span-full flex items-center justify-between gap-3 text-[11.5px] text-muted-foreground">
        <span>{usage.error}</span>
        <button type="button" onClick={usage.retry} className="shrink-0 text-primary hover:underline">{t("common.retry", "Retry")}</button>
      </div>}
      <KpiCard
        label={t("home.netSales")}
        value={netSales == null ? "—" : formatCurrency(netSales)}
        sub={orders == null ? undefined : t("home.xOrders", { n: orders })}
        delta={live.netSalesDelta}
        to="/orders"
        accent={{ icon: <DollarSign />, bg: "bg-primary/10", color: "text-primary" }}
      />
      <KpiCard
        label={t("home.orders")}
        value={orders == null ? "—" : orders.toLocaleString()}
        delta={live.ordersDelta}
        to="/orders"
        accent={{ icon: <ShoppingBag />, bg: "bg-accent/10", color: "text-accent" }}
      />
      <KpiCard
        label={t("home.customers")}
        value={customers == null ? "—" : customers.toLocaleString()}
        to="/customers"
        accent={{ icon: <Users />, bg: "bg-chart-4/10", color: "text-chart-4" }}
      />
      <KpiCard
        label={t("home.aiOrders")}
        value={aiOrders == null ? "—" : aiOrders.toLocaleString()}
        sub={aiOrders == null ? undefined : t("home.aiOrdersHint")}
        to="/ai"
        accent={{ icon: <Sparkles />, bg: "bg-chart-3/15", color: "text-chart-3" }}
      />
      <KpiCard
        label={t("home.aiSpend")}
        value={aiCost == null ? "—" : formatCurrency(Number(aiCost), false, "USD")}
        sub={t("home.thisMonth")}
        to="/usage"
        accent={{ icon: <TrendingUp />, bg: "bg-warning/15", color: "text-warning" }}
      />
    </div>
  );
}
