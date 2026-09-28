"use client";

import { useQuery } from "@tanstack/react-query";
import { t } from "@/lib/t";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState, PageHeader } from "@/components/ui/states";
import { apiClient } from "@/lib/api";

interface QueueJob {
  id: string | number;
  kind?: string;
  name?: string;
  status: string;
  attempts?: number;
  error?: string;
}

type QueueData = QueueJob[] | { items?: QueueJob[] };

export default function QueuesPage() {
  const { data: dataRaw, isLoading, isError } = useQuery({
    queryKey: ["jobs"],
    queryFn: () => apiClient.get("/api/v1/jobs"),
    refetchInterval: 10000,
  });
  const data = dataRaw as QueueData | undefined;

  if (isError) return <ErrorState message={t.somethingWentWrong} />;
  if (isLoading) return <QueuesSkeleton />;

  const jobs: QueueJob[] = Array.isArray(data) ? data : data?.items ?? [];

  return (
    <div className="space-y-6">
      <PageHeader title={t.healthOutbox} description="Background job queue monitoring" />

      {jobs.length === 0 ? (
        <EmptyState title={t.allClear} />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {jobs.map((q) => (
            <Card key={q.id}>
              <CardContent className="p-4">
                <div className="flex items-center justify-between">
                  <span className="font-medium font-mono text-sm">{q.kind ?? q.name ?? "Job"}</span>
                  <Badge variant={q.status === "succeeded" || q.status === "completed" ? "default" : q.status === "failed" ? "danger" : "outline"}>
                    {q.status}
                  </Badge>
                </div>
                <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-muted-foreground">
                  <div>Attempts: <span className="font-medium text-foreground">{q.attempts ?? 0}</span></div>
                  <div>ID: <span className="font-medium font-mono text-foreground">{String(q.id).slice(0, 8)}</span></div>
                  {q.error && <div className="col-span-2 text-danger truncate">{q.error}</div>}
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
      <PageHeader title={t.healthOutbox} />
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
