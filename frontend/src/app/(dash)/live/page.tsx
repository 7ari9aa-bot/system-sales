/* eslint-disable @typescript-eslint/no-explicit-any */
"use client";

import { useQuery } from "@tanstack/react-query";
import { t } from "@/lib/t";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState, PageHeader } from "@/components/ui/states";
import { apiClient } from "@/lib/api";

export default function LivePage() {
  const { data: dataRaw, isLoading, isError } = useQuery({
    queryKey: ["live"],
    queryFn: () => apiClient.get("/api/v1/platform/health"),
    refetchInterval: 10000,
  });
  const data = dataRaw as any;

  if (isError) return <ErrorState message={t.somethingWentWrong} />;
  if (isLoading) return <LiveSkeleton />;

  const systems = data?.subsystems ?? data?.systems ?? [];

  return (
    <div className="space-y-6">
      <PageHeader title={t.health} description="Real-time system health" />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {systems.map((s: any) => (
          <Card key={s.name}>
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <span className="font-medium uppercase">{s.name}</span>
                <Badge
                  variant={s.status === "ok" || s.status === "healthy" ? "default" : s.status === "degraded" ? "warning" : "danger"}
                >
                  {s.status}
                </Badge>
              </div>
              {s.detail && (
                <div className="mt-2 text-xs text-muted-foreground" dir="ltr">
                  {s.detail}
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
          <CardTitle>{t.healthSubsystems}</CardTitle>
        </CardHeader>
        <CardContent>
          {(data?.events ?? []).length === 0 ? (
            <EmptyState title={t.allClear} />
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
      <PageHeader title={t.health} />
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
