import React, { useState } from "react";
import { Save, RotateCcw, ShieldAlert, RefreshCw } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import SettingsShell, { SettingCard, SettingRow } from "@/components/settings/SettingsShell";
import { useSettings } from "@/components/settings/useSettings";
import ScopeSelector from "@/components/settings/ScopeSelector";
import PreviewPanel from "@/components/settings/PreviewPanel";
import ChangeRequestList from "@/components/settings/ChangeRequestList";
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
        {defn.apply_mode === "approval_required" && (
          <Badge tone="warning" className="shrink-0">
            <ShieldAlert className="mr-1 h-3 w-3" />
            {isAr ? "تتطلب موافقة" : "Approval"}
          </Badge>
        )}
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
  const [scope, setScope] = useState("tenant");
  const [scopeId, setScopeId] = useState(null);
  const [segment, setSegment] = useState("");
  const [showPreview, setShowPreview] = useState(false);
  const [crReason, setCrReason] = useState("");

  const s = useSettings({ scope, scopeId, segment: segment || undefined });

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

  // Split dirty keys: approval-required go to change request, rest go to direct save.
  const hasApprovalChanges = s.approvalRequiredKeys.length > 0;
  const hasDirectChanges = s.changedEntries.some((e) => !e.needsApproval);

  const handleSave = () => {
    if (hasApprovalChanges && !hasDirectChanges) return; // only approval-required → use change request
    s.save();
  };

  const handleSubmitChangeRequest = () => {
    s.submitChangeRequest(crReason || undefined);
    setCrReason("");
  };

  const noticeText = {
    saved: isAr ? "تم الحفظ" : "Saved",
    change_request_submitted: isAr ? "تم إرسال طلب التغيير" : "Change request submitted",
    change_request_approved: isAr ? "تمت الموافقة على الطلب" : "Change request approved",
    change_request_rejected: isAr ? "تم رفض الطلب" : "Change request rejected",
  }[s.notice];

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
          {s.dirty && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                const next = !showPreview;
                setShowPreview(next);
                // Opening the preview asks the server: the diff alone cannot say which key is
                // out of range or which one needs approval.
                if (next) s.runPreview();
              }}
              disabled={s.previewing}
            >
              {isAr ? "معاينة" : "Preview"}
            </Button>
          )}
          {hasApprovalChanges && (
            <Button
              size="sm"
              variant="outline"
              onClick={handleSubmitChangeRequest}
              disabled={s.saving}
            >
              <ShieldAlert className="h-3.5 w-3.5" />
              {s.saving ? "…" : (isAr ? "طلب تغيير" : "Request Change")}
            </Button>
          )}
          {hasDirectChanges && (
            <Button size="sm" onClick={handleSave} disabled={!s.dirty || s.saving}>
              <Save className="h-3.5 w-3.5" />
              {s.saving ? "…" : (isAr ? "حفظ" : "Save")}
            </Button>
          )}
        </div>
      }
    >
      {/* Scope + segment selectors */}
      <div className="flex flex-wrap items-center gap-3">
        <ScopeSelector
          scope={scope}
          scopeId={scopeId}
          onScopeChange={(v) => { setScope(v); setScopeId(null); }}
          onScopeIdChange={setScopeId}
          isAr={isAr}
        />
        <Select value={segment} onValueChange={(v) => setSegment(v === "all" ? "" : v)}>
          <SelectTrigger className="w-[140px]">
            <SelectValue placeholder={isAr ? "القطاع" : "Segment"} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{isAr ? "كل القطاعات" : "All segments"}</SelectItem>
            <SelectItem value="retail">{isAr ? "تجزئة" : "Retail"}</SelectItem>
            <SelectItem value="fnb">{isAr ? "طعام وشراب" : "F&B"}</SelectItem>
            <SelectItem value="services">{isAr ? "خدمات" : "Services"}</SelectItem>
            <SelectItem value="wholesale">{isAr ? "جملة" : "Wholesale"}</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* 409 conflict banner */}
      {s.conflict && (
        <div role="alert" className="flex items-center gap-2 rounded-lg bg-amber-50 border border-amber-200 px-3 py-2 text-[12px] text-amber-800">
          <RefreshCw className="h-3.5 w-3.5 shrink-0" />
          <span className="flex-1">
            {isAr
              ? "حد عدّل هذه الإعدادات قبلك. حدّث الصفحة لمشاهدة القيم الجديدة."
              : "Someone edited these settings before you. Refresh to see the latest values."}
          </span>
          <Button
            size="sm"
            variant="outline"
            className="h-7 text-[11px]"
            onClick={() => window.location.reload()}
          >
            {isAr ? "تحديث" : "Refresh"}
          </Button>
        </div>
      )}

      {/* Error banner */}
      {s.error && (
        <div role="alert" className="rounded-lg bg-destructive/10 px-3 py-2 text-[12px] text-destructive">
          {s.error}
        </div>
      )}

      {/* Success / notice banner */}
      {noticeText && !s.conflict && (
        <div role="status" className="rounded-lg bg-success/10 px-3 py-2 text-[12px] text-foreground">
          {noticeText}
        </div>
      )}

      {/* Change request reason input (when approval-required changes exist) */}
      {hasApprovalChanges && (
        <div className="flex items-center gap-2">
          <Input
            className="w-[300px]"
            placeholder={isAr ? "سبب طلب التغيير…" : "Reason for change request…"}
            value={crReason}
            onChange={(e) => setCrReason(e.target.value)}
          />
        </div>
      )}

      {/* What the server says this save would do — before anything is written */}
      {showPreview && s.preview && (
        <div className="rounded-lg border border-border bg-muted/30 p-3 text-[12px]" data-testid="settings-server-preview">
          {s.preview.error ? (
            <div role="alert" className="text-destructive">{s.preview.error}</div>
          ) : (
            <>
              <div className="mb-2 text-[11px] text-muted-foreground">
                {isAr ? "فحص السيرفر قبل الحفظ" : "Server check before saving"}
              </div>
              <ul className="space-y-1">
                {s.preview.keys.map((entry) => (
                  <li key={entry.key} className="flex flex-wrap items-center gap-2" data-action={entry.action}>
                    <span className="font-medium">{entry.key}</span>
                    <span className="text-muted-foreground">
                      {String(entry.current)} → {String(entry.proposed)}
                    </span>
                    {entry.action === "unchanged" && (
                      <span className="text-muted-foreground">{isAr ? "بدون تغيير" : "unchanged"}</span>
                    )}
                    {entry.action === "invalid" && (
                      <span className="text-destructive">{entry.error}</span>
                    )}
                    {entry.needs_approval && entry.action === "change" && (
                      <span className="text-amber-700">{isAr ? "يحتاج موافقة" : "needs approval"}</span>
                    )}
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}

      {/* Preview panel */}
      {showPreview && s.dirty && (
        <PreviewPanel
          changedEntries={s.changedEntries}
          scope={scope}
          isAr={isAr}
        />
      )}

      {/* Change request list */}
      <ChangeRequestList
        changeRequests={s.changeRequests}
        onApprove={(id) => s.approveChangeRequest(id)}
        onReject={(id) => s.rejectChangeRequest(id)}
        isAr={isAr}
      />

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
