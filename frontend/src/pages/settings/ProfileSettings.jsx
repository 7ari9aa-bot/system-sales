import React, { useState } from "react";
import { Save } from "lucide-react";
import { useT } from "@/lib/i18n";
import { useRegional, formatCurrency, formatDate } from "@/lib/regional";
import SettingsShell, { SettingCard, SettingRow } from "@/components/settings/SettingsShell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";

// Merges personal details + business profile + regional settings into one page.
export default function ProfileSettings() {
  const t = useT();
  const { countryCode, setCountryCode, country, countries } = useRegional();

  const [personal, setPersonal] = useState({
    fullName: "Ahmed Hassan",
    email: "ahmed@cedarandco.com",
    phone: "+20 100 123 4567",
  });
  const [business, setBusiness] = useState({
    businessName: "Cedar & Co.",
    legalName: "Cedar & Co. Trading LLC",
    email: "hello@cedarandco.com",
    phone: "+20 100 123 4567",
    website: "cedarandco.com",
    industry: "Retail",
    address: "12 Tahrir Street, Downtown, Cairo",
  });

  const setP = (k) => (e) => setPersonal((f) => ({ ...f, [k]: e.target.value }));
  const setB = (k) => (e) => setBusiness((f) => ({ ...f, [k]: e.target.value }));

  return (
    <SettingsShell title={t("settings.nav.profile")} subtitle={t("settings.profile.desc")}>
      <div className="space-y-5">
        {/* Personal details */}
        <SettingCard title={t("profile.personal")} desc={t("profile.personal.desc")}>
          <div className="flex items-center gap-4 pt-2 pb-5">
            <div className="h-16 w-16 rounded-full bg-accent/15 text-accent grid place-items-center font-display font-semibold text-[20px]">
              AH
            </div>
            <div>
              <div className="text-[14px] font-medium">{personal.fullName}</div>
              <Button variant="outline" className="mt-2 h-8 text-[12.5px]">{t("ls.uploadLogo")}</Button>
            </div>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <Field label={t("profile.fullName")}>
              <Input value={personal.fullName} onChange={setP("fullName")} />
            </Field>
            <Field label={t("profile.email")}>
              <Input value={personal.email} onChange={setP("email")} type="email" />
            </Field>
            <Field label={t("profile.phone")}>
              <Input value={personal.phone} onChange={setP("phone")} />
            </Field>
          </div>
        </SettingCard>

        {/* Business profile */}
        <SettingCard title={t("settings.businessProfile")} desc={t("settings.businessProfile.desc")}>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-2">
            <Field label={t("businessProfile.businessName")}>
              <Input value={business.businessName} onChange={setB("businessName")} />
            </Field>
            <Field label={t("businessProfile.legalName")}>
              <Input value={business.legalName} onChange={setB("legalName")} />
            </Field>
            <Field label={t("businessProfile.email")}>
              <Input value={business.email} onChange={setB("email")} type="email" />
            </Field>
            <Field label={t("businessProfile.phone")}>
              <Input value={business.phone} onChange={setB("phone")} />
            </Field>
            <Field label={t("businessProfile.website")}>
              <Input value={business.website} onChange={setB("website")} />
            </Field>
            <Field label={t("businessProfile.industry")}>
              <Input value={business.industry} onChange={setB("industry")} />
            </Field>
            <div className="sm:col-span-2">
              <Field label={t("businessProfile.address")}>
                <Input value={business.address} onChange={setB("address")} />
              </Field>
            </div>
          </div>
        </SettingCard>

        {/* Regional */}
        <SettingCard title={t("settings.regional")} desc={t("settings.regional.desc")}>
          <div className="pt-2">
            <SettingRow label={t("regional.country")}>
              <Select value={countryCode} onValueChange={setCountryCode}>
                <SelectTrigger className="w-[220px]"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {Object.values(countries).map((c) => (
                    <SelectItem key={c.code} value={c.code}>{c.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </SettingRow>
            <SettingRow label={t("regional.currency")} desc={`${country.currency} — ${country.currencyName}`}>
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
          <div className="mt-4 pt-3 border-t border-border">
            <p className="text-[11.5px] leading-relaxed text-muted-foreground">{t("regional.note")}</p>
          </div>
        </SettingCard>

        <div className="flex justify-end">
          <Button className="gap-1.5">
            <Save className="h-4 w-4" />
            {t("businessProfile.save")}
          </Button>
        </div>
      </div>
    </SettingsShell>
  );
}

function Field({ label, children }) {
  return (
    <div className="space-y-1.5">
      <Label className="text-[12.5px]">{label}</Label>
      {children}
    </div>
  );
}