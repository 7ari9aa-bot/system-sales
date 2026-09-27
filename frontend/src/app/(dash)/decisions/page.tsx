"use client";

import * as React from "react";
import { useState, useTransition } from "react";
import {
  Scale,
  CheckCircle2,
  XCircle,
  Clock,
  RotateCcw,
  Check,
  Ban,
  FileCode2,
  Copy,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import {
  useDecisions,
  useDecisionTransition,
  type Decision,
} from "@/lib/queries";
import { getLang } from "@/lib/i18n";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, ErrorState, PageHeader, TableSkeleton } from "@/components/ui/states";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { cn } from "@/lib/utils";

type FilterStatus = "ALL" | "ACTIVE" | "APPROVED" | "EXECUTED" | "DENIED" | "REVOKED";

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const locale = getLang() === "en" ? "en-GB" : "ar-EG";
  return new Date(value).toLocaleString(locale, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function timeRemaining(expiresAt: string | null | undefined): { label: string; isExpired: boolean } {
  if (!expiresAt) return { label: "∞", isExpired: false };
  const diffMs = new Date(expiresAt).getTime() - Date.now();
  if (diffMs <= 0) return { label: "منتهي (Expired)", isExpired: true };
  const sec = Math.floor(diffMs / 1000);
  if (sec < 60) return { label: `${sec}s`, isExpired: false };
  const min = Math.floor(sec / 60);
  return { label: `${min}m ${sec % 60}s`, isExpired: false };
}

function riskVariant(level: string | null | undefined): "danger" | "warning" | "default" {
  if (level === "HIGH") return "danger";
  if (level === "MEDIUM") return "warning";
  return "default";
}

function statusVariant(status: string): "warning" | "success" | "danger" | "default" | "primary" {
  switch (status) {
    case "PROPOSED":
      return "warning";
    case "VERIFIED":
      return "primary";
    case "APPROVED":
    case "EXECUTED":
      return "success";
    case "DENIED":
    case "REVOKED":
    case "STALE":
      return "danger";
    default:
      return "default";
  }
}

export default function DecisionsPage() {
  const [filter, setFilter] = useState<FilterStatus>("ALL");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [confirmState, setConfirmState] = useState<{
    open: boolean;
    decisionId: string;
    action: "verify" | "approve" | "deny" | "revoke";
    title: string;
    description: string;
  }>({
    open: false,
    decisionId: "",
    action: "approve",
    title: "",
    description: "",
  });

  const statusParam =
    filter === "ALL"
      ? undefined
      : filter === "ACTIVE"
      ? "PROPOSED"
      : filter;

  const { data, isLoading, error, refetch } = useDecisions(statusParam);
  const transitionMutation = useDecisionTransition();
  const [, startTransition] = useTransition();

  const isAr = getLang() === "ar";

  function handleTriggerAction(
    decisionId: string,
    action: "verify" | "approve" | "deny" | "revoke"
  ) {
    const titles: Record<string, string> = {
      verify: isAr ? "التحقق من صحة القرار؟" : "Verify Decision Integrity?",
      approve: isAr ? "الموافقة على تنفيذ القرار؟" : "Approve Decision Execution?",
      deny: isAr ? "رفض هذا القرار؟" : "Deny This Decision?",
      revoke: isAr ? "إلغاء الترخيص وتجريد الصلاحية؟" : "Revoke Grant and Authority?",
    };

    const descriptions: Record<string, string> = {
      verify: isAr
        ? "سيتم فحص البراهين والأوامر وتثبيت حالة القرار كـ VERIFIED."
        : "Evidence hashes and command signatures will be verified.",
      approve: isAr
        ? "ستمنح الصلاحية وتُنشأ أقفال الميزانية للبدء في التنفيذ الذري."
        : "Grants will be locked and autonomy budget allocated for atomic execution.",
      deny: isAr
        ? "سيتم إغلاق مسار القرار ورفض التنفيذ بصورة نهائية."
        : "The decision workflow will be terminated and marked as denied.",
      revoke: isAr
        ? "سيتم سحب الموافقة على الفور ومنع أي تأثيرات لاحقة."
        : "The authority grant will be immediately stripped and effects cancelled.",
    };

    setConfirmState({
      open: true,
      decisionId,
      action,
      title: titles[action],
      description: descriptions[action],
    });
  }

  function handleConfirmAction() {
    if (!confirmState.decisionId) return;
    startTransition(async () => {
      try {
        await transitionMutation.mutateAsync({
          decisionId: confirmState.decisionId,
          action: confirmState.action,
        });
      } finally {
        setConfirmState((prev) => ({ ...prev, open: false }));
      }
    });
  }

  return (
    <div className="space-y-6" data-testid="decisions-page">
      <PageHeader
        title={isAr ? "سجل القرارات والحوكمة" : "Decision Governance Ledger"}
        description={
          isAr
            ? "الحوكمة الصارمة للقرارات الذكية (V12 Decision Lifecycle)، والتحقق الحتمي من البراهين والتواقيع."
            : "Deterministic decision lifecycle, evidence verification, and cryptographic command execution."
        }
        actions={
          <Button
            variant="outline"
            size="sm"
            onClick={() => refetch()}
            className="gap-2"
            data-testid="refresh-decisions"
          >
            <RotateCcw aria-hidden="true" className="size-4" />
            <span>{isAr ? "تحديث" : "Refresh"}</span>
          </Button>
        }
      />

      {/* Filter Tabs */}
      <div className="flex flex-wrap items-center gap-2 border-b border-border pb-3">
        {(["ALL", "ACTIVE", "APPROVED", "EXECUTED", "DENIED", "REVOKED"] as FilterStatus[]).map(
          (tab) => {
            const labels: Record<FilterStatus, string> = {
              ALL: isAr ? "الكل" : "All",
              ACTIVE: isAr ? "قيد المراجعة (Proposed)" : "Proposed",
              APPROVED: isAr ? "تمت الموافقة" : "Approved",
              EXECUTED: isAr ? "مُنفَّذ (Executed)" : "Executed",
              DENIED: isAr ? "مرفوض" : "Denied",
              REVOKED: isAr ? "ملغي (Revoked)" : "Revoked",
            };
            const active = filter === tab;
            return (
              <button
                key={tab}
                type="button"
                onClick={() => setFilter(tab)}
                data-testid={`filter-decision-${tab.toLowerCase()}`}
                className={cn(
                  "rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors duration-150",
                  active
                    ? "bg-primary text-white"
                    : "bg-muted text-muted-foreground hover:bg-muted/80 hover:text-foreground"
                )}
              >
                {labels[tab]}
              </button>
            );
          }
        )}
      </div>

      {isLoading && <TableSkeleton rows={5} cols={5} />}

      {error && !(error.message?.includes("404") || error.message?.toLowerCase().includes("not found")) && (
        <ErrorState
          message={error instanceof Error ? error.message : "Failed to load decisions"}
          onRetry={() => refetch()}
        />
      )}

      {!isLoading && (!error || error.message?.includes("404") || error.message?.toLowerCase().includes("not found")) && (!data?.items || data.items.length === 0) && (
        <EmptyState
          icon={<Scale aria-hidden="true" />}
          title={isAr ? "لا توجد قرارات في هذا المسار" : "No decisions found"}
          description={
            isAr
              ? "القرارات التي تصدرها نماذج الذكاء الاصطناعي أو العمليات الحرجة ستسجل وتظهر هنا فور إنشائها."
              : "Decisions produced by AI agents or critical system workflows will appear here."
          }
        />
      )}

      {!isLoading && !error && data?.items && data.items.length > 0 && (
        <div className="grid gap-4">
          {data.items.map((item: Decision) => {
            const isExpanded = expandedId === item.decision_id;
            const remaining = timeRemaining(item.expires_at);

            return (
              <Card
                key={item.decision_id}
                data-testid={`decision-card-${item.decision_id}`}
                className={cn(
                  "transition-all duration-200 border-border/70 hover:border-primary/40",
                  isExpanded && "ring-1 ring-primary/30"
                )}
              >
                <CardHeader className="pb-3">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-xs font-bold text-muted-foreground">
                          #{item.decision_id.slice(0, 8)}
                        </span>
                        <CardTitle className="text-base font-bold">
                          {item.action}
                        </CardTitle>
                        <Badge variant={riskVariant(item.risk_level)}>
                          {item.risk_level || "LOW"}
                        </Badge>
                        <Badge variant={statusVariant(item.decision_status)}>
                          {item.decision_status}
                        </Badge>
                      </div>
                      {item.intent && (
                        <p className="text-xs text-muted-foreground">{item.intent}</p>
                      )}
                    </div>

                    <div className="flex items-center gap-2">
                      {/* TTL Badge */}
                      {item.expires_at && (
                        <div
                          className={cn(
                            "flex items-center gap-1 rounded-md px-2 py-1 font-mono text-[11px] font-medium border",
                            remaining.isExpired
                              ? "border-danger/30 bg-danger/10 text-danger"
                              : "border-border bg-muted/60 text-muted-foreground"
                          )}
                          title={`Expires: ${formatDateTime(item.expires_at)}`}
                        >
                          <Clock aria-hidden="true" className="size-3" />
                          <span>{remaining.label}</span>
                        </div>
                      )}

                      {/* Expand / Collapse toggle */}
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        onClick={() =>
                          setExpandedId(isExpanded ? null : item.decision_id)
                        }
                        aria-label="Toggle details"
                      >
                        {isExpanded ? (
                          <ChevronUp aria-hidden="true" className="size-4" />
                        ) : (
                          <ChevronDown aria-hidden="true" className="size-4" />
                        )}
                      </Button>
                    </div>
                  </div>
                </CardHeader>

                <CardContent className="space-y-3 pt-0">
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 rounded-lg bg-muted/40 p-3 text-xs">
                    <div>
                      <span className="text-muted-foreground block mb-0.5">
                        {isAr ? "نوع الفاعل" : "Actor"}
                      </span>
                      <span className="font-semibold">{item.actor_type || "SYSTEM"}</span>
                    </div>
                    <div>
                      <span className="text-muted-foreground block mb-0.5">
                        {isAr ? "حالة الاعتماد" : "Approval State"}
                      </span>
                      <span className="font-semibold">{item.approval_state}</span>
                    </div>
                    <div>
                      <span className="text-muted-foreground block mb-0.5">
                        {isAr ? "تاريخ الإنشاء" : "Created At"}
                      </span>
                      <span className="font-semibold">{formatDateTime(item.created_at)}</span>
                    </div>
                    <div>
                      <span className="text-muted-foreground block mb-0.5">
                        {isAr ? "بصمة الأمر" : "Command Hash"}
                      </span>
                      <span
                        className="font-mono text-[11px] truncate block text-primary"
                        title={item.command_hash || "None"}
                      >
                        {item.command_hash ? item.command_hash.slice(0, 10) + "…" : "—"}
                      </span>
                    </div>
                  </div>

                  {/* Actions Bar for Decision Lifecycle */}
                  <div className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-border/50">
                    <div className="flex items-center gap-2">
                      {item.decision_status === "PROPOSED" && (
                        <>
                          <Button
                            size="sm"
                            variant="secondary"
                            onClick={() => handleTriggerAction(item.decision_id, "verify")}
                            className="gap-1.5 text-xs"
                            disabled={transitionMutation.isPending}
                            data-testid={`verify-${item.decision_id}`}
                          >
                            <Check className="size-3.5 text-primary" />
                            <span>{isAr ? "تحقق (Verify)" : "Verify"}</span>
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => handleTriggerAction(item.decision_id, "deny")}
                            className="gap-1.5 text-xs text-danger hover:text-danger"
                            disabled={transitionMutation.isPending}
                            data-testid={`deny-${item.decision_id}`}
                          >
                            <Ban className="size-3.5" />
                            <span>{isAr ? "رفض (Deny)" : "Deny"}</span>
                          </Button>
                        </>
                      )}

                      {item.decision_status === "VERIFIED" && (
                        <>
                          <Button
                            size="sm"
                            variant="default"
                            onClick={() => handleTriggerAction(item.decision_id, "approve")}
                            className="gap-1.5 text-xs"
                            disabled={transitionMutation.isPending}
                            data-testid={`approve-${item.decision_id}`}
                          >
                            <CheckCircle2 className="size-3.5" />
                            <span>{isAr ? "موافقة واعتماد" : "Approve"}</span>
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => handleTriggerAction(item.decision_id, "deny")}
                            className="gap-1.5 text-xs text-danger hover:text-danger"
                            disabled={transitionMutation.isPending}
                            data-testid={`deny-${item.decision_id}`}
                          >
                            <Ban className="size-3.5" />
                            <span>{isAr ? "رفض" : "Deny"}</span>
                          </Button>
                        </>
                      )}

                      {item.decision_status === "APPROVED" && (
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => handleTriggerAction(item.decision_id, "revoke")}
                          className="gap-1.5 text-xs text-danger hover:text-danger"
                          disabled={transitionMutation.isPending}
                          data-testid={`revoke-${item.decision_id}`}
                        >
                          <XCircle className="size-3.5" />
                          <span>{isAr ? "إلغاء الترخيص (Revoke)" : "Revoke Grant"}</span>
                        </Button>
                      )}
                    </div>

                    <button
                      type="button"
                      onClick={() =>
                        setExpandedId(isExpanded ? null : item.decision_id)
                      }
                      className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-1"
                    >
                      <FileCode2 className="size-3.5" />
                      <span>
                        {isExpanded
                          ? isAr
                            ? "إخفاء التفاصيل التشفيرية"
                            : "Hide Details"
                          : isAr
                          ? "عرض البراهين والمعاملات"
                          : "Inspect Cryptographic Details"}
                      </span>
                    </button>
                  </div>

                  {/* Expanded Technical View */}
                  {isExpanded && (
                    <div className="mt-3 space-y-3 rounded-lg border border-border bg-card p-3 text-xs">
                      <div>
                        <span className="font-semibold block mb-1">
                          {isAr ? "المعاملات المقننة (Normalized Arguments):" : "Normalized Arguments:"}
                        </span>
                        <pre
                          dir="ltr"
                          className="max-h-48 overflow-auto rounded bg-muted/70 p-2 font-mono text-[11px] leading-relaxed text-foreground"
                        >
                          {JSON.stringify(item.normalized_arguments, null, 2)}
                        </pre>
                      </div>

                      <div className="space-y-1">
                        <span className="font-semibold block">
                          {isAr ? "بصمة المحتوى (Content Hash):" : "Content Hash:"}
                        </span>
                        <div
                          dir="ltr"
                          className="flex items-center justify-between rounded bg-muted/50 px-2 py-1 font-mono text-[11px]"
                        >
                          <span className="truncate">{item.content_hash}</span>
                          <button
                            type="button"
                            onClick={() =>
                              navigator.clipboard.writeText(item.content_hash)
                            }
                            className="p-1 hover:text-primary"
                            title="Copy Hash"
                          >
                            <Copy className="size-3" />
                          </button>
                        </div>
                      </div>

                      {item.command_hash && (
                        <div className="space-y-1">
                          <span className="font-semibold block">
                            {isAr ? "بصمة الأمر التشفيري (Command Hash):" : "Command Hash:"}
                          </span>
                          <div
                            dir="ltr"
                            className="flex items-center justify-between rounded bg-muted/50 px-2 py-1 font-mono text-[11px]"
                          >
                            <span className="truncate">{item.command_hash}</span>
                            <button
                              type="button"
                              onClick={() =>
                                navigator.clipboard.writeText(item.command_hash!)
                              }
                              className="p-1 hover:text-primary"
                              title="Copy Hash"
                            >
                              <Copy className="size-3" />
                            </button>
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}

      {/* Confirmation Dialog */}
      <ConfirmDialog
        open={confirmState.open}
        onOpenChange={(open) =>
          setConfirmState((prev) => ({ ...prev, open }))
        }
        title={confirmState.title}
        description={confirmState.description}
        confirmLabel={isAr ? "تأكيد الإجراء" : "Confirm Action"}
        onConfirm={handleConfirmAction}
      />
    </div>
  );
}
