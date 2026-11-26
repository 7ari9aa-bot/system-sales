import React from "react";
import { Link } from "react-router-dom";
import { BadgeCheck, Camera, Loader2, Save, ShieldCheck, ShieldQuestion, Trash2 } from "lucide-react";
import { useT, useI18n } from "@/lib/i18n";
import { useAuth } from "@/lib/AuthContext";
import { useTheme } from "@/lib/themeContext";
import { api } from "@/lib/api";
import { activeTenant } from "@/lib/activeTenant";
import useAvatarUpload from "@/hooks/useAvatarUpload";
import SettingsShell, { SettingRow } from "@/components/settings/SettingsShell";
import AccountClosureCard from "@/components/settings/AccountClosureCard";
import AccountAvatar from "@/components/dashboard/AccountAvatar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

/** The person: their picture, their name, their address, and the way out to their account.
 *
 * This page answers "who am I" and nothing else. The shop's name, its country, its currency and
 * the assistant's dialect used to sit here as well, which made a personal page the place where
 * business settings were edited. They now live where they belong (Workspace settings, AI) and are
 * linked from the Account card below.
 */
function Choice({ options, value, onChange, label, testid }) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-md border border-border p-0.5" data-testid={testid}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          role="radio"
          aria-checked={value === option.value}
          onClick={() => onChange(option.value)}
          className={`h-8 rounded px-3 text-[13px] font-medium transition-colors ${
            value === option.value ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"
          }`}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

