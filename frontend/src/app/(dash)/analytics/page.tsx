"use client";

import { useQuery } from "@tanstack/react-query";
import { t } from "@/lib/t";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState, PageHeader } from "@/components/ui/states";
import { Badge } from "@/components/ui/badge";
import { apiClient } from "@/lib/api";

export default function AnalyticsPage() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["analytics", "overview"],
    queryFn: () => apiClient.get("/api/v1/analytics/overview"),
  });

  if (isError) return <ErrorState title={t("analytics")} />;
  if (isLoading) return <AnalyticsSkeleton />;
  if (!data) return <EmptyState title={t("analytics")} />;

  return (
    <div className="space-y-6">
      <PageHeader title={t("analytics")} subtitle="Business insights and reports" />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card data-testid="stat-revenue">
          <CardContent className="p-5">
            <div className="text-[26px] font-bold leading-tight" dir="ltr">
              {data.revenue ? Number(data.revenue).toLocaleString("en-US") : "0"}
            </div>
            <div className="mt-0.5 text-[13px] text-muted-foreground">
              {t("revenue")}
            </div>
          </CardContent>
        </Card>
        <Card data-testid="stat-orders">
          <CardContent className="p-5">
            <div className="text-[26px] font-bold leading-tight" dir="ltr">
              {data.orders_count ?? 0}
            </div>
            <div className="mt-0.5 text-[13px] text-muted-foreground">
              {t("orders")}
            </div>
          </CardContent>
        </Card>
        <Card data-testid="stat-customers">
          <CardContent className="p-5">
            <div className="text-[26px] font-bold leading-tight" dir="ltr">
              {data.customers_count ?? 0}
            </div>
            <div className="mt-0.5 text-[13px] text-muted-foreground">
              {t("customers")}
            </div>
          </CardContent>
        </Card>
        <Card data-testid="stat-conversion">
          <CardContent className="p-5">
            <div className="text-[26px] font-bold leading-tight" dir="ltr">
              {data.conversion_rate ? `${data.conversion_rate}%` : "0%"}
            </div>
            <div className="mt-0.5 text-[13px] text-muted-foreground">
              {t("conversion_rate")}
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>{t("revenue")} — 30d</CardTitle>
          </CardHeader>
          <CardContent>
            <RevenueChart data={data.revenue_chart ?? []} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>{t("top_products")}</CardTitle>
          </CardHeader>
          <CardContent>
            <TopProducts products={data.top_products ?? []} />
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>{t("ai_metrics")}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 sm:grid-cols-3">
            <Metric label={t("ai_resolution_rate")} value={data.ai_resolution_rate ? `${data.ai_resolution_rate}%` : "—"} />
            <Metric label={t("ai_handover_rate")} value={data.ai_handover_rate ? `${data.ai_handover_rate}%` : "—"} />
            <Metric label={t("avg_response_time")} value={data.avg_response_time ?? "—"} />
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[20px] font-bold" dir="ltr">{value}</span>
      <span className="text-[13px] text-muted-foreground">{label}</span>
    </div>
  );
}

function RevenueChart({ data }: { data: { date: string; value: number }[] }) {
  if (!data.length) return <EmptyState title="No data" />;
  const max = Math.max(...data.map((d) => d.value), 1);
  return (
    <div className="flex items-end gap-1 h-[200px]">
      {data.map((d, i) => (
        <div
          key={i}
          className="flex-1 bg-primary/20 rounded-t"
          style={{ height: `${(d.value / max) * 100}%`, minHeight: "2px" }}
          title={`${d.date}: ${d.value}`}
        />
      ))}
    </div>
  );
}

function TopProducts({ products }: { products: { name: string; count: number }[] }) {
  if (!products.length) return <EmptyState title="No data" />;
  return (
    <div className="space-y-2">
      {products.map((p, i) => (
        <div key={i} className="flex items-center justify-between">
          <span className="text-sm">{p.name}</span>
          <Badge variant="secondary" dir="ltr">{p.count}</Badge>
        </div>
      ))}
    </div>
  );
}

function AnalyticsSkeleton() {
  return (
    <div className="space-y-6">
      <PageHeader title={t("analytics")} />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <Card key={i}>
            <CardContent className="p-5">
              <Skeleton className="h-7 w-20" />
              <Skeleton className="mt-2 h-4 w-16" />
            </CardContent>
          </Card>
        ))}
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        {[0, 1].map((i) => (
          <Card key={i}>
            <CardHeader>
              <Skeleton className="h-5 w-32" />
            </CardHeader>
            <CardContent>
              <Skeleton className="h-[200px] w-full" />
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
