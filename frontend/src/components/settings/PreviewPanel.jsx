import React from "react";
import { AlertTriangle, ShieldCheck, ShieldAlert } from "lucide-react";
import { Badge } from "@/components/dashboard/ui";

/**
 * Preview panel — shows the impact of unsaved changes before the user
 * commits them: current vs. new value, scope, which keys need approval.
 * Modelled after the preset dry-run (preview_preset) shape.
 */
export default function PreviewPanel({ changedEntries, scope, isAr }) {
  if (!changedEntries || changedEntries.length === 0) return null;

  const scopeLabel = isAr ? "النطاق" : "Scope";
  const currentValueLabel = isAr ? "القيمة الحالية" : "Current";
  const newValueLabel = isAr ? "القيمة الجديدة" : "New";
  const approvalLabel = isAr ? "تتطلب موافقة" : "Needs approval";
  const noApprovalLabel = isAr ? "حفظ مباشر" : "Direct save";

  return (
    <div className="rounded-lg border border-border bg-card p-3 space-y-2">
      <div className="flex items-center gap-2 text-[13px] font-semibold">
        <AlertTriangle className="h-4 w-4 text-amber-500" />
        {isAr ? "معاينة التغييرات قبل الحفظ" : "Preview changes before saving"}
        <span className="text-[11px] font-normal text-muted-foreground">
          {scopeLabel}: <code className="text-foreground">{scope}</code>
        </span>
      </div>
      <div className="space-y-1.5">
        {changedEntries.map((entry) => (
          <div
            key={entry.key}
            className="flex items-start gap-2 rounded-md border border-border/50 px-2.5 py-2 text-[12px]"
          >
            <div className="min-w-0 flex-1">
              <div className="font-medium text-[12.5px]">{entry.label}</div>
              <div className="mt-0.5 flex flex-wrap gap-x-4 gap-y-0.5 text-[11.5px] text-muted-foreground">
                <span>
                  {currentValueLabel}:{" "}
                  <code className="text-foreground">{String(entry.oldValue ?? "—")}</code>
                </span>
                <span>
                  {newValueLabel}:{" "}
                  <code className="text-foreground">{String(entry.newValue ?? "—")}</code>
                </span>
              </div>
            </div>
            {entry.needsApproval ? (
              <Badge tone="warning" className="shrink-0">
                <ShieldAlert className="mr-1 h-3 w-3" />
                {approvalLabel}
              </Badge>
            ) : (
              <Badge tone="success" className="shrink-0">
                <ShieldCheck className="mr-1 h-3 w-3" />
                {noApprovalLabel}
              </Badge>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
