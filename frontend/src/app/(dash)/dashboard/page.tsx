"use client";

import Link from "next/link";
import { ArrowUpRight, CircleCheck, TriangleAlert } from "lucide-react";
import { useDashboard, useTenantCurrency, type DailyOrderRow } from "@/lib/queries";
import { t } from "@/lib/t";
import { formatMoney, formatNumber } from "@/lib/utils";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState, PageHeader } from "@/components/ui/states";

function Stat({
  label,
  value,
  hint,
  testid,
}: {
  label: string;
  value: string | number;
  hint?: string;
  testid?: string;
}) {
  return (
    <Card data-testid={testid}>
      <CardContent className="p-5">
        <div className="text-[26px] font-bold leading-tight" dir="ltr">
          {typeof value === "number" ? value.toLocaleString("en-US") : value}
        </div>
        <div className="mt-0.5 text-[13px] text-muted-foreground">{label}</div>
        {hint && <div className="mt-1 text-xs text-muted-foreground">{hint}</div>}
      </CardContent>
    </Card>
  );
}

/** Daily buckets are the MERCHANT's day (gap M10) and the bar is NET money —
 *  gross minus refunds — because that is the figure a merchant plans with.
 *  The tooltip keeps gross and refunded on screen so a short bar is never read
 *  as a bad sales day when it was a refund day. A day whose refunds beat its
 *  collections shows a zero bar plus its `refund_excess` in the tooltip: net is
 *  floored at zero, and the unsent-able remainder would otherwise vanish. */
function BarChart({ data, currency }: { data: DailyOrderRow[]; currency: string | null }) {
  const max = Math.max(1, ...data.map((d) => d.net_revenue));
  if (data.length === 0) return <EmptyState title="لا توجد بيانات بعد" className="py-8" />;
  return (
    <div className="flex h-40 items-end gap-1 pt-2" data-testid="daily-net-chart">
      {data.map((d) => (
        <div
          key={d.day}
          className="flex-1 text-center"
          title={
            `${d.day} — ${t.grossShort}: ${formatMoney(d.gross_revenue, currency)} · ` +
            `${t.refundedShort}: ${formatMoney(d.refunded_amount, currency)} · ` +
            `${t.netShort}: ${formatMoney(d.net_revenue, currency)}` +
            (d.refund_excess > 0 ? ` · ${t.refundExcessNote(formatMoney(d.refund_excess, currency))}` : "")
          }
        >
          <div
            data-testid={`daily-bar-${d.day}`}
            className="mx-auto w-full max-w-6 rounded-md bg-primary/85 transition-all duration-300 ease-smooth"
            style={{ height: `${Math.max(4, (d.net_revenue / max) * 110)}px` }}
          />
          <div className="mt-1 text-[10px] text-muted-foreground">{new Date(d.day).getDate()}</div>
        </div>
      ))}
    </div>
  );
}

