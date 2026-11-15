import React from "react";
import { Link } from "react-router-dom";
import { Gauge } from "lucide-react";
import { useT, useI18n } from "@/lib/i18n";
import { apiCached, peekCache } from "@/lib/api";
import { formatDate } from "@/lib/regional";
import SettingsShell, { SettingCard, SettingRow } from "@/components/settings/SettingsShell";
import { Badge } from "@/components/dashboard/ui";

// Money only. This page and /settings/usage used to load the SAME two endpoints and read the same
// numbers back in different layouts, so a merchant could not tell which one was the real bill.
// Consumption (tokens, spend, per-day chart) lives on Usage and is linked to, not copied: one fact,
// one screen, and a link that says where it lives.
export default function BillingSettings() {
  const t = useT();
  const { lang } = useI18n();
  const isAr = lang === "ar";
  const [subscription, setSubscription] = React.useState(() => peekCache("/billing/subscription"));
  const [loading, setLoading] = React.useState(!subscription);
  const [error, setError] = React.useState("");
  const [attempt, setAttempt] = React.useState(0);

  React.useEffect(() => {
    let alive = true;
    setLoading(true);
    apiCached("/billing/subscription")
      .then((result) => {
        if (!alive) return;
        setSubscription(result);
        setError("");
      })
      .catch((err) => alive && setError(err?.message || (isAr ? "تعذر تحميل الاشتراك" : "Could not load subscription")))
      .finally(() => alive && setLoading(false));
    return () => { alive = false; };
  }, [isAr, attempt]);

  const endDate = subscription?.current_period_end ? formatDate(subscription.current_period_end) : null;
  const status = subscription?.status;

  return (
    <SettingsShell title={t("settings.nav.billing")} subtitle={t("settings.billing.desc")}>
      {error && <div role="alert" className="mb-4 flex items-center justify-between gap-3 rounded-lg border border-destructive/20 bg-destructive/10 px-3 py-2 text-[12px] text-destructive">
        <span>{error}</span>
        <button type="button" onClick={() => setAttempt((current) => current + 1)} disabled={loading} className="shrink-0 underline disabled:opacity-60">{t("common.retry", "Retry")}</button>
      </div>}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <SettingCard title={t("billing.plan")} desc={t("billing.plan.desc")}>
          <div className="pt-2">
            <SettingRow label={t("billing.status")}>
              <span data-testid="subscription-status">
                {loading
                  ? "…"
                  : status
                    ? <Badge tone={status === "active" ? "success" : status === "trialing" ? "warning" : "muted"}>{t(`billing.status.${status}`, status)}</Badge>
                    : <span className="text-[13px] font-medium text-muted-foreground">{t("billing.noSubscription")}</span>}
              </span>
            </SettingRow>
            <SettingRow label={status === "trialing" ? t("billing.endDate") : t("billing.renewDate")} last>
              <span className="text-[13px] font-medium tabular-nums">{loading ? "…" : endDate || "—"}</span>
            </SettingRow>
          </div>
          <p className="mt-2 border-t border-border pt-3 text-[11.5px] leading-relaxed text-muted-foreground">
            {t("billing.noInvoices")}
          </p>
        </SettingCard>

        <SettingCard title={t("billing.usage")} desc={t("billing.usage.desc")}>
          <div className="flex items-start gap-3 pt-2">
            <span className="h-10 w-10 shrink-0 rounded-lg bg-accent/10 text-accent grid place-items-center"><Gauge className="h-5 w-5" /></span>
            <div className="min-w-0 flex-1">
              <p className="text-[12px] leading-relaxed text-muted-foreground">{t("billing.usage.moved")}</p>
              <Link
                to="/settings/usage"
                className="mt-2 inline-flex h-8 items-center gap-1.5 rounded-lg border border-border px-3 text-[12.5px] font-medium hover:bg-surface"
                data-testid="billing-usage-link"
              >
                <Gauge className="h-3.5 w-3.5" /> {t("settings.nav.usage")}
              </Link>
            </div>
          </div>
        </SettingCard>
      </div>
    </SettingsShell>
  );
}
