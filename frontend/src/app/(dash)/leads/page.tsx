/* eslint-disable @typescript-eslint/no-explicit-any */
"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { t } from "@/lib/t";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState, PageHeader } from "@/components/ui/states";
import { apiClient } from "@/lib/api";

export default function LeadsPage() {
  const { data: dataRaw, isLoading, isError } = useQuery({
    queryKey: ["leads"],
    queryFn: () => apiClient.get("/api/v1/customers?filter=lead&limit=20"),
  });
  const data = dataRaw as any;

  if (isError) return <ErrorState message={t.somethingWentWrong} />;
  if (isLoading) return <LeadsSkeleton />;

  const leads = data?.items ?? [];

  return (
    <div className="space-y-6">
      <PageHeader title={t.customers} description="Pipeline and lead management" />

      {leads.length === 0 ? (
        <EmptyState title={t.noCustomers} />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {leads.map((lead: any) => (
            <Link key={lead.id} href={`/customers/${lead.id}`}>
              <Card className="hover:border-primary/50 transition-colors">
                <CardContent className="p-4">
                  <div className="flex items-center justify-between">
                    <span className="font-medium">{lead.name}</span>
                    <Badge variant="outline">{lead.status ?? "new"}</Badge>
                  </div>
                  {lead.phone && (
                    <div className="mt-2 text-sm text-muted-foreground" dir="ltr">
                      {lead.phone}
                    </div>
                  )}
                  {lead.source && (
                    <div className="mt-1 text-xs text-muted-foreground">
                      {lead.source}
                    </div>
                  )}
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

function LeadsSkeleton() {
  return (
    <div className="space-y-6">
      <PageHeader title={t.customers} />
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {[0, 1, 2, 3, 4, 5].map((i) => (
          <Card key={i}>
            <CardContent className="p-4">
              <Skeleton className="h-5 w-32" />
              <Skeleton className="mt-2 h-4 w-24" />
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
