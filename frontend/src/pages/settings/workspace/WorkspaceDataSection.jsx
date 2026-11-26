import React from "react";
import { Loader2, Save } from "lucide-react";
import { useT, useI18n } from "@/lib/i18n";
import { useAuth } from "@/lib/AuthContext";
import { api } from "@/lib/api";
import { activeTenant, activeTenantId } from "@/lib/activeTenant";
import { useRegional, formatCurrency, formatDate } from "@/lib/regional";
import SettingsShell, { SettingCard, SettingRow } from "@/components/settings/SettingsShell";
// TODO(settings-map): the brand colour belongs to section 04 (Store & Business) and the
// branch card to section 05 (Locations). They are still rendered here so nothing that
// works today disappears while those two sections are being built; they move out, not
// away, as soon as those pages exist.
import OrganizationBranchCard from "@/components/settings/OrganizationBranchCard";
import BrandColorCard from "@/components/settings/BrandColorCard";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

/** The workspace's own data: what it is called, how it is addressed, where it trades.
 *
 * The name has its own save because renaming is not a regional decision; the currency
 * and the time zone are saved together because changing country changes both, and a
 * workspace trading in EGP while bucketing days in Dubai is a report nobody can trust.
 *
 * The identifier (slug) is shown, not edited: it is the address other systems already
 * hold, and a rename would silently break every link that pointed at it. The brand
 * logo is deliberately NOT here — it is the business's identity and belongs to
 * Store & Business, not to the container.
 */
