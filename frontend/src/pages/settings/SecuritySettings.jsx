import React from "react";
import { ShieldCheck, KeyRound, CheckCircle2, Mail } from "lucide-react";
import { useT, useI18n } from "@/lib/i18n";
import { useAuth } from "@/lib/AuthContext";
import { api } from "@/lib/api";
import SettingsShell, { SettingCard, SettingRow } from "@/components/settings/SettingsShell";
import { Badge } from "@/components/dashboard/ui";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

// Two questions, both answered by the server: is two-step verification ON, and how do I get back
// in if I lose the password. The page used to open with three apologies ("cannot read the MFA
// state", "cannot list sessions", "password change is not available") while every one of those
// facts was already reachable — `GET /users/me` now carries `mfa_enabled`, and the recovery email
// is an ordinary endpoint. What genuinely does not exist (a list of signed-in devices) is said
// once, in one line, instead of standing in for a card of its own.
export default function SecuritySettings() {
  const t = useT();
  const { lang } = useI18n();
  const { user, refreshUser } = useAuth();
  const isAr = lang === "ar";
  const [mfaOn, setMfaOn] = React.useState(Boolean(user?.mfa_enabled));
  const [mode, setMode] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [code, setCode] = React.useState("");
  const [useBackupCode, setUseBackupCode] = React.useState(false);
  const [secret, setSecret] = React.useState(null);
  const [backupCodes, setBackupCodes] = React.useState([]);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [notice, setNotice] = React.useState("");
  const [resetBusy, setResetBusy] = React.useState(false);
  const [resetNotice, setResetNotice] = React.useState("");
  const [resetError, setResetError] = React.useState("");

  // the account is the source of truth: after a save the screen reloads it rather than trusting a
  // local guess about a security setting
  React.useEffect(() => { setMfaOn(Boolean(user?.mfa_enabled)); }, [user?.mfa_enabled]);

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
      setMfaOn(true);
      setNotice(isAr ? "تم تفعيل المصادقة الثنائية. احتفظ برموز الاسترداد؛ لن تظهر مرة أخرى." : "Two-step verification is enabled. Save these recovery codes; they will not be shown again.");
      await refreshUser();
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
      setMfaOn(false);
      setNotice(isAr ? "تم إيقاف المصادقة الثنائية." : "Two-step verification has been disabled.");
      await refreshUser();
    } catch (err) {
      setError(err?.message || (isAr ? "تعذر إيقاف المصادقة الثنائية" : "Could not disable two-step verification"));
    } finally {
      setBusy(false);
    }
  }

  async function sendResetLink() {
    if (!user?.email || resetBusy) return;
    setResetBusy(true);
    setResetError("");
    setResetNotice("");
    try {
      await api("/auth/password-reset/request", { method: "POST", body: { email: user.email } });
      // the endpoint answers the same way for every address, so the screen repeats that promise
      // and never claims an email was delivered
      setResetNotice(isAr
        ? `لو كان ${user.email} حسابًا معروفًا، هيوصله رابط إعادة تعيين خلال دقائق.`
        : `If ${user.email} is a known account, reset instructions arrive within minutes.`);
    } catch (err) {
      setResetError(err?.message || (isAr ? "تعذر إرسال رابط إعادة التعيين" : "Could not send the reset link"));
    } finally {
      setResetBusy(false);
    }
  }

  return (
    <SettingsShell title={t("settings.security")} subtitle={t("settings.security.desc")}>
      <div className="grid grid-cols-1 items-start gap-x-10 gap-y-6 xl:grid-cols-2">
        <SettingCard title={t("security.twoStep")} desc={t("security.twoStep.desc")}>
          <SettingRow label={t("security.status")} last>
            <span data-testid="mfa-status">
              <Badge tone={mfaOn ? "success" : "muted"}>{mfaOn ? t("security.on") : t("security.off")}</Badge>
            </span>
          </SettingRow>

          {error && <div role="alert" className="mt-3 rounded-lg bg-destructive/10 px-3 py-2 text-[12px] text-destructive">{error}</div>}
          {notice && <div role="status" className="mt-3 rounded-lg bg-success/10 px-3 py-2 text-[12px] text-foreground">{notice}</div>}

          {!mfaOn && mode === "" && (
            <form onSubmit={startEnrollment} className="mt-4 space-y-3 border-t border-border pt-4">
              <div className="flex items-start gap-3">
                <span className="h-10 w-10 shrink-0 rounded-lg bg-primary/10 text-primary grid place-items-center"><ShieldCheck className="h-5 w-5" /></span>
                <p className="text-[12px] leading-relaxed text-muted-foreground">{t("security.twoStep.how")}</p>
              </div>
              <label className="grid gap-1.5 text-[12px] text-muted-foreground">
                {isAr ? "كلمة مرور الحساب لبدء الإعداد" : "Account password to start setup"}
                <Input type="password" autoComplete="current-password" required value={password} onChange={(event) => setPassword(event.target.value)} />
              </label>
              <Button type="submit" disabled={busy}>{busy ? "…" : t("security.twoStep.enable")}</Button>
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
                {t("security.twoStep.disable")}
              </Button>
            </div>
          )}

          {mfaOn && mode === "" && (
            <div className="mt-4 flex items-start gap-3 border-t border-border pt-4">
              <span className="h-10 w-10 shrink-0 rounded-lg bg-success/10 text-success grid place-items-center"><CheckCircle2 className="h-5 w-5" /></span>
              <div className="min-w-0 flex-1">
                <p className="text-[12px] leading-relaxed text-muted-foreground">{t("security.twoStep.on.desc")}</p>
                <Button type="button" variant="outline" className="mt-2" onClick={() => { setMode("disable"); setUseBackupCode(false); setError(""); }}>
                  {t("security.twoStep.disable")}
                </Button>
              </div>
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
              <div className="flex flex-wrap gap-2">
                <Button type="submit" variant="destructive" disabled={busy || code.length !== (useBackupCode ? 16 : 6)}>{busy ? "…" : (isAr ? "تأكيد الإيقاف" : "Confirm disable")}</Button>
                <Button type="button" variant="ghost" onClick={() => { setUseBackupCode((value) => !value); setCode(""); }}>{useBackupCode ? (isAr ? "استخدام رمز المصادقة" : "Use authenticator code") : (isAr ? "استخدام رمز استرداد" : "Use recovery code")}</Button>
                <Button type="button" variant="outline" onClick={() => { setMode(""); setCode(""); }}>{t("ls.cancel")}</Button>
              </div>
            </form>
          )}
        </SettingCard>

        <SettingCard title={t("security.password")} desc={t("security.password.desc")}>
          <SettingRow label={t("ls.password")} desc={user?.email || ""} last>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={sendResetLink}
              disabled={!user?.email || resetBusy}
              data-testid="password-reset"
              className="gap-1.5"
            >
              <Mail className="h-3.5 w-3.5" />
              {resetBusy ? "…" : t("security.password.sendReset")}
            </Button>
          </SettingRow>
          {resetError && <div role="alert" className="mt-3 rounded-lg bg-destructive/10 px-3 py-2 text-[12px] text-destructive">{resetError}</div>}
          {resetNotice && <div role="status" data-testid="password-reset-notice" className="mt-3 rounded-lg bg-success/10 px-3 py-2 text-[12px] leading-relaxed text-foreground">{resetNotice}</div>}
          <div className="mt-4 flex items-start gap-2 border-t border-border pt-3 text-[11.5px] leading-relaxed text-muted-foreground">
            <KeyRound className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>{t("security.sessions.note")}</span>
          </div>
        </SettingCard>
      </div>
    </SettingsShell>
  );
}
