import React from "react";
import { Boxes, Megaphone, PackageX, AlertTriangle } from "lucide-react";
import { SectionCard, Skeleton } from "@/components/dashboard/ui";
import { formatCurrency } from "@/lib/regional";
import { useT } from "@/lib/i18n";
import useSalesStats from "@/hooks/useSalesStats";
import { apiCached, peekCache } from "@/lib/api";

export function InventorySnapshot() {
  const t = useT();
  const live = useSalesStats("30d");
  return (
    <SectionCard
      title={
        <span className="flex items-center gap-2">
          <Boxes className="h-4 w-4 text-muted-foreground" />
          {t("home.inventorySnapshot.title")}
        </span>
      }
      action={t("common.review")}
      actionTo="/inventory"
    >
      <div className="grid grid-cols-3 gap-3 mt-2">
        <div className="rounded-xl border border-border bg-surface p-3">
          <div className="flex items-center gap-1.5 text-[11.5px] text-muted-foreground">
            <Boxes className="h-3.5 w-3.5 text-muted-foreground" />
            {t("inventory.active")}
          </div>
          <div className="mt-1 font-display text-[20px] font-semibold tabular-nums" data-testid="inventory-active">
            {live?.activeProducts ?? "—"}
          </div>
        </div>
        <div className="rounded-xl border border-border bg-surface p-3">
          <div className="flex items-center gap-1.5 text-[11.5px] text-muted-foreground">
            <AlertTriangle className="h-3.5 w-3.5 text-warning" />
            {t("inventory.low")}
          </div>
          <div className="mt-1 font-display text-[20px] font-semibold tabular-nums" data-testid="inventory-low">
            {live?.lowStock ?? "—"}
          </div>
        </div>
        <div className="rounded-xl border border-border bg-surface p-3">
          <div className="flex items-center gap-1.5 text-[11.5px] text-muted-foreground">
            <PackageX className="h-3.5 w-3.5 text-destructive" />
            {t("inventory.out")}
          </div>
          <div className="mt-1 font-display text-[20px] font-semibold tabular-nums" data-testid="inventory-out">
            {live?.outOfStock ?? "—"}
          </div>
        </div>
      </div>
    </SectionCard>
  );
}

export function MarketingSnapshot() {
  const t = useT();
  const [summary, setSummary] = React.useState(null);
  const [campaigns, setCampaigns] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    let alive = true;
    const cachedSummary = peekCache("/analytics/summary");
    if (cachedSummary) setSummary(cachedSummary);
    const cachedCampaigns = peekCache("/marketing/campaigns");
    if (cachedCampaigns) setCampaigns(Array.isArray(cachedCampaigns?.items) ? cachedCampaigns.items : []);
    Promise.allSettled([
      apiCached("/analytics/summary"),
      apiCached("/marketing/campaigns"),
    ]).then(([summaryResult, campaignResult]) => {
      if (!alive) return;
      const errors = [];
      if (summaryResult.status === "fulfilled") setSummary(summaryResult.value);
      else errors.push(summaryResult.reason?.message);
      if (campaignResult.status === "fulfilled") setCampaigns(Array.isArray(campaignResult.value?.items) ? campaignResult.value.items : []);
      else errors.push(campaignResult.reason?.message);
      setError(errors.filter(Boolean).join(" · "));
      setLoading(false);
    });
    return () => {
      alive = false;
    };
  }, []);

  const active = campaigns?.filter((x) => (x.status || "").toLowerCase() === "active").length ?? null;
  const top = summary?.revenue_by_source?.[0] ?? null;

  return (
    <SectionCard
      title={
        <span className="flex items-center gap-2">
          <Megaphone className="h-4 w-4 text-muted-foreground" />
          {t("home.marketingSnapshot.title")}
        </span>
      }
      action={t("common.review")}
      actionTo="/marketing"
    >
      {error && <div role="status" className="mb-2 text-[11px] text-muted-foreground">{error}</div>}
      <div className="flex items-baseline gap-2">
        <span className="font-display text-[28px] font-semibold tabular-nums leading-none">{loading ? "…" : (active ?? "—")}</span>
        <span className="text-[12.5px] text-muted-foreground">{t("marketing.activeCampaigns")}</span>
      </div>
      <div className="mt-4 space-y-2.5">
        <div className="flex items-center justify-between text-[13px]">
          <span className="text-muted-foreground">{t("marketing.topSource")}</span>
          <span className="flex items-center gap-2">
            <span className="font-medium">{top ? top.source : "—"}</span>
            <span className="font-semibold tabular-nums">{top ? formatCurrency(Number(top.revenue), true) : "—"}</span>
          </span>
        </div>
        <div className="flex items-center justify-between text-[13px]">
          <span className="text-muted-foreground">{t("marketing.conversions")}</span>
          <span className="font-semibold tabular-nums">{top ? top.conversions : "—"}</span>
        </div>
      </div>
      <div className="mt-3 pt-3 border-t border-border">
        <span className="text-[11px] text-muted-foreground">{t("analytics.attributedHint")}</span>
      </div>
    </SectionCard>
  );
}
