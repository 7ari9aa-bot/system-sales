/** Section 18 — Security & governance, read over the surfaces that already exist.
 *
 * The map's rule for this section is that it is where the Settings Engine becomes visible to
 * the merchant: approvals, change history, sensitive keys and restore. So none of these panels
 * invents a control:
 *
 * - `SecurityPosturePanel` reads `GET /settings/security-posture` — the four `security.*` values
 *   the runtime enforces plus the two token lifetimes the process was started with. It is
 *   read-only ON PURPOSE: the lifetimes are deployment configuration, so the honest thing is to
 *   show them beside a link to the page that owns the half that IS editable.
 * - `SensitiveSettingsPanel` reads `GET /settings/definitions` and lists the keys the registry
 *   marks sensitive: which of them need approval, and whether anything reads them yet.
 * - `SettingsRestorePanel` calls `POST /settings/restore`, the tenant-wide snapshot restore that
 *   already exists and records every change it writes forward.
 */
import React from "react";
import { Link } from "react-router-dom";
import { AlertTriangle, Loader2, RotateCcw, ShieldCheck } from "lucide-react";
import { useI18n, useT } from "@/lib/i18n";
import { api } from "@/lib/api";
import { SettingCard } from "@/components/settings/SettingsShell";
import { Badge } from "@/components/dashboard/ui";
import { Button } from "@/components/ui/button";

function useJson(path) {
  const [state, setState] = React.useState({ loading: true, data: null, error: "" });
  React.useEffect(() => {
    let alive = true;
    api(path)
      .then((data) => alive && setState({ loading: false, data, error: "" }))
      .catch((e) => alive && setState({ loading: false, data: null, error: e?.message || "" }));
    return () => {
      alive = false;
    };
  }, [path]);
  return state;
}

function Frame({ title, desc, state, children, testId }) {
  const t = useT();
  return (
    <SettingCard title={title} desc={desc}>
      {state.loading ? (
        <div className="flex items-center gap-2 py-4 text-[13px] text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> {t("settings.data.loading")}
        </div>
      ) : state.error ? (
        <p role="alert" className="text-[13px] text-destructive">
          {t("settings.data.loadError")}
        </p>
      ) : (
        <div data-testid={testId}>{children}</div>
      )}
    </SettingCard>
  );
}

function Row({ label, value, last = false }) {
  return (
    <div
      className={
        last
          ? "flex items-center justify-between gap-4 py-2.5"
          : "flex items-center justify-between gap-4 border-b border-border py-2.5"
      }
    >
      <span className="text-[12.5px] text-muted-foreground">{label}</span>
      <span className="text-[13px] font-medium tabular-nums">{value}</span>
    </div>
  );
}

/** Hours and days, not raw seconds: a reader should not divide 1 209 600 in their head. */
export function humaniseSeconds(seconds) {
  const value = Number(seconds);
  if (!Number.isFinite(value) || value <= 0) return "—";
  if (value % 86400 === 0) return `${value / 86400} ${value === 86400 ? "day" : "days"}`;
  if (value % 3600 === 0) return `${value / 3600} ${value === 3600 ? "hour" : "hours"}`;
  return `${Math.round(value / 60)} min`;
}

export function SecurityPosturePanel() {
  const t = useT();
  const { lang } = useI18n();
  const isAr = lang === "ar";
  const state = useJson("/settings/security-posture");
  const body = state.data || {};

  return (
    <Frame
      title={t("settings.security.posture.title")}
      desc={t("settings.security.posture.desc")}
      state={state}
      testId="security-posture"
    >
      <Row
        label={t("settings.security.posture.strongPasswords")}
        value={
          body?.password_policy?.require_strong_passwords
            ? isAr
              ? "مفعّل"
              : "On"
            : isAr
              ? "متوقف"
              : "Off"
        }
      />
      <Row
        label={t("settings.security.posture.accessTtl")}
        value={humaniseSeconds(body?.sessions?.access_token_ttl_seconds)}
      />
      <Row
        label={t("settings.security.posture.refreshTtl")}
        value={humaniseSeconds(body?.sessions?.refresh_token_ttl_seconds)}
      />
      <Row
        label={t("settings.security.posture.allowlist")}
        value={
          body?.ip_allowlist?.configured
            ? isAr
              ? `${body.ip_allowlist.entries} عنوان`
              : `${body.ip_allowlist.entries} entries`
            : isAr
              ? "مفتوح للجميع"
              : "Open to all"
        }
      />
      <Row
        label={t("settings.security.posture.auditRetention")}
        value={
          Number(body?.audit?.retention_days) === 0
            ? isAr
              ? "بدون حذف"
              : "Kept forever"
            : `${body?.audit?.retention_days ?? "—"} ${isAr ? "يوم" : "days"}`
        }
      />
      <Row
        label={t("settings.security.posture.keyRotation")}
        value={
          Number(body?.api_keys?.rotation_days) === 0
            ? isAr
              ? "بدون تدوير إلزامي"
              : "No forced rotation"
            : `${body?.api_keys?.rotation_days ?? "—"} ${isAr ? "يوم" : "days"}`
        }
        last
      />
      <p className="mt-3 border-t border-border pt-3 text-[11.5px] leading-relaxed text-muted-foreground">
        {t("settings.security.posture.whereToEdit")}{" "}
        <Link className="underline" to="/settings/security/security-policies">
          {t("settings.security.pages.security-policies.title")}
        </Link>
      </p>
    </Frame>
  );
}

