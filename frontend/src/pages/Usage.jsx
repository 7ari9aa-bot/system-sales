import React from "react";
import { Link } from "react-router-dom";
import { CreditCard, Sparkles } from "lucide-react";
import { PageHeader, SectionCard, Badge } from "@/components/dashboard/ui";
import { apiCached, peekCache } from "@/lib/api";
import { formatCurrency, formatDate } from "@/lib/regional";
import { useI18n, useT } from "@/lib/i18n";

export default function Usage() {
  const t = useT();
  const { lang } = useI18n();
  const isAr = lang === "ar";
  const [usage, setUsage] = React.useState(() => peekCache("/ai/usage/summary"));
  const [subscription, setSubscription] = React.useState(() => peekCache("/billing/subscription"));
  const [usageError, setUsageError] = React.useState("");
  const [subscriptionError, setSubscriptionError] = React.useState("");
  const [loading, setLoading] = React.useState(!usage || !subscription);
  const [attempt, setAttempt] = React.useState(0);

  React.useEffect(() => {
    let alive = true;
    setLoading(true);
    Promise.allSettled([
      apiCached("/ai/usage/summary"),
      apiCached("/billing/subscription"),
    ]).then(([usageResult, subscriptionResult]) => {
      if (!alive) return;
      if (usageResult.status === "fulfilled") {
        setUsage(usageResult.value);
        setUsageError("");
      }
      else setUsageError(usageResult.reason?.message || (isAr ? "تعذر تحميل بيانات الاستهلاك" : "Could not load usage data"));
      if (subscriptionResult.status === "fulfilled") {
        setSubscription(subscriptionResult.value);
        setSubscriptionError("");
      }
      else setSubscriptionError(subscriptionResult.reason?.message || (isAr ? "تعذر تحميل الاشتراك" : "Could not load subscription"));
    }).finally(() => alive && setLoading(false));
    return () => { alive = false; };
  }, [isAr, attempt]);

  const totals = usage?.totals;
  const tokens = totals ? (Number(totals.tokens_in) || 0) + (Number(totals.tokens_out) || 0) : null;
  const days = Array.isArray(usage?.summary) ? usage.summary : [];
  const largestDay = Math.max(1, ...days.map((day) => Number(day.tokens_in || 0) + Number(day.tokens_out || 0)));

  return (
    <div className="space-y-5 animate-fade-in">
      <PageHeader
        title={isAr ? "الاستهلاك" : "Usage"}
        subtitle={isAr ? "ملخص استهلاك الذكاء الاصطناعي والاشتراك من بيانات الخادم." : "AI usage and subscription details from the server."}
        actions={
          <Link to="/settings/billing" className="inline-flex items-center gap-1.5 h-9 px-3.5 rounded-lg bg-primary text-primary-foreground text-[13px] font-medium hover:opacity-90 transition-opacity">
            <CreditCard className="h-4 w-4" /> {t("common.managePlan")}
          </Link>
        }
      />

      {(usageError || subscriptionError) && <div role="alert" className="flex items-center justify-between gap-3 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
        <span>{[usageError, subscriptionError].filter(Boolean).join(" · ")}</span>
        <button type="button" onClick={() => setAttempt((current) => current + 1)} disabled={loading} className="shrink-0 underline disabled:opacity-60">{t("common.retry", "Retry")}</button>
      </div>}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        <SectionCard title={isAr ? "الاشتراك الحالي" : "Current subscription"}>
          {subscriptionError && <div role="alert" className="text-[12px] text-destructive">{subscriptionError}</div>}
          <div className="rounded-xl bg-surface p-4">
            <div className="flex items-center justify-between gap-3">
              <span className="text-[12.5px] text-muted-foreground">{isAr ? "الحالة" : "Status"}</span>
              <Badge tone={subscription?.status === "active" || subscription?.status === "trialing" ? "success" : "muted"}>
                {loading ? "…" : subscription?.status || (isAr ? "لا يوجد اشتراك" : "No subscription")}
              </Badge>
            </div>
            <div className="mt-4 border-t border-border pt-3">
              <div className="text-[12px] text-muted-foreground">{isAr ? "نهاية الفترة الحالية" : "Current period ends"}</div>
              <div className="mt-1 text-[14px] font-semibold tabular-nums">{subscription?.current_period_end ? formatDate(subscription.current_period_end) : "—"}</div>
            </div>
          </div>
          <p className="mt-3 text-[11.5px] leading-relaxed text-muted-foreground">
            {isAr ? "حدود الخطة والفواتير ووسيلة الدفع غير متاحة من الـAPI الحالي." : "Plan limits, invoices, and payment method are not exposed by the current API."}
          </p>
        </SectionCard>

        <SectionCard title={t("ai.usage.title")} className="lg:col-span-2">
          {usageError && <div role="alert" className="mb-3 text-[12px] text-destructive">{usageError}</div>}
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="flex items-center gap-3 rounded-xl border border-border p-4">
              <span className="h-10 w-10 rounded-lg bg-accent/10 text-accent grid place-items-center"><Sparkles className="h-5 w-5" /></span>
              <div><div className="text-[11.5px] text-muted-foreground">{t("ai.stat.tokens")}</div><div className="mt-1 text-[20px] font-semibold tabular-nums" dir="ltr">{loading ? "…" : tokens == null ? "—" : tokens.toLocaleString()}</div></div>
            </div>
            <div className="flex items-center gap-3 rounded-xl border border-border p-4">
              <span className="h-10 min-w-10 rounded-lg bg-warning/10 text-warning grid place-items-center px-1 text-[11px] font-semibold">{totals?.cost == null ? "—" : formatCurrency(Number(totals.cost), true, "USD")}</span>
              <div><div className="text-[11.5px] text-muted-foreground">{t("ai.usage.spend")}</div><div className="mt-1 text-[20px] font-semibold tabular-nums">{totals?.cost == null ? "—" : formatCurrency(Number(totals.cost), false, "USD")}</div></div>
            </div>
          </div>
          <div className="mt-4 border-t border-border pt-3 text-[11.5px] text-muted-foreground">
            {usage?.days ? (isAr ? `آخر ${usage.days} يومًا` : `Last ${usage.days} days`) : t("ai.usage.thisCycle")}
          </div>
        </SectionCard>
      </div>

      <SectionCard title={isAr ? "الاستهلاك اليومي" : "Daily usage"}>
        {usageError ? (
          <div className="py-5 text-center text-[12.5px] text-muted-foreground">{isAr ? "تعذر عرض سجل الأيام." : "Daily history is unavailable."}</div>
        ) : loading && days.length === 0 ? (
          <div className="py-5 text-center text-[12.5px] text-muted-foreground">{isAr ? "جارٍ تحميل الاستهلاك…" : "Loading usage…"}</div>
        ) : days.length === 0 ? (
          <div className="py-5 text-center text-[12.5px] text-muted-foreground">{isAr ? "لا توجد بيانات استهلاك لهذه الفترة." : "No usage data for this period."}</div>
        ) : (
          <div className="space-y-3">
            {days.map((day) => {
              const dayTokens = (Number(day.tokens_in) || 0) + (Number(day.tokens_out) || 0);
              return (
                <div key={day.date} className="grid grid-cols-[90px_1fr_auto] items-center gap-3">
                  <span className="text-[11.5px] text-muted-foreground tabular-nums">{formatDate(day.date, { month: "short", day: "numeric" })}</span>
                  <div className="h-2 overflow-hidden rounded-full bg-surface"><div className="h-full rounded-full bg-primary" style={{ width: `${Math.min(100, (dayTokens / largestDay) * 100)}%` }} /></div>
                  <span className="min-w-[92px] text-right text-[11.5px] tabular-nums">{dayTokens.toLocaleString()} · {formatCurrency(Number(day.cost || 0), true, "USD")}</span>
                </div>
              );
            })}
          </div>
        )}
      </SectionCard>
    </div>
  );
}
