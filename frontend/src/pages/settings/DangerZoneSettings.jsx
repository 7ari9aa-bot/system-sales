import React from "react";
import { AlertTriangle, Archive, Download } from "lucide-react";
import { useT, useI18n } from "@/lib/i18n";
import { useAuth } from "@/lib/AuthContext";
import { api } from "@/lib/api";
import { activeTenantId } from "@/lib/activeTenant";
import SettingsShell, { SettingCard, SettingRow } from "@/components/settings/SettingsShell";
import { Badge } from "@/components/dashboard/ui";

// Named for what it actually does. It was "Danger zone" while holding no destructive control at
// all: a lifecycle badge and a download that the server only serves DURING the offboarding window.
// Two cards now, each one honest — Backup & export says when the file exists, and Workspace
// lifecycle says who starts the end and what it schedules.
export default function DataSettings() {
  const t = useT();
  const { lang } = useI18n();
  const { user } = useAuth();
  const isAr = lang === "ar";
  const tenantId = activeTenantId(user);
  const [lifecycle, setLifecycle] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [exporting, setExporting] = React.useState(false);
  const [error, setError] = React.useState("");

  const offboarding = lifecycle?.lifecycle_state === "offboarding";
  const canExport = offboarding && Boolean(tenantId);

  const downloadExport = async () => {
    if (!canExport || exporting) return;
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
    <SettingsShell title={t("data.title")} subtitle={t("data.desc")}>
      {error && <div role="alert" className="mb-4 rounded-lg border border-destructive/20 bg-destructive/10 px-3 py-2 text-[12px] text-destructive">{error}</div>}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <SettingCard title={t("data.export")} desc={t("data.export.desc")}>
          <div className="flex items-start gap-3 pt-2">
            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-surface text-muted-foreground"><Download className="h-4 w-4" /></span>
            <div className="min-w-0 flex-1">
              <p className="text-[12px] leading-relaxed text-muted-foreground">{t("data.export.contents")}</p>
              <button
                type="button"
                disabled={loading || exporting || !canExport}
                onClick={downloadExport}
                data-testid="data-export"
                title={!canExport && !loading ? t("data.export.onlyOffboarding") : undefined}
                className="mt-3 h-8 shrink-0 rounded-lg border border-border px-3 text-[12.5px] disabled:cursor-not-allowed disabled:opacity-50"
              >
                {exporting ? t("data.export.downloading") : t("data.export.download")}
              </button>
              {!loading && !canExport && (
                <p className="mt-2 text-[11.5px] leading-relaxed text-muted-foreground" data-testid="data-export-reason">{t("data.export.onlyOffboarding")}</p>
              )}
            </div>
          </div>
        </SettingCard>

        <SettingCard title={t("data.lifecycle")} desc={t("data.lifecycle.desc")}>
          <div className="pt-2">
            <SettingRow label={t("data.state")}>
              <span data-testid="workspace-state">
                <Badge tone={lifecycle?.lifecycle_state === "active" || lifecycle?.lifecycle_state === "trial" ? "success" : "warning"}>
                  {loading ? "…" : lifecycle?.lifecycle_state || "—"}
                </Badge>
              </span>
            </SettingRow>
            <SettingRow label={t("data.deletionDate")} last>
              <span className="text-[13px] font-medium tabular-nums">
                {lifecycle?.deletion_scheduled_at
                  ? <time dateTime={lifecycle.deletion_scheduled_at}>{new Date(lifecycle.deletion_scheduled_at).toLocaleString(isAr ? "ar-EG" : "en-US")}</time>
                  : "—"}
              </span>
            </SettingRow>
          </div>
          <div className="mt-4 flex items-start gap-2 rounded-lg border border-warning/30 bg-warning/10 p-3 text-[11.5px] leading-relaxed text-warning">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{t("data.lifecycle.note")}</span>
          </div>
          <div className="mt-3 flex items-start gap-2 text-[11.5px] leading-relaxed text-muted-foreground">
            <Archive className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>{t("data.lifecycle.retention")}</span>
          </div>
        </SettingCard>
      </div>
    </SettingsShell>
  );
}