/** The keys the registry calls sensitive, read-only. Editing happens at each key's home. */
export function SensitiveSettingsPanel() {
  const t = useT();
  const { lang } = useI18n();
  const isAr = lang === "ar";
  const state = useJson("/settings/definitions");
  const rows = Array.isArray(state.data)
    ? state.data.filter((d) => d.sensitivity && d.sensitivity !== "normal")
    : [];

  return (
    <Frame
      title={t("settings.security.sensitive.title")}
      desc={t("settings.security.sensitive.desc")}
      state={state}
      testId="sensitive-settings"
    >
      {rows.length === 0 ? (
        <p className="text-[13px] text-muted-foreground">
          {t("settings.security.sensitive.empty")}
        </p>
      ) : (
        <ul className="divide-y divide-border">
          {rows.map((defn) => (
            <li key={defn.key} className="flex flex-wrap items-center gap-2 py-2.5">
              <ShieldCheck className="h-4 w-4 shrink-0 text-muted-foreground" />
              <span className="min-w-0 flex-1 truncate text-[13px]">
                {isAr ? defn.label_ar || defn.key : defn.label_en || defn.key}
              </span>
              <code className="text-[11px] text-muted-foreground">{defn.key}</code>
              {defn.apply_mode === "approval_required" && (
                <Badge tone="warning">{t("settings.security.sensitive.approval")}</Badge>
              )}
              {defn.enforced === false && (
                <Badge tone="muted">{t("settings.security.sensitive.notActive")}</Badge>
              )}
            </li>
          ))}
        </ul>
      )}
      <p className="mt-3 border-t border-border pt-3 text-[11.5px] leading-relaxed text-muted-foreground">
        {t("settings.security.sensitive.whereToEdit")}
      </p>
    </Frame>
  );
}

/** Tenant-wide snapshot restore. It already exists; the page only makes it reachable. */
export function SettingsRestorePanel() {
  const t = useT();
  const { lang } = useI18n();
  const isAr = lang === "ar";
  const [when, setWhen] = React.useState("");
  const [reason, setReason] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [result, setResult] = React.useState(null);
  const [error, setError] = React.useState("");

  const submit = async () => {
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const body = { snapshot_before: new Date(when).toISOString(), reason: reason || null };
      setResult(await api("/settings/restore", { method: "POST", body }));
    } catch (e) {
      setError(e?.message || (isAr ? "تعذر تنفيذ الاسترجاع" : "Could not run the restore"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <SettingCard
      title={t("settings.security.restore.title")}
      desc={t("settings.security.restore.desc")}
    >
      <div className="space-y-3">
        <div className="flex items-start gap-2 rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-[12px]">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
          <span>{t("settings.security.restore.warning")}</span>
        </div>
        <label className="block text-[12.5px]">
          <span className="mb-1 block text-muted-foreground">
            {t("settings.security.restore.when")}
          </span>
          <input
            type="datetime-local"
            value={when}
            onChange={(e) => setWhen(e.target.value)}
            className="w-full rounded-md border border-border bg-background px-2.5 py-1.5 text-[13px]"
          />
        </label>
        <label className="block text-[12.5px]">
          <span className="mb-1 block text-muted-foreground">
            {t("settings.security.restore.reason")}
          </span>
          <input
            type="text"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            maxLength={200}
            className="w-full rounded-md border border-border bg-background px-2.5 py-1.5 text-[13px]"
          />
        </label>
        <Button size="sm" onClick={submit} disabled={!when || busy}>
          <RotateCcw className="h-3.5 w-3.5" />
          {busy ? "…" : t("settings.security.restore.action")}
        </Button>
        {error && (
          <p role="alert" className="text-[12.5px] text-destructive">
            {error}
          </p>
        )}
        {result && (
          <p className="text-[12.5px] text-muted-foreground">
            {t("settings.security.restore.done")}{" "}
            {Object.entries(result)
              .map(([key, value]) => `${key}: ${value}`)
              .join(" · ")}
          </p>
        )}
        <p className="border-t border-border pt-3 text-[11.5px] leading-relaxed text-muted-foreground">
          {t("settings.security.restore.scope")}
        </p>
      </div>
    </SettingCard>
  );
}
