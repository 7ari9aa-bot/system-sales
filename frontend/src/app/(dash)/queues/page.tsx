"use client";

import { useQuery } from "@tanstack/react-query";
import { t } from "@/lib/t";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState, PageHeader } from "@/components/ui/states";
import { apiClient } from "@/lib/api";

export default function QueuesPage() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["queues"],
    queryFn: () => apiClient.get("/api/v1/operations/queues"),
  });

  if (isError) return <ErrorState title={t("queues")} />;
  if (isLoading) return <QueuesSkeleton />;

  const queues = data?.items ?? [];

  return (
    <div className="space-y-6">
      <PageHeader title={t("queues")} subtitle="Background job queue monitoring" />

      {queues.length === 0 ? (
        <EmptyState title="No active queues" />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {queues.map((q: any) => (
            <Card key={q.name}>
              <CardContent className="p-4">
                <div className="flex items-center justify-between">
                  <span className="font-medium">{q.name}</span>
                  <Badge variant={q.depth > 100 ? "destructive" : "outline"}>
                    {q.depth} pending
                  </Badge>
                </div>
                <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-muted-foreground">
                  <div>Processing: <span className="font-medium text-foreground">{q.processing ?? 0}</span></div>
                  <div>Failed: <span className="font-medium text-foreground">{q.failed ?? 0}</span></div>
                  <div>DLQ: <span className="font-medium text-foreground">{q.dlq ?? 0}</span></div>
                  <div>Throughput: <span className="font-medium text-foreground" dir="ltr">{q.throughput ?? "—"}/min</span></div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

function QueuesSkeleton() {
  return (
    <div className="space-y-6">
      <PageHeader title={t("queues")} />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {[0, 1, 2].map((i) => (
          <Card key={i}>
            <CardContent className="p-4">
              <Skeleton className="h-5 w-32" />
              <Skeleton className="mt-3 h-4 w-full" />
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
