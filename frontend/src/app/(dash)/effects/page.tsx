"use client";

import * as React from "react";
import { useState } from "react";
import {
  RotateCcw,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Layers,
  Copy,
  ChevronDown,
  ChevronUp,
  RefreshCw,
} from "lucide-react";
import {
  useEffects,
  useReconcileEffect,
  type EffectItem,
} from "@/lib/queries";
import { getLang } from "@/lib/i18n";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, ErrorState, PageHeader, TableSkeleton } from "@/components/ui/states";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

type FilterStatus = "ALL" | "AMBIGUOUS" | "COMPLETED" | "FAILED" | "PENDING";

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const locale = getLang() === "en" ? "en-GB" : "ar-EG";
  return new Date(value).toLocaleString(locale, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function statusVariant(status: string): "warning" | "success" | "danger" | "default" | "primary" {
  switch (status) {
    case "AMBIGUOUS":
      return "danger";
    case "PENDING":
    case "EXECUTING":
      return "warning";
    case "COMPLETED":
      return "success";
    case "FAILED":
      return "danger";
    default:
      return "default";
  }
}

export default function EffectsReconciliationPage() {
  const [filter, setFilter] = useState<FilterStatus>("ALL");
  const [expandedId, setExpandedId] = useState<string | null>(null);

  // Reconciliation modal state
  const [reconcileModal, setReconcileModal] = useState<{
    open: boolean;
    effect: EffectItem | null;
    status: "COMPLETED" | "FAILED";
    providerRef: string;
  }>({
    open: false,
    effect: null,
    status: "COMPLETED",
    providerRef: "",
  });

  const isAr = getLang() === "ar";
  const statusParam = filter === "ALL" ? undefined : filter;

  const { data, isLoading, error, refetch } = useEffects(statusParam);
  const reconcileMutation = useReconcileEffect();

  const ambiguousCount =
    data?.items?.filter((item: EffectItem) => item.status === "AMBIGUOUS").length ?? 0;

  function openReconciliation(effect: EffectItem) {
    setReconcileModal({
      open: true,
      effect,
      status: "COMPLETED",
      providerRef: effect.provider_reference || "",
    });
  }

  async function handleReconcileSubmit() {
    if (!reconcileModal.effect) return;
    try {
      await reconcileMutation.mutateAsync({
        effectId: reconcileModal.effect.effect_id,
        status: reconcileModal.status,
        provider_reference: reconcileModal.providerRef.trim() || undefined,
      });
      setReconcileModal((prev) => ({ ...prev, open: false }));
    } catch {
      // Error handled by query / mutation
    }
  }

  return (
    <div className="space-y-6" data-testid="effects-page">
      <PageHeader
        title={isAr ? "سجل التأثيرات والتسوية" : "Effects & Reconciliation Ledger"}
        description={
          isAr
            ? "تتبع حتمي لتأثيرات العالم الخارجي ومفاتيح عدم التكرار (Idempotency) ومعالجة الحالات المعلقة والغامضة (AMBIGUOUS)."
            : "Deterministic outbox/effects idempotency tracking, ambiguous state resolution, and provider reconciliation."
        }
        actions={
          <Button
            variant="outline"
            size="sm"
            onClick={() => refetch()}
            className="gap-2"
            data-testid="refresh-effects"
          >
            <RotateCcw aria-hidden="true" className="size-4" />
            <span>{isAr ? "تحديث" : "Refresh"}</span>
          </Button>
        }
      />

      {/* Ambiguous State Alert Banner if any ambiguous effects exist */}
      {ambiguousCount > 0 && (
        <div
          role="alert"
          className="flex items-center justify-between rounded-xl border border-warning/30 bg-warning/10 p-4 text-warning-foreground"
        >
          <div className="flex items-center gap-3">
            <AlertTriangle className="size-5 text-warning shrink-0" />
            <div>
              <p className="text-sm font-bold text-foreground">
                {isAr
                  ? `يوجد ${ambiguousCount} عمليات خارجية غير محسومة (AMBIGUOUS)`
                  : `${ambiguousCount} ambiguous external effects require manual reconciliation`}
              </p>
              <p className="text-xs text-muted-foreground">
                {isAr
                  ? "انقطعت الاستجابة أثناء الاتصال بالبوابة الخارجية. يرجى مراجعة البوابة وتأكيد التسوية الحتمية."
                  : "External gateway connection timed out. Verify remote provider status and reconcile state."}
              </p>
            </div>
          </div>
          <Button
            size="sm"
            variant="outline"
            className="text-xs font-semibold"
            onClick={() => setFilter("AMBIGUOUS")}
          >
            {isAr ? "عرض الغامضة" : "Filter Ambiguous"}
          </Button>
        </div>
      )}

      {/* Filter Tabs */}
      <div className="flex flex-wrap items-center gap-2 border-b border-border pb-3">
        {(["ALL", "AMBIGUOUS", "COMPLETED", "FAILED", "PENDING"] as FilterStatus[]).map(
          (tab) => {
            const labels: Record<FilterStatus, string> = {
              ALL: isAr ? "الكل" : "All",
              AMBIGUOUS: isAr ? "غير محسومة (Ambiguous)" : "Ambiguous",
              COMPLETED: isAr ? "مكتملة (Completed)" : "Completed",
              FAILED: isAr ? "فاشلة (Failed)" : "Failed",
              PENDING: isAr ? "معلقة (Pending)" : "Pending",
            };
            const active = filter === tab;
            return (
              <button
                key={tab}
                type="button"
                onClick={() => setFilter(tab)}
                data-testid={`filter-effect-${tab.toLowerCase()}`}
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
          message={error instanceof Error ? error.message : "Failed to load effects"}
          onRetry={() => refetch()}
        />
      )}

      {!isLoading && (!error || error.message?.includes("404") || error.message?.toLowerCase().includes("not found")) && (!data?.items || data.items.length === 0) && (
        <EmptyState
          icon={<Layers aria-hidden="true" />}
          title={isAr ? "لا توجد تأثيرات مسجلة" : "No effects recorded"}
          description={
            isAr
              ? "عمليات الدفع والتكاملات الخارجية ورسائل الواتساب يتم تقييدها هنا بصورة غير قابلة للتكرار."
              : "External calls, payment intents, and external messages are tracked here with strict idempotency."
          }
        />
      )}

      {!isLoading && !error && data?.items && data.items.length > 0 && (
        <div className="grid gap-4">
          {data.items.map((item: EffectItem) => {
            const isExpanded = expandedId === item.effect_id;
            const isAmbiguous = item.status === "AMBIGUOUS";

            return (
              <Card
                key={item.effect_id}
                data-testid={`effect-card-${item.effect_id}`}
                className={cn(
                  "transition-all duration-200 border-border/70",
                  isAmbiguous
                    ? "border-warning/60 bg-warning/[0.02]"
                    : "hover:border-primary/40"
                )}
              >
                <CardHeader className="pb-3">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-xs font-bold text-muted-foreground">
                          #{item.effect_id.slice(0, 8)}
                        </span>
                        <CardTitle className="text-base font-bold font-mono">
                          {item.operation}
                        </CardTitle>
                        <Badge variant={statusVariant(item.status)}>
                          {item.status}
                        </Badge>
                        {item.provider && (
                          <Badge variant="outline" className="font-mono text-[11px]">
                            {item.provider}
                          </Badge>
                        )}
                      </div>
                      <div className="flex items-center gap-3 text-xs text-muted-foreground">
                        <span>
                          {isAr ? "المحاولات:" : "Attempts:"}{" "}
                          <strong className="text-foreground">{item.attempts}</strong>
                        </span>
                        <span>•</span>
                        <span>{formatDateTime(item.created_at)}</span>
                      </div>
                    </div>

                    <div className="flex items-center gap-2">
                      {isAmbiguous && (
                        <Button
                          size="sm"
                          variant="default"
                          onClick={() => openReconciliation(item)}
                          className="gap-1.5 text-xs"
                          data-testid={`reconcile-btn-${item.effect_id}`}
                        >
                          <RefreshCw className="size-3.5" />
                          <span>{isAr ? "تسوية الحالة (Reconcile)" : "Reconcile"}</span>
                        </Button>
                      )}

                      <Button
                        variant="ghost"
                        size="icon-sm"
                        onClick={() =>
                          setExpandedId(isExpanded ? null : item.effect_id)
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
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 rounded-lg bg-muted/40 p-3 text-xs">
                    <div>
                      <span className="text-muted-foreground block mb-0.5">
                        {isAr ? "مفتاح عدم التكرار (Idempotency Key):" : "Idempotency Key:"}
                      </span>
                      <div
                        dir="ltr"
                        className="flex items-center justify-between font-mono text-[11px] text-foreground bg-card/70 px-2 py-1 rounded border border-border/50"
                      >
                        <span className="truncate">{item.idempotency_key}</span>
                        <button
                          type="button"
                          onClick={() =>
                            navigator.clipboard.writeText(item.idempotency_key)
                          }
                          className="p-1 hover:text-primary"
                          title="Copy Key"
                        >
                          <Copy className="size-3" />
                        </button>
                      </div>
                    </div>
                    <div>
                      <span className="text-muted-foreground block mb-0.5">
                        {isAr ? "المرجع الخارجي المزود:" : "Provider Reference:"}
                      </span>
                      <span className="font-mono text-xs block py-1">
                        {item.provider_reference || "—"}
                      </span>
                    </div>
                  </div>

                  {/* Expanded Technical View */}
                  {isExpanded && (
                    <div className="mt-3 space-y-3 rounded-lg border border-border bg-card p-3 text-xs">
                      <div>
                        <span className="font-semibold block mb-1">
                          {isAr ? "معاملات الطلب (Arguments):" : "Operation Arguments:"}
                        </span>
                        <pre
                          dir="ltr"
                          className="max-h-40 overflow-auto rounded bg-muted/70 p-2 font-mono text-[11px] leading-relaxed"
                        >
                          {JSON.stringify(item.arguments, null, 2)}
                        </pre>
                      </div>

                      {item.result && (
                        <div>
                          <span className="font-semibold block mb-1 text-success">
                            {isAr ? "النتيجة المقيدة (Result Payload):" : "Result Payload:"}
                          </span>
                          <pre
                            dir="ltr"
                            className="max-h-40 overflow-auto rounded bg-muted/70 p-2 font-mono text-[11px] leading-relaxed"
                          >
                            {JSON.stringify(item.result, null, 2)}
                          </pre>
                        </div>
                      )}

                      {item.error_details && (
                        <div>
                          <span className="font-semibold block mb-1 text-danger">
                            {isAr ? "تفاصيل الخطأ أو الاستثناء:" : "Error Details:"}
                          </span>
                          <pre
                            dir="ltr"
                            className="max-h-40 overflow-auto rounded bg-danger/10 text-danger p-2 font-mono text-[11px] leading-relaxed"
                          >
                            {JSON.stringify(item.error_details, null, 2)}
                          </pre>
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

      {/* Manual Reconciliation Modal */}
      <Dialog
        open={reconcileModal.open}
        onOpenChange={(open) =>
          setReconcileModal((prev) => ({ ...prev, open }))
        }
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>
              {isAr ? "تسوية التأثير الخارجي يدويًا" : "Manual Effect Reconciliation"}
            </DialogTitle>
          </DialogHeader>

          <div className="space-y-4 py-2 text-sm">
            <p className="text-xs text-muted-foreground leading-relaxed">
              {isAr
                ? "حدد نتيجة العملية المؤكدة بعد مطابقة السجلات مع المزود الخارجي. هذا الإجراء سينهي حالة AMBIGUOUS بصورة حتمية."
                : "Choose the confirmed outcome after checking provider dashboard. Resolves the AMBIGUOUS state deterministically."}
            </p>

            <div className="space-y-2">
              <label className="text-xs font-semibold block">
                {isAr ? "الحالة النهائية المحققة:" : "Target State:"}
              </label>
              <div className="flex gap-3">
                <Button
                  type="button"
                  size="sm"
                  variant={reconcileModal.status === "COMPLETED" ? "default" : "outline"}
                  onClick={() =>
                    setReconcileModal((prev) => ({ ...prev, status: "COMPLETED" }))
                  }
                  className="flex-1 gap-1.5"
                >
                  <CheckCircle2 className="size-4" />
                  <span>{isAr ? "نجحت (COMPLETED)" : "COMPLETED"}</span>
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant={reconcileModal.status === "FAILED" ? "destructive" : "outline"}
                  onClick={() =>
                    setReconcileModal((prev) => ({ ...prev, status: "FAILED" }))
                  }
                  className="flex-1 gap-1.5"
                >
                  <XCircle className="size-4" />
                  <span>{isAr ? "فشلت (FAILED)" : "FAILED"}</span>
                </Button>
              </div>
            </div>

            <div className="space-y-2">
              <label className="text-xs font-semibold block">
                {isAr ? "مرجع العملية الخارجي (Provider Reference):" : "Provider Reference Code:"}
              </label>
              <input
                type="text"
                dir="ltr"
                value={reconcileModal.providerRef}
                onChange={(e) =>
                  setReconcileModal((prev) => ({
                    ...prev,
                    providerRef: e.target.value,
                  }))
                }
                placeholder="e.g. pay_29a8f092b1..."
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-xs font-mono focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              />
            </div>
          </div>

          <DialogFooter className="gap-2 sm:gap-0">
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                setReconcileModal((prev) => ({ ...prev, open: false }))
              }
            >
              {isAr ? "إلغاء" : "Cancel"}
            </Button>
            <Button
              variant="default"
              size="sm"
              onClick={handleReconcileSubmit}
              disabled={reconcileMutation.isPending}
              data-testid="submit-reconciliation"
            >
              {reconcileMutation.isPending
                ? isAr
                  ? "جاري الحفظ..."
                  : "Saving..."
                : isAr
                ? "تأكيد التسوية الحتمية"
                : "Confirm Reconciliation"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
