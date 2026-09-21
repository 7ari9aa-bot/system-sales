"use client";

import { useQuery } from "@tanstack/react-query";
import { t } from "@/lib/t";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState, PageHeader } from "@/components/ui/states";
import { apiClient } from "@/lib/api";

export default function JourneysPage() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["journeys"],
    queryFn: () => apiClient.get("/api/v1/journeys?limit=20"),
  });

  if (isError) return <ErrorState title={t("journeys")} />;
  if (isLoading) return <JourneysSkeleton />;

  const journeys = data?.items ?? [];

  return (
    <div className="space-y-6">
      <PageHeader title={t("journeys")} subtitle="Customer lifecycle automation" />

      {journeys.length === 0 ? (
        <EmptyState title={t("no_journeys_yet")} />
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {journeys.map((journey: any) => (
            <Card key={journey.id}>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <CardTitle className="text-base">{journey.name}</CardTitle>
                  <Badge variant={journey.status === "active" ? "default" : "outline"}>
                    {journey.status}
                  </Badge>
                </div>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-muted-foreground">
                  {journey.description ?? "—"}
                </p>
                <div className="mt-3 flex gap-4 text-xs text-muted-foreground">
                  <span>{journey.steps?.length ?? 0} steps</span>
                  <span>{journey.runs_count ?? 0} runs</span>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

function JourneysSkeleton() {
  return (
    <div className="space-y-6">
      <PageHeader title={t("journeys")} />
      <div className="grid gap-4 md:grid-cols-2">
        {[0, 1, 2, 3].map((i) => (
          <Card key={i}>
            <CardHeader>
              <Skeleton className="h-5 w-40" />
            </CardHeader>
            <CardContent>
              <Skeleton className="h-4 w-full" />
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
