"use client";

/**
 * HealthIndicator (§103) — the top-bar badge for `GET /platform/health`.
 *
 * Contract with the backend (`build_health_response`):
 *   { status: "healthy" | "degraded" | "down",
 *     subsystems: [{ name, status, detail?, integrations? }] }
 * "Worst status wins" server-side, so the envelope status is authoritative and
 * the per-subsystem rows only explain *which* thing is unwell.
 *
 * A failed request must never crash the shell: with no data the indicator reads
 * as "unknown" (a muted dot), never as "healthy" or as a broken widget.
 */

import Link from "next/link";
import { AlertTriangle, Activity } from "lucide-react";
import { usePlatformHealth, type HealthStatus, type HealthSubsystem } from "@/lib/queries";
import { t } from "@/lib/t";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

type DisplayStatus = HealthStatus | "unknown";

const DOT_CLASS: Record<DisplayStatus, string> = {
  healthy: "bg-success",
  degraded: "bg-warning",
  down: "bg-danger",
  unknown: "bg-muted-foreground/40",
};

const TEXT_CLASS: Record<DisplayStatus, string> = {
  healthy: "text-success",
  degraded: "text-warning",
  down: "text-danger",
  unknown: "text-muted-foreground",
};

const BADGE_VARIANT: Record<DisplayStatus, "success" | "warning" | "danger" | "default"> = {
  healthy: "success",
  degraded: "warning",
  down: "danger",
  unknown: "default",
};

/** The subsystem `name` values the backend emits (`subsystem(...)` calls). */
function subsystemLabel(name: string): string {
  switch (name) {
    case "database":
      return t.healthDatabase;
    case "redis":
      return t.healthRedis;
    case "outbox":
      return t.healthOutbox;
    case "dlq":
      return t.healthDlq;
    case "integrations":
      return t.healthIntegrations;
    default:
      return name;
  }
}

function subsystemStatusLabel(status: DisplayStatus): string {
  switch (status) {
    case "healthy":
      return t.healthOk;
    case "degraded":
      return t.healthDegraded;
    case "down":
      return t.healthDown;
    default:
      return t.healthUnknown;
  }
}

function overallLabel(status: DisplayStatus): string {
  switch (status) {
    case "healthy":
      return t.healthHealthy;
    case "degraded":
      return t.healthDegraded;
    case "down":
      return t.healthDown;
    default:
      return t.healthUnknown;
  }
}

function toDisplay(status: HealthStatus | undefined): DisplayStatus {
  return status === "healthy" || status === "degraded" || status === "down" ? status : "unknown";
}

export function HealthIndicator() {
  const { data } = usePlatformHealth();

  // No data covers both "still loading" and "the request failed" — both read
  // as unknown rather than as a false alarm.
  const status: DisplayStatus = toDisplay(data?.status);
  const subsystems: HealthSubsystem[] = data?.subsystems ?? [];
  const issueCount = subsystems.filter((row) => row.status !== "healthy").length;
  const showCount = status !== "unknown" && status !== "healthy" && issueCount > 0;

  const label =
    status === "unknown"
      ? `${t.healthLabel}: ${t.healthUnknown}`
      : status === "healthy"
        ? `${t.healthLabel}: ${t.healthHealthy}`
        : `${t.healthLabel}: ${overallLabel(status)} — ${t.healthIssues(issueCount)}`;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          className="gap-1.5 px-2"
          aria-label={label}
          data-testid="health-indicator"
        >
          <span className={cn("size-2.5 shrink-0 rounded-full", DOT_CLASS[status])} aria-hidden="true" />
          {showCount && (
            <span className={cn("flex items-center gap-0.5 text-[12px] font-bold", TEXT_CLASS[status])} aria-hidden="true">
              <AlertTriangle className="size-3" />
              {issueCount}
            </span>
          )}
        </Button>
      </DropdownMenuTrigger>

      <DropdownMenuContent align="end" className="w-80" aria-label={t.healthLabel}>
        <DropdownMenuLabel className="flex items-center justify-between gap-2">
          <span>{t.healthLabel}</span>
          <Badge variant={BADGE_VARIANT[status]}>{overallLabel(status)}</Badge>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />

        {status === "unknown" ? (
          <p className="px-3 py-4 text-center text-[13px] text-muted-foreground">
            {t.healthUnknown}
          </p>
        ) : (
          <ul className="py-0.5 space-y-1">
            <li className="px-2.5 pb-1 pt-1.5 text-[11px] font-bold uppercase tracking-wide text-muted-foreground/80">
              {t.healthSubsystems}
            </li>
            {subsystems.map((row) => {
              const rowStatus = toDisplay(row.status);
              return (
                <li
                  key={row.name}
                  className="flex flex-col gap-1 rounded-lg px-2.5 py-1.5 text-[13px] hover:bg-muted/40 transition-colors"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="flex min-w-0 items-center gap-2">
                      <span
                        className={cn("size-2 shrink-0 rounded-full", DOT_CLASS[rowStatus])}
                        aria-hidden="true"
                      />
                      <span className="truncate font-medium">{subsystemLabel(row.name)}</span>
                    </span>
                    <Badge variant={BADGE_VARIANT[rowStatus]}>{subsystemStatusLabel(rowStatus)}</Badge>
                  </div>
                  {row.detail && (
                    <p
                      className={cn(
                        "text-[11px] leading-snug ps-4",
                        rowStatus === "healthy" ? "text-muted-foreground" : "text-danger font-medium",
                      )}
                    >
                      {row.detail}
                    </p>
                  )}
                </li>
              );
            })}
          </ul>
        )}
        <DropdownMenuSeparator />
        <div className="p-1">
          <Link
            href="/diagnostics"
            data-testid="health-open-diagnostics"
            className="flex items-center justify-center gap-2 w-full rounded-md bg-muted/60 px-3 py-2 text-xs font-semibold text-foreground hover:bg-muted transition-colors text-center"
          >
            <Activity className="size-3.5 text-primary" />
            <span>مركز التشخيص والفحص الشامل</span>
          </Link>
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
