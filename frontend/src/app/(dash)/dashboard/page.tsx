"use client";

import Link from "next/link";
import { ArrowUpRight, CircleCheck, TriangleAlert } from "lucide-react";
import { useDashboard } from "@/lib/queries";
import { t } from "@/lib/t";
import { formatNumber } from "@/lib/utils";
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

function BarChart({ data }: { data: { day: string; revenue: number }[] }) {
  const max = Math.max(1, ...data.map((d) => d.revenue));
  if (data.length === 0) return <EmptyState title="لا توجد بيانات بعد" className="py-8" />;
  return (
    <div className="flex h-40 items-end gap-1 pt-2">
      {data.map((d) => (
        <div key={d.day} className="flex-1 text-center" title={`${d.day}: ${d.revenue}`}>
          <div
            className="mx-auto w-full max-w-6 rounded-md bg-primary/85 transition-all duration-300 ease-smooth"
            style={{ height: `${Math.max(4, (d.revenue / max) * 110)}px` }}
          />
          <div className="mt-1 text-[10px] text-muted-foreground">{new Date(d.day).getDate()}</div>
        </div>
      ))}
    </div>
  );
}

export default function DashboardPage() {
  const { data, error, refetch, isLoading } = useDashboard();

  if (error) return <ErrorState message={error.message} onRetry={() => refetch()} />;

  if (isLoading || !data) return <PageSkeleton />;

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
          {data.conversations.unread === 0 && data.low_stock === 0 ? (
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
              {data.low_stock > 0 && (
                <Link
                  href="/inventory"
                  data-testid="attention-low-stock"
                  className="group flex items-center justify-between rounded-lg border border-warning/40 p-3 transition-colors hover:bg-warning/10"
                >
                  <span className="flex items-center gap-2 text-sm font-semibold">
                    <TriangleAlert aria-hidden="true" className="size-4 text-warning" />
                    {t.nearlyOut(data.low_stock)}
                  </span>
                  <ArrowUpRight aria-hidden="true" className="size-4 text-muted-foreground transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5" />
                </Link>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        <Stat
          label={t.revenue30}
          value={`${Number(data.orders.revenue).toFixed(0)} ج.م`}
          testid="stat-revenue"
        />
        <Stat label={t.orders30} value={data.orders.orders_count} testid="stat-orders" />
        <Stat label={t.aov} value={Number(data.orders.aov).toFixed(0)} testid="stat-aov" />
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
          hint={data.low_stock > 0 ? t.nearlyOut(data.low_stock) : undefined}
          testid="stat-products"
        />
      </div>

      {data.low_stock > 0 && (
        <Card className="mt-4 border-s-4 border-s-warning" data-testid="low-stock-alert">
          <CardContent className="flex items-center gap-3 p-4">
            <TriangleAlert aria-hidden="true" className="size-5 shrink-0 text-warning" />
            <p className="flex-1 text-sm font-semibold">{t.lowStockAlert(data.low_stock)}</p>
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
            <CardTitle>{t.dailyRevenue}</CardTitle>
          </CardHeader>
          <CardContent>
            <BarChart data={data.daily_orders} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>{t.revenueBySource}</CardTitle>
          </CardHeader>
          <CardContent>
            {sources.length === 0 ? (
              <EmptyState title={t.noSourceData} className="py-8" />
            ) : (
              <div className="space-y-3">
                {sources.map((s) => (
                  <div key={s.source}>
                    <div className="flex items-center justify-between text-[13px]">
                      <span className="flex items-center gap-2 font-semibold">
                        <Badge variant="outline">{s.source}</Badge>
                      </span>
                      <span dir="ltr" className="text-muted-foreground">
                        {Number(s.revenue).toFixed(0)} ({formatNumber(s.conversions)})
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
