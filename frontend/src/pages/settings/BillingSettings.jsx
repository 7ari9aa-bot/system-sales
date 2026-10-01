import React from "react";
import { useT, useI18n } from "@/lib/i18n";
import { apiCached, peekCache } from "@/lib/api";
import { formatCurrency, formatDate } from "@/lib/regional";
import SettingsShell, { SettingCard, SettingRow } from "@/components/settings/SettingsShell";
import { Sparkles } from "lucide-react";

export default function BillingSettings() {
  const t = useT();
  const { lang } = useI18n();
  const isAr = lang === "ar";
  const [subscription, setSubscription] = React.useState(() => peekCache("/billing/subscription"));
  const [usage, setUsage] = React.useState(() => peekCache("/ai/usage/summary"));
  const [loading, setLoading] = React.useState(!subscription || !usage);
  const [subscriptionError, setSubscriptionError] = React.useState("");
  const [usageError, setUsageError] = React.useState("");
  const [attempt, setAttempt] = React.useState(0);

  React.useEffect(() => {
    let alive = true;
    setLoading(true);
    Promise.allSettled([
      apiCached("/billing/subscription"),
      apiCached("/ai/usage/summary"),
    ])
      .then(([subscriptionResult, usageResult]) => {
        if (!alive) return;
        if (subscriptionResult.status === "fulfilled") {
          setSubscription(subscriptionResult.value);
          setSubscriptionError("");
        } else setSubscriptionError(subscriptionResult.reason?.message || (isAr ? "تعذر تحميل الاشتراك" : "Could not load subscription"));
        if (usageResult.status === "fulfilled") {
          setUsage(usageResult.value);
          setUsageError("");
        } else setUsageError(usageResult.reason?.message || (isAr ? "تعذر تحميل بيانات الاستخدام" : "Could not load usage data"));
      })
      .finally(() => alive && setLoading(false));
    return () => { alive = false; };
  }, [isAr, attempt]);

  const totals = usage?.totals;
  const tokenCount = totals ? (Number(totals.tokens_in) || 0) + (Number(totals.tokens_out) || 0) : null;
  const endDate = subscription?.current_period_end ? formatDate(subscription.current_period_end) : null;

  return (
    <SettingsShell title={t("settings.nav.billing")} subtitle={t("settings.billing.desc")}>
      {(subscriptionError || usageError) && <div role="alert" className="mb-4 flex items-center justify-between gap-3 rounded-lg border border-destructive/20 bg-destructive/10 px-3 py-2 text-[12px] text-destructive">
        <span>{[subscriptionError, usageError].filter(Boolean).join(" · ")}</span>
        <button type="button" onClick={() => setAttempt((current) => current + 1)} disabled={loading} className="shrink-0 underline disabled:opacity-60">{t("common.retry", "Retry")}</button>
      </div>}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <SettingCard title={isAr ? "الاشتراك" : "Subscription"}>
          <div className="pt-2">
            <SettingRow label={isAr ? "الحالة" : "Status"}>
              <span className="text-[13px] font-medium capitalize">{loading ? "…" : subscription?.status || (isAr ? "لا يوجد اشتراك" : "No subscription")}</span>
            </SettingRow>
            <SettingRow label={subscription?.status === "trialing" ? t("billing.endDate") : t("billing.renewDate")} last>
              <span className="text-[13px] font-medium tabular-nums">{loading ? "…" : endDate || "—"}</span>
            </SettingRow>
          </div>
          <p className="mt-2 border-t border-border pt-3 text-[11.5px] leading-relaxed text-muted-foreground">
            {isAr
              ? "تفاصيل الخطة والفواتير ووسائل الدفع غير متاحة من الـAPI الحالي. الحالة والتاريخ يعكسان بيانات الاشتراك الفعلية فقط."
              : "Plan details, invoices, and payment methods are not exposed by the current API. The status and date above are the available subscription data."}
          </p>
        </SettingCard>

        <SettingCard title={t("billing.tokenUsage")}>
          <div className="pt-2 space-y-4">
            <div className="flex items-center gap-3.5">
              <span className="h-11 w-11 rounded-xl bg-accent/10 text-accent grid place-items-center"><Sparkles className="h-5 w-5" /></span>
              <div className="min-w-0">
                <div className="font-display text-[20px] font-semibold tabular-nums leading-none" dir="ltr">{loading ? "…" : tokenCount == null ? "—" : tokenCount.toLocaleString()}</div>
                <div className="text-[12px] text-muted-foreground mt-1">{t("ai.stat.tokens")} · {usage?.days ? `${usage.days} ${isAr ? "يومًا" : "days"}` : t("ai.usage.thisCycle")}</div>
              </div>
            </div>
            <div className="flex items-center gap-3.5">
              <span className="h-11 min-w-11 px-2 rounded-xl bg-warning/15 text-warning grid place-items-center font-display text-[13px] font-bold">{totals?.cost == null ? "—" : formatCurrency(Number(totals.cost), false, "USD")}</span>
              <div className="min-w-0">
                <div className="font-display text-[15px] font-semibold leading-none">{t("ai.usage.spend")}</div>
                <div className="text-[12px] text-muted-foreground mt-1">{t("ai.usage.thisCycle")}</div>
              </div>
            </div>
            <p className="text-[11.5px] text-muted-foreground leading-relaxed pt-2 border-t border-border">
              {isAr ? "الاستهلاك والتكلفة إجماليات حقيقية للفترة التي يعيدها الخادم؛ لا توجد حدود استهلاك منشورة حاليًا." : "Usage and cost are actual totals for the period returned by the server; no usage limits are currently exposed."}
            </p>
          </div>
        </SettingCard>
      </div>
    </SettingsShell>
  );
}
