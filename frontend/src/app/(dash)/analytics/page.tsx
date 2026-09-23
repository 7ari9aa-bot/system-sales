"use client";

/** Analytics screen — one call, `GET /analytics/overview` (contract T3).
 *
 *  This page used to fetch a path the server never published, so it landed on
 *  its error state on every visit while `as any` hid the missing contract from
 *  `tsc`. What it reads now is typed in `@/lib/queries` and mirrors the route's
 *  payload key for key.
 *
 *  Three honesty rules, copied from the dashboard:
 *  - Gross and net are two figures, never one card called "الإيرادات" (ADR-053).
 *    Net is what the merchant keeps, and the refund that produced the gap sits
 *    beside it so the difference is visible instead of mysterious.
 *  - Money crosses the wire as a STRING and is rendered through `formatMoney`,
 *    which never coerces it (ADR-001). The only place a figure becomes a number
 *    here is a bar height, which is geometry rather than an amount.
 *  - A figure the server does not compute is not rendered. The old page showed
 *    `customers_count`, `conversion_rate`, `top_products` and an AI-usage block
 *    that no endpoint ever returned; they are gone rather than faked. */

import Link from "next/link";
import { TriangleAlert } from "lucide-react";
import { useAnalyticsOverview, type OverviewDailyRow } from "@/lib/queries";
import { t } from "@/lib/t";
import { formatMoney } from "@/lib/utils";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState, PageHeader } from "@/components/ui/states";

/** Money is a string on the wire; a bar height is geometry, so the scale may
 *  read it as a number. The value never escapes as a displayed amount. */
function magnitude(amount: string): number {
  const n = Number(amount);
  return Number.isFinite(n) && n > 0 ? n : 0;
}

function Stat({
  label,
  value,
  hint,
  testid,
}: {
  label: string;
  value: string | number;
  hint?: string;
  testid: string;
}) {
  return (
    <Card data-testid={testid}>
      <CardContent className="p-5">
        <div className="text-[26px] font-bold leading-tight" dir="ltr">
          {value}
        </div>
        <div className="mt-0.5 text-[13px] text-muted-foreground">{label}</div>
        {hint && <div className="mt-1 text-xs text-muted-foreground">{hint}</div>}
      </CardContent>
    </Card>
  );
}

/** The merchant's day, bucketed server-side in the payload's own `timezone`
 *  (gap M10). The bar is NET money because that is the figure a merchant plans
 *  with; the tooltip keeps gross and refunded so a short bar is never read as a
 *  bad sales day when it was a refund day. A day that returned more than it
 *  collected shows a zero bar plus its `refund_excess` in the tooltip: net is
 *  floored at zero upstream and the remainder would otherwise vanish. */
function DailyChart({ rows, currency }: { rows: OverviewDailyRow[]; currency: string | null }) {
  if (rows.length === 0) {
    return <EmptyState title={t.noOrders} description={t.noOrdersHint} className="py-8" />;
  }
  const max = Math.max(1, ...rows.map((r) => magnitude(r.net_revenue)));
  return (
    <div data-testid="overview-daily-chart">
      <p className="text-[11px] text-muted-foreground">
        {`${t.netShort} · ${t.grossShort} · ${t.refundedShort}`}
      </p>
      <div className="flex h-40 items-end gap-1 pt-2">
        {rows.map((r) => (
          <div
            key={r.day}
            className="flex-1 text-center"
            title={
              `${r.day} — ${t.grossShort}: ${formatMoney(r.gross_revenue, currency)} · ` +
              `${t.refundedShort}: ${formatMoney(r.refunded_amount, currency)} · ` +
              `${t.netShort}: ${formatMoney(r.net_revenue, currency)}` +
              (magnitude(r.refund_excess) > 0
                ? ` · ${t.refundExcessNote(formatMoney(r.refund_excess, currency))}`
                : "")
            }
          >
            <div
              data-testid={`overview-bar-${r.day}`}
              className="mx-auto w-full max-w-6 rounded-md bg-primary/85 transition-all duration-300 ease-smooth"
              style={{ height: `${Math.max(4, (magnitude(r.net_revenue) / max) * 110)}px` }}
            />
            <div className="mt-1 text-[10px] text-muted-foreground">{r.day.slice(8)}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function AnalyticsPage() {
  const { data, error, refetch, isLoading } = useAnalyticsOverview();

  if (error) return <ErrorState message={error.message} onRetry={() => refetch()} />;
  if (isLoading || !data) return <PageSkeleton />;

  // §47: the payload labels its own currency and zone — no literal, no guess.
  const currency = data.currency || null;
  const stock = data.stock;

  return (
    <div className="space-y-6">
      <PageHeader
        title={t.groupAnalytics}
        description={`${data.since.slice(0, 10)} → ${data.until.slice(0, 10)} · ${data.timezone}`}
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat
          label={t.grossRevenue30}
          value={formatMoney(data.gross_revenue, currency)}
          testid="stat-gross-revenue"
        />
        <Stat
          label={t.netRevenue30}
          value={formatMoney(data.net_revenue, currency)}
          hint={`${t.refundedShort}: ${formatMoney(data.refunded_amount, currency)}`}
          testid="stat-net-revenue"
        />
        <Stat label={t.orders30} value={data.orders_count} testid="stat-orders" />
        <Stat
          label={t.netAov}
          value={formatMoney(data.net_aov, currency)}
          hint={`${t.grossAov}: ${formatMoney(data.gross_aov, currency)}`}
          testid="stat-aov"
        />
      </div>

      {/* Net is floored at zero upstream: a window that refunded more than it
          collected would otherwise read as a clean zero and the difference
          would vanish from the screen. `refund_excess` is that remainder. */}
      {magnitude(data.refund_excess) > 0 && (
        <Card className="border-s-4 border-s-warning" data-testid="refund-excess-note">
          <CardContent className="flex items-center gap-3 p-4">
            <TriangleAlert aria-hidden="true" className="size-5 shrink-0 text-warning" />
            <p className="flex-1 text-sm font-semibold">
              {t.refundExcessNote(formatMoney(data.refund_excess, currency))}
            </p>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>{t.netRevenue30}</CardTitle>
          </CardHeader>
          <CardContent>
            <DailyChart rows={data.daily_series} currency={currency} />
          </CardContent>
        </Card>

        {/* M7: an empty shelf is its own band, not "low stock" noise. */}
        <Card data-testid="overview-stock-health">
          <CardHeader>
            <CardTitle>{t.inventory}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {stock.out_of_stock_count === 0 && stock.low_stock_count === 0 ? (
              <p className="text-sm text-success">{t.allClear}</p>
            ) : (
              <div className="space-y-2">
                {stock.out_of_stock_count > 0 && (
                  <p className="text-sm font-semibold text-danger" data-testid="overview-sold-out">
                    {t.soldOutCount(stock.out_of_stock_count)}
                  </p>
                )}
                {stock.low_stock_count > 0 && (
                  <p className="text-sm font-semibold text-warning" data-testid="overview-low-stock">
                    {t.nearlyOut(stock.low_stock_count)}
                  </p>
                )}
              </div>
            )}
            <p className="text-[11px] text-muted-foreground">
              {t.lowStockThresholdNote(stock.low_stock_threshold)}
            </p>
            <Link
              href="/inventory"
              className="text-[13px] font-bold text-primary underline-offset-4 hover:underline"
            >
              {t.goInventory}
            </Link>
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
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
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
