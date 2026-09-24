"use client";

/** §135 approvals — the human-in-the-loop queue for HIGH-risk AI actions.
 *
 *  A HIGH-risk tool call parks the run in WAITING_APPROVAL with the action NOT
 *  yet done (approvals.py:1-7); this is where a person releases it or kills it.
 *  Each row states what a decision needs and nothing more: the action, the risk,
 *  who asked (`requested_by`), when, the argument snapshot the approval is bound
 *  to (`payload`, the same arguments `decide` matches through G-02's `payload_hash`),
 *  and any rejection reason already recorded — enough to decide without opening a
 *  database.
 *
 *  Money rule §47, applied to the arguments: the snapshot is rendered as TEXT. A
 *  Decimal amount arrives from the backend as a string, and `renderArgumentValue`
 *  never runs `Number()`/`.toFixed()` over it, so "250.00" reads exactly as sent.
 *
 *  Gating: like every sibling screen this one renders inside `Shell`'s auth
 *  guard, and there is NO client-side permission model to consult —
 *  `require_permission("settings:write")` runs on the server (router.py:324), so
 *  approve/deny appear on a decidable row and a reviewer who lacks the permission
 *  learns it from the 403's own sentence (see `decision-dialog.tsx`). The decide
 *  buttons are offered only where `ApprovalService.decide` would accept a
 *  decision (`status === PENDING`); the service is still the authority. */

import * as React from "react";
import { Check, ShieldAlert, TriangleAlert, X } from "lucide-react";
import { useApprovals, type Approval } from "@/lib/queries";
import { getLang } from "@/lib/i18n";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState, PageHeader } from "@/components/ui/states";
import { ap } from "@/components/approvals/labels";
import {
  APPROVE,
  DENY,
  argumentEntries,
  isDecidable,
  type Decision,
} from "@/components/approvals/decision";
import { ApprovalDecisionDialog } from "@/components/approvals/decision-dialog";

/* The three queues the list route can answer (`status` is a single value,
   router.py:312). APPROVED / REJECTED are the decided histories a reviewer may
   audit; EXPIRED / CANCELLED are reachable via the tabs' filter only by their own
   status word, so they surface as row badges rather than tabs. */
type TabStatus = "PENDING" | "APPROVED" | "REJECTED";

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const locale = getLang() === "en" ? "en-GB" : "ar-EG";
  return new Date(value).toLocaleString(locale, { dateStyle: "medium", timeStyle: "short" });
}

function riskLabel(level: string | null | undefined): string {
  switch (level) {
    case "HIGH":
      return ap.riskHigh;
    case "MEDIUM":
      return ap.riskMedium;
    case "LOW":
      return ap.riskLow;
    default:
      // An unknown risk is shown as the server wrote it, never as a guess.
      return level ?? "—";
  }
}

function riskVariant(level: string | null | undefined): "danger" | "warning" | "default" {
  if (level === "HIGH") return "danger";
  if (level === "MEDIUM") return "warning";
  return "default";
}

function statusLabel(status: string): string {
  switch (status) {
    case "PENDING":
      return ap.statusPending;
    case "APPROVED":
      return ap.statusApproved;
    case "REJECTED":
      return ap.statusRejected;
    case "EXPIRED":
      return ap.statusExpired;
    case "CANCELLED":
      return ap.statusCancelled;
    default:
      return status;
  }
}

function statusVariant(status: string): "warning" | "success" | "danger" | "default" {
  switch (status) {
    case "PENDING":
      return "warning";
    case "APPROVED":
      return "success";
    case "REJECTED":
    case "EXPIRED":
      return "danger";
    default:
      return "default";
  }
}

