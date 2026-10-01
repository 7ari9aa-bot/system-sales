import React, { useState, useEffect } from "react";
import { Plus, TrendingUp } from "lucide-react";
import { Badge } from "@/components/dashboard/ui";
import { Skeleton } from "@/components/dashboard/ui";
import ChannelIcon from "@/components/dashboard/ChannelIcon";
import { apiCached, peekCache, api } from "@/lib/api";
import { formatCurrency } from "@/lib/regional";
import { useI18n, useT } from "@/lib/i18n";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

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
  const { lang } = useI18n();
  const isAr = lang === "ar";
  const [campaigns, setCampaigns] = useState(() => peekCache(LIST_PATH)?.items ?? null);
  const [summary, setSummary] = useState(() => peekCache(SUMMARY_PATH));
  const [summaryError, setSummaryError] = useState("");
  const [creating, setCreating] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [nextCursor, setNextCursor] = useState(() => peekCache(LIST_PATH)?.next_cursor ?? null);
  const [formOpen, setFormOpen] = useState(false);
  const [campaignName, setCampaignName] = useState("");
  const [provider, setProvider] = useState("manual");
  const [objective, setObjective] = useState("");
  const [budget, setBudget] = useState("");
  const [error, setError] = useState(null);

  useEffect(() => {
    let alive = true;
    apiCached(LIST_PATH)
      .then((d) => {
        if (!alive) return;
        setCampaigns(Array.isArray(d?.items) ? d.items : []);
        setNextCursor(d?.next_cursor ?? null);
      })
      .catch((error) => {
        if (!alive) return;
        setError(error?.message || (isAr ? "تعذر تحميل الحملات" : "Could not load campaigns"));
      });
    apiCached(SUMMARY_PATH)
      .then((d) => alive && setSummary(d))
      .catch((error) => alive && setSummaryError(error?.message || (isAr ? "تعذر تحميل الملخص" : "Could not load the summary")));
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

  async function retryCampaigns() {
    setError(null);
    try {
      const fresh = await apiCached(LIST_PATH, { ttlMs: 0 });
      setCampaigns(Array.isArray(fresh?.items) ? fresh.items : []);
      setNextCursor(fresh?.next_cursor ?? null);
    } catch (e) {
      setError(e?.message || (isAr ? "تعذر تحميل الحملات" : "Could not load campaigns"));
    }
  }

  async function createCampaign(event) {
    event.preventDefault();
    if (!campaignName.trim()) return;
    setCreating(true);
    setError(null);
    try {
      await api("/marketing/campaigns", {
        method: "POST",
        body: {
          name: campaignName.trim(),
          provider,
          objective: objective.trim() || null,
          budget: budget.trim() || null,
        },
      });
      setCampaignName("");
      setObjective("");
      setBudget("");
      setFormOpen(false);
      await retryCampaigns();
    } catch (e) {
      setError(e?.message || (isAr ? "تعذر إنشاء الحملة" : "Could not create the campaign"));
    } finally {
      setCreating(false);
    }
  }

  async function loadMore() {
    if (!nextCursor || loadingMore) return;
    setLoadingMore(true);
    setError(null);
    try {
      const page = await api(`${LIST_PATH}?limit=50&cursor=${encodeURIComponent(nextCursor)}`);
      setCampaigns((current) => [...(current || []), ...(Array.isArray(page?.items) ? page.items : [])]);
      setNextCursor(page?.next_cursor ?? null);
    } catch (e) {
      setError(e?.message || "—");
    } finally {
      setLoadingMore(false);
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
              <Stat label={t("marketing.stat.total")} value={`${items.length.toLocaleString()}${nextCursor ? "+" : ""}`} />
            </>
          )}
        </div>
        <Button type="button" onClick={() => setFormOpen((open) => !open)} disabled={creating} className="ml-4 shrink-0 gap-1.5">
          <Plus className="h-4 w-4" /> {t("marketing.new")}
        </Button>
      </div>

      {formOpen && (
        <form onSubmit={createCampaign} className="mb-4 grid gap-3 rounded-2xl border border-border bg-card p-4 sm:grid-cols-2 lg:grid-cols-4">
          <label className="grid gap-1.5 text-[12px] text-muted-foreground">{isAr ? "اسم الحملة" : "Campaign name"}<Input required maxLength={255} value={campaignName} onChange={(event) => setCampaignName(event.target.value)} /></label>
          <label className="grid gap-1.5 text-[12px] text-muted-foreground">
            {isAr ? "المصدر" : "Provider"}
            <select value={provider} onChange={(event) => setProvider(event.target.value)} className="h-9 rounded-md border border-input bg-background px-3 text-[13px] text-foreground">
              <option value="manual">{isAr ? "يدوي" : "Manual"}</option>
              <option value="whatsapp">WhatsApp</option>
              <option value="facebook">Facebook</option>
              <option value="messenger">Messenger</option>
              <option value="instagram">Instagram</option>
              <option value="telegram">Telegram</option>
              <option value="webchat">{isAr ? "محادثة الموقع" : "Website chat"}</option>
            </select>
          </label>
          <label className="grid gap-1.5 text-[12px] text-muted-foreground">{isAr ? "الهدف" : "Objective"}<Input maxLength={255} value={objective} onChange={(event) => setObjective(event.target.value)} /></label>
          <label className="grid gap-1.5 text-[12px] text-muted-foreground">{t("marketing.metric.budget")}<Input type="number" min="0" step="0.01" value={budget} onChange={(event) => setBudget(event.target.value)} /></label>
          <div className="flex gap-2 sm:col-span-2 lg:col-span-4">
            <Button type="submit" disabled={creating || !campaignName.trim()}>{creating ? "…" : (isAr ? "حفظ الحملة" : "Save campaign")}</Button>
            <Button type="button" variant="outline" onClick={() => setFormOpen(false)}>{isAr ? "إلغاء" : "Cancel"}</Button>
          </div>
        </form>
      )}

      {error && (
        <div className="mb-4 rounded-xl border border-destructive/30 bg-destructive/10 px-4 py-2.5 text-[13px] text-destructive">
          {error}
        </div>
      )}
      {summaryError && <div role="status" className="mb-4 text-[11.5px] text-muted-foreground">{summaryError}</div>}

      {campaigns == null && error ? (
        <div className="rounded-2xl border border-border bg-card py-8 text-center text-[13px] text-muted-foreground">
          <p>{isAr ? "تعذر تحميل الحملات." : "Campaigns could not be loaded."}</p>
          <Button type="button" variant="outline" onClick={() => void retryCampaigns()} className="mt-3">{isAr ? "إعادة المحاولة" : "Retry"}</Button>
        </div>
      ) : campaigns == null ? (
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
                      <div className="text-[12px] text-muted-foreground">{c.provider === "manual" ? (isAr ? "يدوي" : "Manual") : t(`channel.${c.provider}`)}</div>
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
      {nextCursor && <div className="mt-4 text-center"><Button type="button" variant="outline" disabled={loadingMore} onClick={loadMore}>{loadingMore ? "…" : (isAr ? "تحميل المزيد" : "Load more")}</Button></div>}
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
