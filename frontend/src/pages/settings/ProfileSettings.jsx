import React from "react";
import { Save } from "lucide-react";
import { useT, useI18n } from "@/lib/i18n";
import { useAuth } from "@/lib/AuthContext";
import { api, getTokens } from "@/lib/api";
import { useRegional, formatCurrency, formatDate } from "@/lib/regional";
import SettingsShell, { SettingCard, SettingRow } from "@/components/settings/SettingsShell";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Button } from "@/components/ui/button";

function activeTenantId(user) {
  try {
    const payload = getTokens()?.access_token?.split(".")[1];
    const normalized = payload?.replace(/-/g, "+").replace(/_/g, "/");
    const tokenTenant = normalized ? JSON.parse(window.atob(normalized.padEnd(Math.ceil(normalized.length / 4) * 4, "="))).tenant_id : null;
    return tokenTenant || (user?.tenants?.length === 1 ? user.tenants[0].id : null);
  } catch {
    return user?.tenants?.length === 1 ? user.tenants[0].id : null;
  }
}

export default function ProfileSettings() {
  const t = useT();
  const { lang } = useI18n();
  const { user } = useAuth();
  const { countryCode, setCountryCode, country, countries } = useRegional();
  const tenantId = activeTenantId(user);
  const tenant = user?.tenants?.find((item) => item.id === tenantId);
  const [savingRegion, setSavingRegion] = React.useState(false);
  const [regionError, setRegionError] = React.useState("");
  const [regionNotice, setRegionNotice] = React.useState("");

  React.useEffect(() => {
    if (!tenantId) return;
    let alive = true;
    Promise.all([
      api(`/tenants/${tenantId}/currency`),
      api(`/tenants/${tenantId}/timezone`),
    ]).then(([currency, timezone]) => {
      if (!alive) return;
      const match = Object.values(countries).find((item) =>
        item.currency === currency?.currency && (!timezone?.timezone || item.timezone === timezone.timezone),
      );
      if (match) setCountryCode(match.code);
    }).catch((error) => {
      if (alive) setRegionError(error?.message || (lang === "ar" ? "تعذر تحميل الإعدادات الإقليمية" : "Could not load regional settings"));
    });
    return () => { alive = false; };
  }, [tenantId, countries, setCountryCode, lang]);

  async function saveRegionalSettings() {
    if (!tenantId) return;
    setSavingRegion(true);
    setRegionError("");
    setRegionNotice("");
    try {
      await api(`/tenants/${tenantId}/currency`, { method: "PUT", body: { currency: country.currency } });
      await api(`/tenants/${tenantId}/timezone`, { method: "PUT", body: { timezone: country.timezone } });
      setRegionNotice(lang === "ar" ? "تم حفظ العملة والمنطقة الزمنية لمساحة العمل." : "Workspace currency and time zone were saved.");
    } catch (error) {
      setRegionError(error?.message || (lang === "ar" ? "تعذر حفظ الإعدادات الإقليمية" : "Could not save regional settings"));
    } finally {
      setSavingRegion(false);
    }
  }
  const initials = (user?.full_name || user?.email || "?")
    .split(/[\s@._-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0])
    .join("")
    .toUpperCase();

  return (
    <SettingsShell title={t("settings.nav.profile")} subtitle={t("settings.profile.desc")}>
      <div className="space-y-5">
        <SettingCard title={t("profile.personal")} desc={t("profile.personal.desc")}>
          <div className="flex items-center gap-4 pt-2 pb-4">
            <div className="h-14 w-14 rounded-full bg-accent/15 text-accent grid place-items-center font-display font-semibold text-[18px]">{initials || "—"}</div>
            <div className="min-w-0">
              <div className="text-[14px] font-medium truncate">{user?.full_name || "—"}</div>
              <div className="text-[12px] text-muted-foreground truncate">{user?.email || "—"}</div>
            </div>
          </div>
          <div className="grid gap-2 border-t border-border pt-3 sm:grid-cols-2">
            <ReadOnlyField label={t("profile.fullName")} value={user?.full_name} />
            <ReadOnlyField label={t("profile.email")} value={user?.email} />
          </div>
          <p className="mt-3 text-[11.5px] leading-relaxed text-muted-foreground">
            {lang === "ar"
              ? "تعديل الاسم والبريد الإلكتروني غير متاح في عقد الـAPI الحالي. البيانات هنا مقروءة من حسابك المسجل."
              : "Name and email editing are not available in the current API contract. These values are read from your signed-in account."}
          </p>
        </SettingCard>

        <SettingCard title={lang === "ar" ? "مساحة العمل" : "Workspace"}>
          <div className="pt-2">
            <SettingRow label={lang === "ar" ? "مساحة العمل" : "Workspace"}>
              <span className="text-[13px] font-medium">{tenant?.name || "—"}</span>
            </SettingRow>
            <SettingRow label={lang === "ar" ? "الدور" : "Role"} last>
              <span className="text-[13px] font-medium">{tenant?.role_code || "—"}</span>
            </SettingRow>
          </div>
          <p className="mt-2 text-[11.5px] leading-relaxed text-muted-foreground">
            {lang === "ar"
              ? "تفاصيل النشاط التجاري مثل العنوان والهاتف لا يعيدها الـAPI الحالي؛ أزلت القيم التجريبية من النموذج."
              : "The current API does not return business details such as address or phone; sample values have been removed."}
          </p>
        </SettingCard>

        <SettingCard title={t("settings.regional")} desc={t("settings.regional.desc")}>
          <div className="pt-2">
            <SettingRow label={t("regional.country")}>
              <Select value={countryCode} onValueChange={setCountryCode}>
                <SelectTrigger className="w-[220px]"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {Object.values(countries).map((item) => (
                    <SelectItem key={item.code} value={item.code}>{lang === "ar" ? item.nameAr : item.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </SettingRow>
            <SettingRow label={t("regional.currency")} desc={`${country.currency} — ${lang === "ar" ? country.currencyNameAr : country.currencyName}`}>
              <span className="text-[13px] font-medium tabular-nums bdi">{country.currency}</span>
            </SettingRow>
            <SettingRow label={t("regional.timezone")} desc={country.timezone}>
              <span className="text-[13px] text-muted-foreground">{country.timezone}</span>
            </SettingRow>
            <SettingRow label={t("regional.numberFormat")}>
              <span className="text-[13px] text-muted-foreground tabular-nums bdi">{new Intl.NumberFormat(country.dateLocale).format(124820)}</span>
            </SettingRow>
            <SettingRow label={t("regional.dateFormat")}>
              <span className="text-[13px] text-muted-foreground">{formatDate(new Date())}</span>
            </SettingRow>
            <SettingRow label={t("regional.preview")} last>
              <span className="text-[14px] font-semibold tabular-nums bdi">{formatCurrency(124820)}</span>
            </SettingRow>
          </div>
          <div className="mt-4 border-t border-border pt-3">
            <p className="text-[11.5px] leading-relaxed text-muted-foreground">{t("regional.note")}</p>
          </div>
          {(regionError || regionNotice) && <div role={regionError ? "alert" : "status"} className={`mt-3 rounded-lg px-3 py-2 text-[12px] ${regionError ? "bg-destructive/10 text-destructive" : "bg-success/10 text-foreground"}`}>{regionError || regionNotice}</div>}
          <div className="mt-4 flex justify-end">
            <Button type="button" onClick={saveRegionalSettings} disabled={!tenantId || savingRegion} className="gap-1.5"><Save className="h-4 w-4" />{savingRegion ? "…" : t("businessProfile.save")}</Button>
          </div>
        </SettingCard>
      </div>
    </SettingsShell>
  );
}

function ReadOnlyField({ label, value }) {
  return (
    <div className="rounded-lg border border-border px-3 py-2.5">
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className="mt-0.5 text-[13px] font-medium break-all">{value || "—"}</div>
    </div>
  );
}
