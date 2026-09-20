"use client";

import * as React from "react";
import { RotateCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { t } from "@/lib/t";
import { cn } from "@/lib/utils";

/** عنوان صفحة موحّد — 24px للعنوان حسب سلم الخطوط (§91). */
function PageHeader({ title, description, actions, className }: { title: string; description?: string; actions?: React.ReactNode; className?: string }) {
  return (
    <div className={cn("mb-6 flex flex-wrap items-start justify-between gap-3", className)}>
      <div>
        <h1 className="text-2xl font-bold leading-tight tracking-tight">{title}</h1>
        {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

/** حالة فارغة مع الخطوة التالية (§107). */
function EmptyState({
  icon,
  title,
  description,
  action,
  className,
  testid,
}: {
  icon?: React.ReactNode;
  title: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
  /** Stable hook for E2E — the copy itself is translated, the testid is not. */
  testid?: string;
}) {
  return (
    <div
      data-testid={testid}
      className={cn("flex flex-col items-center justify-center gap-2 rounded-xl px-6 py-12 text-center", className)}
    >
      {icon && (
        <div className="mb-1 flex size-11 items-center justify-center rounded-full bg-muted text-muted-foreground [&_svg]:size-5">
          {icon}
        </div>
      )}
      <p className="text-[15px] font-bold">{title}</p>
      {description && <p className="max-w-sm text-[13px] text-muted-foreground">{description}</p>}
      {action && <div className="mt-3">{action}</div>}
    </div>
  );
}

/** حالة خطأ مع إعادة محاولة (§108). */
function ErrorState({ message, onRetry, className }: { message: string; onRetry?: () => void; className?: string }) {
  return (
    <div
      role="alert"
      data-testid="error-state"
      className={cn(
        "flex flex-col items-center justify-center gap-2 rounded-xl border border-danger/20 bg-danger-soft/50 px-6 py-10 text-center",
        className,
      )}
    >
      <p className="text-sm font-bold text-danger">{t.somethingWentWrong}</p>
      <p className="max-w-sm text-[13px] text-muted-foreground">{message}</p>
      {onRetry && (
        <Button variant="outline" size="sm" className="mt-2" onClick={onRetry}>
          <RotateCw aria-hidden="true" />
          {t.retry}
        </Button>
      )}
    </div>
  );
}

/** هيكل عظمي لجدول. */
function TableSkeleton({ rows = 5, cols = 4 }: { rows?: number; cols?: number }) {
  return (
    <div className="space-y-3 p-4" aria-busy="true" aria-label={t.loading}>
      <Skeleton className="h-9 w-64" />
      <div className="space-y-2">
        {Array.from({ length: rows }).map((_, r) => (
          <div key={r} className="flex gap-3">
            {Array.from({ length: cols }).map((_, c) => (
              <Skeleton key={c} className="h-8 flex-1" />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

export { PageHeader, EmptyState, ErrorState, TableSkeleton };
