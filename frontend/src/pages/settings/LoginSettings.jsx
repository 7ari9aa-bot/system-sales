import React from "react";
import { Link } from "react-router-dom";
import { BadgeCheck, KeyRound, Loader2, Mail, ShieldQuestion } from "lucide-react";
import { useT, useI18n } from "@/lib/i18n";
import { useAuth } from "@/lib/AuthContext";
import { api } from "@/lib/api";
import SettingsShell, { SettingCard, SettingRow } from "@/components/settings/SettingsShell";
import { Badge } from "@/components/dashboard/ui";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

// How you get IN: the password, the address it belongs to, and the way back when it is lost.
// Two-step verification and the devices that are signed in are the NEXT page — a person changing a
// password and a person auditing their sessions are asking different questions.
export default function LoginSettings() {
  const t = useT();
  const { lang } = useI18n();
  const { user, refreshUser } = useAuth();
  const isAr = lang === "ar";

  const [current, setCurrent] = React.useState("");
  const [next, setNext] = React.useState("");
  const [confirm, setConfirm] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [notice, setNotice] = React.useState("");

  const [resetBusy, setResetBusy] = React.useState(false);
  const [resetError, setResetError] = React.useState("");
  const [resetNotice, setResetNotice] = React.useState("");

  const mismatch = confirm.length > 0 && next !== confirm;
  const tooShort = next.length > 0 && next.length < 8;
  const canSubmit =
    current.length > 0 && next.length >= 8 && next === confirm && next !== current && !busy;

  async function changePassword(event) {
    event.preventDefault();
    if (!canSubmit) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await api("/auth/password/change", {
        method: "POST",
        body: { current_password: current, new_password: next },
      });
      setCurrent("");
      setNext("");
      setConfirm("");
      // the change signed every other device out; the account itself is unchanged
      await refreshUser();
      setNotice(t("login.password.changed"));
    } catch (failure) {
      setError(failure?.message || t("login.password.failed"));
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
      // the endpoint answers identically for every address, so the screen repeats that promise
      // and never claims an email was delivered
      setResetNotice(t("login.recovery.sent", { email: user.email }));
    } catch (failure) {
      setResetError(failure?.message || t("login.recovery.failed"));
    } finally {
      setResetBusy(false);
    }
  }

  return (
    <SettingsShell title={t("settings.login")} subtitle={t("settings.login.desc")}>
      <div className="grid grid-cols-1 items-start gap-x-10 gap-y-6 xl:grid-cols-2">
        <SettingCard title={t("login.password.title")} desc={t("login.password.desc")}>
          <form onSubmit={changePassword} className="space-y-3 pt-2" data-testid="password-change-form">
            <label className="grid gap-1.5 text-[12.5px] text-muted-foreground">
              {t("login.password.current")}
              <Input
                type="password"
                autoComplete="current-password"
                required
                value={current}
                onChange={(event) => setCurrent(event.target.value)}
                data-testid="password-current"
              />
            </label>
            <label className="grid gap-1.5 text-[12.5px] text-muted-foreground">
              {t("login.password.new")}
              <Input
                type="password"
                autoComplete="new-password"
                required
                minLength={8}
                value={next}
                onChange={(event) => setNext(event.target.value)}
                data-testid="password-new"
              />
              <span className={`text-[11.5px] ${tooShort ? "text-destructive" : "text-muted-foreground"}`}>
                {t("login.password.rule")}
              </span>
            </label>
            <label className="grid gap-1.5 text-[12.5px] text-muted-foreground">
              {t("login.password.confirm")}
              <Input
                type="password"
                autoComplete="new-password"
                required
                value={confirm}
                onChange={(event) => setConfirm(event.target.value)}
                data-testid="password-confirm"
              />
              {mismatch && (
                <span className="text-[11.5px] text-destructive" data-testid="password-mismatch">
                  {t("login.password.mismatch")}
                </span>
              )}
            </label>

            {error && (
              <div role="alert" className="rounded-lg bg-destructive/10 px-3 py-2 text-[12px] text-destructive">
                {error}
              </div>
            )}
            {notice && (
              <div role="status" className="rounded-lg bg-success/10 px-3 py-2 text-[12px] text-foreground" data-testid="password-changed">
                {notice}
              </div>
            )}

            <div className="flex flex-wrap items-center gap-2">
              <Button type="submit" disabled={!canSubmit} data-testid="password-submit">
                {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <KeyRound className="h-4 w-4" />}
                {t("login.password.submit")}
              </Button>
              <span className="text-[11.5px] text-muted-foreground">{t("login.password.signsOut")}</span>
            </div>
          </form>
        </SettingCard>

        <div className="space-y-6">
          <SettingCard title={t("login.methods.title")} desc={t("login.methods.desc")}>
            <SettingRow label={t("login.methods.email")} desc={user?.email || "—"}>
              <span data-testid="login-method-email">
                <Badge tone="muted">{t("login.methods.active")}</Badge>
              </span>
            </SettingRow>
            <SettingRow label={t("login.methods.address")} last>
              <span className="inline-flex items-center gap-1.5 text-[12.5px]">
                {user?.email_verified ? (
                  <>
                    <BadgeCheck className="h-4 w-4 text-success" />
                    <span className="text-success">{t("profile.email.verified")}</span>
                  </>
                ) : (
                  <>
                    <ShieldQuestion className="h-4 w-4 text-muted-foreground" />
                    <Link to="/verify-email" className="font-medium text-primary hover:underline">
                      {t("profile.email.verify")}
                    </Link>
                  </>
                )}
              </span>
            </SettingRow>
            <p className="pt-2 text-[11.5px] leading-relaxed text-muted-foreground">{t("login.methods.only")}</p>
          </SettingCard>

          <SettingCard title={t("login.recovery.title")} desc={t("login.recovery.desc")}>
            <SettingRow label={t("login.recovery.link")} desc={user?.email || ""} last>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={sendResetLink}
                disabled={!user?.email || resetBusy}
                data-testid="login-reset-link"
                className="gap-1.5"
              >
                <Mail className="h-3.5 w-3.5" />
                {resetBusy ? "…" : t("login.recovery.send")}
              </Button>
            </SettingRow>
            {resetError && (
              <div role="alert" className="mt-3 rounded-lg bg-destructive/10 px-3 py-2 text-[12px] text-destructive">
                {resetError}
              </div>
            )}
            {resetNotice && (
              <div role="status" className="mt-3 rounded-lg bg-success/10 px-3 py-2 text-[12px] leading-relaxed text-foreground" data-testid="login-reset-notice">
                {resetNotice}
              </div>
            )}
            <p className="mt-3 border-t border-border pt-3 text-[11.5px] leading-relaxed text-muted-foreground">
              {isAr
                ? "رموز الاسترداد الخاصة بالمصادقة الثنائية موجودة في صفحة الأمان الشخصي."
                : "Two-step recovery codes live on the personal security page."}{" "}
              <Link to="/settings/security" className="font-medium text-primary hover:underline">
                {t("settings.security")}
              </Link>
            </p>
          </SettingCard>
        </div>
      </div>
    </SettingsShell>
  );
}
