import React from "react";
import { Save, RotateCcw } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import SettingsShell, { SettingCard, SettingRow } from "@/components/settings/SettingsShell";
import { useSettings } from "@/components/settings/useSettings";
import { Switch } from "@/components/ui/switch";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/dashboard/ui";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";

const DOMAIN_LABELS_AR = {
  business: "النشاط والملف التجاري",
  pos: "نقطة البيع",
  inventory: "المخزون",
  purchasing: "المشتريات",
  orders: "الطلبات",
  print: "الطباعة والمستندات",
  einvoice: "الفاتورة الإلكترونية",
  customer_agent: "وكيل الذكاء الاصطناعي للعملاء",
  analytics_agent: "وكيل التحليلات",
  organization: "المؤسسة",
  branch: "الفروع",
  catalog: "الكتالوج",
  team: "الفريق",
  security: "الأمان",
  billing: "الفوترة",
  notifications: "الإشعارات",
  imports: "الاستيراد",
  capability: "القدرات",
};

const DOMAIN_LABELS_EN = {
  business: "Business & Profile",
  pos: "Point of Sale",
  inventory: "Inventory",
  purchasing: "Purchasing",
  orders: "Orders",
  print: "Print & Documents",
  einvoice: "E-Invoice",
  customer_agent: "Customer AI Agent",
  analytics_agent: "Analytics Agent",
  organization: "Organization",
  branch: "Branches",
  catalog: "Catalog",
  team: "Team",
  security: "Security",
  billing: "Billing",
  notifications: "Notifications",
  imports: "Imports",
  capability: "Capabilities",
};

function SettingField({ defn, value, onChange, isAr }) {
  const label = isAr ? defn.label_ar || defn.key : defn.label_en || defn.key;
  const desc = isAr ? defn.description_ar : defn.description_en;

  const renderControl = () => {
    if (defn.type === "bool") {
      return (
        <Switch
          checked={Boolean(value)}
          onCheckedChange={(checked) => onChange(defn.key, checked)}
        />
      );
    }

    if (defn.type === "enum" && defn.allowed_values) {
      return (
        <Select value={String(value ?? "")} onValueChange={(v) => onChange(defn.key, v)}>
          <SelectTrigger className="w-[200px]">
            <SelectValue placeholder={isAr ? "اختر…" : "Select…"} />
          </SelectTrigger>
          <SelectContent>
            {defn.allowed_values.map((v) => (
              <SelectItem key={v} value={v}>{v}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      );
    }

    if (defn.type === "number") {
      return (
        <Input
          type="number"
          className="w-[140px]"
          value={value ?? ""}
          min={defn.min_value ?? undefined}
          max={defn.max_value ?? undefined}
          onChange={(e) => onChange(defn.key, e.target.value === "" ? null : Number(e.target.value))}
        />
      );
    }

    if (defn.type === "list") {
      return (
        <Input
          className="w-[260px]"
          value={Array.isArray(value) ? value.join(", ") : String(value ?? "")}
          onChange={(e) => onChange(defn.key, e.target.value.split(",").map((s) => s.trim()).filter(Boolean))}
        />
      );
    }

    // string
    return (
      <Input
        className="w-[260px]"
        value={String(value ?? "")}
        maxLength={defn.max_length ?? undefined}
        onChange={(e) => onChange(defn.key, e.target.value)}
      />
    );
  };

  return (
    <SettingRow label={label} desc={desc} stretch={defn.type === "list" || defn.type === "string"}>
      <div className="flex items-center gap-2">
        {renderControl()}
        {defn.enforced ? (
          <Badge tone="success">{isAr ? "مفعّل" : "Active"}</Badge>
        ) : (
          <Badge tone="muted">{isAr ? "غير مفعّل" : "Not active"}</Badge>
        )}
      </div>
    </SettingRow>
  );
}

export default function UnifiedSettings() {
  const { lang } = useI18n();
  const isAr = lang === "ar";
  const s = useSettings();

  if (s.loading) {
    return (
      <SettingsShell
        title={isAr ? "كل الإعدادات" : "All Settings"}
        subtitle={isAr ? "إعدادات النظام موزّعة حسب المجال." : "System settings grouped by domain."}
      >
        <div className="py-8 text-center text-[13px] text-muted-foreground">
          {s.error || (isAr ? "جارٍ التحميل…" : "Loading…")}
        </div>
      </SettingsShell>
    );
  }

  const domainLabels = isAr ? DOMAIN_LABELS_AR : DOMAIN_LABELS_EN;
  const domains = Object.keys(s.grouped).sort();

  return (
    <SettingsShell
      title={isAr ? "كل الإعدادات" : "All Settings"}
      subtitle={isAr ? "إعدادات النظام موزّعة حسب المجال من الـ registry." : "System settings grouped by domain from the registry."}
      actions={
        <div className="flex items-center gap-2">
          {s.dirty && (
            <Button variant="outline" size="sm" onClick={s.reset} disabled={s.saving}>
              <RotateCcw className="h-3.5 w-3.5" />
              {isAr ? "تراجع" : "Reset"}
            </Button>
          )}
          <Button size="sm" onClick={s.save} disabled={!s.dirty || s.saving}>
            <Save className="h-3.5 w-3.5" />
            {s.saving ? "…" : (isAr ? "حفظ" : "Save")}
          </Button>
        </div>
      }
    >
      {s.error && (
        <div role="alert" className="rounded-lg bg-destructive/10 px-3 py-2 text-[12px] text-destructive">
          {s.error}
        </div>
      )}
      {s.notice === "saved" && (
        <div role="status" className="rounded-lg bg-success/10 px-3 py-2 text-[12px] text-foreground">
          {isAr ? "تم الحفظ" : "Saved"}
        </div>
      )}

      <Accordion type="multiple" defaultValue={[domains[0] || ""]} className="w-full">
        {domains.map((dom) => {
          const domDefs = s.grouped[dom];
          const label = domainLabels[dom] || dom;
          return (
            <AccordionItem key={dom} value={dom}>
              <AccordionTrigger className="text-[14px] font-semibold hover:no-underline">
                {label}
                <span className="ml-2 text-[11px] font-normal text-muted-foreground">
                  ({domDefs.length})
                </span>
              </AccordionTrigger>
              <AccordionContent>
                <SettingCard>
                  {domDefs.map((defn) => (
                    <SettingField
                      key={defn.key}
                      defn={defn}
                      value={s.values[defn.key]}
                      onChange={s.setValue}
                      isAr={isAr}
                    />
                  ))}
                </SettingCard>
              </AccordionContent>
            </AccordionItem>
          );
        })}
      </Accordion>
    </SettingsShell>
  );
}