export default function DashboardPage() {
  const { data, error, refetch, isLoading } = useDashboard();
  // §47: money has a currency. The read model ships it on the summary itself
  // (`orders.currency`), which is authoritative for these figures; the tenant
  // read is the fallback for rows the payload does not label (an attributed
  // credit row carries no currency of its own).
  const currencyQuery = useTenantCurrency();
  const tenantCurrency = currencyQuery.data?.currency ?? null;

  if (error) return <ErrorState message={error.message} onRetry={() => refetch()} />;

  if (isLoading || !data) return <PageSkeleton />;

  const money = data.orders;
  const currency = money.currency || tenantCurrency;
  const lowStock = data.low_stock_count;
  const soldOut = data.out_of_stock_count;
  const sources = [...data.revenue_by_source].sort((a, b) => b.revenue - a.revenue).slice(0, 5);
  const maxSource = Math.max(1, ...sources.map((s) => s.revenue));

  return (
    <div>
      <PageHeader title={t.dashboard} description="نظرة سريعة على أداء متجرك" />

      <Card className="mt-4" data-testid="needs-attention">
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <CardTitle>{t.needsAttention}</CardTitle>
          <span className="text-xs text-muted-foreground">{t.today}</span>
        </CardHeader>
        <CardContent>
          {data.conversations.unread === 0 && lowStock === 0 && soldOut === 0 ? (
            <div className="flex items-center gap-2 text-sm text-success">
              <CircleCheck aria-hidden="true" className="size-4" />
              <span>{t.allClear}</span>
            </div>
          ) : (
            <div className="grid gap-2 sm:grid-cols-2">
              {data.conversations.unread > 0 && (
                <Link
                  href="/inbox"
                  data-testid="attention-unread"
                  className="group flex items-center justify-between rounded-lg border border-border p-3 transition-colors hover:border-primary/40 hover:bg-muted"
                >
                  <span className="flex items-center gap-2 text-sm font-semibold">
                    <span className="size-2 rounded-full bg-primary" aria-hidden="true" />
                    {data.conversations.unread} {t.unread}
                  </span>
                  <ArrowUpRight aria-hidden="true" className="size-4 text-muted-foreground transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5" />
                </Link>
              )}
              {lowStock > 0 && (
                <Link
                  href="/inventory"
                  data-testid="attention-low-stock"
                  className="group flex items-center justify-between rounded-lg border border-warning/40 p-3 transition-colors hover:bg-warning/10"
                >
                  <span className="flex items-center gap-2 text-sm font-semibold">
                    <TriangleAlert aria-hidden="true" className="size-4 text-warning" />
                    {t.nearlyOut(lowStock)}
                  </span>
                  <ArrowUpRight aria-hidden="true" className="size-4 text-muted-foreground transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5" />
                </Link>
              )}
              {/* M7: a sold-out shelf is its own band — it was counted as "low
                  stock" before, which made the alert mostly noise. */}
              {soldOut > 0 && (
                <Link
                  href="/inventory"
                  data-testid="attention-sold-out"
                  className="group flex items-center justify-between rounded-lg border border-danger/40 p-3 transition-colors hover:bg-danger/10"
                >
                  <span className="flex items-center gap-2 text-sm font-semibold">
                    <TriangleAlert aria-hidden="true" className="size-4 text-danger" />
                    {t.soldOutCount(soldOut)}
                  </span>
                  <ArrowUpRight aria-hidden="true" className="size-4 text-muted-foreground transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5" />
                </Link>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {/* ADR-053: gross and net are two cards, never one card called
          "الإيرادات". Net is what the merchant keeps, and the refunded figure
          sits next to it so the gap between the two is visible. */}
      <div className="mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        <Stat
          label={t.grossRevenue30}
          value={formatMoney(money.gross_revenue, currency)}
          testid="stat-gross-revenue"
        />
        <Stat
          label={t.netRevenue30}
          value={formatMoney(money.net_revenue, currency)}
          hint={`${t.refundedShort}: ${formatMoney(money.refunded_amount, currency)}`}
          testid="stat-net-revenue"
        />
        <Stat label={t.orders30} value={money.orders_count} testid="stat-orders" />
        <Stat
          label={t.netAov}
          value={formatMoney(money.net_aov, currency)}
          hint={`${t.grossAov}: ${formatMoney(money.gross_aov, currency)}`}
          testid="stat-aov"
        />
        <Stat
          label={t.openConversations}
          value={data.conversations.open}
          hint={`${data.conversations.unread} ${t.unread}`}
          testid="stat-conversations"
        />
        <Stat label={t.customers} value={data.customers} testid="stat-customers" />
        <Stat
          label={t.activeProducts}
          value={data.products_active}
          hint={
            [
              soldOut > 0 ? t.soldOutCount(soldOut) : null,
              lowStock > 0 ? t.nearlyOut(lowStock) : null,
            ]
              .filter(Boolean)
              .join(" · ") || undefined
          }
          testid="stat-products"
        />
      </div>

      {/* Net is floored at zero upstream: a window that refunded more than it
          collected would otherwise read as a clean zero and the difference
          would vanish from the screen. `refund_excess` is that remainder. */}
      {money.refund_excess > 0 && (
        <Card className="mt-4 border-s-4 border-s-warning" data-testid="refund-excess-note">
          <CardContent className="flex items-center gap-3 p-4">
            <TriangleAlert aria-hidden="true" className="size-5 shrink-0 text-warning" />
            <p className="flex-1 text-sm font-semibold">
              {t.refundExcessNote(formatMoney(money.refund_excess, currency))}
            </p>
          </CardContent>
        </Card>
      )}

      {(lowStock > 0 || soldOut > 0) && (
        <Card className="mt-4 border-s-4 border-s-warning" data-testid="low-stock-alert">
          <CardContent className="flex items-start gap-3 p-4">
            <TriangleAlert aria-hidden="true" className="size-5 shrink-0 text-warning" />
            <div className="flex-1 space-y-1">
              {soldOut > 0 && (
                <p className="text-sm font-semibold" data-testid="low-stock-sold-out">
                  {t.outOfStockAlert(soldOut)}
                </p>
              )}
              {lowStock > 0 && (
                <p className="text-sm font-semibold" data-testid="low-stock-running-low">
                  {t.lowStockAlert(lowStock)}
                </p>
              )}
              <p className="text-xs text-muted-foreground">
                {t.lowStockThresholdNote(data.low_stock_threshold)}
              </p>
            </div>
            <Link
              href="/inventory"
              className="text-[13px] font-bold text-primary underline-offset-4 hover:underline"
            >
              {t.inventory}
            </Link>
          </CardContent>
        </Card>
      )}

      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>{t.dailyNetRevenue}</CardTitle>
          </CardHeader>
          <CardContent>
            <BarChart data={data.daily_orders} currency={currency} />
          </CardContent>
        </Card>

        {/* §167: this card is last-touch ATTRIBUTED credit, not collected money
            — the title says so and the footnote keeps saying it. */}
        <Card data-testid="attributed-by-source">
          <CardHeader>
            <CardTitle>{t.revenueBySource}</CardTitle>
          </CardHeader>
          <CardContent>
            {sources.length === 0 ? (
              <EmptyState title={t.noSourceData} className="py-8" />
            ) : (
              <div className="space-y-3">
                <p className="text-[11px] text-muted-foreground">{t.attributedCreditHint}</p>
                {sources.map((s) => (
                  <div key={s.source}>
                    <div className="flex items-center justify-between text-[13px]">
                      <span className="flex items-center gap-2 font-semibold">
                        <Badge variant="outline">{s.source}</Badge>
                      </span>
                      <span dir="ltr" className="text-muted-foreground">
                        {formatMoney(s.revenue, currency)} ({formatNumber(s.conversions)})
                      </span>
                    </div>
                    <div className="mt-1 h-2 rounded-full bg-muted">
                      <div
                        className="h-2 rounded-full bg-success transition-all duration-300 ease-smooth"
                        style={{ width: `${(s.revenue / maxSource) * 100}%` }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function PageSkeleton() {
  return (
    <div className="space-y-6" aria-busy="true" aria-label={t.loading}>
      <Skeleton className="h-7 w-40" />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-24" />
        ))}
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Skeleton className="h-72" />
        <Skeleton className="h-72" />
      </div>
    </div>
  );
}
