import React from "react";
import { Boxes, PackageX, AlertTriangle } from "lucide-react";
import { SectionCard } from "@/components/dashboard/ui";
import { useT } from "@/lib/i18n";
import useSalesStats from "@/hooks/useSalesStats";

/** لمحة المخزون — بطاقة مدمجة تناسب عمود واحد. ثلاثة أرقام حقيقية
 *  من read model السيرفر: منتجات نشطة، مخزون منخفض، نفد المخزون. */
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
      <div className="space-y-2.5 mt-1">
        <div className="flex items-center justify-between rounded-xl border border-border bg-surface px-3.5 py-3">
          <div className="flex items-center gap-2.5 text-[13px] text-muted-foreground">
            <Boxes className="h-4 w-4 text-muted-foreground" />
            {t("inventory.active")}
          </div>
          <span className="font-display text-[18px] font-semibold tabular-nums" data-testid="inventory-active">
            {live ? (live.activeProducts ?? "—") : "…"}
          </span>
        </div>
        <div className="flex items-center justify-between rounded-xl border border-border bg-surface px-3.5 py-3">
          <div className="flex items-center gap-2.5 text-[13px] text-muted-foreground">
            <AlertTriangle className="h-4 w-4 text-warning" />
            {t("inventory.low")}
          </div>
          <span className="font-display text-[18px] font-semibold tabular-nums" data-testid="inventory-low">
            {live ? (live.lowStock ?? "—") : "…"}
          </span>
        </div>
        <div className="flex items-center justify-between rounded-xl border border-border bg-surface px-3.5 py-3">
          <div className="flex items-center gap-2.5 text-[13px] text-muted-foreground">
            <PackageX className="h-4 w-4 text-destructive" />
            {t("inventory.out")}
          </div>
          <span className="font-display text-[18px] font-semibold tabular-nums" data-testid="inventory-out">
            {live ? (live.outOfStock ?? "—") : "…"}
          </span>
        </div>
      </div>
    </SectionCard>
  );
}
