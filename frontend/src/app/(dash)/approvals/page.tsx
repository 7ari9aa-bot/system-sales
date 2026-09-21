"use client";

import * as React from "react";
import { Check, X, Clock, AlertTriangle } from "lucide-react";
import { useApprovals, useDecideApproval } from "@/lib/queries";
import { PageHeader } from "@/components/ui/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";

const RISK_LABELS: Record<string, string> = {
  LOW: "منخفض",
  MEDIUM: "متوسط",
  HIGH: "عالي",
};

const STATUS_LABELS: Record<string, string> = {
  PENDING: "بانتظار الموافقة",
  APPROVED: "تمت الموافقة",
  REJECTED: "مرفوض",
  EXPIRED: "منتهي",
  CANCELLED: "ملغي",
};

export default function ApprovalsPage() {
  const [status, setStatus] = React.useState<"PENDING" | "APPROVED" | "REJECTED">("PENDING");
  const approvalsQuery = useApprovals(status);
  const decideMutation = useDecideApproval();

  const approvals = approvalsQuery.data ?? [];

  return (
    <div className="mx-auto w-full max-w-4xl space-y-6">
      <PageHeader
        title="الموافقات"
        description="إجراءات الـAI عالية المخاطرة التي بتنتظر قرار بشري (§135)"
      />

      {/* Status tabs */}
      <div className="flex gap-2">
        {(["PENDING", "APPROVED", "REJECTED"] as const).map((s) => (
          <Button
            key={s}
            variant={status === s ? "default" : "ghost"}
            size="sm"
            onClick={() => setStatus(s)}
          >
            {STATUS_LABELS[s]}
            {s === "PENDING" && approvals.length > 0 && (
              <span className="mr-1.5 rounded-full bg-primary-soft px-1.5 py-0.5 text-[11px] font-bold text-primary">
                {approvals.length}
              </span>
            )}
          </Button>
        ))}
      </div>

      {/* Loading */}
      {approvalsQuery.isLoading && (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <Card key={i} className="animate-pulse">
              <CardHeader>
                <div className="h-4 w-1/3 rounded bg-muted" />
                <div className="h-3 w-1/2 rounded bg-muted" />
              </CardHeader>
              <CardContent>
                <div className="h-3 w-full rounded bg-muted" />
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Empty */}
      {!approvalsQuery.isLoading && approvals.length === 0 && (
        <Card>
          <CardContent className="flex flex-col items-center justify-center gap-3 py-12">
            <Check className="size-8 text-muted-foreground" aria-hidden="true" />
            <p className="text-[14px] text-muted-foreground">
              {status === "PENDING"
                ? "مفيش موافقات بتنتظر قرار دلوقتي"
                : `مفيش موافقات ${STATUS_LABELS[status]}`}
            </p>
          </CardContent>
        </Card>
      )}

      {/* Approvals list */}
      {approvals.length > 0 && (
        <div className="space-y-3">
          {approvals.map((approval) => (
            <Card key={approval.id}>
              <CardHeader>
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <AlertTriangle
                      className="size-4 text-warning"
                      aria-hidden="true"
                    />
                    <CardTitle className="text-[16px]">
                      {approval.action}
                    </CardTitle>
                  </div>
                  <div className="flex items-center gap-2">
                    {approval.risk_level && (
                      <Badge variant={approval.risk_level === "HIGH" ? "danger" : "warning"}>
                        {RISK_LABELS[approval.risk_level] ?? approval.risk_level}
                      </Badge>
                    )}
                    <Badge variant="outline">{STATUS_LABELS[approval.status] ?? approval.status}</Badge>
                  </div>
                </div>
                <CardDescription>
                  {approval.entity_type && approval.entity_id && (
                    <span className="text-muted-foreground">
                      {approval.entity_type}: {approval.entity_id}
                    </span>
                  )}
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="space-y-3">
                  {approval.requested_by && (
                    <div className="text-[13px] text-muted-foreground">
                      <Clock className="ml-1 inline size-3" aria-hidden="true" />
                      طُلب بواسطة: {approval.requested_by}
                    </div>
                  )}

                  {/* Decision buttons */}
                  {approval.status === "PENDING" && (
                    <div className="flex gap-2">
                      <Button
                        size="sm"
                        variant="default"
                        disabled={decideMutation.isPending}
                        onClick={() =>
                          decideMutation.mutate({
                            approvalId: approval.id,
                            decision: "APPROVED",
                          })
                        }
                        className="gap-1.5"
                      >
                        <Check className="size-4" aria-hidden="true" />
                        موافقة
                      </Button>
                      <Button
                        size="sm"
                        variant="destructive"
                        disabled={decideMutation.isPending}
                        onClick={() =>
                          decideMutation.mutate({
                            approvalId: approval.id,
                            decision: "REJECTED",
                            reason: "rejected by human reviewer",
                          })
                        }
                        className="gap-1.5"
                      >
                        <X className="size-4" aria-hidden="true" />
                        رفض
                      </Button>
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
