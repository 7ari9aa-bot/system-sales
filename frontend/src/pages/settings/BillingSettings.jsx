import React from "react";
import { useT } from "@/lib/i18n";
import { useRealUsage } from "@/hooks/useRealData";
import { formatCurrency } from "@/lib/regional";
import SettingsShell, { SettingCard } from "@/components/settings/SettingsShell";
import { Sparkles } from "lucide-react";

/** الفوترة — الحقيقي المتاح فعلًا من الـbackend: استهلاك التوكنز
 *  والمصروف من /ai/usage/summary. مفيش خطط ولا فواتير ولا حدود —
 *  الـbackend مش بينشرهم، فمش بنعرض نسخ وهمية منهم. */
export default function BillingSettings() {
  const t = useT();
  const u = useRealUsage();

  return (
    <SettingsShell
      title={t("settings.nav.billing")}
      subtitle={t("settings.billing.desc")}
    >
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <SettingCard>
          <div className="flex items-center gap-2.5 pt-1">
            <span className="h-10 w-10 rounded-lg bg-primary/15 text-primary grid place-items-center font-display font-semibold text-[15px]">
              {t("billing.planBadge")}
            </span>
            <div>
              <div className="font-display text-[17px] font-semibold leading-none">{t("billing.earlyAccess")}</div>
              <div className="text-[12px] text-muted-foreground mt-1">
                {u.spend == null ? "—" : formatCurrency(u.spend)} {t("billing.spent")}
              </div>
            </div>
          </div>
          <div className="mt-4 pt-3 border-t border-border">
            <Row label={t("billing.renewDate")} value={t("billing.earlyAccessNote")} />
            <Row label={t("billing.invoices")} value={t("billing.earlyAccessNote")} />
          </div>
        </SettingCard>

        <SettingCard title={t("billing.tokenUsage")}>
          <div className="pt-2 space-y-4">
            <div className="flex items-center gap-3.5">
              <span className="h-11 w-11 rounded-xl bg-accent/10 text-accent grid place-items-center">
                <Sparkles className="h-5 w-5" />
              </span>
              <div className="min-w-0">
                <div className="font-display text-[20px] font-semibold tabular-nums leading-none" dir="ltr">
                  {u.aiUsage.used ? u.aiUsage.used.toLocaleString() : "—"}
                </div>
                <div className="text-[12px] text-muted-foreground mt-1">{t("ls.aiUsage")} · {t("ai.usage.thisCycle")}</div>
              </div>
            </div>
            <div className="flex items-center gap-3.5">
              <span className="h-11 w-11 rounded-xl bg-warning/15 text-warning grid place-items-center font-display text-[15px] font-bold">
                {u.spend == null ? "—" : formatCurrency(u.spend)}
              </span>
              <div className="min-w-0">
                <div className="font-display text-[15px] font-semibold leading-none">{t("home.aiSpend")}</div>
                <div className="text-[12px] text-muted-foreground mt-1">{t("ai.usage.thisCycle")}</div>
              </div>
            </div>
            <p className="text-[11.5px] text-muted-foreground leading-relaxed pt-2 border-t border-border">
              {t("billing.noPlansNote")}
            </p>
          </div>
        </SettingCard>
      </div>
    </SettingsShell>
  );
}

function Row({ label, value }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-[12.5px] text-muted-foreground">{label}</span>
      <span className="text-[13px] font-medium tabular-nums">{value}</span>
    </div>
  );
}
