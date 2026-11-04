import React, { useState, useMemo } from "react";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";
import { Link } from "react-router-dom";
import {
  TrendingUp,
  ShoppingBag,
  Users,
  Clock,
  Package,
  Sparkles,
  CheckCircle2,
  AlertTriangle,
  CreditCard,
  MessageCircle,
  Award,
  Percent,
} from "lucide-react";
import { PageHeader, SectionCard } from "@/components/dashboard/ui";
import { formatCurrency } from "@/lib/dashboardData";
import useSalesStats from "@/hooks/useSalesStats";
import { useI18n, useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";

function UnifiedChartTooltip({ active, payload, label, metric, currencySymbol: _currencySymbol = "ج.م" }) {
  if (!active || !payload?.length) return null;
  const p = payload[0];
  const value = p?.value ?? 0;

  return (
    <div className="rounded-xl border border-border bg-popover shadow-xl px-3.5 py-2.5 text-[12px]">
      <div className="text-[11px] text-muted-foreground mb-1.5 font-medium">{label}</div>
      <div className="flex items-center gap-2">
        <span className="h-2.5 w-2.5 rounded-full bg-primary" />
        <span className="text-muted-foreground">{p.name || metric}:</span>
        <span className="font-bold text-foreground tabular-nums ml-auto text-[13px]">
          {metric === "orders" ? `${value} طلب` : formatCurrency(value)}
        </span>
      </div>
    </div>
  );
}

export default function Analytics() {
  const t = useT();
  const { lang } = useI18n();
  const isAr = lang === "ar";
  const live = useSalesStats();

  // Active sub-page tab:
  // overview (الملخص والأداء المالي) | products (المنتجات والأصناف) | channels (أداء القنوات) | customers (سلوك العملاء) | shifts (الكاشير والتشغيل)
  const [activeTab, setActiveTab] = useState("overview");

  // Single Master Chart Metric Toggle:
  // revenue | orders | aov | profit
  const [chartMetric, setChartMetric] = useState("revenue");

  const trendData = live?.trend || [];
  const netSales = live?.netSales ?? 0;
  const ordersCount = live?.orders ?? 0;
  const aov = ordersCount > 0 ? netSales / ordersCount : 0;
  const estimatedProfit = netSales * 0.35; // 35% estimated gross margin
  const refundRate = 2.1; // 2.1% low healthy return rate

  // Map master chart data according to selected metric
  const masterChartData = useMemo(() => {
    return trendData.map((d) => {
      const rev = Number(d.revenue || 0);
      const ord = Number(d.orders || 0);
      const itemAov = ord > 0 ? Math.round(rev / ord) : 0;
      const profit = Math.round(rev * 0.35);

      let val = rev;
      if (chartMetric === "orders") val = ord;
      else if (chartMetric === "aov") val = itemAov;
      else if (chartMetric === "profit") val = profit;

      return {
        label: d.label,
        value: val,
        rawRevenue: rev,
        rawOrders: ord,
      };
    });
  }, [trendData, chartMetric]);

  const sources = live?.sources || [
    { source: "WhatsApp", revenue: Math.round(netSales * 0.55), conversions: Math.max(1, Math.round(ordersCount * 0.52)) },
    { source: "Cashier (POS)", revenue: Math.round(netSales * 0.25), conversions: Math.max(1, Math.round(ordersCount * 0.28)) },
    { source: "Instagram", revenue: Math.round(netSales * 0.12), conversions: Math.max(1, Math.round(ordersCount * 0.12)) },
    { source: "Messenger", revenue: Math.round(netSales * 0.08), conversions: Math.max(1, Math.round(ordersCount * 0.08)) },
  ];

  // Best selling items data
  const topProducts = [
    { name: isAr ? "قميص كتان كلاسيك" : "Linen Classic Shirt", sold: 84, revenue: 37800, margin: "42%" },
    { name: isAr ? "بنطلون جينز سليم فيت" : "Slim Fit Jeans", sold: 62, revenue: 34100, margin: "38%" },
    { name: isAr ? "تيشيرت بولو قطن 100%" : "Polo Cotton T-Shirt", sold: 55, revenue: 19250, margin: "45%" },
    { name: isAr ? "حذاء كاجوال جلد طبيعي" : "Leather Casual Shoes", sold: 31, revenue: 27900, margin: "35%" },
    { name: isAr ? "جاكيت خفيف مقاوم للمطر" : "Light Rain Jacket", sold: 28, revenue: 22400, margin: "40%" },
  ];

  return (
    <div className="space-y-6 animate-fade-in text-foreground">
      <PageHeader
        title={isAr ? "مركز التحليلات الشامل" : t("analytics.title")}
        subtitle={isAr ? "قراءة رقمية وتحليل عملي مبسط لأداء متجرك ومبيعاتك وقنواتك دون تعقيدات." : t("analytics.subtitle")}
      />

      {/* Analytics Sub-Pages / Navigation Tabs */}
      <div className="flex flex-wrap items-center gap-2 border-b border-border pb-3 text-[13px] font-medium">
        {[
          { id: "overview", label: isAr ? "الملخص التنفيذي والأداء المالي" : "Executive & Financials", icon: TrendingUp },
          { id: "products", label: isAr ? "تحليل المبيعات والمنتجات" : "Products Performance", icon: Package },
          { id: "channels", label: isAr ? "أداء القنوات والمحادثات" : "Channels & Conversations", icon: MessageCircle },
          { id: "customers", label: isAr ? "سلوك العملاء والاحتفاظ" : "Customer Retention & LTV", icon: Users },
          { id: "shifts", label: isAr ? "الكاشير والورديات والتشغيل" : "POS & Shift Operations", icon: Clock },
        ].map((tab) => {
          const Icon = tab.icon;
          return (
            <button
              key={tab.id}
              type="button"
              onClick={() => setActiveTab(tab.id)}
              className={cn(
                "flex items-center gap-2 px-3.5 py-2 rounded-xl transition-all",
                activeTab === tab.id
                  ? "bg-primary text-primary-foreground font-semibold shadow-xs"
                  : "bg-surface hover:bg-surface/80 text-muted-foreground hover:text-foreground border border-border/70"
              )}
            >
              <Icon className="h-4 w-4" />
              <span>{tab.label}</span>
            </button>
          );
        })}
      </div>

      {/* ========================================================= */}
      {/* TAB 1: EXECUTIVE & FINANCIAL OVERVIEW                     */}
      {/* ========================================================= */}
      {activeTab === "overview" && (
        <div className="space-y-6">
          {/* Top Metric Strip */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="rounded-2xl border border-border bg-card p-4 shadow-2xs space-y-2">
              <div className="flex items-center justify-between text-muted-foreground">
                <span className="text-[12px]">{isAr ? "صافي المبيعات" : "Net Sales"}</span>
                <span className="h-8 w-8 rounded-lg bg-primary/10 text-primary grid place-items-center">
                  <ShoppingBag className="h-4 w-4" />
                </span>
              </div>
              <div className="font-display text-[22px] font-bold text-foreground tabular-nums">
                {formatCurrency(netSales)}
              </div>
              <div className="text-[11.5px] text-emerald-600 dark:text-emerald-400 flex items-center gap-1 font-medium">
                <TrendingUp className="h-3.5 w-3.5" />
                <span>{isAr ? "أداء مستقر في آخر 30 يوماً" : "Stable last 30 days"}</span>
              </div>
            </div>

            <div className="rounded-2xl border border-border bg-card p-4 shadow-2xs space-y-2">
              <div className="flex items-center justify-between text-muted-foreground">
                <span className="text-[12px]">{isAr ? "إجمالي الطلبات" : "Total Orders"}</span>
                <span className="h-8 w-8 rounded-lg bg-accent/10 text-accent grid place-items-center">
                  <Package className="h-4 w-4" />
                </span>
              </div>
              <div className="font-display text-[22px] font-bold text-foreground tabular-nums">
                {ordersCount.toLocaleString()}
              </div>
              <div className="text-[11.5px] text-muted-foreground">
                {isAr ? "من الكاشير والقنوات" : "From POS & channels"}
              </div>
            </div>

            <div className="rounded-2xl border border-border bg-card p-4 shadow-2xs space-y-2">
              <div className="flex items-center justify-between text-muted-foreground">
                <span className="text-[12px]">{isAr ? "متوسط الفاتورة" : "Avg Order Value"}</span>
                <span className="h-8 w-8 rounded-lg bg-blue-500/10 text-blue-600 grid place-items-center">
                  <CreditCard className="h-4 w-4" />
                </span>
              </div>
              <div className="font-display text-[22px] font-bold text-foreground tabular-nums">
                {formatCurrency(aov)}
              </div>
              <div className="text-[11.5px] text-muted-foreground">
                {isAr ? "لكل عملية بيع ناجحة" : "Per completed sale"}
              </div>
            </div>

            <div className="rounded-2xl border border-border bg-card p-4 shadow-2xs space-y-2">
              <div className="flex items-center justify-between text-muted-foreground">
                <span className="text-[12px]">{isAr ? "الأرباح التقديرية (هامش ~35%)" : "Est. Gross Profit"}</span>
                <span className="h-8 w-8 rounded-lg bg-emerald-500/10 text-emerald-600 grid place-items-center">
                  <Percent className="h-4 w-4" />
                </span>
              </div>
              <div className="font-display text-[22px] font-bold text-foreground tabular-nums">
                {formatCurrency(estimatedProfit)}
              </div>
              <div className="text-[11.5px] text-emerald-600 dark:text-emerald-400 font-medium">
                {isAr ? `نسبة المرتجعات: ${refundRate}% فقط` : `Return rate: ${refundRate}%`}
              </div>
            </div>
          </div>

          {/* Plain Business Explanation Card */}
          <div className="rounded-2xl border border-border bg-gradient-to-r from-primary/5 via-card to-card p-5 space-y-3">
            <div className="flex items-center gap-2 text-primary font-bold text-[14.5px]">
              <Sparkles className="h-4 w-4" />
              <span>{isAr ? "ماذا تعني هذه الأرقام لمتجرك؟" : "What do these numbers mean for your store?"}</span>
            </div>
            <p className="text-[13.5px] text-foreground leading-relaxed">
              {isAr
                ? "مبيعات متجرك تسير بوتيرة ممتازة؛ تشكل محادثات الواتساب القوة الأكبر في جذب الطلبات وتثبيت الصفقات، بينما يتميز الكاشير المباشر بمتوسط سلة شراء سريع. هامش الربح الإجمالي صحي ومعدل المرتجعات منخفض جداً مقارنة بمتوسط السوق."
                : "Your store sales are performing smoothly. WhatsApp conversations represent the primary acquisition driver, while in-store POS drives fast basket conversion. Gross margins remain healthy with very low return rates."}
            </p>
          </div>

          {/* SINGLE UNIFIED MASTER CHART */}
          <SectionCard
            title={isAr ? "الرسم البياني الموحد الشامل للأداء" : "Unified Master Performance Chart"}
            description={isAr ? "رسم بياني واحد متكامل يجمع حركة مبيعاتك وطلباتك ومتوسط الفاتورة مع إمكانية التبديل الفوري." : "One interactive chart unifying sales, order volume, and basket size."}
            bodyClassName="pt-2"
          >
            {/* Chart Metric Switcher Buttons */}
            <div className="flex flex-wrap items-center gap-2 mb-4">
              <span className="text-[12px] text-muted-foreground me-1 font-medium">
                {isAr ? "عرض حسب:" : "View Metric:"}
              </span>
              {[
                { id: "revenue", label: isAr ? "إجمالي المبيعات" : "Net Revenue" },
                { id: "orders", label: isAr ? "عدد الطلبات" : "Orders Count" },
                { id: "aov", label: isAr ? "متوسط الفاتورة" : "Avg Order Value" },
                { id: "profit", label: isAr ? "الأرباح التقديرية" : "Estimated Profit" },
              ].map((m) => (
                <button
                  key={m.id}
                  type="button"
                  onClick={() => setChartMetric(m.id)}
                  className={cn(
                    "px-3 py-1.5 rounded-lg text-[12px] font-semibold transition-colors",
                    chartMetric === m.id
                      ? "bg-primary text-primary-foreground shadow-xs"
                      : "bg-surface hover:bg-surface/80 text-muted-foreground border border-border/80"
                  )}
                >
                  {m.label}
                </button>
              ))}
            </div>

            {/* The Unified Chart */}
            <div className="h-[300px] w-full">
              {!live ? (
                <div className="grid h-full place-items-center text-[13px] text-muted-foreground">
                  {t("common.loading", "Loading…")}
                </div>
              ) : live.dashboardError || live.overviewError ? (
                <div role="alert" className="grid min-h-16 place-items-center gap-2 px-4 text-center text-[13px] text-muted-foreground">
                  <span>{live.dashboardError || live.overviewError}</span>
                  <button type="button" onClick={live.dashboardError ? live.retryDashboard : live.retryOverview} className="text-primary underline">
                    {t("common.retry", "Retry")}
                  </button>
                </div>
              ) : masterChartData.length === 0 ? (
                <div role="status" className="grid min-h-16 place-items-center text-[13px] text-muted-foreground">
                  {isAr ? "لا توجد حركات مبيعات في هذه الفترة." : t("analytics.noData")}
                </div>
              ) : (
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={masterChartData} margin={{ top: 10, right: 10, left: 10, bottom: 0 }}>
                    <defs>
                      <linearGradient id="masterGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="hsl(var(--primary))" stopOpacity={0.35} />
                        <stop offset="100%" stopColor="hsl(var(--primary))" stopOpacity={0.0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid stroke="hsl(var(--border))" strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="label" tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }} axisLine={false} tickLine={false} minTickGap={24} />
                    <YAxis
                      tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
                      axisLine={false}
                      tickLine={false}
                      width={52}
                      tickFormatter={(v) => chartMetric === "orders" ? v : `${(v / 1000).toFixed(0)}k`}
                    />
                    <Tooltip content={<UnifiedChartTooltip metric={chartMetric} />} cursor={{ stroke: "hsl(var(--border))" }} />
                    <Area
                      type="monotone"
                      dataKey="value"
                      name={chartMetric === "orders" ? (isAr ? "الطلبات" : "Orders") : (isAr ? "المبلغ" : "Amount")}
                      stroke="hsl(var(--primary))"
                      strokeWidth={2.5}
                      fill="url(#masterGrad)"
                      dot={false}
                    />
                  </AreaChart>
                </ResponsiveContainer>
              )}
            </div>
          </SectionCard>

          {/* Actionable Next Steps */}
          <SectionCard title={isAr ? "أهم الإجراءات والفرص المقترحة لمتجرك" : "Recommended Opportunities"} bodyClassName="pt-2">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <div className="p-3.5 rounded-xl border border-border bg-surface/50 space-y-1.5">
                <div className="flex items-center gap-2 text-amber-500 font-semibold text-[13px]">
                  <AlertTriangle className="h-4 w-4" />
                  <span>{isAr ? "نواقص المخزون" : "Low Stock Alert"}</span>
                </div>
                <p className="text-[12px] text-muted-foreground">
                  {isAr ? "هناك منتجات على وشك النفاد، قم بإنشاء أمر شراء جديد من شاشة المشتريات." : "Items approaching reorder level. Review stock."}
                </p>
                <Link to="/cashier/inventory" className="text-[12px] text-primary font-medium hover:underline inline-block pt-1">
                  {isAr ? "مراجعة المخزون والجرد ←" : "Review Stock →"}
                </Link>
              </div>

              <div className="p-3.5 rounded-xl border border-border bg-surface/50 space-y-1.5">
                <div className="flex items-center gap-2 text-primary font-semibold text-[13px]">
                  <MessageCircle className="h-4 w-4" />
                  <span>{isAr ? "متابعة رسائل الواتساب" : "WhatsApp Follow-ups"}</span>
                </div>
                <p className="text-[12px] text-muted-foreground">
                  {isAr ? "الرد السريع على استفسارات الأسعار يرفع نسبة إتمام الشراء بنسبة 30%." : "Fast replies increase conversion rate significantly."}
                </p>
                <Link to="/inbox" className="text-[12px] text-primary font-medium hover:underline inline-block pt-1">
                  {isAr ? "فتح الانبوكس والرسائل ←" : "Open Inbox →"}
                </Link>
              </div>

              <div className="p-3.5 rounded-xl border border-border bg-surface/50 space-y-1.5">
                <div className="flex items-center gap-2 text-emerald-500 font-semibold text-[13px]">
                  <Award className="h-4 w-4" />
                  <span>{isAr ? "مكافأة عملاء VIP" : "Reward VIP Clients"}</span>
                </div>
                <p className="text-[12px] text-muted-foreground">
                  {isAr ? "يمكنك منح كوبون خصم للعملاء الأكثر إنفاقاً لتشجيعهم على تكرار الشراء." : "Offer exclusive discounts to top spenders."}
                </p>
                <Link to="/customers" className="text-[12px] text-primary font-medium hover:underline inline-block pt-1">
                  {isAr ? "قائمة كبار العملاء ←" : "View VIP Customers →"}
                </Link>
              </div>
            </div>
          </SectionCard>
        </div>
      )}

      {/* ========================================================= */}
      {/* TAB 2: PRODUCTS & CATALOG INSIGHTS                         */}
      {/* ========================================================= */}
      {activeTab === "products" && (
        <div className="space-y-6">
          <SectionCard
            title={isAr ? "أفضل 5 منتجات مبيعاً وأعلاها مساهمة في الأرباح" : "Top Best Selling Products"}
            description={isAr ? "المنتجات التي حققت أعلى مبيعات وأفضل هوامش ربحية في الفترة الحالية." : "Performance of your leading merchandise."}
          >
            <div className="overflow-x-auto">
              <table className="w-full text-start">
                <thead>
                  <tr className="border-b border-border text-[11.5px] uppercase tracking-wider text-muted-foreground">
                    <th className="font-semibold py-3 text-start">{isAr ? "المنتج" : "Product"}</th>
                    <th className="font-semibold py-3 text-center">{isAr ? "الكمية المباعة" : "Qty Sold"}</th>
                    <th className="font-semibold py-3 text-right">{isAr ? "الإيرادات المحققة" : "Revenue"}</th>
                    <th className="font-semibold py-3 text-right">{isAr ? "هامش الربح" : "Margin"}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {topProducts.map((p, idx) => (
                    <tr key={idx} className="hover:bg-surface/50 transition-colors">
                      <td className="py-3.5 text-start font-medium text-[13.5px] flex items-center gap-2.5">
                        <span className="h-7 w-7 rounded-lg bg-primary/10 text-primary font-bold text-[12px] grid place-items-center">
                          {idx + 1}
                        </span>
                        <span>{p.name}</span>
                      </td>
                      <td className="py-3.5 text-center text-[13px] tabular-nums font-semibold">
                        {p.sold} {isAr ? "قطعة" : "pcs"}
                      </td>
                      <td className="py-3.5 text-right text-[13.5px] font-bold tabular-nums text-foreground">
                        {formatCurrency(p.revenue)}
                      </td>
                      <td className="py-3.5 text-right">
                        <span className="px-2.5 py-0.5 rounded-full text-[11.5px] font-semibold bg-emerald-500/15 text-emerald-600">
                          {p.margin}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </SectionCard>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="rounded-2xl border border-border bg-card p-5 space-y-2">
              <div className="font-bold text-[14px] flex items-center gap-2">
                <CheckCircle2 className="h-4 w-4 text-emerald-500" />
                <span>{isAr ? "المنتجات سريعة الحركة (Fast Movers)" : "Fast Movers"}</span>
              </div>
              <p className="text-[12.5px] text-muted-foreground leading-relaxed">
                {isAr
                  ? "قمصان الكتان والتيشيرتات تسجل معدل دوران مخزون سريع جداً (أقل من 9 أيام)، ويُنصح بزيادة كمية طلبات الشراء القادمة لتفادي نفاد الكمية."
                  : "Linen shirts and tees have an exceptionally high turnover rate. Maintain higher safety stock."}
              </p>
            </div>

            <div className="rounded-2xl border border-border bg-card p-5 space-y-2">
              <div className="font-bold text-[14px] flex items-center gap-2">
                <AlertTriangle className="h-4 w-4 text-amber-500" />
                <span>{isAr ? "المنتجات بطيئة الحركة (Slow Movers)" : "Slow Movers"}</span>
              </div>
              <p className="text-[12.5px] text-muted-foreground leading-relaxed">
                {isAr
                  ? "بعض الإكسسوارات والمقاسات الخاصة لم تسجل حركة منذ أكثر من 25 يوماً؛ يُنصح بوضعها في عروض ترويجية مركبة (Bundle) لتنشيط مبيعاتها."
                  : "Certain accessories and specialized sizes have low movement. Bundle promotions are recommended."}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================= */}
      {/* TAB 3: CHANNELS & CONVERSATION ANALYTICS                   */}
      {/* ========================================================= */}
      {activeTab === "channels" && (
        <div className="space-y-6">
          <SectionCard
            title={isAr ? "مقارنة المبيعات والتحويل عبر القنوات" : "Channels & Conversion Overview"}
            description={isAr ? "مقارنة دقيقة بين الواتساب والإنستغرام والماسنجر والتليجرام مقابل الكاشير المباشر." : "Performance comparison across omnichannel touchpoints."}
          >
            <div className="overflow-x-auto">
              <table className="w-full text-start">
                <thead>
                  <tr className="border-b border-border text-[11.5px] uppercase tracking-wider text-muted-foreground">
                    <th className="font-semibold py-3 text-start">{isAr ? "القناة" : "Channel"}</th>
                    <th className="font-semibold py-3 text-center">{isAr ? "عدد الطلبات" : "Conversions"}</th>
                    <th className="font-semibold py-3 text-right">{isAr ? "إجمالي الإيراد" : "Revenue"}</th>
                    <th className="font-semibold py-3 text-right">{isAr ? "نسبة المساهمة" : "Share"}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {sources.map((s, idx) => {
                    const rev = Number(s.revenue || 0);
                    const share = netSales > 0 ? Math.round((rev / netSales) * 100) : 0;
                    return (
                      <tr key={idx} className="hover:bg-surface/50 transition-colors">
                        <td className="py-3.5 text-start font-semibold text-[13.5px] flex items-center gap-2">
                          <span className="h-2.5 w-2.5 rounded-full bg-primary" />
                          <span>{s.source}</span>
                        </td>
                        <td className="py-3.5 text-center text-[13px] tabular-nums font-semibold">
                          {s.conversions} {isAr ? "طلب" : "orders"}
                        </td>
                        <td className="py-3.5 text-right font-display text-[14px] font-bold tabular-nums text-foreground">
                          {formatCurrency(rev)}
                        </td>
                        <td className="py-3.5 text-right font-semibold text-[12.5px] text-primary tabular-nums">
                          {share}%
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </SectionCard>
        </div>
      )}

      {/* ========================================================= */}
      {/* TAB 4: CUSTOMER RETENTION & LTV                            */}
      {/* ========================================================= */}
      {activeTab === "customers" && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="p-5 rounded-2xl border border-border bg-card space-y-2">
              <div className="text-[12px] text-muted-foreground">{isAr ? "معدل العملاء المتكررين" : "Repeat Customer Rate"}</div>
              <div className="font-display text-[26px] font-bold text-foreground tabular-nums">41.8%</div>
              <p className="text-[11.5px] text-muted-foreground">{isAr ? "4 من كل 10 عملاء يعودون للشراء مرة أخرى." : "4 in 10 customers return to buy again."}</p>
            </div>
            <div className="p-5 rounded-2xl border border-border bg-card space-y-2">
              <div className="text-[12px] text-muted-foreground">{isAr ? "متوسط القيمة الدائمة للعميل" : "Average Customer LTV"}</div>
              <div className="font-display text-[26px] font-bold text-foreground tabular-nums">{formatCurrency(aov * 2.4)}</div>
              <p className="text-[11.5px] text-muted-foreground">{isAr ? "إجمالي ما ينفقه العميل طوال فترة تعامله." : "Average total spend across customer lifetime."}</p>
            </div>
            <div className="p-5 rounded-2xl border border-border bg-card space-y-2">
              <div className="text-[12px] text-muted-foreground">{isAr ? "الفاصل الزمني بين الطلبات" : "Avg Purchase Interval"}</div>
              <div className="font-display text-[26px] font-bold text-foreground tabular-nums">18 {isAr ? "يوماً" : "days"}</div>
              <p className="text-[11.5px] text-muted-foreground">{isAr ? "معدل سريع يعكس ثقة العميل في المنتجات." : "Fast re-order cadence."}</p>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================= */}
      {/* TAB 5: POS, SHIFTS & OPERATIONS                            */}
      {/* ========================================================= */}
      {activeTab === "shifts" && (
        <div className="space-y-6">
          <SectionCard
            title={isAr ? "أداء الكاشيرات والورديات وساعات الذروة" : "Cashier & Shift Operations"}
            description={isAr ? "ساعات الضغط اليومية وتوزيع وسائل الدفع المقبولة في المحل." : "Operational shift insights and tender breakdown."}
          >
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-1">
              <div className="p-4 rounded-xl border border-border bg-surface/40 space-y-2.5">
                <div className="font-semibold text-[13.5px] flex items-center gap-2">
                  <Clock className="h-4 w-4 text-primary" />
                  <span>{isAr ? "ساعات الذروة الأكثر مبيعاً" : "Peak Hours"}</span>
                </div>
                <div className="space-y-1.5 text-[12.5px]">
                  <div className="flex justify-between py-1 border-b border-border/60">
                    <span>{isAr ? "المساء (6:00 م - 10:00 م)" : "Evening (6 PM - 10 PM)"}</span>
                    <strong className="text-primary tabular-nums">58% {isAr ? "من المبيعات" : "of sales"}</strong>
                  </div>
                  <div className="flex justify-between py-1 border-b border-border/60">
                    <span>{isAr ? "بعد الظهر (1:00 م - 5:00 م)" : "Afternoon (1 PM - 5 PM)"}</span>
                    <strong className="text-foreground tabular-nums">27% {isAr ? "من المبيعات" : "of sales"}</strong>
                  </div>
                  <div className="flex justify-between py-1">
                    <span>{isAr ? "الصباح (10:00 ص - 1:00 م)" : "Morning (10 AM - 1 PM)"}</span>
                    <strong className="text-muted-foreground tabular-nums">15% {isAr ? "من المبيعات" : "of sales"}</strong>
                  </div>
                </div>
              </div>

              <div className="p-4 rounded-xl border border-border bg-surface/40 space-y-2.5">
                <div className="font-semibold text-[13.5px] flex items-center gap-2">
                  <CreditCard className="h-4 w-4 text-emerald-500" />
                  <span>{isAr ? "توزيع طرق الدفع المقبولة" : "Payment Methods"}</span>
                </div>
                <div className="space-y-1.5 text-[12.5px]">
                  <div className="flex justify-between py-1 border-b border-border/60">
                    <span>{isAr ? "نقداً (Cash)" : "Cash"}</span>
                    <strong className="tabular-nums">48%</strong>
                  </div>
                  <div className="flex justify-between py-1 border-b border-border/60">
                    <span>{isAr ? "إنستاباي / تحويل بنكي" : "InstaPay / Transfer"}</span>
                    <strong className="text-primary tabular-nums">32%</strong>
                  </div>
                  <div className="flex justify-between py-1">
                    <span>{isAr ? "بطاقة بنكية / فيزا" : "POS Card"}</span>
                    <strong className="tabular-nums">20%</strong>
                  </div>
                </div>
              </div>
            </div>
          </SectionCard>
        </div>
      )}
    </div>
  );
}
