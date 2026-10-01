import React from "react";
import { ShieldCheck, KeyRound, Smartphone } from "lucide-react";
import { useT, useI18n } from "@/lib/i18n";
import { api } from "@/lib/api";
import SettingsShell, { SettingCard, SettingRow } from "@/components/settings/SettingsShell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export default function SecuritySettings() {
  const t = useT();
  const { lang } = useI18n();
  const isAr = lang === "ar";
  const [mode, setMode] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [code, setCode] = React.useState("");
  const [useBackupCode, setUseBackupCode] = React.useState(false);
  const [secret, setSecret] = React.useState(null);
  const [backupCodes, setBackupCodes] = React.useState([]);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [notice, setNotice] = React.useState("");

  async function startEnrollment(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await api("/auth/mfa/enroll", { method: "POST", body: { password } });
      setSecret(result);
      setPassword("");
      setCode("");
      setMode("confirm");
    } catch (err) {
      setError(err?.message || (isAr ? "تعذر بدء إعداد المصادقة الثنائية" : "Could not start two-step setup"));
    } finally {
      setBusy(false);
    }
  }

  async function confirmEnrollment(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await api("/auth/mfa/confirm", { method: "POST", body: { code: code.trim() } });
      setBackupCodes(Array.isArray(result?.backup_codes) ? result.backup_codes : []);
      setMode("enabled");
      setCode("");
      setNotice(isAr ? "تم تفعيل المصادقة الثنائية. احتفظ برموز الاسترداد؛ لن تظهر مرة أخرى." : "Two-step verification is enabled. Save these recovery codes; they will not be shown again.");
    } catch (err) {
      setError(err?.message || (isAr ? "رمز التحقق غير صحيح" : "The verification code was not accepted"));
    } finally {
      setBusy(false);
    }
  }

  async function disableMfa(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await api("/auth/mfa/disable", {
        method: "POST",
        body: useBackupCode ? { backup_code: code.trim() } : { code: code.trim() },
      });
      setMode("");
      setCode("");
      setSecret(null);
      setBackupCodes([]);
      setNotice(isAr ? "تم إيقاف المصادقة الثنائية." : "Two-step verification has been disabled.");
    } catch (err) {
      setError(err?.message || (isAr ? "تعذر إيقاف المصادقة الثنائية" : "Could not disable two-step verification"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <SettingsShell title={t("settings.security")} subtitle={t("settings.security.desc")}>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <SettingCard title={isAr ? "المصادقة الثنائية" : "Two-step verification"}>
          <div className="flex items-start gap-3 pt-2">
            <span className="h-10 w-10 shrink-0 rounded-lg bg-primary/10 text-primary grid place-items-center"><ShieldCheck className="h-5 w-5" /></span>
            <p className="text-[12px] leading-relaxed text-muted-foreground">
              {isAr
                ? "استخدم تطبيق مصادقة ورموز احتياطية. الـAPI الحالي لا يوفر قراءة حالة المصادقة عند فتح الصفحة."
                : "Use an authenticator app and recovery codes. The current API does not expose the existing MFA status when this page loads."}
            </p>
          </div>
          {error && <div role="alert" className="mt-3 rounded-lg bg-destructive/10 px-3 py-2 text-[12px] text-destructive">{error}</div>}
          {notice && <div role="status" className="mt-3 rounded-lg bg-success/10 px-3 py-2 text-[12px] text-foreground">{notice}</div>}

          {!mode && (
            <form onSubmit={startEnrollment} className="mt-4 space-y-3 border-t border-border pt-4">
              <label className="grid gap-1.5 text-[12px] text-muted-foreground">
                {isAr ? "كلمة مرور الحساب لبدء الإعداد" : "Account password to start setup"}
                <Input type="password" autoComplete="current-password" required value={password} onChange={(event) => setPassword(event.target.value)} />
              </label>
              <div className="flex flex-wrap gap-2">
                <Button type="submit" disabled={busy}>{busy ? "…" : (isAr ? "إعداد المصادقة الثنائية" : "Set up two-step verification")}</Button>
                <Button type="button" variant="outline" onClick={() => { setMode("disable"); setUseBackupCode(false); setError(""); setNotice(""); }}>
                  {isAr ? "إيقاف المصادقة الثنائية" : "Disable two-step verification"}
                </Button>
              </div>
            </form>
          )}

          {mode === "confirm" && secret && (
            <div className="mt-4 space-y-3 border-t border-border pt-4">
              <div className="rounded-lg border border-border bg-surface/50 p-3 text-[12px]">
                <div className="font-medium">{isAr ? "أضف المفتاح إلى تطبيق المصادقة" : "Add this key to your authenticator app"}</div>
                <div className="mt-2 break-all font-mono text-[12px]" dir="ltr">{secret.secret}</div>
                <a className="mt-2 inline-block break-all text-primary underline" href={secret.otpauth_url}>{isAr ? "فتح رابط إعداد تطبيق المصادقة" : "Open authenticator setup link"}</a>
              </div>
              <form onSubmit={confirmEnrollment} className="space-y-3">
                <label className="grid gap-1.5 text-[12px] text-muted-foreground">
                  {isAr ? "رمز التحقق المكوّن من 6 أرقام" : "6-digit verification code"}
                  <Input inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} required value={code} onChange={(event) => setCode(event.target.value.replace(/\D/g, ""))} />
                </label>
                <div className="flex gap-2">
                  <Button type="submit" disabled={busy || code.length !== 6}>{busy ? "…" : (isAr ? "تأكيد وتفعيل" : "Confirm and enable")}</Button>
                  <Button type="button" variant="outline" onClick={() => { setMode(""); setSecret(null); setPassword(""); setCode(""); }}>{t("ls.cancel")}</Button>
                </div>
              </form>
            </div>
          )}

          {mode === "enabled" && (
            <div className="mt-4 border-t border-border pt-4">
              {backupCodes.length > 0 ? (
                <>
                  <div className="mb-2 text-[12px] font-medium">{isAr ? "رموز الاسترداد" : "Recovery codes"}</div>
                  <div className="grid grid-cols-2 gap-2 rounded-lg border border-border bg-surface/50 p-3 font-mono text-[12px]" dir="ltr">
                    {backupCodes.map((backupCode) => <span key={backupCode}>{backupCode}</span>)}
                  </div>
                </>
              ) : <p className="text-[12px] text-muted-foreground">{isAr ? "تم التفعيل، لكن لم تُرجع الخوادم رموز استرداد لعرضها." : "Enabled, but the server did not return recovery codes to display."}</p>}
              <Button type="button" variant="outline" onClick={() => { setMode("disable"); setUseBackupCode(false); setError(""); }} className="mt-3">
                {isAr ? "إيقاف المصادقة الثنائية" : "Disable two-step verification"}
              </Button>
            </div>
          )}

          {mode === "disable" && (
            <form onSubmit={disableMfa} className="mt-4 space-y-3 border-t border-border pt-4">
              <label className="grid gap-1.5 text-[12px] text-muted-foreground">
                {useBackupCode
                  ? (isAr ? "رمز الاسترداد" : "Recovery code")
                  : (isAr ? "رمز تطبيق المصادقة الحالي" : "Current authenticator code")}
                <Input
                  inputMode={useBackupCode ? "text" : "numeric"}
                  autoComplete={useBackupCode ? "off" : "one-time-code"}
                  pattern={useBackupCode ? "[a-fA-F0-9]{16}" : "[0-9]{6}"}
                  maxLength={useBackupCode ? 16 : 6}
                  required
                  value={code}
                  onChange={(event) => setCode(useBackupCode ? event.target.value.replace(/[^a-fA-F0-9]/g, "").slice(0, 16) : event.target.value.replace(/\D/g, ""))}
                />
              </label>
              <div className="flex gap-2">
                <Button type="submit" variant="destructive" disabled={busy || code.length !== (useBackupCode ? 16 : 6)}>{busy ? "…" : (isAr ? "تأكيد الإيقاف" : "Confirm disable")}</Button>
                <Button type="button" variant="ghost" onClick={() => { setUseBackupCode((value) => !value); setCode(""); }}>{useBackupCode ? (isAr ? "استخدام رمز المصادقة" : "Use authenticator code") : (isAr ? "استخدام رمز استرداد" : "Use recovery code")}</Button>
                <Button type="button" variant="outline" onClick={() => { setMode(""); setCode(""); }}>{t("ls.cancel")}</Button>
              </div>
            </form>
          )}
        </SettingCard>

        <SettingCard title={t("ls.sessions")}>
          <div className="flex items-start gap-3 pt-2">
            <span className="h-10 w-10 shrink-0 rounded-lg bg-surface text-muted-foreground grid place-items-center"><Smartphone className="h-5 w-5" /></span>
            <p className="text-[12px] leading-relaxed text-muted-foreground">
              {isAr
                ? "قائمة الجلسات النشطة وإلغاؤها غير متاحين في الـAPI الحالي؛ أزلت الأجهزة التجريبية من الشاشة."
                : "The current API does not expose active sessions or session revocation; sample devices have been removed."}
            </p>
          </div>
          <SettingRow label={t("ls.password")} desc={isAr ? "تغيير كلمة المرور غير متاح من هذه الصفحة حاليًا." : "Password changes are not available from this page yet."} last>
            <span className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border px-2.5 text-[12px] text-muted-foreground"><KeyRound className="h-3.5 w-3.5" />—</span>
          </SettingRow>
        </SettingCard>
      </div>
    </SettingsShell>
  );
}