export default function WorkspaceDataSection() {
  const t = useT();
  const { lang } = useI18n();
  const { user, refreshUser } = useAuth();
  const tenantId = activeTenantId(user);
  const tenant = activeTenant(user);
  const { countryCode, setCountryCode, country, countries } = useRegional();

  const [name, setName] = React.useState(tenant?.name || "");
  const [savingName, setSavingName] = React.useState(false);
  const [nameError, setNameError] = React.useState("");
  const [nameNotice, setNameNotice] = React.useState("");

  const [savingRegion, setSavingRegion] = React.useState(false);
  const [regionError, setRegionError] = React.useState("");
  const [regionNotice, setRegionNotice] = React.useState("");

  const storedName = tenant?.name || "";
  React.useEffect(() => {
    setName((current) => (current === "" ? storedName : current));
  }, [storedName]);

  React.useEffect(() => {
    if (!tenantId) return undefined;
    let alive = true;
    Promise.all([api(`/tenants/${tenantId}/currency`), api(`/tenants/${tenantId}/timezone`)])
      .then(([currency, timezone]) => {
        if (!alive) return;
        const match = Object.values(countries).find(
          (item) =>
            item.currency === currency?.currency &&
            (!timezone?.timezone || item.timezone === timezone.timezone),
        );
        if (match) setCountryCode(match.code);
      })
      .catch((failure) => {
        if (alive) {
          setRegionError(
            failure?.message ||
              (lang === "ar" ? "تعذر تحميل الإعدادات الإقليمية" : "Could not load regional settings"),
          );
        }
      });
    return () => {
      alive = false;
    };
  }, [tenantId, countries, setCountryCode, lang]);

  const nameChanged = name.trim() !== "" && name.trim() !== storedName.trim();

  async function saveName(event) {
    event.preventDefault();
    if (!tenantId || !nameChanged || savingName) return;
    setSavingName(true);
    setNameError("");
    setNameNotice("");
    try {
      const saved = await api(`/tenants/${tenantId}/name`, { method: "PUT", body: { name } });
      setName(saved?.name || name.trim());
      // the workspace's name is printed in the shell (sidebar, receipts); refresh it once, here
      await refreshUser();
      setNameNotice(t("workspace.name.saved"));
    } catch (failure) {
      setNameError(failure?.message || t("workspace.name.failed"));
    } finally {
      setSavingName(false);
    }
  }

  async function saveRegionalSettings() {
    if (!tenantId) return;
    setSavingRegion(true);
    setRegionError("");
    setRegionNotice("");
    try {
      await api(`/tenants/${tenantId}/currency`, { method: "PUT", body: { currency: country.currency } });
      await api(`/tenants/${tenantId}/timezone`, { method: "PUT", body: { timezone: country.timezone } });
      setRegionNotice(
        lang === "ar"
          ? "تم حفظ العملة والمنطقة الزمنية لمساحة العمل."
          : "Workspace currency and time zone were saved.",
      );
    } catch (failure) {
      setRegionError(
        failure?.message ||
          (lang === "ar" ? "تعذر حفظ الإعدادات الإقليمية" : "Could not save regional settings"),
      );
    } finally {
      setSavingRegion(false);
    }
  }

  return (
    <SettingsShell title={t("workspace.data.title")} subtitle={t("workspace.data.desc")}>
      <div className="grid grid-cols-1 items-start gap-x-10 gap-y-6 xl:grid-cols-2">
        <SettingCard title={t("workspace.data.identity")} desc={t("workspace.name.desc")}>
          <form className="pt-2" onSubmit={saveName}>
            <label className="block">
              <span className="text-[11.5px] text-muted-foreground">{t("workspace.name")}</span>
              <div className="mt-1 flex flex-col gap-2 sm:flex-row">
                <Input
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  maxLength={255}
                  autoComplete="organization"
                  disabled={!tenantId}
                  data-testid="workspace-name"
                />
                <Button
                  type="submit"
                  disabled={!tenantId || !nameChanged || savingName}
                  className="gap-1.5 shrink-0"
                  data-testid="workspace-name-save"
                >
                  {savingName ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                  {savingName ? "…" : t("businessProfile.save")}
                </Button>
              </div>
            </label>
          </form>
          {(nameError || nameNotice) && (
            <div
              role={nameError ? "alert" : "status"}
              data-testid="workspace-name-message"
              className={`mt-3 rounded-lg px-3 py-2 text-[12px] ${nameError ? "bg-destructive/10 text-destructive" : "bg-success/10 text-foreground"}`}
            >
              {nameError || nameNotice}
            </div>
          )}
          <div className="mt-2">
            <SettingRow label={t("workspace.slug")} desc={t("workspace.slug.desc")}>
              <span className="text-[13px] font-medium text-muted-foreground bdi" dir="ltr">
                {tenant?.slug || "—"}
              </span>
            </SettingRow>
            <SettingRow label={t("workspace.role")} last>
              <span className="text-[13px] font-medium">
                {tenant?.role_code ? t(`workspace.role.${tenant.role_code}`) : "—"}
              </span>
            </SettingRow>
          </div>
        </SettingCard>

        <SettingCard title={t("settings.regional")} desc={t("settings.regional.desc")}>
          <div className="pt-2">
            <SettingRow label={t("regional.country")}>
              <Select value={countryCode} onValueChange={setCountryCode}>
                <SelectTrigger className="w-[220px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {Object.values(countries).map((item) => (
                    <SelectItem key={item.code} value={item.code}>
                      {lang === "ar" ? item.nameAr : item.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </SettingRow>
            <SettingRow
              label={t("regional.currency")}
              desc={`${country.currency} — ${lang === "ar" ? country.currencyNameAr : country.currencyName}`}
            >
              <span className="text-[13px] font-medium tabular-nums bdi">{country.currency}</span>
            </SettingRow>
            <SettingRow label={t("regional.timezone")} desc={country.timezone}>
              <span className="text-[13px] text-muted-foreground">{country.timezone}</span>
            </SettingRow>
            <SettingRow label={t("regional.numberFormat")}>
              <span className="text-[13px] text-muted-foreground tabular-nums bdi">
                {new Intl.NumberFormat(country.dateLocale).format(124820)}
              </span>
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
          {(regionError || regionNotice) && (
            <div
              role={regionError ? "alert" : "status"}
              className={`mt-3 rounded-lg px-3 py-2 text-[12px] ${regionError ? "bg-destructive/10 text-destructive" : "bg-success/10 text-foreground"}`}
            >
              {regionError || regionNotice}
            </div>
          )}
          <div className="mt-4 flex justify-end">
            <Button
              type="button"
              onClick={saveRegionalSettings}
              disabled={!tenantId || savingRegion}
              className="gap-1.5"
            >
              <Save className="h-4 w-4" />
              {savingRegion ? "…" : t("businessProfile.save")}
            </Button>
          </div>
        </SettingCard>
      </div>
      <div className="mt-6">
        <OrganizationBranchCard />
        <BrandColorCard />
      </div>
      <p className="mt-6 text-[11.5px] leading-relaxed text-muted-foreground">{t("workspace.data.logoNote")}</p>
    </SettingsShell>
  );
}
