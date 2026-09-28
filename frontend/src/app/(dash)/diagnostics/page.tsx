"use client";

/**
 * مركز التشخيص والفحص الشامل — Anti-Silent-Failures (§103)
 *
 * Full system diagnostics dashboard. Runs a deep sweep across every subsystem
 * (DB, Redis, Outbox, DLQ, AI, Channels, Data Integrity, Environment) and
 * surfaces the exact root cause and remediation for every issue found.
 *
 * One-click auto-remediation reclaims stranded outbox events and fixes
 * recoverable issues without manual intervention.
 */

import * as React from "react";
import {
  Activity,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  RefreshCw,
  Wrench,
  Clock,
  Zap,
  Shield,
} from "lucide-react";
import {
  useSystemDiagnostics,
  useAutoRemediate,
  type DiagnosticItem,
  type HealthStatus,
} from "@/lib/queries";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/* ------------------------------------------------------------------ helpers */

const STATUS_CONFIG: Record<
  HealthStatus,
  {
    label: string;
    icon: React.ReactNode;
    dot: string;
    badge: "success" | "warning" | "danger";
    bg: string;
    border: string;
  }
> = {
  healthy: {
    label: "سليم",
    icon: <CheckCircle2 className="size-5 text-success" />,
    dot: "bg-success",
    badge: "success",
    bg: "bg-success/5",
    border: "border-success/20",
  },
  degraded: {
    label: "متراجع",
    icon: <AlertTriangle className="size-5 text-warning" />,
    dot: "bg-warning",
    badge: "warning",
    bg: "bg-warning/5",
    border: "border-warning/20",
  },
  down: {
    label: "معطّل",
    icon: <XCircle className="size-5 text-danger" />,
    dot: "bg-danger",
    badge: "danger",
    bg: "bg-danger/5",
    border: "border-danger/20",
  },
};

const CATEGORY_ICON: Record<string, React.ReactNode> = {
  infrastructure: <Zap className="size-4 text-primary" />,
  messaging: <Activity className="size-4 text-primary" />,
  ai: <Shield className="size-4 text-primary" />,
  data_integrity: <Shield className="size-4 text-primary" />,
  environment: <Shield className="size-4 text-primary" />,
};

function formatLatency(ms: number | null): string {
  if (ms === null || ms === undefined) return "—";
  if (ms < 1) return "<1ms";
  return `${ms.toFixed(0)}ms`;
}

function formatTimestamp(iso: string | undefined | null): string {
  if (!iso) return "الآن";
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return "الآن";
    return d.toLocaleString("ar-EG", {
      dateStyle: "medium",
      timeStyle: "medium",
    });
  } catch {
    return "الآن";
  }
}

/* ------------------------------------------------------------------ components */

