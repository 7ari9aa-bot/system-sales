"use client";

import { useQuery } from "@tanstack/react-query";
import { t } from "@/lib/t";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState, PageHeader } from "@/components/ui/states";
import { apiClient } from "@/lib/api";

export default function IntegrationsPage() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["integrations"],
    queryFn: () => apiClient.get("/api/v1/integrations"),
  });

  if (isError) return <ErrorState title={t("integrations")} />;
  if (isLoading) return <IntegrationsSkeleton />;

  const integrations = data?.items ?? [];

  return (
    <div className="space-y-6">
      <PageHeader title={t("integrations")} subtitle="Connected channels and services" />

      {integrations.length === 0 ? (
        <EmptyState title={t("no_integrations_yet")} />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {integrations.map((item: any) => (
            <Card key={item.id}>
              <CardContent className="p-4">
                <div className="flex items-center justify-between">
                  <span className="font-medium">{item.provider ?? item.type}</span>
                  <Badge variant={item.status === "active" ? "default" : "outline"}>
                    {item.status}
                  </Badge>
                </div>
                {item.last_synced_at && (
                  <div className="mt-2 text-xs text-muted-foreground">
                    {t("last_synced")}: {new Date(item.last_synced_at).toLocaleString()}
                  </div>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

function IntegrationsSkeleton() {
  return (
    <div className="space-y-6">
      <PageHeader title={t("integrations")} />
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
