import React from "react";
import { Check, X, Clock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/dashboard/ui";

/**
 * Lists pending and resolved change requests for APPROVAL_REQUIRED settings.
 * A second admin can approve or reject pending requests inline.
 * Shows the status (pending_approval / approved / rejected) and the
 * submitted-by and reason metadata.
 */
const STATUS_META = {
  pending_approval: { labelAr: "بانتظار الموافقة", labelEn: "Pending", tone: "warning", Icon: Clock },
  approved: { labelAr: "تمت الموافقة", labelEn: "Approved", tone: "success", Icon: Check },
  rejected: { labelAr: "مرفوض", labelEn: "Rejected", tone: "error", Icon: X },
};

export default function ChangeRequestList({
  changeRequests = [],
  onApprove,
  onReject,
  isAr,
}) {
  if (changeRequests.length === 0) return null;

  return (
    <div className="rounded-lg border border-border bg-card p-3 space-y-2">
      <div className="text-[13px] font-semibold">
        {isAr ? "طلبات التغيير" : "Change Requests"}
        <span className="ml-2 text-[11px] font-normal text-muted-foreground">
          ({changeRequests.length})
        </span>
      </div>
      {changeRequests.map((req) => {
        const meta = STATUS_META[req.status] || STATUS_META.pending_approval;
        const Icon = meta.Icon;
        const isPending = req.status === "pending_approval";

        return (
          <div
            key={req.id}
            className="rounded-md border border-border/50 px-2.5 py-2 space-y-1.5"
          >
            <div className="flex items-center justify-between gap-2">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap gap-1.5 text-[11.5px] text-muted-foreground">
                  {Object.entries(req.changes || {}).map(([key, val]) => (
                    <code key={key} className="text-foreground">
                      {key} → {String(val)}
                    </code>
                  ))}
                </div>
                {req.reason && (
                  <div className="mt-0.5 text-[11px] text-muted-foreground italic">
                    {req.reason}
                  </div>
                )}
              </div>
              <Badge tone={meta.tone} className="shrink-0">
                <Icon className="mr-1 h-3 w-3" />
                {isAr ? meta.labelAr : meta.labelEn}
              </Badge>
            </div>
            {isPending && (
              <div className="flex items-center gap-2 pt-1">
                <Button
                  size="sm"
                  variant="outline"
                  className="h-7 text-[11.5px]"
                  onClick={() => onApprove(req.id)}
                >
                  <Check className="h-3 w-3" />
                  {isAr ? "موافقة" : "Approve"}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  className="h-7 text-[11.5px]"
                  onClick={() => onReject(req.id)}
                >
                  <X className="h-3 w-3" />
                  {isAr ? "رفض" : "Reject"}
                </Button>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
