import React from "react";
import { AlertTriangle, Archive, Download } from "lucide-react";
import { useT, useI18n } from "@/lib/i18n";
import { useAuth } from "@/lib/AuthContext";
import { getTokens, api } from "@/lib/api";
import SettingsShell, { SettingCard } from "@/components/settings/SettingsShell";
import { Badge } from "@/components/dashboard/ui";

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

export default function DangerZoneSettings() {
  const t = useT();
  const { lang } = useI18n();
  const { user } = useAuth();
  const isAr = lang === "ar";
  const tenantId = activeTenantId(user);
  const [lifecycle, setLifecycle] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [exporting, setExporting] = React.useState(false);
  const [error, setError] = React.useState("");

  const downloadExport = async () => {
    if (!tenantId || lifecycle?.lifecycle_state !== "offboarding" || exporting) return;
    setError("");
    setExporting(true);
    try {
      const data = await api(`/tenants/${tenantId}/offboarding/export`, { method: "POST" });
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `sales-os-export-${tenantId}.json`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (err) {
      setError(err?.message || (isAr ? "تعذر تنزيل بيانات مساحة العمل." : "Could not download workspace data."));
    } finally {
      setExporting(false);
    }
  };

  React.useEffect(() => {
    let alive = true;
    if (!tenantId) {
      setError(isAr ? "تعذر تحديد مساحة العمل الحالية." : "Could not determine the active workspace.");
      setLoading(false);
      return () => { alive = false; };
    }
    api(`/tenants/${tenantId}/lifecycle`)
      .then((result) => alive && setLifecycle(result))
      .catch((err) => alive && setError(err?.message || (isAr ? "تعذر قراءة حالة مساحة العمل" : "Could not read workspace status")))
      .finally(() => alive && setLoading(false));
    return () => { alive = false; };
  }, [tenantId, isAr]);

  return (
    <SettingsShell title={t("settings.dangerZone")} subtitle={t("settings.dangerZone.desc")}>
      {error && <div role="alert" className="mb-4 rounded-lg border border-destructive/20 bg-destructive/10 px-3 py-2 text-[12px] text-destructive">{error}</div>}
      <SettingCard>
        <div className="rounded-lg border border-border p-4">
          <div className="flex items-start gap-3">
            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-surface text-muted-foreground"><Archive className="h-4 w-4" /></span>
            <div className="min-w-0 flex-1">
              <div className="text-[13.5px] font-medium">{isAr ? "حالة مساحة العمل" : "Workspace lifecycle"}</div>
              <div className="mt-1"><Badge tone={lifecycle?.lifecycle_state === "active" || lifecycle?.lifecycle_state === "trial" ? "success" : "warning"}>{loading ? "…" : lifecycle?.lifecycle_state || "—"}</Badge></div>
              <p className="mt-2 text-[11.5px] leading-relaxed text-muted-foreground">
                {isAr
                  ? "تظل مساحة العمل قابلة للتصدير خلال فترة الاحتفاظ بعد بدء الإنهاء. بعد انتهاء المهلة تُحذف بياناتها نهائيًا."
                  : "The workspace can be exported during its retention period after offboarding begins. Its data is permanently deleted when that period ends."}
              </p>
              {lifecycle?.deletion_scheduled_at && (
                <p className="mt-2 text-[11.5px] text-muted-foreground">
                  {isAr ? "موعد الحذف المجدول: " : "Scheduled deletion: "}
                  <time dateTime={lifecycle.deletion_scheduled_at}>{new Date(lifecycle.deletion_scheduled_at).toLocaleString(isAr ? "ar-EG" : "en-US")}</time>
                </p>
              )}
            </div>
          </div>
        </div>

        <div className="mt-3 rounded-lg border border-border p-4">
          <div className="flex items-start gap-3">
            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-surface text-muted-foreground"><Download className="h-4 w-4" /></span>
            <div className="min-w-0 flex-1">
              <div className="text-[13.5px] font-medium">{t("danger.export")}</div>
              <div className="mt-1 text-[12px] text-muted-foreground">{isAr ? "يتضمن التصدير بيانات مساحة العمل وسجلاتها، مع استبعاد أسرار التكامل. ملفات الوسائط نفسها تظل في التخزين." : "The export includes workspace records and history, with integration secrets removed. Binary media files remain in object storage."}</div>
            </div>
            <button
              type="button"
              disabled={loading || exporting || lifecycle?.lifecycle_state !== "offboarding"}
              onClick={downloadExport}
              className="h-8 shrink-0 rounded-lg border border-border px-3 text-[12.5px] disabled:cursor-not-allowed disabled:opacity-50"
            >
              {exporting ? (isAr ? "جارٍ التصدير..." : "Exporting...") : t("danger.export")}
            </button>
          </div>
        </div>

        <div className="mt-4 flex items-start gap-2 rounded-lg border border-warning/30 bg-warning/10 p-3 text-[11.5px] leading-relaxed text-warning">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{isAr ? "يبدأ الإنهاء من إعدادات الحساب/الدعم. بعد بدء المهلة، نزّل نسخة البيانات قبل موعد الحذف النهائي." : "Offboarding is started through account support. Download an export before the scheduled permanent deletion."}</span>
        </div>
      </SettingCard>
    </SettingsShell>
  );
}