function ApprovalRow({ approval, onDecide }: { approval: Approval; onDecide: (d: Decision) => void }) {
  const arguments_ = argumentEntries(approval.payload);
  const decidable = isDecidable(approval.status);
  return (
    <Card data-testid={`approval-${approval.id}`}>
      <CardHeader className="space-y-1">
        <div className="flex items-start justify-between gap-3">
          <CardTitle className="flex items-center gap-2 text-[16px]" dir="ltr">
            <TriangleAlert aria-hidden="true" className="size-4 shrink-0 text-warning" />
            {/* The action is a vocabulary token from the tool registry: shown as
                the server wrote it, so a refusal sentence names a thing the
                reviewer can see here. */}
            {approval.action}
          </CardTitle>
          <div className="flex shrink-0 items-center gap-2">
            <Badge variant={riskVariant(approval.risk_level)}>{riskLabel(approval.risk_level)}</Badge>
            <Badge variant={statusVariant(approval.status)}>{statusLabel(approval.status)}</Badge>
          </div>
        </div>
        {approval.entity_type && approval.entity_id && (
          <p className="text-[12px] text-muted-foreground" dir="ltr">
            {approval.entity_type}: {approval.entity_id}
          </p>
        )}
      </CardHeader>
      <CardContent className="space-y-3">
        {/* who asked / when — the provenance a reviewer weighs. `requested_by` is
            the fixed token `ai | automation | system` (models.py:318), shown
            LTR as the server stores it. */}
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-muted-foreground">
          {approval.requested_by && (
            <span>
              {ap.requestedBy}: <span dir="ltr">{approval.requested_by}</span>
            </span>
          )}
          <span>
            {ap.when}: <span dir="ltr">{formatDateTime(approval.created_at)}</span>
          </span>
          <span>
            {ap.expires}:{" "}
            <span dir="ltr">{approval.expires_at ? formatDateTime(approval.expires_at) : ap.noExpiry}</span>
          </span>
        </div>

        {/* the argument snapshot G-02 binds this decision to — as text. */}
        <div>
          <p className="mb-1 text-[12px] font-semibold">{ap.argumentsHeading}</p>
          {arguments_.length === 0 ? (
            <p className="text-[12px] text-muted-foreground">{ap.argumentsEmpty}</p>
          ) : (
            <dl className="space-y-0.5 rounded-lg border border-border p-2 text-[12px]" data-testid={`approval-args-${approval.id}`}>
              {arguments_.map((entry) => (
                <div key={entry.key} className="flex gap-2">
                  <dt className="text-muted-foreground" dir="ltr">
                    {entry.key}
                  </dt>
                  <dd className="min-w-0 break-all" dir="ltr">
                    {entry.value}
                  </dd>
                </div>
              ))}
            </dl>
          )}
        </div>

        {approval.rejection_reason && (
          <p className="text-[12px] text-muted-foreground">
            {ap.rejectionReasonHeading}: <span dir="ltr">{approval.rejection_reason}</span>
          </p>
        )}

        {decidable && (
          <div className="flex gap-2 pt-1">
            <Button
              size="sm"
              variant="default"
              className="gap-1.5"
              onClick={() => onDecide(APPROVE)}
              data-testid={`approve-${approval.id}`}
            >
              <Check aria-hidden="true" className="size-4" />
              {ap.approve}
            </Button>
            <Button
              size="sm"
              variant="destructive"
              className="gap-1.5"
              onClick={() => onDecide(DENY)}
              data-testid={`deny-${approval.id}`}
            >
              <X aria-hidden="true" className="size-4" />
              {ap.reject}
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default function ApprovalsPage() {
  const [status, setStatus] = React.useState<TabStatus>("PENDING");
  const approvalsQuery = useApprovals(status);
  const [target, setTarget] = React.useState<{ approval: Approval; decision: Decision } | null>(null);

  const approvals = approvalsQuery.data?.items ?? [];
  const truncated = approvalsQuery.data?.truncated ?? false;

  const tabs: { id: TabStatus; label: string }[] = [
    { id: "PENDING", label: ap.tabPending },
    { id: "APPROVED", label: ap.tabApproved },
    { id: "REJECTED", label: ap.tabRejected },
  ];

  return (
    <div className="mx-auto w-full max-w-4xl space-y-6">
      <PageHeader title={ap.title} description={ap.subtitle} />

      <div className="flex gap-2" role="tablist" aria-label={ap.title}>
        {tabs.map((tab) => (
          <Button
            key={tab.id}
            role="tab"
            aria-selected={status === tab.id}
            variant={status === tab.id ? "default" : "ghost"}
            size="sm"
            onClick={() => setStatus(tab.id)}
            data-testid={`approvals-tab-${tab.id}`}
          >
            {tab.label}
            {tab.id === "PENDING" && status === "PENDING" && approvals.length > 0 && (
              <span className="ms-1.5 rounded-full bg-primary-soft px-1.5 py-0.5 text-[11px] font-bold text-primary" dir="ltr">
                {truncated ? `${approvals.length}+` : approvals.length}
              </span>
            )}
          </Button>
        ))}
      </div>

      {/* The queue is read a page at a time (approvals.py `APPROVALS_PAGE_SIZE`).
          When the server says it cut rows off, saying so is the only way this
          screen stays a complete picture of what is owed rather than a full-
          looking page that happens to be a prefix. */}
      {truncated && (
        <p
          role="status"
          data-testid="approvals-truncated"
          className="rounded-lg border border-warning/40 bg-warning-soft px-3 py-2 text-[12px]"
        >
          {ap.queueTruncated}
        </p>
      )}

      {approvalsQuery.isLoading ? (
        <div className="space-y-3" aria-busy="true" aria-label={ap.loading}>
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-40 w-full rounded-xl" />
          ))}
        </div>
      ) : approvalsQuery.isError ? (
        <ErrorState
          message={approvalsQuery.error instanceof Error ? approvalsQuery.error.message : ap.title}
          onRetry={() => void approvalsQuery.refetch()}
        />
      ) : approvals.length === 0 ? (
        <EmptyState
          icon={<ShieldAlert aria-hidden="true" />}
          title={status === "PENDING" ? ap.pendingEmptyTitle : ap.resolvedEmptyTitle}
          description={status === "PENDING" ? ap.pendingEmptyHint : ap.resolvedEmptyHint}
          testid="approvals-empty"
        />
      ) : (
        <div className="space-y-3" data-testid="approvals-list">
          {approvals.map((approval) => (
            <ApprovalRow
              key={approval.id}
              approval={approval}
              onDecide={(decision) => setTarget({ approval, decision })}
            />
          ))}
        </div>
      )}

      {target && (
        <ApprovalDecisionDialog
          approval={target.approval}
          decision={target.decision}
          open={target !== null}
          onOpenChange={(next) => {
            if (!next) setTarget(null);
          }}
        />
      )}
    </div>
  );
}
