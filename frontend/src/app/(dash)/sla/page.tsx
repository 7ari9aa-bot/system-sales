/* eslint-disable @typescript-eslint/no-explicit-any */
"use client";

import { useQuery } from "@tanstack/react-query";
import { t } from "@/lib/t";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState, PageHeader } from "@/components/ui/states";
import { apiClient } from "@/lib/api";

export default function SLAPage() {
  const { data: dataRaw, isLoading, isError } = useQuery({
    queryKey: ["sla"],
    queryFn: () => apiClient.get("/api/v1/operations/sla"),
  });
  const data = dataRaw as any;

  if (isError) return <ErrorState message={t.somethingWentWrong} />;
  if (isLoading) return <SLASkeleton />;

  const sla = data ?? {};

  return (
    <div className="space-y-6">
      <PageHeader title={t.slaRisk} description="Service level agreement monitoring" />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardContent className="p-5">
            <div className="text-[26px] font-bold" dir="ltr">{sla.at_risk ?? 0}</div>
            <div className="mt-0.5 text-[13px] text-muted-foreground">{t.slaAtRisk}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-5">
            <div className="text-[26px] font-bold" dir="ltr">{sla.breached ?? 0}</div>
            <div className="mt-0.5 text-[13px] text-muted-foreground">{t.slaBreached}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-5">
            <div className="text-[26px] font-bold" dir="ltr">{sla.avg_response_time ?? "—"}</div>
            <div className="mt-0.5 text-[13px] text-muted-foreground">{t.loading}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-5">
            <div className="text-[26px] font-bold" dir="ltr">{sla.compliance_rate ? `${sla.compliance_rate}%` : "—"}</div>
            <div className="mt-0.5 text-[13px] text-muted-foreground">{t.healthOk}</div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>{t.slaRisk}</CardTitle>
        </CardHeader>
        <CardContent>
          {(sla.conversations ?? []).length === 0 ? (
            <EmptyState title={t.slaRiskEmpty} />
          ) : (
            <div className="space-y-2">
              {(sla.conversations ?? []).map((c: any) => (
                <div key={c.id} className="flex items-center justify-between border-b last:border-0 pb-2 last:pb-0">
                  <span className="text-sm">{c.customer_name ?? "—"}</span>
                  <Badge variant={c.status === "breached" ? "danger" : "outline"}>
                    {c.status}
                  </Badge>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function SLASkeleton() {
  return (
    <div className="space-y-6">
      <PageHeader title={t.slaRisk} />
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
    </div>
  );
}
