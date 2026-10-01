import React, { useState, useEffect } from "react";
import { Plus, TrendingUp } from "lucide-react";
import { Badge } from "@/components/dashboard/ui";
import { Skeleton } from "@/components/dashboard/ui";
import ChannelIcon from "@/components/dashboard/ChannelIcon";
import { apiCached, peekCache, api } from "@/lib/api";
import { formatCurrency } from "@/lib/regional";
import { useT } from "@/lib/i18n";

const LIST_PATH = "/marketing/campaigns";
const SUMMARY_PATH = "/analytics/summary";

/** الحملات — بيانات حقيقية فقط:
 *  القائمة من GET /marketing/campaigns (الاسم والقناة والحالة والميزانية)،
 *  والإيراد المنسوب والتحويلات لكل حملة من GET /analytics/summary
 *  (إيراد منسوب لآخر لمسة — مش بالضرورة مُحصَّل، §167)، والـROAS
 *  من نفس النداء لما يكون محسوبًا على الخادم. مفيش معادلات مخترعة
 *  ولا leads/conversion وهمية — الحقول دي مش منشورة من الـbackend. */
export default function Campaigns() {
  const t = useT();
  const [campaigns, setCampaigns] = useState(() => peekCache(LIST_PATH)?.items ?? null);
  const [summary, setSummary] = useState(() => peekCache(SUMMARY_PATH));
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    let alive = true;
    apiCached(LIST_PATH)
      .then((d) => alive && setCampaigns(Array.isArray(d?.items) ? d.items : []))
      .catch(() => alive && setCampaigns((prev) => (Array.isArray(prev) ? prev : [])));
    apiCached(SUMMARY_PATH)
      .then((d) => alive && setSummary(d))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  const items = campaigns || [];
  const active = items.filter((c) => (c.status || "").toLowerCase() === "active");
  const byCampaign = new Map(
    (summary?.revenue_by_campaign ?? []).map((r) => [r.campaign_id, r]),
  );
  const roasByCampaign = new Map(
    (summary?.campaign_budget_roas ?? []).map((r) => [r.campaign_id, r]),
  );
  const top = (summary?.revenue_by_campaign ?? []).slice().sort((a, b) => Number(b.revenue) - Number(a.revenue))[0] ?? null;

  async function createCampaign() {
    const name = window.prompt(t("marketing.new"));
    if (!name) return;
    setCreating(true);
    setError(null);
    try {
      await api("/marketing/campaigns", {
        method: "POST",
        body: { name, provider: "whatsapp", objective: "sales" },
      });
      const fresh = await apiCached(LIST_PATH, { ttlMs: 0 });
      setCampaigns(Array.isArray(fresh?.items) ? fresh.items : []);
    } catch (e) {
      setError(e?.message || "—");
    } finally {
      setCreating(false);
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div className="grid grid-cols-2 lg:grid-cols-3 gap-3.5 flex-1">
          {campaigns == null ? (
            <>
              <Skeleton className="h-[72px]" />
              <Skeleton className="h-[72px]" />
              <Skeleton className="h-[72px]" />
            </>
          ) : (
            <>
              <Stat label={t("marketing.stat.active")} value={active.length} />
              <Stat
                label={t("marketing.topSource")}
                value={top ? `${top.campaign_name} · ${formatCurrency(Number(top.revenue), true)}` : "—"}
                icon={<TrendingUp className="h-4 w-4" />}
              />
              <Stat label={t("marketing.stat.total")} value={items.length} />
            </>
          )}
        </div>
        <button
          onClick={createCampaign}
          disabled={creating}
          className="h-9 px-3.5 rounded-lg bg-primary text-primary-foreground text-[13px] font-medium flex items-center gap-1.5 ml-4 shrink-0 disabled:opacity-60"
        >
          <Plus className="h-4 w-4" /> {t("marketing.new")}
        </button>
      </div>

      {error && (
        <div className="mb-4 rounded-xl border border-destructive/30 bg-destructive/10 px-4 py-2.5 text-[13px] text-destructive">
          {t("marketing.createError")}: {error}
        </div>
      )}

      {campaigns == null ? (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <Skeleton className="h-36" />
          <Skeleton className="h-36" />
        </div>
      ) : items.length === 0 ? (
        <div className="rounded-2xl bg-card border border-border py-14 text-center text-[13.5px] text-muted-foreground">
          {t("marketing.empty")}
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {items.map((c) => {
            const attributed = byCampaign.get(c.id);
            const roas = roasByCampaign.get(c.id)?.budget_roas;
            return (
              <div key={c.id} className="rounded-2xl bg-card border border-border p-5">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-center gap-3">
                    <ChannelIcon channel={c.provider} />
                    <div>
                      <div className="text-[14px] font-semibold">{c.name}</div>
                      <div className="text-[12px] text-muted-foreground">{t(`channel.${c.provider}`)}</div>
                    </div>
                  </div>
                  <Badge tone={(c.status || "").toLowerCase() === "active" ? "success" : "muted"}>
                    {c.status}
                  </Badge>
                </div>
                <div className="mt-4 grid grid-cols-3 gap-3 pt-4 border-t border-border">
                  <Metric label={t("marketing.metric.budget")} value={c.budget == null ? "—" : formatCurrency(Number(c.budget), true)} />
                  <Metric
                    label={t("marketing.metric.attributed")}
                    value={attributed ? formatCurrency(Number(attributed.revenue), true) : "—"}
                  />
                  <Metric label={t("marketing.metric.conversions")} value={attributed ? attributed.conversions : "—"} />
                </div>
                <div className="mt-3 text-[11px] text-muted-foreground">
                  {roas != null ? `ROAS: ${roas}×` : t("marketing.noRoas")}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, icon }) {
  return (
    <div className="rounded-2xl bg-card border border-border p-4">
      <div className="flex items-center gap-2 text-muted-foreground">{icon}<span className="text-[12.5px] font-medium">{label}</span></div>
      <div className="mt-2 font-display text-[22px] font-semibold tabular-nums truncate" title={typeof value === "string" ? value : undefined}>{value}</div>
    </div>
  );
}
function Metric({ label, value }) {
  return (
    <div>
      <div className="text-[11.5px] text-muted-foreground">{label}</div>
      <div className="text-[15px] font-semibold tabular-nums mt-0.5">{value}</div>
    </div>
  );
}