function DiagnosticCard({ item }: { item: DiagnosticItem }) {
  const cfg = STATUS_CONFIG[item.status] ?? STATUS_CONFIG.healthy;

  return (
    <Card
      className={cn(
        "transition-all duration-200 hover:shadow-md",
        cfg.bg,
        "border",
        cfg.border,
      )}
    >
      <CardHeader className="flex flex-row items-start justify-between gap-3 pb-2">
        <div className="flex items-center gap-3 min-w-0">
          {cfg.icon}
          <div className="min-w-0">
            <CardTitle className="text-sm font-bold leading-tight truncate">
              {item.name_ar}
            </CardTitle>
            <p className="text-[11px] text-muted-foreground mt-0.5">
              {item.name_en}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {item.latency_ms !== null && (
            <span className="flex items-center gap-1 text-[11px] text-muted-foreground">
              <Clock className="size-3" />
              {formatLatency(item.latency_ms)}
            </span>
          )}
          <Badge variant={cfg.badge}>{cfg.label}</Badge>
        </div>
      </CardHeader>

      <CardContent className="pt-0 space-y-2">
        {item.error && (
          <div className="rounded-lg bg-danger/10 border border-danger/20 p-2.5">
            <p className="text-[12px] font-bold text-danger mb-1">الخطأ:</p>
            <p className="text-[12px] text-danger/90 leading-relaxed font-mono break-all">
              {item.error}
            </p>
          </div>
        )}

        {item.root_cause && (
          <div className="rounded-lg bg-warning/10 border border-warning/20 p-2.5">
            <p className="text-[12px] font-bold text-warning mb-1">السبب الجذري:</p>
            <p className="text-[12px] text-foreground/80 leading-relaxed">
              {item.root_cause}
            </p>
          </div>
        )}

        {item.remediation && (
          <div className="rounded-lg bg-primary/5 border border-primary/20 p-2.5">
            <p className="text-[12px] font-bold text-primary mb-1">الإصلاح:</p>
            <p className="text-[12px] text-foreground/80 leading-relaxed">
              {item.remediation}
            </p>
          </div>
        )}

        {Object.keys(item.metrics).length > 0 && (
          <div className="flex flex-wrap gap-2 pt-1">
            {Object.entries(item.metrics).map(([key, value]) => (
              <span
                key={key}
                className="inline-flex items-center gap-1 rounded-md bg-muted px-2 py-0.5 text-[11px] font-medium"
              >
                <span className="text-muted-foreground">{key}:</span>
                <span className="font-bold">{String(value)}</span>
              </span>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function SummaryStats({
  total,
  passed,
  issues,
  status,
}: {
  total: number;
  passed: number;
  issues: number;
  status: HealthStatus;
}) {
  const cfg = STATUS_CONFIG[status] ?? STATUS_CONFIG.healthy;
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
      <Card className="border-border/50">
        <CardContent className="flex flex-col items-center justify-center py-4 px-3">
          <span className="text-2xl font-bold">{total}</span>
          <span className="text-[11px] text-muted-foreground mt-0.5">إجمالي الفحوصات</span>
        </CardContent>
      </Card>
      <Card className="border-success/30 bg-success/5">
        <CardContent className="flex flex-col items-center justify-center py-4 px-3">
          <span className="text-2xl font-bold text-success">{passed}</span>
          <span className="text-[11px] text-muted-foreground mt-0.5">ناجحة</span>
        </CardContent>
      </Card>
      <Card className={cn("border-border/50", issues > 0 ? "border-danger/30 bg-danger/5" : "")}>
        <CardContent className="flex flex-col items-center justify-center py-4 px-3">
          <span className={cn("text-2xl font-bold", issues > 0 ? "text-danger" : "text-foreground")}>
            {issues}
          </span>
          <span className="text-[11px] text-muted-foreground mt-0.5">مشاكل</span>
        </CardContent>
      </Card>
      <Card className={cn(cfg.bg, cfg.border, "border")}>
        <CardContent className="flex flex-col items-center justify-center py-4 px-3">
          {cfg.icon}
          <span className="text-[12px] font-bold mt-1">{cfg.label}</span>
          <span className="text-[11px] text-muted-foreground">الحالة العامة</span>
        </CardContent>
      </Card>
    </div>
  );
}

function LoadingSkeleton() {
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-24 rounded-xl" />
        ))}
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-40 rounded-xl" />
        ))}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ page */

export default function DiagnosticsPage() {
  const { data, isLoading, isError, error, refetch, isFetching } = useSystemDiagnostics();
  const remediate = useAutoRemediate();

  // Group checks by category for organized display
  const groupedChecks = React.useMemo(() => {
    if (!data?.checks) return {};
    const groups: Record<string, DiagnosticItem[]> = {};
    for (const check of data.checks) {
      const cat = check.category || "other";
      (groups[cat] ??= []).push(check);
    }
    return groups;
  }, [data?.checks]);

  const categoryLabel: Record<string, string> = {
    infrastructure: "البنية التحتية",
    messaging: "الرسائل والقنوات",
    ai: "الذكاء الاصطناعي",
    data_integrity: "سلامة البيانات",
    environment: "البيئة والإعدادات",
  };

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-4 md:p-6">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <div className="flex size-10 items-center justify-center rounded-xl bg-primary/10">
            <Activity className="size-5 text-primary" />
          </div>
          <div>
            <h1 className="text-lg font-bold">مركز التشخيص والفحص الشامل</h1>
            <p className="text-[13px] text-muted-foreground">
              فحص شامل لجميع أنظمة المنصة مع تحديد الأسباب الجذرية للمشاكل
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => refetch()}
            disabled={isFetching}
            className="gap-1.5"
            data-testid="diagnostics-refresh-btn"
          >
            <RefreshCw className={cn("size-3.5", isFetching && "animate-spin")} />
            إعادة الفحص
          </Button>
          <Button
            size="sm"
            onClick={() => remediate.mutate()}
            disabled={remediate.isPending || isLoading}
            className="gap-1.5"
            data-testid="diagnostics-remediate-btn"
          >
            <Wrench className={cn("size-3.5", remediate.isPending && "animate-spin")} />
            إصلاح تلقائي
          </Button>
        </div>
      </div>

      {/* Content */}
      {isLoading ? (
        <LoadingSkeleton />
      ) : isError ? (
        <Card className="border-danger/30 bg-danger/5">
          <CardContent className="flex flex-col items-center justify-center py-12 text-center">
            <XCircle className="size-10 text-danger mb-3" />
            <p className="text-sm font-bold text-danger mb-1">
              فشل تحميل بيانات التشخيص
            </p>
            <p className="text-[12px] text-muted-foreground mb-4 max-w-md">
              {error instanceof Error ? error.message : "خطأ غير متوقع — تأكد من اتصال الخادم"}
            </p>
            <Button variant="outline" size="sm" onClick={() => refetch()}>
              إعادة المحاولة
            </Button>
          </CardContent>
        </Card>
      ) : data ? (
        <>
          {/* Timestamp */}
          <p className="text-[11px] text-muted-foreground text-start">
            آخر فحص: {formatTimestamp(data.timestamp)}
          </p>

          {/* Summary */}
          <SummaryStats
            total={data.total_checks}
            passed={data.passed_checks}
            issues={data.issues_count}
            status={data.overall_status}
          />

          {/* Summary message */}
          <Card className="border-border/50">
            <CardContent className="py-3 px-4">
              <p className="text-sm font-medium leading-relaxed">{data.summary_ar}</p>
              <p className="text-[12px] text-muted-foreground mt-0.5">{data.summary_en}</p>
            </CardContent>
          </Card>

          {/* Grouped checks */}
          {Object.entries(groupedChecks).map(([category, checks]) => (
            <div key={category} className="space-y-3">
              <div className="flex items-center gap-2">
                {CATEGORY_ICON[category] ?? <Activity className="size-4 text-primary" />}
                <h2 className="text-sm font-bold">
                  {categoryLabel[category] ?? category}
                </h2>
                <span className="text-[11px] text-muted-foreground">
                  ({checks.length} فحص)
                </span>
                {checks.some((c) => c.status !== "healthy") && (
                  <Badge variant="danger" className="text-[10px]">
                    {checks.filter((c) => c.status !== "healthy").length} مشكلة
                  </Badge>
                )}
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                {checks.map((item) => (
                  <DiagnosticCard key={item.id} item={item} />
                ))}
              </div>
            </div>
          ))}

          {/* Auto-remediation result */}
          {remediate.data && (
            <Card className="border-success/30 bg-success/5">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-2">
                  <CheckCircle2 className="size-4 text-success" />
                  نتيجة الإصلاح التلقائي
                </CardTitle>
              </CardHeader>
              <CardContent className="pt-0 space-y-2">
                <p className="text-[13px]">{remediate.data.message_ar}</p>
                {Array.isArray(remediate.data.actions_taken) && remediate.data.actions_taken.length > 0 && (
                  <ul className="space-y-1">
                    {remediate.data.actions_taken.map((action, i) => (
                      <li key={i} className="flex items-start gap-2 text-[12px]">
                        <CheckCircle2 className="size-3 mt-0.5 text-success shrink-0" />
                        <span>{action}</span>
                      </li>
                    ))}
                  </ul>
                )}
                {remediate.data.reclaimed_outbox_events > 0 && (
                  <p className="text-[12px] font-bold text-success">
                    تم استعادة {remediate.data.reclaimed_outbox_events} حدث من الـ Outbox
                  </p>
                )}
              </CardContent>
            </Card>
          )}
        </>
      ) : null}
    </div>
  );
}
