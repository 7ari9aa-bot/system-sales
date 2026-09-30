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

  const netSales = live?.netSales ?? 0;
  const orders = live?.orders ?? 0;
  const customers = live?.customers ?? 0;
  const aiOrders = live?.aiOrders ?? 0;
  const aiCost = usage?.totals?.cost ?? null;

  if (!live) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-3.5" data-testid="dash-pulse">
        {[0, 1, 2, 3, 4].map((i) => <KpiSkeleton key={i} />)}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-3.5" data-testid="dash-pulse">
      <KpiCard
        label={t("home.netSales")}
        value={formatCurrency(netSales)}
        sub={t("home.xOrders", { n: orders })}
        to="/orders"
        accent={{ icon: <DollarSign />, bg: "bg-primary/10", color: "text-primary" }}
      />
      <KpiCard
        label={t("home.orders")}
        value={orders.toLocaleString()}
        to="/orders"
        accent={{ icon: <ShoppingBag />, bg: "bg-accent/10", color: "text-accent" }}
      />
      <KpiCard
        label={t("home.customers")}
        value={customers.toLocaleString()}
        to="/customers"
        accent={{ icon: <Users />, bg: "bg-chart-4/10", color: "text-chart-4" }}
      />
      <KpiCard
        label={t("home.aiOrders")}
        value={aiOrders.toLocaleString()}
        sub={t("home.aiOrdersHint")}
        to="/ai"
        accent={{ icon: <Sparkles />, bg: "bg-chart-3/15", color: "text-chart-3" }}
      />
      <KpiCard
        label={t("home.aiSpend")}
        value={aiCost == null ? "—" : formatCurrency(Number(aiCost))}
        sub={t("home.thisMonth")}
        to="/usage"
        accent={{ icon: <TrendingUp />, bg: "bg-warning/15", color: "text-warning" }}
      />
    </div>
  );
}