export default function ProfileSettings() {
  const t = useT();
  const { lang, setLang } = useI18n();
  const { theme, setTheme } = useTheme();
  const { user, refreshUser } = useAuth();
  const tenant = activeTenant(user);
  const avatar = useAvatarUpload();

  const [name, setName] = React.useState(user?.full_name || "");
  const [savingName, setSavingName] = React.useState(false);
  const [nameError, setNameError] = React.useState("");
  const [nameNotice, setNameNotice] = React.useState("");

  // The two optional contact facts the account owns. They save on their own row, like the name,
  // so a half-filled form never blocks the field the person actually came to change.
  const [phone, setPhone] = React.useState(user?.phone || "");
  const [jobTitle, setJobTitle] = React.useState(user?.job_title || "");
  const [savingField, setSavingField] = React.useState("");
  const [fieldError, setFieldError] = React.useState("");
  const [fieldNotice, setFieldNotice] = React.useState("");

  const [closure, setClosure] = React.useState(null);
  const [closureBusy, setClosureBusy] = React.useState(false);
  const [closureError, setClosureError] = React.useState("");
  const [closureNotice, setClosureNotice] = React.useState("");

  const loadClosure = React.useCallback(async () => {
    try {
      setClosure(await api("/users/me/closure-request"));
    } catch {
      // a card that cannot be read must not invent a state: leave it loading and say why
      setClosureError(t("account.closure.failed"));
    }
  }, [t]);

  React.useEffect(() => { void loadClosure(); }, [loadClosure]);

  // A refreshed account is the truth; only overwrite a field the person is not editing.
  React.useEffect(() => { setPhone((current) => (current === "" ? user?.phone || "" : current)); }, [user?.phone]);
  React.useEffect(() => { setJobTitle((current) => (current === "" ? user?.job_title || "" : current)); }, [user?.job_title]);

  async function saveContact(field) {
    if (savingField) return;
    const body = field === "phone" ? { phone } : { job_title: jobTitle };
    setSavingField(field);
    setFieldError("");
    setFieldNotice("");
    try {
      await api("/users/me", { method: "PATCH", body });
      await refreshUser();
      setFieldNotice(t("profile.contact.saved"));
    } catch (failure) {
      setFieldError(failure?.message || t("profile.contact.failed"));
    } finally {
      setSavingField("");
    }
  }

  async function openClosure(mode, reason) {
    setClosureBusy(true);
    setClosureError("");
    setClosureNotice("");
    try {
      setClosure(await api("/users/me/closure-request", { method: "POST", body: { mode, reason } }));
      setClosureNotice(t("account.closure.submitted"));
    } catch (failure) {
      setClosureError(failure?.message || t("account.closure.failed"));
    } finally {
      setClosureBusy(false);
    }
  }

  async function cancelClosure() {
    setClosureBusy(true);
    setClosureError("");
    setClosureNotice("");
    try {
      await api("/users/me/closure-request", { method: "DELETE" });
      await loadClosure();
      setClosureNotice(t("account.closure.cancelled"));
    } catch (failure) {
      setClosureError(failure?.message || t("account.closure.failed"));
    } finally {
      setClosureBusy(false);
    }
  }

  // A refreshed account (another tab, an avatar change) is the truth; only overwrite the field
  // when the owner is not mid-edit, so their typing is never yanked away.
  const storedName = user?.full_name || "";
  React.useEffect(() => {
    setName((current) => (current === "" ? storedName : current));
  }, [storedName]);

  const nameChanged = name.trim() !== "" && name.trim() !== storedName.trim();

  async function saveName(event) {
    event.preventDefault();
    if (!nameChanged || savingName) return;
    setSavingName(true);
    setNameError("");
    setNameNotice("");
    try {
      const updated = await api("/users/me", { method: "PATCH", body: { full_name: name } });
      // render what the server stored (it collapses whitespace), then refresh the shell so the
      // sidebar, account menu and header show the same name
      setName(updated?.full_name || name.trim());
      await refreshUser();
      setNameNotice(t("profile.name.saved"));
    } catch (failure) {
      setNameError(failure?.message || t("profile.name.failed"));
    } finally {
      setSavingName(false);
    }
  }

  const roleLabel = tenant?.role_code || "—";

  return (
    <SettingsShell title={t("settings.nav.profile")} subtitle={t("settings.profile.desc")}>
      {/* No boxes: one open page. The person on top, then plain rows separated by hairlines. */}
      <div className="w-full">
        <div className="flex flex-col gap-4 pb-5 sm:flex-row sm:items-center">
          <AccountAvatar user={user} size="lg" />
          <div className="min-w-0 flex-1">
            <div className="truncate text-[17px] font-semibold leading-6">{user?.full_name || "—"}</div>
            <div className="truncate text-[13px] text-muted-foreground">{tenant?.name || "—"}</div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              variant="outline"
              className="gap-1.5"
              disabled={avatar.busy}
              onClick={avatar.pick}
            >
              {avatar.busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Camera className="h-4 w-4" />}
              {t(user?.avatar_url ? "account.avatar.change" : "account.avatar.add")}
            </Button>
            {user?.avatar_url && (
              <Button
                type="button"
                variant="ghost"
                className="gap-1.5 text-destructive hover:text-destructive"
                disabled={avatar.busy}
                onClick={() => void avatar.remove()}
              >
                <Trash2 className="h-4 w-4" />
                {t("account.avatar.remove")}
              </Button>
            )}
            <input
              ref={avatar.inputRef}
              type="file"
              accept="image/png,image/jpeg,image/webp"
              className="hidden"
              aria-label={t("account.avatar.pick")}
              onChange={avatar.upload}
            />
          </div>
        </div>
        {(avatar.error || avatar.notice) && (
          <p
            role={avatar.error ? "alert" : "status"}
            className={`-mt-2 mb-3 text-[12px] ${avatar.error ? "text-destructive" : "text-muted-foreground"}`}
          >
            {avatar.error || avatar.notice}
          </p>
        )}

        <form onSubmit={saveName} className="border-t border-border">
          <SettingRow label={t("profile.fullName")} stretch>
            <div className="flex w-full items-center gap-2 sm:w-auto">
              <Input
                value={name}
                onChange={(event) => setName(event.target.value)}
                maxLength={255}
                autoComplete="name"
                aria-label={t("profile.fullName")}
                className="min-w-0 flex-1 sm:w-80 sm:flex-none"
                data-testid="profile-name"
              />
              <Button
                type="submit"
                disabled={!nameChanged || savingName}
                className="gap-1.5"
                data-testid="profile-name-save"
              >
                {savingName ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                {savingName ? "" : t("businessProfile.save")}
              </Button>
            </div>
          </SettingRow>
          {(nameError || nameNotice) && (
            <div
              role={nameError ? "alert" : "status"}
              data-testid="profile-name-message"
              className={`border-b border-border py-2 text-[12.5px] ${nameError ? "text-destructive" : "text-success"}`}
            >
              {nameError || nameNotice}
            </div>
          )}
        </form>
        <SettingRow label={t("profile.email")} desc={t("profile.email.locked")}>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[13px] font-medium" dir="ltr">{user?.email || "—"}</span>
            <span data-testid="profile-email-verified">
              {user?.email_verified ? (
                <span className="inline-flex items-center gap-1 text-[12px] text-success">
                  <BadgeCheck className="h-3.5 w-3.5" />
                  {t("profile.email.verified")}
                </span>
              ) : (
                <span className="inline-flex items-center gap-1 text-[12px] text-muted-foreground">
                  <ShieldQuestion className="h-3.5 w-3.5" />
                  {t("profile.email.unverified")}
                </span>
              )}
            </span>
            {!user?.email_verified && (
              <Link to="/verify-email" className="text-[12.5px] font-medium text-primary hover:underline">
                {t("profile.email.verify")}
              </Link>
            )}
          </div>
        </SettingRow>
        <SettingRow label={t("profile.phone")} desc={t("profile.phone.desc")} stretch>
          <div className="flex w-full items-center gap-2 sm:w-auto">
            <Input
              value={phone}
              onChange={(event) => setPhone(event.target.value)}
              maxLength={32}
              autoComplete="tel"
              inputMode="tel"
              dir="ltr"
              aria-label={t("profile.phone")}
              placeholder="+20 100 123 4567"
              className="min-w-0 flex-1 sm:w-56 sm:flex-none"
              data-testid="profile-phone"
            />
            <Button
              type="button"
              variant="outline"
              disabled={savingField === "phone" || phone === (user?.phone || "")}
              onClick={() => void saveContact("phone")}
              data-testid="profile-phone-save"
            >
              {savingField === "phone" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            </Button>
          </div>
        </SettingRow>
        <SettingRow label={t("profile.jobTitle")} desc={t("profile.jobTitle.desc")} stretch>
          <div className="flex w-full items-center gap-2 sm:w-auto">
            <Input
              value={jobTitle}
              onChange={(event) => setJobTitle(event.target.value)}
              maxLength={120}
              autoComplete="organization-title"
              aria-label={t("profile.jobTitle")}
              className="min-w-0 flex-1 sm:w-56 sm:flex-none"
              data-testid="profile-job-title"
            />
            <Button
              type="button"
              variant="outline"
              disabled={savingField === "job_title" || jobTitle === (user?.job_title || "")}
              onClick={() => void saveContact("job_title")}
              data-testid="profile-job-title-save"
            >
              {savingField === "job_title" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            </Button>
          </div>
        </SettingRow>
        {(fieldError || fieldNotice) && (
          <div
            role={fieldError ? "alert" : "status"}
            data-testid="profile-contact-message"
            className={`border-b border-border py-2 text-[12.5px] ${fieldError ? "text-destructive" : "text-success"}`}
          >
            {fieldError || fieldNotice}
          </div>
        )}
        <SettingRow label={t("appearance.language")}>
          <Choice
            label={t("appearance.language")}
            testid="profile-language"
            value={lang}
            onChange={setLang}
            options={[
              { value: "ar", label: t("appearance.language.ar") },
              { value: "en", label: t("appearance.language.en") },
            ]}
          />
        </SettingRow>
        <SettingRow label={t("appearance.theme")}>
          <Choice
            label={t("appearance.theme")}
            testid="profile-theme"
            value={theme}
            onChange={setTheme}
            options={[
              { value: "system", label: t("appearance.theme.system") },
              { value: "light", label: t("appearance.theme.light") },
              { value: "dark", label: t("appearance.theme.dark") },
            ]}
          />
        </SettingRow>
        <SettingRow label={t("workspace.role")} desc={tenant?.name || undefined}>
          <span className="text-[13px] font-medium">{roleLabel}</span>
        </SettingRow>
        <SettingRow label={t("settings.nav.security")} desc={t("profile.link.security.desc")} last>
          <Link
            to="/settings/security"
            className="inline-flex items-center gap-1.5 text-[13px] font-medium text-primary hover:underline"
          >
            <ShieldCheck className="h-4 w-4" />
            {t("profile.link.security")}
          </Link>
        </SettingRow>
      </div>

      <div className="mt-8 border-t border-border pt-5">
        <AccountClosureCard
          state={closure}
          busy={closureBusy}
          error={closureError}
          notice={closureNotice}
          onOpen={openClosure}
          onCancel={cancelClosure}
        />
      </div>
    </SettingsShell>
  );
}
