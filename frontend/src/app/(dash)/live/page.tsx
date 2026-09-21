"use client";

import { useQuery } from "@tanstack/react-query";
import { t } from "@/lib/t";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState, PageHeader } from "@/components/ui/states";
import { apiClient } from "@/lib/api";

export default function LivePage() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["live"],
    queryFn: () => apiClient.get("/api/v1/operations/live"),
    refetchInterval: 5000,
  });

  if (isError) return <ErrorState title={t("live")} />;
  if (isLoading) return <LiveSkeleton />;

  const systems = data?.systems ?? [];

  return (
    <div className="space-y-6">
      <PageHeader title={t("live")} subtitle="Real-time system health" />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {systems.map((s: any) => (
          <Card key={s.name}>
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <span className="font-medium">{s.name}</span>
                <Badge
                  variant={s.status === "healthy" ? "default" : s.status === "degraded" ? "secondary" : "destructive"}
                >
                  {s.status}
                </Badge>
              </div>
              {s.latency_ms && (
                <div className="mt-2 text-xs text-muted-foreground" dir="ltr">
                  Latency: {s.latency_ms}ms
                </div>
              )}
              {s.error_rate && (
                <div className="mt-1 text-xs text-muted-foreground" dir="ltr">
                  Error rate: {s.error_rate}%
                </div>
              )}
            </CardContent>
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>{t("recent_events")}</CardTitle>
        </CardHeader>
        <CardContent>
          {(data?.events ?? []).length === 0 ? (
            <EmptyState title="No recent events" />
          ) : (
            <div className="space-y-2">
              {(data?.events ?? []).map((e: any, i: number) => (
                <div key={i} className="flex items-center justify-between border-b last:border-0 pb-2 last:pb-0">
                  <span className="text-sm">{e.message}</span>
                  <span className="text-xs text-muted-foreground" dir="ltr">
                    {new Date(e.timestamp).toLocaleTimeString()}
                  </span>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function LiveSkeleton() {
  return (
    <div className="space-y-6">
      <PageHeader title={t("live")} />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {[0, 1, 2].map((i) => (
          <Card key={i}>
            <CardContent className="p-4">
              <Skeleton className="h-5 w-32" />
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
