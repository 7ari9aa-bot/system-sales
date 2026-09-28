"use client";

import { useQuery } from "@tanstack/react-query";
import { t } from "@/lib/t";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState, PageHeader } from "@/components/ui/states";
import { apiClient } from "@/lib/api";

interface TeamMember {
  id: string;
  email?: string;
  name?: string;
  role?: string;
  status?: string;
}

type TeamData = TeamMember[] | { items?: TeamMember[] };

export default function TeamPage() {
  const { data: dataRaw, isLoading, isError } = useQuery({
    queryKey: ["invitations"],
    queryFn: () => apiClient.get("/api/v1/invitations"),
  });
  const data = dataRaw as TeamData | undefined;

  if (isError) return <ErrorState message={t.somethingWentWrong} />;
  if (isLoading) return <TeamSkeleton />;

  const members: TeamMember[] = Array.isArray(data) ? data : data?.items ?? [];

  return (
    <div className="space-y-6">
      <PageHeader title={t.team} description="Team members and invitations" />

      {members.length === 0 ? (
        <EmptyState title={t.noInvitations} />
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>{t.team}</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {members.map((m) => (
                <div key={m.id} className="flex items-center justify-between border-b last:border-0 pb-3 last:pb-0">
                  <div className="flex items-center gap-3">
                    <div className="flex h-9 w-9 items-center justify-center rounded-full bg-muted text-sm font-medium">
                      {(m.email ?? m.name ?? "?").charAt(0).toUpperCase()}
                    </div>
                    <div>
                      <div className="text-sm font-medium">{m.email ?? m.name}</div>
                      <div className="text-xs text-muted-foreground">{m.role ?? "member"}</div>
                    </div>
                  </div>
                  <Badge variant={m.status === "accepted" ? "default" : "outline"}>
                    {m.status ?? "pending"}
                  </Badge>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function TeamSkeleton() {
  return (
    <div className="space-y-6">
      <PageHeader title={t.team} />
      <Card>
        <CardHeader>
          <Skeleton className="h-5 w-24" />
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-12 w-full" />
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
