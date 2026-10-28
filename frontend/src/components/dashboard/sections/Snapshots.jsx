import React from "react";
import { Boxes, PackageX, AlertTriangle } from "lucide-react";
import { SectionCard } from "@/components/dashboard/ui";
import { useT } from "@/lib/i18n";
import useSalesStats from "@/hooks/useSalesStats";

export function InventorySnapshot() {
  const t = useT();
  const live = useSalesStats();
  return (
    <SectionCard
      title={
        <span className="flex items-center gap-2">
          <Boxes className="h-4 w-4 text-muted-foreground" />
          {t("home.inventorySnapshot.title")}
        </span>
      }
      action={t("common.review")}
      actionTo="/cashier/inventory"
      className="h-full"
    >
      {live?.dashboardError && (
        <div role="alert" className="mb-2 flex items-center justify-between gap-2 text-[11.5px] text-destructive">
          <span>{live.dashboardError}</span>
          <button type="button" onClick={live.retryDashboard} className="shrink-0 underline">
            {t("common.retry", "Retry")}
          </button>
        </div>
      )}
      <div className="grid grid-cols-3 gap-3 mt-2">
        <div className="rounded-xl border border-border bg-surface p-3">
          <div className="flex items-center gap-1.5 text-[11.5px] text-muted-foreground">
            <Boxes className="h-3.5 w-3.5 text-muted-foreground" />
            {t("inventory.active")}
          </div>
          <div className="mt-1 font-display text-[20px] font-semibold tabular-nums" data-testid="inventory-active">
            {live ? (live.activeProducts ?? "—") : "…"}
          </div>
        </div>
        <div className="rounded-xl border border-border bg-surface p-3">
          <div className="flex items-center gap-1.5 text-[11.5px] text-muted-foreground">
            <AlertTriangle className="h-3.5 w-3.5 text-warning" />
            {t("inventory.low")}
          </div>
          <div className="mt-1 font-display text-[20px] font-semibold tabular-nums" data-testid="inventory-low">
            {live ? (live.lowStock ?? "—") : "…"}
          </div>
        </div>
        <div className="rounded-xl border border-border bg-surface p-3">
          <div className="flex items-center gap-1.5 text-[11.5px] text-muted-foreground">
            <PackageX className="h-3.5 w-3.5 text-destructive" />
            {t("inventory.out")}
          </div>
          <div className="mt-1 font-display text-[20px] font-semibold tabular-nums" data-testid="inventory-out">
            {live ? (live.outOfStock ?? "—") : "…"}
          </div>
        </div>
      </div>
    </SectionCard>
  );
}
